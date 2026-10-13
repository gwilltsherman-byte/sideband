import math
import random

import pytest

from musicfinder.feedback import calibration, feedback_stats, like_probability
from musicfinder.models import Feedback
from musicfinder.stats import (
    auc, bootstrap_ci, fit_logistic, mean_percentile_rank, ndcg_at_k, precision_at_k, recall_at_k, wilson_interval,
)


def test_auc():
    assert auc([3, 4], [1, 2]) == 1.0
    assert auc([1, 2], [3, 4]) == 0.0
    assert auc([1, 1], [1, 1]) == 0.5
    assert auc([2, 0], [1]) == 0.5
    assert auc([], [1]) is None


def test_ranking_metrics():
    ranked = ["a", "b", "c", "d"]
    assert recall_at_k(ranked, {"b", "z"}, 2) == 0.5
    assert precision_at_k(ranked, {"b", "z"}, 2) == 0.5
    assert ndcg_at_k(ranked, {"a"}, 3) == 1.0
    assert ndcg_at_k(ranked, {"b"}, 3) == pytest.approx(1 / math.log2(3))
    assert mean_percentile_rank(ranked, {"a"}) == 0.0
    assert mean_percentile_rank(ranked, {"d"}) == 100.0


def test_wilson_and_bootstrap():
    lo, hi = wilson_interval(8, 10)
    assert 0.45 < lo < 0.8 < hi < 0.97
    assert wilson_interval(0, 0) is None
    ci = bootstrap_ci(lambda s: sum(s) / len(s), [0, 1] * 50, n=300)
    assert ci[0] < 0.5 < ci[1]


def test_logistic_recovers_signal_and_prior_shrinks():
    rng = random.Random(0)
    x, y = [], []
    for _ in range(2000):
        a, b = rng.gauss(0, 1), rng.gauss(0, 1)
        p = 1 / (1 + math.exp(-(2.0 * a - 1.0 * b + 0.5)))
        x.append([a, b])
        y.append(1 if rng.random() < p else 0)
    w, b0 = fit_logistic(x, y, prior_precision=1e-6)
    assert w[0] == pytest.approx(2.0, abs=0.25) and w[1] == pytest.approx(-1.0, abs=0.2)
    assert b0 == pytest.approx(0.5, abs=0.2)
    # with three data points the prior (default weights) dominates
    w_small, _ = fit_logistic(x[:3], y[:3], prior_mean=[1.0, 1.0], prior_precision=50.0)
    assert all(abs(v - 1.0) < 0.2 for v in w_small)


def test_feedback_stats_and_calibration():
    fbs = []
    rng = random.Random(1)
    for i in range(60):
        m = rng.uniform(0, 100)
        liked = rng.random() < m / 100
        fbs.append(Feedback(f"A{i}", "like" if liked else "dislike", context={"match": m, "exploration": 0.1,
                                                                            "source": "recommendations"}))
    st = feedback_stats(fbs)
    assert st["overall"]["rated"] == 60 and st["overall"]["ci95"][0] < st["overall"]["like_rate"]
    cal = calibration(fbs)
    assert cal and cal["a"] > 0
    assert like_probability(95, cal) > like_probability(10, cal)
    assert calibration(fbs[:5]) is None
