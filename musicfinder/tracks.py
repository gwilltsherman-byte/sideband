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
    feedback: str | None = None
    context: dict | None = None

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


def song_seeds(profile: TasteProfile, n: int) -> list[TrackTaste]:
    """Strong songs across several artists, rather than one repeated album dominating every lookup."""
    if n <= 0:
        return []
    blocked = profile.blocked_artists()
    candidates = [t for t in profile.top_tracks(max(n * 8, 100)) if t.artist_key not in blocked]
    artists = {t.artist_key for t in candidates}
    cap = math.ceil(n / min(4, len(artists))) if artists else n
    counts: dict[str, int] = {}
    chosen: list[TrackTaste] = []
    overflow: list[TrackTaste] = []
    for t in candidates:
        if counts.get(t.artist_key, 0) >= cap:
            overflow.append(t)
            continue
        chosen.append(t)
        counts[t.artist_key] = counts.get(t.artist_key, 0) + 1
        if len(chosen) == n:
            break
    return (chosen + overflow)[:n]


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
    blocked = profile.blocked_artists()
    selected: set[tuple[str, str]] = set()

    def available(artist: str, title: str) -> bool:
        k = (artist_key(artist), track_key(title))
        return bool(k[0] and k[1] and k not in known_tracks and k not in selected and k[0] not in blocked)

    # 1. gateway songs of recommended new artists
    new_artist: list[TrackRec] = []
    heads = [c for c in artist_recs if c.key not in blocked][:max(0, n_new)]
    favs = [a for a in profile.top_artists(max(0, n_deep)) if a.key not in blocked]
    seeds = song_seeds(profile, seed_tracks)
    rejected = sorted((t for t in profile.tracks.values() if t.feedback == "dislike"),
                      key=lambda t: t.feedback_ts or profile.as_of, reverse=True)[:25]
    yield Need("top_tracks", [(c.name, 5) for c in heads] + [(a.name, 15) for a in favs], "Looking up songs")
    fav_tops = _parallel(lambda a: knowledge.top_tracks(a.name, 15), favs, workers)
    if len(seeds) < seed_tracks:
        # Favourite artists with no songs in the history (e.g. only picked in the app so far): start
        # from their best-known song.
        covered = {t.artist_key for t in seeds}
        for a, tops in zip(favs, fav_tops):
            tops = [t for t in tops if track_key(t.title) and artist_key(t.artist or a.name) not in blocked
                    and not getattr(profile.tracks.get((artist_key(t.artist or a.name), track_key(t.title))),
                                    "banned", False)
                    and getattr(profile.tracks.get((artist_key(t.artist or a.name), track_key(t.title))),
                                "feedback", None) != "dislike"]
            if a.key not in covered and tops and len(seeds) < seed_tracks:
                seeds.append(TrackTaste(a.key, track_key(tops[0].title), tops[0].title, tops[0].artist or a.name,
                                        explicit=a.affinity))
    yield Need("similar_tracks", [(t.artist, t.name, 50) for t in seeds + rejected],
               "Learning from songs you like and dislike")
    all_similar = _parallel(lambda t: knowledge.similar_tracks(t.artist, t.name, 50), seeds + rejected, workers)
    penalties: dict[tuple[str, str], float] = {}
    for sims in all_similar[len(seeds):]:
        for artist, title, match in sims:
            if isinstance(match, (int, float)) and not isinstance(match, bool) and math.isfinite(match) and match > 0:
                key = (artist_key(artist), track_key(title))
                penalties[key] = min(2.0, penalties.get(key, 0.0) + 0.6 * min(1.0, match))

    def factor(artist: str, title: str) -> float:
        return 1 / (1 + penalties.get((artist_key(artist), track_key(title)), 0.0))

    for rec, tops in zip(heads, _parallel(lambda c: knowledge.top_tracks(c.name, 5), heads, workers)):
        ranked = sorted(enumerate(tops), key=lambda it: -factor(it[1].artist or rec.name, it[1].title) / math.sqrt(it[0] + 1))
        for rank, t in ranked:
            if available(t.artist or rec.name, t.title):
                why = f"#{rank + 1} most-played song by {rec.name}"
                if rec.because:
                    why += f", who is similar to {', '.join(rec.because[:2])}"
                new_artist.append(TrackRec(t.title, t.artist or rec.name, rec.score, "new_artist", why, t.link))
                selected.add((artist_key(t.artist or rec.name), track_key(t.title)))
                break

    # 2. track-to-track CF from your favourite songs
    agg: dict[tuple[str, str], list] = {}
    results = all_similar[:len(seeds)]
    seed_keys = {(t.artist_key, t.key) for t in seeds}
    for seed, sims in zip(seeds, results):
        w = math.sqrt(seed.affinity)
        for artist, title, match in sims:
            k = (artist_key(artist), track_key(title))
            # (artist radio, used without Last.fm, also plays the seed artist's own songs: those are
            # in the third list, not "goes with" the seed)
            if (not available(artist, title) or k in seed_keys or k[0] == seed.artist_key
                    or not isinstance(match, (int, float)) or not math.isfinite(match) or match <= 0):
                continue
            entry = agg.setdefault(k, [artist, title, 0.0, None, 0.0])
            contrib = w * min(1.0, match) * factor(artist, title)
            entry[2] += contrib
            if contrib > entry[4]:
                entry[3], entry[4] = seed, contrib
    similar = sorted(agg.values(), key=lambda e: -e[2])
    similar_song: list[TrackRec] = []
    per_artist: dict[str, int] = {}
    for artist, title, score, seed, _ in similar:
        if len(similar_song) >= max(0, n_similar):
            break
        ak = artist_key(artist)
        if per_artist.get(ak, 0) >= 2:
            continue
        per_artist[ak] = per_artist.get(ak, 0) + 1
        similar_song.append(TrackRec(title, artist, score, "similar_song",
                                     f"Goes with “{seed.name}” by {seed.artist}, from your listening and favourites"))
        selected.add((ak, track_key(title)))

    # 3. unheard popular songs by artists you love
    deep_cut: list[TrackRec] = []
    for a, tops in zip(favs, fav_tops):
        ranked = sorted(enumerate(tops), key=lambda it: -factor(it[1].artist or a.name, it[1].title) / math.sqrt(it[0] + 1))
        for rank, t in ranked:
            if available(t.artist or a.name, t.title):
                why = (f"You play {a.name} ({a.streams} plays); this was not in your import, their "
                       f"#{rank + 1} most popular song" if a.streams
                       else (f"{a.name}’s #{rank + 1} most popular song (you picked {a.name} as a favourite)"
                             if a.picked else f"{a.name}’s #{rank + 1} most popular song (from your saved taste)"))
                deep_cut.append(TrackRec(t.title, t.artist or a.name,
                                         math.sqrt(a.affinity) / math.sqrt(rank + 1) * factor(t.artist or a.name, t.title),
                                         "deep_cut", why, t.link))
                selected.add((artist_key(t.artist or a.name), track_key(t.title)))
                break
    deep_cut.sort(key=lambda r: -r.score)
    groups = {
        "new_artist": [r.to_dict() for r in new_artist],
        "similar_song": [r.to_dict() for r in similar_song],
        "deep_cut": [r.to_dict() for r in deep_cut],
    }
    for songs in groups.values():
        for song in songs:
            t = profile.tracks.get((artist_key(song["artist"]), track_key(song["title"])))
            song["feedback"] = t.feedback if t else None
            song["context"] = {"source": "songs", "kind": song["kind"]}
            song["learned_penalty"] = round(penalties.get((artist_key(song["artist"]), track_key(song["title"])), 0), 3)
    return groups
