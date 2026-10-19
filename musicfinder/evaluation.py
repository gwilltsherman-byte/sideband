"""Measure how accurately musicfinder predicts *your* taste, using your own history as the test.

Protocol (time-based holdout, so the model never sees the future it is graded on):

    |------------- train ------------|-- validation --|----- test -----|
                                    t_val           t_test            now

1. **Ground truth.** In a window, an artist you had never played before counts as *adopted* if you
   streamed them (>= 30 s, not skipped) at least 3 times on at least 2 different days, and as
   *rejected* if every play was skipped in the first 30 seconds.
2. **Validation.** Build the taste profile from plays before ``t_val`` only, crawl the similarity
   graph, and score candidates under a grid of hyper-parameters (memory half-life, seed weighting,
   random-walk restart). Settings only change with sufficient observed outcomes and a validation
   improvement. Regularised feature fitting uses actual adopted/rejected artists, and must beat the
   default on a separate subset of validation artists before it is accepted.
3. **Test.** Re-train on everything before ``t_test`` with the chosen setting and grade the
   predictions on the final window, which played no part in any choice. Reported with 95% bootstrap
   confidence intervals, next to baselines (popularity, plain similar-artists, random).

Metrics grade the diversified lists shown to users. Missing discoveries count against recall and
mean percentile rank. Preference AUC compares observed adopted/rejected artists already present
in the prediction pool; its coverage is reported, and future outcome identities never expand that
pool or the graph. Repeats/skips remain implicit preference proxies, not ratings or causal evidence.
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
    # Retained for settings compatibility. Unheard artists are never fitted as dislikes.
    unlabeled_weight: float = 0.0
    max_unlabeled: int = 1500
    prior_precision: float = 2.0
    min_positives: int = 5
    min_span_days: int = 90
    min_validation_class: int = 10
    min_selection_gain: float = 0.02
    selection_bootstrap: int = 200


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
    # First determine what was already known. Input order must not let a later row masquerade
    # as a new discovery merely because its older playback appeared further down an export.
    known = {p.artist_key for p in plays if p.ts < cutoff and
             not (play_engagement(p, None, params)[1] == "neutral" and p.ms_played < params.noise_ms)}
    stats: dict[str, dict] = {}
    for p in plays:
        _, outcome = play_engagement(p, None, params)
        if outcome == "neutral" and p.ms_played < params.noise_ms:
            continue
        k = p.artist_key
        if cutoff <= p.ts < end and k not in known:
            st = stats.setdefault(k, {"name": p.artist, "streams": 0, "skips": 0, "neutral": 0, "days": set()})
            if outcome == "stream":
                if p.skipped is True or p.reason_end == "fwdbtn":
                    st["neutral"] += 1  # a qualifying late skip is not a successful adoption play
                else:
                    st["streams"] += 1
                    st["days"].add(p.ts.date())
            elif outcome == "early_skip":
                st["skips"] += 1
            else:
                st["neutral"] += 1
    truth = Truth()
    for k, st in stats.items():
        if st["streams"] >= cfg.min_streams and len(st["days"]) >= cfg.min_days:
            truth.adopted[k] = st["name"]
        elif st["streams"] == 0 and st["neutral"] == 0 and st["skips"] >= 1:
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
    # Conditional rank alone rewards a tiny pool that misses most discoveries. Missing artists
    # count as the worst rank when choosing settings; keep the conditional statistic visible too.
    out["retrieved_mean_percentile_rank"] = mean_percentile_rank(ranked, relevant)
    out["mean_percentile_rank"] = (sum(100.0 * pos[r] / max(1, len(ranked) - 1)
                                          if r in pos else 100.0 for r in relevant) / len(relevant)
                                    if relevant else None)
    return out


def _expected_random(pool: int, relevant_in_pool: int, n_relevant: int, ks: tuple[int, ...]) -> dict:
    out: dict = {"pool_size": pool, "in_pool": relevant_in_pool}
    for k in ks:
        frac = min(1.0, k / pool) if pool else 0.0
        out[f"recall@{k}"] = relevant_in_pool * frac / n_relevant if n_relevant else 0.0
        out[f"precision@{k}"] = relevant_in_pool * frac / k if k > 0 else 0.0
        dcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, pool)))
        ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, n_relevant)))
        out[f"ndcg@{k}"] = dcg * relevant_in_pool / pool / ideal if pool and ideal else 0.0
    average_rank = 0.5 if pool > 1 else 0.0
    out["mean_percentile_rank"] = (100.0 * (n_relevant - (1 - average_rank) * relevant_in_pool) / n_relevant
                                    if n_relevant else None)
    return out


def _display_ranking(pool, kg: KnowledgeGraph, cfg: EvalConfig, sp: ScoringParams, depth: int = 50) -> list[str]:
    """Grade the same diversity re-ranking users get, at each reported recommendation depth."""
    shown = diversify(pool, kg, depth, min(0.8, sp.diversity + 0.45 * sp.exploration))
    head = [c.key for c in shown]
    seen = set(head)
    return head + [c.key for c in pool.candidates if c.key not in seen]


def _model_metrics(pool, kg: KnowledgeGraph, relevant: set[str], cfg: EvalConfig,
                   sp: ScoringParams, n_boot: int) -> dict:
    # MMR's candidate head depends on list length, just as it does in the application. Generate
    # each K using its actual list length, instead of grading the prefix of a different-sized list.
    m = _ranking_metrics(_display_ranking(pool, kg, cfg, sp), relevant, cfg.ks, n_boot, 7)
    for k in cfg.ks:
        ranked = _display_ranking(pool, kg, cfg, sp, k)
        m[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        m[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        m[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k)
    return m


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

    results: list[tuple[ModelConfig, dict]] = []
    rows: dict[ModelConfig, list] = {}
    pools = {}
    for i, mc in enumerate(configs):
        progress(f"{label}: scoring settings", i + 1, len(configs))
        pool = score_pool(profiles[mc.taste], kg, mc.scoring())
        pools[mc] = pool
        ranked = _display_ranking(pool, kg, cfg, mc.scoring())
        m = _model_metrics(pool, kg, adopted, cfg, mc.scoring(),
                           cfg.bootstrap if label.lower() == "test" else 0)
        m["coverage"] = len(adopted & set(ranked)) / len(adopted) if adopted else None
        results.append((mc, m))
        if collect_rows:
            data = []
            for c in pool.candidates:
                xv = [c.z[f] for f in FEATURES]
                if c.key in adopted:
                    data.append((xv, 1, 1.0))
                elif c.key in truth.rejected:
                    data.append((xv, 0, 1.0))
            rows[mc] = data

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

    # Tradeoff between accuracy and exploration on the first configuration's history-built graph.
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

    # Only grade the original prediction pool. Looking up or including held-out artists here
    # would change PageRank, IDF or standardisation using identities learned from future outcomes.
    for (mc, m) in results:
        pool = pools[mc]
        scores = {c.key: c.score for c in pool.candidates}
        pos = [scores[k] for k in truth.adopted if k in scores]
        neg = [scores[k] for k in truth.rejected if k in scores]
        m["auc"] = auc(pos, neg)
        m["auc_n"] = (len(pos), len(neg))
        n_heard = len(truth.adopted) + len(truth.rejected)
        m["preference_coverage"] = ((len(pos) + len(neg)) / n_heard if n_heard else None)
        m["preference_available"] = (len(pos) + len(neg), n_heard)
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


def _paired_gain_ci(positive: list[tuple[float, float]], negative: list[tuple[float, float]],
                    n: int, rank_gains: list[float] | None = None) -> tuple[float, float] | None:
    """Resample the same held-out artists for both models, so improvements have an error bar."""
    if min(len(positive), len(negative)) < 2 or n <= 0:
        return None
    rng = random.Random(29)
    gains = []
    for _ in range(n):
        p = [positive[rng.randrange(len(positive))] for _ in positive]
        q = [negative[rng.randrange(len(negative))] for _ in negative]
        delta = auc([x for x, _ in p], [x for x, _ in q]) - auc([y for _, y in p], [y for _, y in q])
        if rank_gains:
            ranking = sum(rank_gains[rng.randrange(len(rank_gains))] for _ in rank_gains) / len(rank_gains)
            delta = (delta + ranking) / 2
        gains.append(delta)
    gains.sort()
    return gains[int(0.025 * n)], gains[min(n - 1, int(0.975 * n))]


def _settings_gain_ci(phase: PhaseOutput, candidate: ModelConfig, default: ModelConfig,
                      cfg: EvalConfig) -> tuple[float, float] | None:
    proposed = score_pool(phase.profiles[candidate.taste], phase.kg, candidate.scoring())
    base = score_pool(phase.profiles[default.taste], phase.kg, default.scoring())
    a, b = proposed.by_key(), base.by_key()
    positive = [(a[k].score, b[k].score) for k in phase.truth.adopted if k in a and k in b]
    negative = [(a[k].score, b[k].score) for k in phase.truth.rejected if k in a and k in b]
    arank = {k: i / max(1, len(a) - 1) for i, k in enumerate(_display_ranking(proposed, phase.kg, cfg, candidate.scoring()))}
    brank = {k: i / max(1, len(b) - 1) for i, k in enumerate(_display_ranking(base, phase.kg, cfg, default.scoring()))}
    gains = [brank.get(k, 1.0) - arank.get(k, 1.0) for k in phase.truth.adopted]
    return _paired_gain_ci(positive, negative, cfg.selection_bootstrap, gains)


def _fit_weights(rows: list[tuple[list[float], int, float]], cfg: EvalConfig) -> tuple[dict[str, float] | None, dict]:
    # Only unit-weight rows are observed outcomes. Legacy callers' low-confidence, unheard
    # negatives must not turn a large catalog into thousands of invented dislikes.
    observed = [(x, y, sw) for x, y, sw in rows if sw >= 1.0 and y in (0, 1) and
                len(x) == len(FEATURES) and math.isfinite(sw) and all(math.isfinite(v) for v in x)]
    positive = [r for r in observed if r[1] == 1]
    negative = [r for r in observed if r[1] == 0]
    evidence = {"positives": len(positive), "negatives": len(negative), "accepted": False,
                "holdout_gain": None}
    minimum = max(10, cfg.min_positives, cfg.min_validation_class)
    if min(len(positive), len(negative)) < minimum:
        evidence["reason"] = "Not enough observed outcomes in both classes to fit weights safely."
        return None, evidence

    def fitted(data):
        n_small = min(sum(y for _, y, _ in data), sum(1 - y for _, y, _ in data))
        precision = cfg.prior_precision * max(1.0, 40.0 / max(1, n_small))
        coef, _ = fit_logistic([r[0] for r in data], [r[1] for r in data], [r[2] for r in data],
                               prior_mean=[DEFAULT_WEIGHTS[f] for f in FEATURES], prior_precision=precision)
        weights = dict(zip(FEATURES, coef))
        # Similarity to rejected artists must never become a positive signal because of a noisy
        # small sample, and similarity/support evidence must retain its intended direction.
        weights["neg"] = min(0.0, weights["neg"])
        for f in ("cf", "cf_recent", "ppr", "support", "tag", "agree"):
            weights[f] = max(0.0, weights[f])
        return _normalise_weights(weights)

    rng = random.Random(19)
    rng.shuffle(positive)
    rng.shuffle(negative)
    p_hold, n_hold = max(5, len(positive) // 3), max(5, len(negative) // 3)
    holdout = positive[:p_hold] + negative[:n_hold]
    training = positive[p_hold:] + negative[n_hold:]
    proposed = fitted(training)

    def scores(weights):
        return [sum(weights[f] * x[i] for i, f in enumerate(FEATURES)) for x, _, _ in holdout]

    bs, ps = scores(DEFAULT_WEIGHTS), scores(proposed)
    base_auc = auc(bs[:p_hold], bs[p_hold:])
    proposed_auc = auc(ps[:p_hold], ps[p_hold:])
    gain = proposed_auc - base_auc
    gain_ci = _paired_gain_ci(list(zip(ps[:p_hold], bs[:p_hold])),
                             list(zip(ps[p_hold:], bs[p_hold:])), cfg.selection_bootstrap)
    evidence.update({"holdout_positives": p_hold, "holdout_negatives": n_hold,
                     "default_holdout_auc": base_auc, "fitted_holdout_auc": proposed_auc,
                     "holdout_gain": round(gain, 4), "holdout_gain_ci95": gain_ci})
    if gain < cfg.min_selection_gain or gain_ci is None or gain_ci[0] <= 0:
        evidence["reason"] = "Learned weights did not improve on defaults in withheld validation ratings."
        return None, evidence
    evidence["accepted"] = True
    return fitted(observed), evidence


def fit_weights(rows: list[tuple[list[float], int, float]], cfg: EvalConfig) -> dict[str, float] | None:
    """Fit only if observed outcomes demonstrate a benefit on separate validation artists."""
    return _fit_weights(rows, cfg)[0]


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
        return {"ok": False, "reason": "The replay test needs an imported listening history. Without one, "
                                       "your Keep and Pass choices measure accuracy instead."}
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
    candidate_cfg, candidate_val = ranked[0]
    default_val = next(m for mc, m in val.results if mc == default)
    val_classes = candidate_val.get("auc_n", (0, 0))
    sufficient_validation = min(val_classes) >= max(10, cfg.min_positives, cfg.min_validation_class)
    setting_gain = _objective(candidate_val) - _objective(default_val)
    setting_ci = (_settings_gain_ci(val, candidate_cfg, default, cfg)
                  if sufficient_validation and candidate_cfg != default else None)
    settings_accepted = (sufficient_validation and candidate_cfg != default and
                         setting_gain >= cfg.min_selection_gain and setting_ci is not None and setting_ci[0] > 0)
    best_cfg = candidate_cfg if settings_accepted else default
    learned, weight_evidence = _fit_weights(val.rows.get(best_cfg, []), cfg)
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
        "chosen_is_personalised": chosen != default,
        "selection": {
            "validated": settings_accepted or learned is not None,
            "personalised": chosen != default,
            "settings_accepted": settings_accepted,
            "setting_gain": round(setting_gain, 4),
            "setting_gain_ci95": setting_ci,
            "validation_covered_adopted": val_classes[0],
            "validation_covered_rejected": val_classes[1],
            "min_class": max(10, cfg.min_positives, cfg.min_validation_class),
            "weights": weight_evidence,
            "reason": ("Changed settings passed validation checks; the final test was not used to choose."
                       if settings_accepted or learned is not None else
                       "Kept defaults because validation did not support a reliable improvement."),
        },
        "model": _clean(chosen_m),
        "default_model": _clean(default_m),
        "baselines": {k: (_clean(v) if isinstance(v, dict) else v) for k, v in test.baselines.items()},
        "validation_grid": [
            {**mc.describe(), "objective": round(_objective(m), 4), "auc": m.get("auc"),
             "mean_percentile_rank": m.get("mean_percentile_rank")}
            for mc, m in ranked[:8]
        ],
        "graph": {"nodes": len(test.kg.names), "expanded": len(test.kg.expanded)},
        "limitations": [
            "Listening repeats and skips are evidence of preference, not direct ratings.",
            "The artist catalog and similarity data are current, not historical snapshots.",
            "Preference accuracy only covers artists reachable in the history-built graph.",
            "Confidence intervals describe this window's artists, not certainty about future listening.",
        ],
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
        f"In the last {days} days you returned to {n_pos} new artists across multiple days. Using only "
        f"your history from before that window, Sideband’s diversified top 50 contained {hits} of them "
        f"(recall {_pct(m.get('recall@50'))}" + (
            f", 95% CI {_pct(m['recall@50_ci'][0])}–{_pct(m['recall@50_ci'][1])})." if m.get("recall@50_ci") else ").")
    )
    pr = pop.get("recall@50") or 0
    mr = m.get("recall@50") or 0
    line = (f"For comparison, simply recommending the most popular artists in the same neighbourhood would "
            f"have found {round(pr * n_pos)} (recall {_pct(pr)})")
    if pr > 0 and mr >= pr:
        line += f" — Sideband found {mr / pr:.1f}× as many."
    elif mr < pr:
        line += " — the popularity baseline did better on this window, so treat these results with caution."
    else:
        line += "."
    lines.append(line)
    if m.get("auc") is not None:
        a, (npos, nneg) = m["auc"], m.get("auc_n", (0, 0))
        ci = m.get("auc_ci")
        lines.append(
            f"Preference accuracy within the mapped artists: shown one new artist you returned to and "
            f"one you consistently skipped, Sideband ranks the repeated one higher {_pct(a)} of the time"
            + (f" (95% CI {_pct(ci[0])}–{_pct(ci[1])})" if ci else "")
            + f"; guessing would be 50%. Based on {npos} adopted vs {nneg} rejected artists."
        )
    cov = m.get("coverage")
    if cov is not None and cov < 1:
        lines.append(f"{_pct(1 - cov)} of the artists you adopted were absent from the candidate pool. "
                     "They count as missed discoveries; the test cannot say how you found them.")
    lines.append(report["selection"]["reason"])
    return lines
