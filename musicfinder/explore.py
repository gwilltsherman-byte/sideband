"""Guided exploration of music outside your comfort zone.

Exploration is framed as a multi-armed bandit (explore vs. exploit): every unfamiliar genre near
your taste is an "arm" with a Beta posterior over "will you like music from here?". Its prior mean
comes from how well that genre's best artists score for you; your thumbs-up/down update it. Genres
are ordered by Thompson sampling (Thompson 1933; Chapelle & Li 2011), which mixes promising genres
with uncertain ones. Its hand-chosen prior and selectively collected votes guide exploration; they
are not a calibrated forecast. Rejected genres become less likely, not forbidden.

Within a genre we show *gateway artists*: the members of that genre that sit closest to what you
already love, which is the most reliable way into an unfamiliar style.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable

from musicfinder.feedback import latest_by_artist
from musicfinder.graph import KnowledgeGraph, cosine
from musicfinder.models import Feedback
from musicfinder.recommender import Candidate, ScoredPool
from musicfinder.taste import TasteProfile

FAMILIAR_SHARE = 0.03  # genres above this share of your listening are already "yours"


def genre_shares(profile: TasteProfile, kg: KnowledgeGraph, seeds: dict[str, float] | None = None) -> dict[str, float]:
    """Share of your (seed-weighted) listening that falls in each genre tag; sums to 1."""
    seeds = seeds if seeds is not None else profile.positive_seeds()
    acc: dict[str, float] = {}
    for s, w in seeds.items():
        tags = kg.tags.get(s) or {}
        total = sum(tags.values())
        if total <= 0:
            continue
        for t, x in tags.items():
            acc[t] = acc.get(t, 0.0) + w * x / total
    z = sum(acc.values())
    return {t: v / z for t, v in sorted(acc.items(), key=lambda kv: -kv[1])} if z else {}


@dataclass
class Territory:
    tag: str
    familiarity: float
    affinity: float
    distance: float
    gateways: list[Candidate]
    likes: int = 0
    dislikes: int = 0
    prior: tuple[float, float] = (1.0, 1.0)
    sample: float = 0.0
    neighbours: list[str] = field(default_factory=list)

    @property
    def posterior_mean(self) -> float:
        a, b = self.prior
        return (a + self.likes) / (a + b + self.likes + self.dislikes)

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "familiarity": round(self.familiarity, 4),
            "fit": round(self.affinity, 3),
            "distance": round(self.distance, 3),
            "predicted_like_rate": round(self.posterior_mean, 3),
            "estimate_kind": "exploration_heuristic", "calibrated": False,
            "likes": self.likes,
            "dislikes": self.dislikes,
            "related_genres_you_know": self.neighbours,
            "gateways": [c.to_dict() for c in self.gateways],
        }


def territory_feedback(feedback: Iterable[Feedback]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for fb in latest_by_artist(feedback).values():
        tag = (fb.context or {}).get("territory")
        if not isinstance(tag, str) or not tag.strip() or fb.verdict not in ("like", "dislike"):
            continue
        tag = tag.strip().casefold()
        rec = out.setdefault(tag, [0, 0])
        rec[0 if fb.verdict == "like" else 1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def territories(
    profile: TasteProfile,
    kg: KnowledgeGraph,
    pool: ScoredPool,
    feedback: Iterable[Feedback] = (),
    n: int = 8,
    per_territory: int = 4,
    min_artists: int = 3,
    rng: random.Random | None = None,
) -> list[Territory]:
    if n <= 0 or per_territory <= 0:
        return []
    rng = rng or random.Random()
    shares = genre_shares(profile, kg)
    fb = territory_feedback(feedback)
    members: dict[str, list[Candidate]] = {}
    for c in pool.candidates:
        for t, w in (kg.tags.get(c.key) or {}).items():
            if w >= 0.4:
                members.setdefault(t, []).append(c)
    familiar = [t for t, s in shares.items() if s >= FAMILIAR_SHARE]
    out: list[Territory] = []
    for tag, cs in members.items():
        if len(cs) < min_artists or shares.get(tag, 0.0) >= FAMILIAR_SHARE:
            continue
        cs = sorted(cs, key=lambda c: -c.score)
        gate = cs[:per_territory]
        affinity = sum(c.percentile for c in gate) / (100.0 * len(gate))
        centroid: dict[str, float] = {}
        for c in cs:
            for t, x in pool.tag_vectors.get(c.key, {}).items():
                centroid[t] = centroid.get(t, 0.0) + x
        norm = math.sqrt(sum(v * v for v in centroid.values())) or 1.0
        centroid = {t: v / norm for t, v in centroid.items()}
        distance = 1.0 - cosine(pool.user_tags, centroid)
        # co-occurring genres you already know: why this territory is "next door"
        co: dict[str, float] = {}
        for c in cs:
            for t, x in (kg.tags.get(c.key) or {}).items():
                if t != tag and t in familiar:
                    co[t] = co.get(t, 0.0) + x
        m = 0.15 + 0.65 * affinity
        prior = (4 * m, 4 * (1 - m))
        likes, dislikes = fb.get(tag, (0, 0))
        terr = Territory(tag, shares.get(tag, 0.0), affinity, distance, gate, likes, dislikes, prior,
                         neighbours=sorted(co, key=lambda t: -co[t])[:3])
        terr.sample = rng.betavariate(prior[0] + likes, prior[1] + dislikes)
        out.append(terr)
    out.sort(key=lambda t: -t.sample)
    # avoid near-duplicate territories (e.g. "doom metal" and "metal" with the same gateways)
    chosen: list[Territory] = []
    seen_gateways: set[str] = set()
    for terr in out:
        keys = {c.key for c in terr.gateways}
        if len(keys & seen_gateways) >= max(1, len(keys) // 2):
            continue
        terr.gateways = [c for c in terr.gateways if c.key not in seen_gateways] or terr.gateways
        seen_gateways |= keys
        chosen.append(terr)
        if len(chosen) >= n:
            break
    return chosen
