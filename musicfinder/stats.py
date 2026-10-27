"""Evaluation metrics, confidence intervals and a small regularised logistic regression (no numpy needed)."""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence


# ---- ranking metrics ----------------------------------------------------------------------------
def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked[:k]) & relevant) / k


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    dcg = sum(1.0 / math.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in relevant)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / idcg if idcg else 0.0


def mean_percentile_rank(ranked: Sequence[str], relevant: set[str]) -> float | None:
    """Hu, Koren & Volinsky (2008) 'expected percentile ranking': 0% = always top, 50% = random."""
    n = len(ranked)
    if n < 2:
        return None
    pos = {item: i for i, item in enumerate(ranked)}
    ranks = [100.0 * pos[r] / (n - 1) for r in relevant if r in pos]
    return sum(ranks) / len(ranks) if ranks else None


def auc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """Probability a random positive outscores a random negative (Mann-Whitney U), ties count half."""
    if not pos or not neg:
        return None
    labelled = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i, n = 0.0, 0, len(labelled)
    while i < n:
        j = i
        while j + 1 < n and labelled[j + 1][0] == labelled[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        rank_sum += avg_rank * sum(1 for t in range(i, j + 1) if labelled[t][1] == 1)
        i = j + 1
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


# ---- uncertainty --------------------------------------------------------------------------------
def bootstrap_ci(stat: Callable[[list], float | None], items: list, n: int = 1000, level: float = 0.95,
                 seed: int = 0) -> tuple[float, float] | None:
    """Percentile bootstrap CI of ``stat`` over resamples of ``items``."""
    if len(items) < 2 or n <= 0:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        v = stat([items[rng.randrange(len(items))] for _ in items])
        if v is not None:
            vals.append(v)
    if len(vals) < n // 2:
        return None
    vals.sort()
    lo = vals[int((1 - level) / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 + level) / 2 * len(vals)))]
    return lo, hi


def auc_ci(pos: list[float], neg: list[float], n: int = 1000, seed: int = 0) -> tuple[float, float] | None:
    if len(pos) < 2 or len(neg) < 2 or n <= 0:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        p = [pos[rng.randrange(len(pos))] for _ in pos]
        q = [neg[rng.randrange(len(neg))] for _ in neg]
        vals.append(auc(p, q))
    vals.sort()
    return vals[int(0.025 * n)], vals[min(n - 1, int(0.975 * n))]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion (well-behaved for small n)."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


# ---- logistic regression ------------------------------------------------------------------------
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            continue
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                if f:
                    for c in range(col, n + 1):
                        m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit_logistic(
    x: list[list[float]],
    y: list[int],
    sample_weight: list[float] | None = None,
    prior_mean: list[float] | None = None,
    prior_precision: float = 1.0,
    iters: int = 25,
) -> tuple[list[float], float]:
    """MAP logistic regression by Newton-Raphson with a Gaussian prior N(prior_mean, 1/prior_precision).

    Shrinking toward sensible default weights (instead of zero) means a listener with little data keeps
    the defaults, while a listener with a lot of history gets weights fitted to them.
    Returns (weights, intercept). The intercept is unpenalised.
    """
    n, d = len(x), len(x[0]) if x else 0
    sw = sample_weight or [1.0] * n
    mu0 = prior_mean or [0.0] * d
    w = list(mu0) + [0.0]  # last = intercept
    pos_w = sum(s for s, t in zip(sw, y) if t)
    tot_w = sum(sw)
    if 0 < pos_w < tot_w:
        w[-1] = math.log(pos_w / (tot_w - pos_w))
    for _ in range(iters):
        grad = [0.0] * (d + 1)
        hess = [[0.0] * (d + 1) for _ in range(d + 1)]
        for xi, yi, si in zip(x, y, sw):
            row = list(xi) + [1.0]
            z = sum(a * b for a, b in zip(w, row))
            p = 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))
            g = si * (p - yi)
            h = si * p * (1 - p)
            for i in range(d + 1):
                grad[i] += g * row[i]
                hi = h * row[i]
                if hi:
                    for j in range(i, d + 1):
                        hess[i][j] += hi * row[j]
        for i in range(d + 1):
            for j in range(i):
                hess[i][j] = hess[j][i]
        for i in range(d):
            grad[i] += prior_precision * (w[i] - mu0[i])
            hess[i][i] += prior_precision
        hess[d][d] += 1e-6
        step = _solve(hess, grad)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return w[:d], w[d]
