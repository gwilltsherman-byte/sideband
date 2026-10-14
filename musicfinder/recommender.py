"""Score every unknown artist in the graph and pick the list to show.

Each candidate gets eight interpretable features, standardised within the candidate pool:

  cf         item-based collaborative filtering: sum over your artists of affinity x similarity
  cf_recent  the same with a short (45-day) memory -- captures where your taste is heading now
  ppr        Personalized PageRank mass (multi-hop: friends-of-friends of your taste)
  support    how many of your artists independently point to the candidate
  tag        cosine similarity between the candidate's genre tags and your TF-IDF genre profile
  pop        log popularity (lets the model learn how mainstream *you* are)
  neg        similarity to artists you skip, hide or disliked (should push the score down)
  agree      how many independent sources agree on the similarity edges

The score is a linear model over those z-scores. Default weights are sensible priors; running the
backtest (``evaluation.py``) re-fits them to *your* history. Final lists are re-ranked with Maximal
Marginal Relevance (Carbonell & Goldstein, 1998) so they are not ten clones of one band, and an
``exploration`` dial trades predicted accuracy for novelty (less popular, less familiar genres).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from musicfinder.graph import KnowledgeGraph, cosine, idf_weights, tag_vector
from musicfinder.normalize import artist_key
from musicfinder.taste import TasteProfile

FEATURES = ("cf", "cf_recent", "ppr", "support", "tag", "pop", "neg", "agree")
DEFAULT_WEIGHTS: dict[str, float] = {
    "cf": 1.0, "cf_recent": 0.35, "ppr": 0.5, "support": 0.4, "tag": 0.6, "pop": -0.1, "neg": -0.4, "agree": 0.2,
}
FEATURE_LABELS = {
    "cf": "Similar to artists you play a lot",
    "cf_recent": "Similar to what you play lately",
    "ppr": "Central to your taste network",
    "support": "Linked from many of your artists",
    "tag": "Matches your genre profile",
    "pop": "Popularity",
    "neg": "Similar to music you dislike or skip",
    "agree": "Sources agree",
    "novelty": "Adventure setting",
}


@dataclass(frozen=True)
class ScoringParams:
    alpha: float = 0.3  # PPR restart probability
    weights: tuple[tuple[str, float], ...] = tuple(DEFAULT_WEIGHTS.items())
    exploration: float = 0.0  # 0 = safest bets, 1 = most adventurous
    diversity: float = 0.15  # MMR trade-off at exploration 0

    @property
    def weight_map(self) -> dict[str, float]:
        w = dict(DEFAULT_WEIGHTS)
        w.update(dict(self.weights))
        return w

    @staticmethod
    def from_weights(weights: dict[str, float], **kw) -> "ScoringParams":
        return ScoringParams(weights=tuple((f, float(weights.get(f, DEFAULT_WEIGHTS[f]))) for f in FEATURES), **kw)


@dataclass
class Candidate:
    key: str
    name: str
    raw: dict[str, float]
    z: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    percentile: float = 0.0
    because: list[str] = field(default_factory=list)
    shared_tags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    popularity: float | None = None
    support: int = 0
    contributions: dict[str, float] = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "score": round(self.score, 4),
            "match": round(self.percentile, 1), "because": self.because, "shared_tags": self.shared_tags,
            "rank_percentile": round(self.percentile, 1), "rank_label": "Relative rank among available candidates",
            "evidence": self.evidence,
            "tags": self.tags, "popularity": self.popularity, "support": self.support,
            "contributions": {FEATURE_LABELS[k]: round(v, 3) for k, v in self.contributions.items()},
        }


@dataclass
class ScoredPool:
    candidates: list[Candidate]  # sorted by score, best first
    user_tags: dict[str, float]
    tag_vectors: dict[str, dict[str, float]]

    def ranked_keys(self) -> list[str]:
        return [c.key for c in self.candidates]

    def by_key(self) -> dict[str, Candidate]:
        return {c.key: c for c in self.candidates}


def _standardise(values: list[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    mu = sum(values) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in values) / n)
    if sd < 1e-9:
        return [0.0] * n
    return [(v - mu) / sd for v in values]


def user_tag_profile(profile: TasteProfile, kg: KnowledgeGraph, seeds: dict[str, float] | None = None,
                     idf: dict[str, float] | None = None) -> dict[str, float]:
    idf = idf if idf is not None else idf_weights(kg)
    seeds = seeds if seeds is not None else profile.positive_seeds()
    acc: dict[str, float] = {}
    for s, w in seeds.items():
        for t, x in tag_vector(kg.tags.get(s, {}), idf).items():
            acc[t] = acc.get(t, 0.0) + w * x
    norm = math.sqrt(sum(v * v for v in acc.values()))
    return {t: v / norm for t, v in acc.items()} if norm > 0 else {}


def score_pool(
    profile: TasteProfile,
    kg: KnowledgeGraph,
    params: ScoringParams = ScoringParams(),
    exclude: Iterable[str] = (),
    include: Iterable[str] = (),
    hops: int = 1,
) -> ScoredPool:
    """Score unknown artists adjacent to the listener's taste (``hops=2``: every unknown artist in the
    graph reachable from the listener, including neighbours-of-neighbours), plus any keys in
    ``include`` that are not known or explicitly excluded."""
    seeds = {k: v for k, v in profile.positive_seeds().items() if k in kg.adj}
    recent = {k: v for k, v in profile.positive_seeds(recent=True).items() if k in kg.adj}
    negs = {k: v for k, v in profile.negative_seeds().items() if k in kg.adj}
    known = profile.known_artists() | {artist_key(e) for e in exclude}
    seed_total = sum(seeds.values()) or 1.0
    recent_total = sum(recent.values()) or 1.0

    exploration = max(0.0, min(1.0, params.exploration))
    alpha = max(0.05, min(0.95, params.alpha * (1 - 0.5 * exploration)))
    pi = kg.ppr(seeds, alpha=alpha) if seeds else {}
    pool: set[str] = set()
    if hops >= 2:
        # A previously searched, disconnected genre must not quietly become a personalised
        # recommendation. Explicit genre search can still include those artists below.
        pool.update(c for c, mass in pi.items() if mass > 0 and c not in known)
    else:
        for s in seeds:
            pool.update(c for c in kg.adj[s] if c not in known)
    pool.update(k for name in include if (k := artist_key(name)) in kg.adj and k not in known)
    idf = idf_weights(kg)
    utags = user_tag_profile(profile, kg, seeds, idf)

    keys = sorted(pool)
    raw_rows: list[dict[str, float]] = []
    tag_vecs: dict[str, dict[str, float]] = {}
    meta: dict[str, tuple[list[str], int]] = {}
    for c in keys:
        nb = kg.adj.get(c, {})
        contrib = [(s, seeds[s] * w) for s, w in nb.items() if s in seeds]
        cf = sum(x for _, x in contrib) / seed_total
        cfr = sum(recent[s] * w for s, w in nb.items() if s in recent) / recent_total
        neg = sum(negs[n] * w for n, w in nb.items() if n in negs)
        agree_w = sum(x * kg.sources_agreeing(c, s) for s, x in contrib)
        agree = agree_w / sum(x for _, x in contrib) if contrib else 0.0
        tv = tag_vector(kg.tags.get(c, {}), idf)
        tag_vecs[c] = tv
        pop = kg.popularity.get(c)
        valid_pop = isinstance(pop, (int, float)) and not isinstance(pop, bool) and math.isfinite(pop) and pop >= 0
        raw_rows.append({
            "cf": math.log(cf + 1e-6),
            "cf_recent": math.log(cfr + 1e-6),
            "ppr": math.log(pi.get(c, 0.0) + 1e-12),
            "support": math.log1p(len(contrib)),
            "tag": cosine(utags, tv) if tv and utags else math.nan,
            "pop": math.log10(1 + pop) if valid_pop else math.nan,
            "neg": math.log1p(10 * neg),
            "agree": agree,
        })
        contrib.sort(key=lambda x: -x[1])
        meta[c] = ([kg.names.get(s, s) for s, _ in contrib[:3]], len(contrib))

    # impute missing tag/popularity with the pool mean (the uninformative value after standardising)
    for f in ("tag", "pop"):
        vals = [r[f] for r in raw_rows if not math.isnan(r[f])]
        fill = sum(vals) / len(vals) if vals else 0.0
        for r in raw_rows:
            if math.isnan(r[f]):
                r[f] = fill
    zcols = {f: _standardise([r[f] for r in raw_rows]) for f in FEATURES}
    w = params.weight_map
    novelty_w = {"pop": -0.8, "tag": -0.5, "support": -0.2}
    cands = []
    for i, c in enumerate(keys):
        z = {f: zcols[f][i] for f in FEATURES}
        contributions = {f: w[f] * z[f] for f in FEATURES if w[f]}
        score = sum(contributions.values())
        if exploration:
            novelty = exploration * sum(novelty_w[f] * z[f] for f in novelty_w)
            # Novelty is a bounded rerank, so a metadata outlier cannot outweigh every taste
            # signal. Keep it visible in the explanation rather than concealing its contribution.
            novelty = max(-1.5, min(1.5, novelty))
            score += novelty
            contributions["novelty"] = novelty
        tv = tag_vecs[c]
        shared = sorted((t for t in tv if utags.get(t, 0) > 0), key=lambda t: -tv[t] * utags[t])[:3]
        because, support = meta[c]
        cands.append(Candidate(
            key=c, name=kg.names.get(c, c), raw=raw_rows[i], z=z, score=score, because=because,
            shared_tags=shared, tags=sorted(kg.tags.get(c, {}), key=lambda t: -kg.tags[c][t])[:5],
            popularity=(kg.popularity[c] if isinstance(kg.popularity.get(c), (int, float))
                        and math.isfinite(kg.popularity[c]) and kg.popularity[c] >= 0 else None),
            support=support, contributions=contributions,
            evidence={"direct_links": support,
                      "source_agreement": round(raw_rows[i]["agree"], 2),
                      "genre_overlap": bool(shared),
                      "basis": "direct_links" if support else "indirect_graph" if pi.get(c, 0) > 0 else "genre_search",
                      "calibrated": False},
        ))
    cands.sort(key=lambda x: -x.score)
    n = len(cands)
    start = 0
    while start < n:
        end = start + 1
        while end < n and math.isclose(cands[start].score, cands[end].score, abs_tol=1e-12):
            end += 1
        # Midpoint ranks give equal scores equal labels; a lone candidate is a 50th-percentile
        # rank, not "100% likely to like". This remains a relative rank, never confidence.
        percentile = 100.0 * (1 - (start + end) / (2 * n))
        for cand in cands[start:end]:
            cand.percentile = percentile
        start = end
    return ScoredPool(cands, utags, tag_vecs)


def diversify(pool: ScoredPool, kg: KnowledgeGraph, n: int, lam: float) -> list[Candidate]:
    """Greedy MMR: trade relevance against similarity to what is already on the list."""
    if n <= 0:
        return []
    lam = max(0.0, min(0.8, lam))
    head = pool.candidates[: max(3 * n, 60)]
    if lam <= 0 or len(head) <= 1:
        return head[:n]
    hi, lo = head[0].score, head[-1].score
    span = (hi - lo) or 1.0
    rel = {c.key: (c.score - lo) / span for c in head}
    chosen: list[Candidate] = []
    remaining = list(head)
    sim_cache: dict[str, float] = {c.key: 0.0 for c in head}
    while remaining and len(chosen) < n:
        best = max(remaining, key=lambda c: (1 - lam) * rel[c.key] - lam * sim_cache[c.key])
        chosen.append(best)
        remaining.remove(best)
        bt = pool.tag_vectors.get(best.key, {})
        for c in remaining:
            s = max(cosine(bt, pool.tag_vectors.get(c.key, {})), kg.weight(best.key, c.key))
            if s > sim_cache[c.key]:
                sim_cache[c.key] = s
    return chosen


def recommend(
    profile: TasteProfile,
    kg: KnowledgeGraph,
    params: ScoringParams = ScoringParams(),
    n: int = 30,
    exclude: Iterable[str] = (),
) -> list[Candidate]:
    pool = score_pool(profile, kg, params, exclude=exclude)
    lam = min(0.8, params.diversity + 0.45 * params.exploration)
    return diversify(pool, kg, n, lam)
