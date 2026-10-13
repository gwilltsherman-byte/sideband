"""The artist-similarity graph and the random walk that scores it.

Nodes are artists; an edge's weight blends the similarity judgements of every source that reported
it (Last.fm, ListenBrainz, Deezer). The graph is crawled outward from the listener's own artists, so
it only contains the neighbourhood that matters.

Scoring uses Personalized PageRank (random walk with restart; Haveliwala 2002) seeded with the
listener's affinities. Unlike plain "similar to X" lists it rewards candidates reachable from *many*
of your artists by *many* paths -- the graph analogue of "people who like what you like, also like".
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable

from musicfinder.normalize import artist_key, is_various
from musicfinder.sources import SOURCE_WEIGHTS
from musicfinder.sources.base import Knowledge, Neighbor
from musicfinder.steps import Need, Steps, run
from musicfinder.taste import TasteProfile

Progress = Callable[[str, int, int], None]


def _noop(step: str, done: int, total: int) -> None:  # pragma: no cover - trivial
    pass


@dataclass
class KnowledgeGraph:
    names: dict[str, str] = field(default_factory=dict)
    adj: dict[str, dict[str, float]] = field(default_factory=dict)
    agree: dict[tuple[str, str], int] = field(default_factory=dict)  # number of sources reporting the edge
    expanded: set[str] = field(default_factory=set)
    tags: dict[str, dict[str, float]] = field(default_factory=dict)
    popularity: dict[str, float] = field(default_factory=dict)
    tagged: set[str] = field(default_factory=set)  # nodes whose tags/popularity were fetched

    def add_node(self, name: str) -> str:
        k = artist_key(name)
        if k and k not in self.names:
            self.names[k] = name
            self.adj.setdefault(k, {})
        return k

    def add_neighbors(self, name: str, per_source: dict[str, list[Neighbor]]) -> None:
        """Blend each source's list into one weight per edge; keep the max of both directions."""
        src = self.add_node(name)
        self.expanded.add(src)
        answered = [s for s, lst in per_source.items() if lst]
        if not answered:
            return
        denom = sum(SOURCE_WEIGHTS.get(s, 0.5) for s in answered)
        blended: dict[str, float] = {}
        counts: dict[str, int] = {}
        for s in answered:
            beta = SOURCE_WEIGHTS.get(s, 0.5)
            for nb in per_source[s]:
                if is_various(nb.name):
                    continue
                k = self.add_node(nb.name)
                if not k or k == src:
                    continue
                blended[k] = blended.get(k, 0.0) + beta * max(0.0, min(1.0, nb.score))
                counts[k] = counts.get(k, 0) + 1
        for k, w in blended.items():
            w /= denom
            if w <= 0:
                continue
            if w > self.adj[src].get(k, 0.0):
                self.adj[src][k] = w
                self.adj[k][src] = w
            pair = (src, k) if src < k else (k, src)
            self.agree[pair] = max(self.agree.get(pair, 0), counts[k])

    def to_dict(self) -> dict:
        """Compact, JSON-friendly form (each undirected edge once), for saving the map between visits."""
        edges = [[a, b, round(w, 5)] for a, nb in self.adj.items() for b, w in nb.items() if a < b]
        return {
            "v": 1, "names": self.names, "edges": edges,
            "agree": [[a, b, n] for (a, b), n in self.agree.items()],
            "expanded": sorted(self.expanded), "tagged": sorted(self.tagged),
            "tags": {k: v for k, v in self.tags.items() if v}, "popularity": self.popularity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeGraph":
        kg = cls()
        kg.names = dict(d.get("names") or {})
        kg.adj = {k: {} for k in kg.names}
        for a, b, w in d.get("edges") or []:
            kg.adj.setdefault(a, {})[b] = w
            kg.adj.setdefault(b, {})[a] = w
        kg.agree = {(a, b): n for a, b, n in d.get("agree") or []}
        kg.expanded = set(d.get("expanded") or [])
        kg.tagged = set(d.get("tagged") or [])
        kg.tags = {k: dict(v) for k, v in (d.get("tags") or {}).items()}
        for k in kg.tagged:
            kg.tags.setdefault(k, {})
        kg.popularity = {k: float(v) for k, v in (d.get("popularity") or {}).items()}
        return kg

    def weight(self, a: str, b: str) -> float:
        return self.adj.get(a, {}).get(b, 0.0)

    def sources_agreeing(self, a: str, b: str) -> int:
        return self.agree.get((a, b) if a < b else (b, a), 0)

    def ppr(self, restart: dict[str, float], alpha: float = 0.3, iters: int = 50, tol: float = 1e-9) -> dict[str, float]:
        """Personalized PageRank by power iteration. ``alpha`` = restart probability."""
        total = sum(v for k, v in restart.items() if k in self.adj and v > 0)
        if total <= 0:
            return {}
        s = {k: v / total for k, v in restart.items() if k in self.adj and v > 0}
        deg = {k: sum(nb.values()) for k, nb in self.adj.items()}
        pi = dict(s)
        for _ in range(iters):
            nxt: dict[str, float] = {k: alpha * v for k, v in s.items()}
            dangling = 0.0
            for u, mass in pi.items():
                d = deg.get(u, 0.0)
                if d <= 0:
                    dangling += mass
                    continue
                share = (1 - alpha) * mass / d
                for v, w in self.adj[u].items():
                    nxt[v] = nxt.get(v, 0.0) + share * w
            if dangling:
                for k, v in s.items():
                    nxt[k] = nxt.get(k, 0.0) + (1 - alpha) * dangling * v
            delta = sum(abs(nxt.get(k, 0.0) - pi.get(k, 0.0)) for k in set(nxt) | set(pi))
            pi = nxt
            if delta < tol:
                break
        return pi


@dataclass(frozen=True)
class CrawlConfig:
    seeds: int = 60
    recent_seeds: int = 15
    negative_seeds: int = 20
    expand_candidates: int = 120
    tag_candidates: int = 300
    explore_candidates: int = 120  # 2-hop artists annotated for the Explore view
    workers: int = 6


def _fetch_all(names: list[str], fn, workers: int, progress: Progress, step: str):
    out = {}
    if not names:
        return out
    if workers <= 1:  # also the only option where threads are unavailable (the browser build)
        for i, name in enumerate(names, 1):
            out[name] = fn(name)
            progress(step, i, len(names))
        return out
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, result in zip(names, pool.map(fn, names)):
            out[name] = result
            done += 1
            progress(step, done, len(names))
    return out


def expand_steps(kg: KnowledgeGraph, knowledge: Knowledge, names: Iterable[str], workers: int = 6,
                 progress: Progress = _noop, step: str = "Reading similar artists") -> Steps[None]:
    """Fetch similar-artist lists for ``names`` (skipping ones already expanded) and add them to the graph."""
    todo = list(dict.fromkeys(n for n in names if artist_key(n) and artist_key(n) not in kg.expanded))
    if todo:
        yield Need("neighbors", todo, step)
        prefetch = getattr(knowledge, "prefetch", None)
        if prefetch is not None:  # e.g. look up ten artists per MusicBrainz request instead of one
            prefetch("neighbors", todo)
    results = _fetch_all(todo, knowledge.neighbors, workers, progress, step)
    for name in todo:
        kg.add_neighbors(name, results.get(name) or {})


def annotate_steps(kg: KnowledgeGraph, knowledge: Knowledge, names: Iterable[str], workers: int = 6,
                   progress: Progress = _noop, step: str = "Collecting genres and popularity") -> Steps[None]:
    """Fetch genre tags and popularity for ``names`` (skipping ones already annotated)."""
    todo = list(dict.fromkeys(n for n in names if artist_key(n) and artist_key(n) not in kg.tagged))
    if todo:
        yield Need("annotate", todo, step)
        prefetch = getattr(knowledge, "prefetch", None)
        if prefetch is not None:  # e.g. look up ten artists per MusicBrainz request instead of one
            prefetch("annotate", todo)
    results = _fetch_all(todo, lambda n: (knowledge.tags(n), knowledge.popularity(n)), workers, progress, step)
    for name in todo:
        k = kg.add_node(name)
        tags, pop = results.get(name) or ({}, None)
        kg.tags[k] = tags or {}
        if pop:
            kg.popularity[k] = float(pop)
        kg.tagged.add(k)


def expand(*args, **kwargs) -> None:
    run(expand_steps(*args, **kwargs))


def annotate(*args, **kwargs) -> None:
    run(annotate_steps(*args, **kwargs))


def crawl_steps(
    profile: TasteProfile,
    knowledge: Knowledge,
    cfg: CrawlConfig = CrawlConfig(),
    progress: Progress = _noop,
    extra_expand: Iterable[str] = (),
    extra_seed_profiles: Iterable[TasteProfile] = (),
    kg: KnowledgeGraph | None = None,
) -> Steps[KnowledgeGraph]:
    """Build (or extend) the similarity graph around a listener.

    1. expand the listener's top artists (all-time and recent) and the artists they reject;
    2. expand the most promising unknown neighbours, which adds the reverse edges and 2-hop structure;
    3. fetch genre tags and popularity for the strongest candidates.
    """
    kg = kg or KnowledgeGraph()
    known = profile.known_artists()

    seed_keys: dict[str, str] = {}
    for prof in (profile, *extra_seed_profiles):
        for k in list(prof.positive_seeds(cfg.seeds)) + list(prof.positive_seeds(cfg.recent_seeds, recent=True)):
            seed_keys.setdefault(k, prof.artists[k].name)
    for k, a in profile.artists.items():
        if a.feedback == "like":
            seed_keys.setdefault(k, a.name)
    negs = sorted(profile.negative_seeds().items(), key=lambda kv: -kv[1])[: cfg.negative_seeds]
    for k, _ in negs:
        seed_keys.setdefault(k, profile.artists[k].name)
    extra = list(extra_expand)
    for name in extra:
        seed_keys.setdefault(artist_key(name), name)

    yield from expand_steps(kg, knowledge, seed_keys.values(), cfg.workers, progress,
                            "Reading similar artists for your favourites")

    seeds = profile.positive_seeds(cfg.seeds)

    def most_promising(n: int) -> list[str]:
        score: dict[str, float] = {}
        for s, w in seeds.items():
            for c, sim in kg.adj.get(s, {}).items():
                if c not in known:
                    score[c] = score.get(c, 0.0) + w * sim
        return sorted(score, key=lambda c: -score[c])[:n]

    yield from expand_steps(kg, knowledge, [kg.names[c] for c in most_promising(cfg.expand_candidates)],
                            cfg.workers, progress, "Exploring the most promising new artists")
    top = most_promising(cfg.tag_candidates)
    # a second ring for exploration: unknown artists the random walk reaches beyond direct neighbours
    chosen = set(top)
    pi = kg.ppr(seeds, alpha=0.3) if cfg.explore_candidates else {}
    ring2 = [k for k in sorted(pi, key=lambda k: -pi[k]) if k not in known and k not in chosen]
    names = [kg.names[k] for k in seed_keys if k in kg.names] + [kg.names[c] for c in top]
    names += [kg.names[k] for k in ring2[: cfg.explore_candidates]]
    yield from annotate_steps(kg, knowledge, names, cfg.workers, progress, "Collecting genres and popularity")
    return kg


def crawl(*args, **kwargs) -> KnowledgeGraph:
    return run(crawl_steps(*args, **kwargs))


def idf_weights(kg: KnowledgeGraph) -> dict[str, float]:
    df: dict[str, int] = {}
    for tags in kg.tags.values():
        for t in tags:
            df[t] = df.get(t, 0) + 1
    n = max(1, sum(1 for t in kg.tags.values() if t))
    return {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}


def tag_vector(tags: dict[str, float], idf: dict[str, float]) -> dict[str, float]:
    v = {t: w * idf.get(t, 1.0) for t, w in tags.items()}
    norm = math.sqrt(sum(x * x for x in v.values()))
    return {t: x / norm for t, x in v.items()} if norm > 0 else {}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())
