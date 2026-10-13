"""Accuracy safeguards: future identities, sparse labels, fitting and fair baselines."""

from datetime import datetime, timedelta, timezone

import pytest

from musicfinder.evaluation import (
    EvalConfig, ModelConfig, _expected_random, _fit_weights, _model_metrics, _ranking_metrics,
    _run_phase_steps, backtest, fit_weights, ground_truth,
)
from musicfinder.graph import CrawlConfig, KnowledgeGraph
from musicfinder.models import Play
from musicfinder.recommender import Candidate, FEATURES, ScoredPool, ScoringParams
from musicfinder.sources.base import Neighbor
from musicfinder.stats import auc_ci
from musicfinder.steps import run
from musicfinder.taste import TasteParams

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def play(name, day, skipped=False, neutral=False):
    return Play(T0 + timedelta(days=day), name, "song", ms_played=8_000 if skipped or neutral else 180_000,
                skipped=skipped, reason_end="fwdbtn" if skipped else "endplay" if neutral else "trackdone")


class Catalog:
    sources = ["test"]

    def __init__(self):
        self.expanded = []

    def neighbors(self, name):
        self.expanded.append(name)
        return {"test": [Neighbor("Adopted", 0.9), Neighbor("Rejected", 0.2)]} if name == "Seed" else {}

    def tags(self, name):
        return {"indie": 1.0}

    def popularity(self, name):
        return 100.0


FAST_CRAWL = CrawlConfig(seeds=1, recent_seeds=0, negative_seeds=0, expand_candidates=0,
                         tag_candidates=0, explore_candidates=0, workers=1)


def test_ground_truth_is_order_independent_and_neutral_stops_are_not_rejection():
    cutoff, end = T0 + timedelta(days=10), T0 + timedelta(days=30)
    plays = [play("Previously heard", d) for d in (11, 12, 13)] + [play("Previously heard", 1)]
    plays += [play("Interrupted", 11, skipped=True), play("Interrupted", 12, neutral=True)]
    plays += [play("Actually rejected", 12, skipped=True)]
    forward, reverse = ground_truth(plays, cutoff, end), ground_truth(plays[::-1], cutoff, end)
    assert forward == reverse
    assert not forward.adopted
    assert forward.rejected == {"actually rejected": "Actually rejected"}


def test_repeated_qualifying_late_skips_do_not_establish_adoption():
    plays = [Play(T0 + timedelta(days=d), "Late skips", "song", ms_played=60_000,
                  skipped=True, reason_end="fwdbtn") for d in (11, 12, 13)]
    truth = ground_truth(plays, T0 + timedelta(days=10), T0 + timedelta(days=30))
    assert not truth.adopted and not truth.rejected


def test_future_outcome_artists_do_not_expand_history_graph_or_become_training_negatives():
    plays = [play("Seed", 1)] + [play("Adopted", d) for d in (11, 12, 13)]
    plays += [play("Unreachable", d) for d in (11, 12, 13)] + [play("Rejected", 11, skipped=True)]
    catalog = Catalog()
    mc = ModelConfig(TasteParams(), 0.3)
    cfg = EvalConfig(bootstrap=0)
    out = run(_run_phase_steps(plays, T0 + timedelta(days=10), T0 + timedelta(days=30), catalog,
                               [mc], cfg, FAST_CRAWL, lambda *_: None, "Test", collect_rows=True))
    assert catalog.expanded == ["Seed"]
    assert "unreachable" not in out.kg.names
    m = out.results[0][1]
    assert m["coverage"] == 0.5
    assert m["auc_n"] == (1, 1)
    assert m["preference_coverage"] == pytest.approx(2 / 3)
    assert m["auc_ci"] is None
    assert sorted(y for _, y, _ in out.rows[mc]) == [0, 1]


def test_unreachable_discoveries_count_as_misses_when_selecting_settings():
    m = _ranking_metrics(["adopted", "other"], {"adopted", "missing"}, (1, 50), 0, 0)
    assert m["retrieved_mean_percentile_rank"] == 0
    assert m["mean_percentile_rank"] == 50
    assert m["recall@50"] == 0.5


def test_random_baseline_uses_same_short_list_denominator_and_missing_discoveries():
    m = _expected_random(2, 1, 2, (1, 50))
    assert m["recall@50"] == 0.5
    assert m["precision@50"] == 0.02
    assert m["mean_percentile_rank"] == 75
    assert 0 < m["ndcg@50"] < 1
    assert _expected_random(1, 1, 1, (50,))["mean_percentile_rank"] == 0
    assert _expected_random(0, 0, 1, (50,))["mean_percentile_rank"] == 100
    assert auc_ci([1, 2], [3, 4], n=0) is None


def test_report_grades_the_diversified_list_actually_generated_for_each_depth(monkeypatch):
    import musicfinder.evaluation as evaluation

    a = Candidate("a", "A", {}, score=2)
    b = Candidate("b", "B", {}, score=1)
    pool = ScoredPool([a, b], {}, {})
    lengths = []

    def selected(_pool, _kg, n, _lam):
        lengths.append(n)
        return [b, a][:n]

    monkeypatch.setattr(evaluation, "diversify", selected)
    m = _model_metrics(pool, KnowledgeGraph(), {"b"}, EvalConfig(ks=(1, 2), bootstrap=0), ScoringParams(), 0)
    assert m["recall@1"] == 1
    assert {1, 2, 50} <= set(lengths)


def pop_row(value, verdict, weight=1.0):
    x = [0.0] * len(FEATURES)
    x[FEATURES.index("pop")] = value
    return x, verdict, weight


def test_weight_fit_does_not_treat_unheard_artists_as_observed_dislikes():
    rows = [pop_row(1, 1)] * 30 + [pop_row(-1, 0, 0.3)] * 1500
    learned, evidence = _fit_weights(rows, EvalConfig())
    assert learned is None
    assert evidence["positives"] == 30 and evidence["negatives"] == 0


def test_fitting_needs_both_classes_and_separate_validation_benefit():
    assert fit_weights([pop_row(1, 1)] * 50, EvalConfig()) is None
    # Defaults already prefer the lower-popularity artists here; re-fitting cannot improve them.
    assert fit_weights([pop_row(-1, 1)] * 30 + [pop_row(1, 0)] * 30, EvalConfig()) is None
    learned, evidence = _fit_weights([pop_row(1, 1)] * 30 + [pop_row(-1, 0)] * 30, EvalConfig())
    assert learned and learned["pop"] > 0
    assert evidence["accepted"] and evidence["holdout_gain"] > 0
    assert evidence["holdout_positives"] == evidence["holdout_negatives"] == 10


def test_sparse_validation_keeps_defaults_without_grading_test_to_choose():
    plays = [play("Seed", 0), play("Seed", 70)] + [play("Adopted", d) for d in (95, 96, 97)]
    plays += [play("Rejected", 96, skipped=True), play("Seed", 120)]
    rep = backtest(plays, Catalog(), EvalConfig(half_lives=(60,), seed_powers=(1,), alphas=(0.4,), bootstrap=0),
                   FAST_CRAWL)
    assert rep["ok"]
    assert not rep["selection"]["validated"]
    assert not rep["chosen_is_personalised"]
    assert rep["chosen"]["memory_half_life_days"] == 365
    assert rep["chosen"]["restart_probability"] == 0.3
    assert rep["limitations"]
