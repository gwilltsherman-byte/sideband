"""Graph, scoring, exploration and the scientific validation against planted ground truth."""

import random
import statistics
from datetime import timedelta

import pytest

from musicfinder.evaluation import EvalConfig, backtest, ground_truth
from musicfinder.explore import territories
from musicfinder.graph import CrawlConfig, KnowledgeGraph, cosine, crawl
from musicfinder.recommender import FEATURES, ScoringParams, diversify, recommend, score_pool
from musicfinder.sources.base import Neighbor
from musicfinder.stats import auc, fit_logistic
from musicfinder.taste import build_profile


def test_edge_blending_and_symmetry():
    kg = KnowledgeGraph()
    kg.add_neighbors("A", {"lastfm": [Neighbor("B", 1.0), Neighbor("C", 0.5)], "deezer": [Neighbor("B", 0.9)]})
    assert kg.weight("a", "b") == kg.weight("b", "a")
    assert kg.weight("a", "b") > kg.weight("a", "c")  # two sources agree on B
    assert kg.sources_agreeing("a", "b") == 2 and kg.sources_agreeing("a", "c") == 1
    kg.add_neighbors("C", {"lastfm": [Neighbor("A", 0.9)]})
    assert kg.weight("a", "c") == pytest.approx(0.9)  # max of both directions


def test_ppr_is_a_distribution_and_personalised():
    kg = KnowledgeGraph()
    kg.add_neighbors("A", {"x": [Neighbor("B", 1.0), Neighbor("C", 0.2)]})
    kg.add_neighbors("D", {"x": [Neighbor("E", 1.0)]})
    pi = kg.ppr({"a": 1.0}, alpha=0.3)
    assert sum(pi.values()) == pytest.approx(1.0, abs=1e-6)
    assert pi["a"] > pi["b"] > pi["c"]
    assert pi.get("e", 0.0) == 0.0  # unreachable from the seed


@pytest.fixture(scope="module")
def setup(world, plays):
    from musicfinder.synthetic import SyntheticKnowledge

    prof = build_profile(plays)
    kg = crawl(prof, SyntheticKnowledge(world))
    return prof, kg


def test_known_artists_never_recommended(setup):
    prof, kg = setup
    recs = recommend(prof, kg, n=50)
    assert recs and not {r.key for r in recs} & prof.known_artists()


def test_recommendations_match_planted_taste(setup, world, listener):
    """Core scientific check: the simulated listener's *true* like-probability of what we recommend."""
    prof, kg = setup
    recs = recommend(prof, kg, n=30)
    rec_p = statistics.mean(listener.like_prob(world.by_key[r.key]) for r in recs)
    unknown = [a for a in world.artists if a.key not in prof.known_artists()]
    base_p = statistics.mean(listener.like_prob(a) for a in unknown)
    oracle = statistics.mean(sorted((listener.like_prob(a) for a in unknown), reverse=True)[:30])
    assert rec_p > 3 * base_p
    assert rec_p > 0.75 * oracle
    # Across the whole candidate pool (a much harder, fine-grained ranking task), compare the default
    # model against the best *any* linear model on these features could do, fitted in-sample on the truth.
    pool = score_pool(prof, kg)
    labels = [1 if listener.like_prob(world.by_key[c.key]) >= 0.5 else 0 for c in pool.candidates]
    ours = auc([c.score for c, y in zip(pool.candidates, labels) if y],
               [c.score for c, y in zip(pool.candidates, labels) if not y])
    x = [[c.z[f] for f in FEATURES] for c in pool.candidates]
    w, _ = fit_logistic(x, labels, prior_precision=0.5)
    oracle_scores = [sum(a * b for a, b in zip(w, row)) for row in x]
    ceiling = auc([s for s, y in zip(oracle_scores, labels) if y], [s for s, y in zip(oracle_scores, labels) if not y])
    assert ours > 0.55
    assert ours >= ceiling - 0.12


def test_negative_feature_pushes_down(setup):
    prof, kg = setup
    pool = score_pool(prof, kg, ScoringParams.from_weights({"neg": -3.0}))
    base = score_pool(prof, kg)
    near_neg = [c.key for c in base.candidates if c.raw["neg"] > 0]
    if not near_neg:
        pytest.skip("no candidate near a rejected artist")
    rank = lambda p: {c.key: i for i, c in enumerate(p.candidates)}  # noqa: E731
    r_base, r_neg = rank(base), rank(pool)
    assert statistics.mean(r_neg[k] for k in near_neg) > statistics.mean(r_base[k] for k in near_neg)


def test_exploration_trades_popularity_and_diversity(setup):
    prof, kg = setup
    safe = recommend(prof, kg, ScoringParams(exploration=0.0), n=30)
    wild = recommend(prof, kg, ScoringParams(exploration=1.0), n=30)
    pop = lambda lst: statistics.median(c.popularity or 0 for c in lst)  # noqa: E731
    assert pop(wild) < pop(safe)
    assert {r.key for r in wild} != {r.key for r in safe}


def test_mmr_reduces_redundancy(setup):
    prof, kg = setup
    pool = score_pool(prof, kg)
    plain = diversify(pool, kg, 20, 0.0)
    div = diversify(pool, kg, 20, 0.7)
    def redundancy(lst):
        sims = [max(cosine(pool.tag_vectors[a.key], pool.tag_vectors[b.key]), kg.weight(a.key, b.key))
                for i, a in enumerate(lst) for b in lst[i + 1:]]
        return sum(sims) / len(sims)
    assert redundancy(div) < redundancy(plain)
    assert len({c.tags[0] for c in div if c.tags}) >= len({c.tags[0] for c in plain if c.tags})


def test_territories_are_unfamiliar_and_thompson_ordered(setup):
    prof, kg = setup
    pool = score_pool(prof, kg, hops=2)
    terrs = territories(prof, kg, pool, rng=random.Random(0))
    assert terrs
    for t in terrs:
        assert t.familiarity < 0.03 and t.gateways
        assert all(g.key not in prof.known_artists() for g in t.gateways)
    samples = [t.sample for t in terrs]
    assert samples == sorted(samples, reverse=True)


def test_ground_truth_has_no_leakage(plays):
    end = plays[-1].ts
    cutoff = end.replace(microsecond=0) - (end - plays[0].ts) / 8
    truth = ground_truth(plays, cutoff, end)
    before = {p.artist_key for p in plays if p.ts < cutoff}
    assert truth.adopted and not set(truth.adopted) & before
    assert not set(truth.rejected) & before
    assert not set(truth.adopted) & set(truth.rejected)


def test_backtest_beats_baselines(plays, knowledge):
    cfg = EvalConfig(half_lives=(60.0, 365.0), seed_powers=(0.5,), alphas=(0.3,), bootstrap=200)
    rep = backtest(plays, knowledge, cfg, CrawlConfig())
    assert rep["ok"] and rep["enough_data"]
    m, b = rep["model"], rep["baselines"]
    assert m["auc"] > 0.8
    assert m["recall@50"] > b["popularity"]["recall@50"]
    assert m["recall@50"] > b["random"]["recall@50"]
    assert m["mean_percentile_rank"] < 30  # 50 would be random
    assert rep["summary"] and rep["windows"]["test"][0] > rep["windows"]["validation"][0]
    curve = b["exploration_tradeoff"]
    assert curve[0]["recall@50"] >= curve[-1]["recall@50"]


def test_backtest_refuses_too_little_history(plays, knowledge):
    cutoff = plays[-1].ts - timedelta(days=30)
    rep = backtest([p for p in plays if p.ts > cutoff], knowledge)
    assert not rep["ok"] and "days" in rep["reason"]
