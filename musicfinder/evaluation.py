"""Measure how accurately musicfinder predicts *your* taste, using your own history as the test.

Protocol (time-based holdout, so the model never sees the future it is graded on):

    |------------- train ------------|-- validation --|----- test -----|
                                    t_val           t_test            now

1. **Ground truth.** In a window, an artist you had never played before counts as *adopted* if you
   streamed them (>= 30 s, not skipped) at least 3 times on at least 2 different days, and as
   *rejected* if every play was skipped in the first 30 seconds.
2. **Validation.** Build the taste profile from plays before ``t_val`` only, crawl the similarity
   graph, and score candidates under a grid of hyper-parameters (memory half-life, seed weighting,
   random-walk restart). The best setting is chosen, then the feature weights are re-fitted to you by
   regularised logistic regression (prior = the default weights).
3. **Test.** Re-train on everything before ``t_test`` with the chosen setting and grade the
   predictions on the final window, which played no part in any choice. Reported with 95% bootstrap
   confidence intervals, next to baselines (popularity, plain similar-artists, random).

Metrics: Recall@K / Precision@K / NDCG@K for discovery ("of the artists you went on to love, how
many were in our top K?"), mean percentile rank (Hu et al. 2008; 50% = random), and *preference
AUC*: given an artist you liked and one you rejected after hearing both, how often does musicfinder
score the liked one higher? That last one is the cleanest measure of "predicting what you'd like",
because both artists were actually heard.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from musicfinder.graph import CrawlConfig, KnowledgeGraph, crawl_steps
from musicfinder.models import Play
from musicfinder.recommender import DEFAULT_WEIGHTS, FEATURES, ScoringParams, diversify, score_pool
from musicfinder.sources.base import Knowledge
from musicfinder.stats import (
    auc, auc_ci, bootstrap_ci, fit_logistic, mean_percentile_rank, ndcg_at_k, precision_at_k, recall_at_k,
)
from musicfinder.steps import Steps, run
from musicfinder.taste import TasteParams, TasteProfile, build_profile, play_engagement

Progress = Callable[[str, int, int], None]


def _noop(step: str, done: int, total: int) -> None:  # pragma: no cover
    pass


@dataclass(frozen=True)
class EvalConfig:
    window_days: int = 90
    min_streams: int = 3
    min_days: int = 2
    ks: tuple[int, ...] = (10, 25, 50, 100)
    half_lives: tuple[float | None, ...] = (60.0, 180.0, 365.0, 730.0, None)
    seed_powers: tuple[float, ...] = (0.5, 1.0)
    alphas: tuple[float, ...] = (0.2, 0.4)
    bootstrap: int = 600
    unlabeled_weight: float = 0.3
    max_unlabeled: int = 1500
    prior_precision: float = 2.0
    min_positives: int = 5
    min_span_days: int = 90


@dataclass(frozen=True)
class ModelConfig:
    taste: TasteParams
    alpha: float
    weights: tuple[tuple[str, float], ...] = tuple(DEFAULT_WEIGHTS.items())

    def scoring(self, exploration: float = 0.0) -> ScoringParams:
        return ScoringParams(alpha=self.alpha, weights=self.weights, exploration=exploration)

    def describe(self) -> dict:
        return {
            "memory_half_life_days": self.taste.half_life_days,
            "seed_power": self.taste.seed_power,
            "restart_probability": self.alpha,
            "weights": {k: round(v, 3) for k, v in self.weights},
        }


@dataclass
class Truth:
    adopted: dict[str, str] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


def ground_truth(plays: list[Play], cutoff: datetime, end: datetime, cfg: EvalConfig = EvalConfig(),
                 params: TasteParams = TasteParams()) -> Truth:
    known: set[str] = set()
    stats: dict[str, dict] = {}
    for p in plays:
        _, outcome = play_engagement(p, None, params)
        if outcome == "neutral" and p.ms_played < params.noise_ms:
            continue
        k = p.artist_key
        if p.ts < cutoff:
            known.add(k)
        elif p.ts < end and k not in known:
            st = stats.setdefault(k, {"name": p.artist, "streams": 0, "skips": 0, "days": set()})
            if outcome == "stream":
                st["streams"] += 1
                st["days"].add(p.ts.date())
            elif outcome == "early_skip":
                st["skips"] += 1
    truth = Truth()
    for k, st in stats.items():
        if st["streams"] >= cfg.min_streams and len(st["days"]) >= cfg.min_days:
            truth.adopted[k] = st["name"]
        elif st["streams"] == 0 and st["skips"] >= 1:
            truth.rejected[k] = st["name"]
    return truth


def _ranking_metrics(ranked: list[str], relevant: set[str], ks: tuple[int, ...], n_boot: int, seed: int) -> dict:
    out: dict = {"pool_size": len(ranked), "in_pool": len(relevant & set(ranked))}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k)
    pos = {item: i for i, item in enumerate(ranked)}
    items = sorted(relevant)
    for k in (50,):
        ci = bootstrap_ci(lambda s, k=k: sum(1 for r in s if pos.get(r, 10**9) < k) / len(s), items, n_boot, seed=seed)
        out[f"recall@{k}_ci"] = ci
    out["mean_percentile_rank"] = mean_percentile_rank(ranked, relevant)
    return out


def _expected_random(pool: int, relevant_in_pool: int, n_relevant: int, ks: tuple[int, ...]) -> dict:
    out: dict = {"pool_size": pool, "in_pool": relevant_in_pool}
    for k in ks:
        frac = min(1.0, k / pool) if pool else 0.0
        out[f"recall@{k}"] = relevant_in_pool * frac / n_relevant if n_relevant else 0.0
        out[f"precision@{k}"] = relevant_in_pool / pool if pool else 0.0
    out["mean_percentile_rank"] = 50.0
    return out


def _objective(m: dict) -> float:
    parts = []
    if m.get("auc") is not None:
        parts.append(m["auc"])
    if m.get("mean_percentile_rank") is not None:
        parts.append(1 - m["mean_percentile_rank"] / 100)
    return sum(parts) / len(parts) if parts else 0.0


@dataclass
class PhaseOutput:
    cutoff: datetime
    end: datetime
    truth: Truth
    results: list[tuple[ModelConfig, dict]]
    baselines: dict
    rows: dict[ModelConfig, list[tuple[list[float], int, float]]]
    kg: KnowledgeGraph
    profiles: dict[TasteParams, TasteProfile]


def _run_phase_steps(plays: list[Play], cutoff: datetime, end: datetime, knowledge: Knowledge,
                     configs: list[ModelConfig], cfg: EvalConfig, crawl_cfg: CrawlConfig, progress: Progress,
                     label: str, collect_rows: bool = False, tradeoff: bool = False) -> Steps[PhaseOutput]:
    truth = ground_truth(plays, cutoff, end, cfg)
    adopted = set(truth.adopted)
    profiles: dict[TasteParams, TasteProfile] = {}
    for c in configs:
        if c.taste not in profiles:
            profiles[c.taste] = build_profile(plays, (), c.taste, as_of=cutoff)
    main = profiles[configs[0].taste]
    others = [p for t, p in profiles.items() if t != configs[0].taste]
    wrap = lambda step, d, t: progress(f"{label}: {step}", d, t)  # noqa: E731
    kg = yield from crawl_steps(main, knowledge, crawl_cfg, wrap, extra_seed_profiles=others)

    rng = random.Random(1)
    results: list[tuple[ModelConfig, dict]] = []
    rows: dict[ModelConfig, list] = {}
    pools = {}
    for i, mc in enumerate(configs):
        progress(f"{label}: scoring settings", i + 1, len(configs))
        pool = score_pool(profiles[mc.taste], kg, mc.scoring())
        pools[mc] = pool
        ranked = pool.ranked_keys()
        m = _ranking_metrics(ranked, adopted, cfg.ks, cfg.bootstrap if label.lower() == "test" else 0, seed=7)
        m["coverage"] = len(adopted & set(ranked)) / len(adopted) if adopted else None
        results.append((mc, m))
        if collect_rows:
            data = []
            unl = []
            for c in pool.candidates:
                xv = [c.z[f] for f in FEATURES]
                if c.key in adopted:
                    data.append((xv, 1, 1.0))
                elif c.key in truth.rejected:
                    data.append((xv, 0, 1.0))
                else:
                    unl.append((xv, 0, cfg.unlabeled_weight))
            rng.shuffle(unl)
            rows[mc] = data + unl[: cfg.max_unlabeled]

    # baselines on the main configuration's pool
    base_pool = pools[configs[0]]
    by_pop = sorted(base_pool.candidates, key=lambda c: -(c.popularity or 0.0))
    by_cf = sorted(base_pool.candidates, key=lambda c: -c.raw["cf"])
    ranked0 = base_pool.ranked_keys()
    in_pool = len(adopted & set(ranked0))
    baselines = {
        "popularity": _ranking_metrics([c.key for c in by_pop], adopted, cfg.ks, 0, 0),
        "similar_artists_only": _ranking_metrics([c.key for c in by_cf], adopted, cfg.ks, 0, 0),
        "random": _expected_random(len(ranked0), in_pool, len(adopted), cfg.ks),
    }

    # tradeoff between accuracy and exploration (on the first config, before augmentation)
    if tradeoff:
        mc = configs[0]
        curve = []
        for eps in (0.0, 0.5, 1.0):
            sp = mc.scoring(exploration=eps)
            pool = score_pool(profiles[mc.taste], kg, sp)
            lst = diversify(pool, kg, 50, min(0.8, sp.diversity + 0.45 * eps))
            keys = [c.key for c in lst]
            pops = [math.log10(1 + c.popularity) for c in lst if c.popularity]
            tags = {c.tags[0] for c in lst if c.tags}
            curve.append({
                "exploration": eps,
                "recall@50": recall_at_k(keys, adopted, 50),
                "hits@50": len(set(keys) & adopted),
                "median_listeners": round(10 ** sorted(pops)[len(pops) // 2]) if pops else None,
                "distinct_genres": len(tags),
            })
        baselines["exploration_tradeoff"] = curve

    # Preference AUC: make sure every artist heard in the window is in the graph, then score them all.
    truth_names = list(truth.adopted.values()) + list(truth.rejected.values())
    yield from crawl_steps(main, knowledge, crawl_cfg, wrap, extra_expand=truth_names, kg=kg)
    include = [k for k in list(truth.adopted) + list(truth.rejected) if k in kg.adj]
    for (mc, m) in results:
        pool = score_pool(profiles[mc.taste], kg, mc.scoring(), include=include)
        scores = {c.key: c.score for c in pool.candidates}
        pos = [scores[k] for k in truth.adopted if k in scores]
        neg = [scores[k] for k in truth.rejected if k in scores]
        m["auc"] = auc(pos, neg)
        m["auc_n"] = (len(pos), len(neg))
        if label.lower() == "test":
            m["auc_ci"] = auc_ci(pos, neg, cfg.bootstrap)
        if mc is configs[0]:
            pops = {c.key: (c.popularity or 0.0) for c in pool.candidates}
            baselines["popularity"]["auc"] = auc([pops[k] for k in truth.adopted if k in pops],
                                                 [pops[k] for k in truth.rejected if k in pops])
            cfs = {c.key: c.raw["cf"] for c in pool.candidates}
            baselines["similar_artists_only"]["auc"] = auc([cfs[k] for k in truth.adopted if k in cfs],
                                                           [cfs[k] for k in truth.rejected if k in cfs])
            baselines["random"]["auc"] = 0.5
    return PhaseOutput(cutoff, end, truth, results, baselines, rows, kg, profiles)


def _normalise_weights(w: dict[str, float]) -> dict[str, float]:
    """Rescale learned weights to the default weights' L1 norm so the exploration dial keeps its meaning."""
    target = sum(abs(v) for v in DEFAULT_WEIGHTS.values())
    cur = sum(abs(v) for v in w.values()) or 1.0
    return {k: v * target / cur for k, v in w.items()}


def fit_weights(rows: list[tuple[list[float], int, float]], cfg: EvalConfig) -> dict[str, float] | None:
    if sum(y for _, y, _ in rows) < cfg.min_positives:
        return None
    x = [r[0] for r in rows]
    y = [r[1] for r in rows]
    sw = [r[2] for r in rows]
    coef, _ = fit_logistic(x, y, sw, prior_mean=[DEFAULT_WEIGHTS[f] for f in FEATURES],
                           prior_precision=cfg.prior_precision)
    return _normalise_weights(dict(zip(FEATURES, coef)))


def _clean(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        if isinstance(v, float):
            out[k] = round(v, 4)
        elif isinstance(v, tuple):
            out[k] = [round(x, 4) if isinstance(x, float) else x for x in v]
        else:
            out[k] = v
    return out


def backtest(*args, **kwargs) -> dict:
    return run(backtest_steps(*args, **kwargs))


def backtest_steps(plays: list[Play], knowledge: Knowledge, cfg: EvalConfig = EvalConfig(),
                   crawl_cfg: CrawlConfig = CrawlConfig(), progress: Progress = _noop) -> Steps[dict]:
    plays = sorted(plays, key=lambda p: p.ts)
    if not plays:
        return {"ok": False, "reason": "The accuracy test replays your listening history, so it needs your Spotify "
                                       "export first. Until then, rating recommendations (Like / Not for me) "
                                       "measures accuracy instead."}
    end = plays[-1].ts + timedelta(seconds=1)
    span = (end - plays[0].ts).days
    if span < cfg.min_span_days:
        return {"ok": False, "reason": f"Need at least {cfg.min_span_days} days of history to test accuracy "
                                       f"(you have {span}). The Extended Streaming History export covers all years."}
    h = cfg.window_days if span >= 4 * cfg.window_days else max(21, span // 4)
    t_test = end - timedelta(days=h)
    t_val = t_test - timedelta(days=h)

    grid = [ModelConfig(TasteParams(half_life_days=hl, seed_power=sp), alpha)
            for hl in cfg.half_lives for sp in cfg.seed_powers for alpha in cfg.alphas]
    default = ModelConfig(TasteParams(), 0.3)
    if default not in grid:
        grid.insert(0, default)
    else:
        grid.remove(default)
        grid.insert(0, default)

    val = yield from _run_phase_steps(plays, t_val, t_test, knowledge, grid, cfg, crawl_cfg, progress, "Validation", collect_rows=True)
    n_val_pos = len(val.truth.adopted)
    ranked = sorted(val.results, key=lambda r: -_objective(r[1]))
    best_cfg, best_val = ranked[0]
    learned = fit_weights(val.rows.get(best_cfg, []), cfg)
    tuned = ModelConfig(best_cfg.taste, best_cfg.alpha,
                        tuple((f, learned[f]) for f in FEATURES)) if learned else best_cfg

    test_configs = [tuned] + ([best_cfg] if tuned is not best_cfg else []) + ([default] if default != best_cfg else [])
    test = yield from _run_phase_steps(plays, t_test, end, knowledge, test_configs, cfg, crawl_cfg, progress, "Test", tradeoff=True)
    res = {id(mc): m for mc, m in test.results}
    tuned_m = res[id(tuned)]
    default_m = res[id(default)] if default in test_configs else tuned_m

    # The choice was made on validation data only; the test window is reported, never used to choose.
    chosen, chosen_m = tuned, tuned_m
    n_pos = len(test.truth.adopted)
    pop = test.baselines["popularity"]
    report = {
        "ok": True,
        "enough_data": n_pos >= cfg.min_positives,
        "windows": {
            "validation": [t_val.date().isoformat(), t_test.date().isoformat()],
            "test": [t_test.date().isoformat(), end.date().isoformat()],
            "days": h,
        },
        "ground_truth": {
            "test_adopted": n_pos, "test_rejected": len(test.truth.rejected),
            "validation_adopted": n_val_pos, "validation_rejected": len(val.truth.rejected),
            "examples_adopted": sorted(test.truth.adopted.values())[:12],
        },
        "chosen": chosen.describe(),
        "chosen_is_personalised": chosen is tuned and learned is not None,
        "model": _clean(chosen_m),
        "default_model": _clean(default_m),
        "baselines": {k: (_clean(v) if isinstance(v, dict) else v) for k, v in test.baselines.items()},
        "validation_grid": [
            {**mc.describe(), "objective": round(_objective(m), 4), "auc": m.get("auc"),
             "mean_percentile_rank": m.get("mean_percentile_rank")}
            for mc, m in ranked[:8]
        ],
        "graph": {"nodes": len(test.kg.names), "expanded": len(test.kg.expanded)},
    }
    report["summary"] = _summarise(report, n_pos, chosen_m, pop)
    return report


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def _summarise(report: dict, n_pos: int, m: dict, pop: dict) -> list[str]:
    days = report["windows"]["days"]
    lines = []
    if n_pos == 0:
        return [f"You did not adopt any brand-new artists in the last {days} days, so discovery accuracy "
                "cannot be measured yet."]
    hits = round(m.get("recall@50", 0) * n_pos)
    lines.append(
        f"In the last {days} days you started loving {n_pos} artists you had never played before. Using only "
        f"your history from before that window, musicfinder’s top 50 already contained {hits} of them "
        f"(recall {_pct(m.get('recall@50'))}" + (
            f", 95% CI {_pct(m['recall@50_ci'][0])}–{_pct(m['recall@50_ci'][1])})." if m.get("recall@50_ci") else ").")
    )
    pr = pop.get("recall@50") or 0
    mr = m.get("recall@50") or 0
    line = (f"For comparison, simply recommending the most popular artists in the same neighbourhood would "
            f"have found {round(pr * n_pos)} (recall {_pct(pr)})")
    if pr > 0 and mr >= pr:
        line += f" — musicfinder found {mr / pr:.1f}× as many."
    elif mr < pr:
        line += " — the popularity baseline did better on this window, so treat these results with caution."
    else:
        line += "."
    lines.append(line)
    if m.get("auc") is not None:
        a, (npos, nneg) = m["auc"], m.get("auc_n", (0, 0))
        ci = m.get("auc_ci")
        lines.append(
            f"Preference accuracy: shown a pair of new artists you actually heard — one you went on to love, "
            f"one you skipped — musicfinder ranks the loved one higher {_pct(a)} of the time"
            + (f" (95% CI {_pct(ci[0])}–{_pct(ci[1])})" if ci else "")
            + f"; guessing would be 50%. Based on {npos} loved vs {nneg} rejected artists."
        )
    cov = m.get("coverage")
    if cov is not None and cov < 1:
        lines.append(f"{_pct(1 - cov)} of the artists you adopted were not reachable from your taste graph at all "
                     "— a hard ceiling for any similarity-based recommender (they usually come from friends, "
                     "films, or editorial playlists).")
    return lines
