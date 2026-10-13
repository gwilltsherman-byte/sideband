"""Song-level recommendations.

Three complementary sources, shown separately so it is always clear *why* a song is suggested:

* ``new_artist``   the most-played ("gateway") songs of the top recommended new artists;
* ``similar_song`` track-to-track collaborative filtering (Last.fm track.getSimilar) seeded by the
                   songs you engage with most, weighted by how much you love each seed song;
* ``deep_cut``     popular songs by artists you already love that you have never played.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from musicfinder.normalize import artist_key, track_key
from musicfinder.recommender import Candidate
from musicfinder.sources.base import Knowledge
from musicfinder.steps import Need, Steps, run
from musicfinder.taste import TasteProfile, TrackTaste


@dataclass
class TrackRec:
    title: str
    artist: str
    score: float
    kind: str
    because: str
    link: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(self.score, 4)
        return d


def _parallel(fn, items, workers: int):
    if not items:
        return []
    if workers <= 1:
        return [fn(it) for it in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def recommend_tracks(*args, **kwargs) -> dict[str, list[dict]]:
    return run(recommend_tracks_steps(*args, **kwargs))


def recommend_tracks_steps(
    profile: TasteProfile,
    knowledge: Knowledge,
    artist_recs: list[Candidate],
    n_new: int = 15,
    n_similar: int = 25,
    n_deep: int = 15,
    seed_tracks: int = 25,
    workers: int = 6,
) -> Steps[dict[str, list[dict]]]:
    known_tracks = profile.known_tracks()
    blocked = set(profile.negative_seeds())

    # 1. gateway songs of recommended new artists
    new_artist: list[TrackRec] = []
    heads = artist_recs[:n_new]
    favs = profile.top_artists(n_deep)
    seeds = profile.top_tracks(seed_tracks)
    yield Need("top_tracks", [(c.name, 5) for c in heads] + [(a.name, 15) for a in favs], "Looking up songs")
    fav_tops = _parallel(lambda a: knowledge.top_tracks(a.name, 15), favs, workers)
    if len(seeds) < seed_tracks:
        # Favourite artists with no songs in the history (e.g. only picked in the app so far): start
        # from their best-known song.
        covered = {t.artist_key for t in seeds}
        for a, tops in zip(favs, fav_tops):
            if a.key not in covered and tops and len(seeds) < seed_tracks:
                seeds.append(TrackTaste(a.key, track_key(tops[0].title), tops[0].title, tops[0].artist or a.name,
                                        explicit=a.affinity))
    yield Need("similar_tracks", [(t.artist, t.name, 50) for t in seeds], "Finding songs like your favourites")
    for rec, tops in zip(heads, _parallel(lambda c: knowledge.top_tracks(c.name, 5), heads, workers)):
        for t in tops:
            if (artist_key(t.artist or rec.name), track_key(t.title)) not in known_tracks:
                why = f"Most-played song by {rec.name}"
                if rec.because:
                    why += f", who is similar to {', '.join(rec.because[:2])}"
                new_artist.append(TrackRec(t.title, t.artist or rec.name, rec.score, "new_artist", why, t.link))
                break

    # 2. track-to-track CF from your favourite songs
    agg: dict[tuple[str, str], list] = {}
    results = _parallel(lambda t: knowledge.similar_tracks(t.artist, t.name, 50), seeds, workers)
    seed_keys = {(t.artist_key, t.key) for t in seeds}
    for seed, sims in zip(seeds, results):
        w = math.sqrt(seed.affinity)
        for artist, title, match in sims:
            k = (artist_key(artist), track_key(title))
            # (artist radio, used without Last.fm, also plays the seed artist's own songs: those are
            # in the third list, not "goes with" the seed)
            if k in known_tracks or k in seed_keys or k[0] == seed.artist_key or k[0] in blocked or not k[1]:
                continue
            entry = agg.setdefault(k, [artist, title, 0.0, None, 0.0])
            contrib = w * match
            entry[2] += contrib
            if contrib > entry[4]:
                entry[3], entry[4] = seed, contrib
    similar = sorted(agg.values(), key=lambda e: -e[2])
    similar_song: list[TrackRec] = []
    per_artist: dict[str, int] = {}
    for artist, title, score, seed, _ in similar:
        ak = artist_key(artist)
        if per_artist.get(ak, 0) >= 2:
            continue
        per_artist[ak] = per_artist.get(ak, 0) + 1
        similar_song.append(TrackRec(title, artist, score, "similar_song",
                                     f"Goes with “{seed.name}” by {seed.artist}, which you love"))
        if len(similar_song) >= n_similar:
            break

    # 3. unheard popular songs by artists you love
    deep_cut: list[TrackRec] = []
    for a, tops in zip(favs, fav_tops):
        for rank, t in enumerate(tops):
            if (a.key, track_key(t.title)) not in known_tracks:
                why = (f"You love {a.name} ({a.streams} plays) but have never played this, their "
                       f"#{rank + 1} most popular song" if a.streams
                       else f"{a.name}’s #{rank + 1} most popular song (you picked {a.name} as a favourite)")
                deep_cut.append(TrackRec(t.title, t.artist or a.name, math.sqrt(a.affinity) / math.sqrt(rank + 1),
                                         "deep_cut", why, t.link))
                break
    deep_cut.sort(key=lambda r: -r.score)
    return {
        "new_artist": [r.to_dict() for r in new_artist],
        "similar_song": [r.to_dict() for r in similar_song],
        "deep_cut": [r.to_dict() for r in deep_cut],
    }
