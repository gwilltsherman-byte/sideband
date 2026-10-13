"""A simulated music universe and listener with *known* ground-truth taste.

Real listening logs never reveal what someone would have liked had they heard it, so the only way to
check a recommender against the truth is simulation. This module builds:

* a catalogue of artists embedded in a latent "style space" (genre families -> genres -> artists),
* Last.fm-like and Deezer-like similar-artist lists derived from that space plus noise and a
  popularity bias (as in real CF data),
* a listener whose probability of liking an artist is a known function of the style space, whose
  taste drifts over time, and who discovers music mostly through similarity-driven radio/autoplay,
  producing a Spotify *Extended Streaming History* with realistic skips.

It powers the test-suite (does the engine recover the planted taste better than baselines?) and the
offline ``--demo`` mode of the app.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from musicfinder.normalize import artist_key, track_key
from musicfinder.sources.base import Neighbor, TrackInfo

# (genre, family, tags)
GENRES: list[tuple[str, str, list[str]]] = [
    ("indie rock", "rock", ["indie rock", "indie", "alternative rock"]),
    ("shoegaze", "rock", ["shoegaze", "dream pop", "noise pop"]),
    ("post-punk", "rock", ["post-punk", "new wave", "darkwave"]),
    ("classic rock", "rock", ["classic rock", "hard rock", "blues rock"]),
    ("metal", "rock", ["metal", "heavy metal", "doom metal"]),
    ("dream pop", "pop", ["dream pop", "indie pop", "ethereal"]),
    ("synthpop", "pop", ["synthpop", "electropop", "new wave"]),
    ("k-pop", "pop", ["k-pop", "dance pop", "pop"]),
    ("singer songwriter", "roots", ["singer songwriter", "folk", "acoustic"]),
    ("indie folk", "roots", ["indie folk", "folk", "chamber pop"]),
    ("country", "roots", ["country", "americana", "alt-country"]),
    ("house", "electronic", ["house", "deep house", "dance"]),
    ("techno", "electronic", ["techno", "minimal techno", "industrial"]),
    ("ambient", "electronic", ["ambient", "drone", "electronic"]),
    ("idm", "electronic", ["idm", "electronic", "glitch"]),
    ("hip hop", "urban", ["hip hop", "boom bap", "conscious hip hop"]),
    ("trap", "urban", ["trap", "hip hop", "southern hip hop"]),
    ("rnb", "urban", ["rnb", "neo-soul", "soul"]),
    ("jazz", "jazz", ["jazz", "hard bop", "modal jazz"]),
    ("jazz fusion", "jazz", ["jazz fusion", "jazz", "funk"]),
    ("soul", "jazz", ["soul", "funk", "motown"]),
    ("classical", "classical", ["classical", "romantic", "orchestral"]),
    ("modern classical", "classical", ["modern classical", "minimalism", "piano"]),
    ("bossa nova", "global", ["bossa nova", "mpb", "latin"]),
    ("reggaeton", "global", ["reggaeton", "latin", "urbano latino"]),
    ("afrobeats", "global", ["afrobeats", "afropop", "dance"]),
]

_ADJ = ("Velvet Hollow Neon Paper Silver Midnight Glass Wild Golden Static Quiet Electric Lunar Crimson "
        "Northern Painted Broken Gentle Wandering Hidden Burning Frozen Distant Secret Restless Copper Amber "
        "Ivory Scarlet Cosmic Lucid Feral Tender Solar Rusty Marble Phantom Violet Cobalt Hazy").split()
_NOUN = ("Owls Coast Harbor Machines Gardens Ghosts Tides Echoes Parade Satellites Rivers Lanterns Wolves "
         "Arcade Signals Mirrors Orchards Comets Engines Islands Pilots Saints Rooms Horses Canyons Atlas "
         "Choir Weather Season Motel Fountain Circuit Meadow Tower Bloom Ferns Cartel Ocean").split()
_FIRST = ("Mara Jonas Ines Theo Ada Felix Noor Ruben Lila Oskar Yara Milo Eva Kofi Sana Arlo Nina Elio "
          "Juno Iris Tomas Leni Aiko Dario Wren Bea Cyrus Odile Rafa Signe").split()
_LAST = ("Lindqvist Moreau Okafor Varga Castell Brandt Nakamura Quinn Alvarez Holm Sato Petrova Delacroix "
         "Mbeki Ferreira Kowalski Haddad Larsen Ricci Novak Abara Silva Weller Dunmore Ibarra Kaur").split()
_TITLE_A = ("Blue Slow Last Summer Paper Cold Golden Little Neon Quiet Endless Silver Late Falling Open "
            "Tiny Wild Lost Bright Hollow Second Electric").split()
_TITLE_B = ("Hours Light Hearts Song Lines Rain Signals Waves Morning Dreams Fever Static Avenue Window "
            "Letters Weather Bloom Motion Glow Heat Rooms Season").split()

_SYLL = "ka lo mi ra ve su no ta li do fe ri sa mo ne vi ar el on ul zi bo ma te".split()

DIM = 24


def _coined(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLL) for _ in range(rng.randint(2, 3))).capitalize()


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class SynthArtist:
    name: str
    key: str
    genre: str
    family: str
    vec: list[float]
    listeners: float
    tags: dict[str, float]
    tracks: list[str]


@dataclass
class World:
    artists: list[SynthArtist]
    genre_vecs: dict[str, list[float]]
    lfm: dict[str, list[Neighbor]] = field(default_factory=dict)
    dz: dict[str, list[Neighbor]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_key = {a.key: a for a in self.artists}


def _similar_candidates(artists: list["SynthArtist"], popz: list[float], seed: int, k: int = 120):
    """For each artist, the k most similar others under noisy, popularity-biased similarity.

    Returns rows of (noisy_score, true_similarity, index). Uses numpy when available (fast);
    otherwise a pure-Python path that only compares artists within the same genre family.
    """
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        v = np.asarray([a.vec for a in artists])
        pz = np.asarray(popz)
        nrng = np.random.default_rng(seed)
        rows = []
        for start in range(0, len(artists), 256):
            block = v[start:start + 256] @ v.T
            noisy = block + nrng.normal(0.0, 0.04, block.shape) + 0.03 * pz[None, :]
            for i in range(block.shape[0]):
                noisy[i, start + i] = -np.inf
            idx = np.argpartition(-noisy, k, axis=1)[:, :k]
            for i in range(block.shape[0]):
                order = sorted(idx[i], key=lambda j: -noisy[i, j])
                rows.append([(float(noisy[i, j]), float(block[i, j]), int(j)) for j in order])
        return rows
    import heapq
    rng = random.Random(seed)
    fam = {}
    for i, a in enumerate(artists):
        fam.setdefault(a.family, []).append(i)
    rows = []
    for i, a in enumerate(artists):
        scored = []
        for j in fam[a.family]:
            if j != i:
                s = _dot(a.vec, artists[j].vec)
                scored.append((s + rng.gauss(0, 0.04) + 0.03 * popz[j], s, j))
        rows.append(heapq.nlargest(k, scored))
    return rows


def make_world(n_artists: int = 8000, seed: int = 7) -> World:
    rng = random.Random(seed)
    families = sorted({f for _, f, _ in GENRES})
    # Orthogonal family directions (Gram-Schmidt) so unrelated families are genuinely unrelated.
    fam_vec: dict[str, list[float]] = {}
    for f in families:
        v = [rng.gauss(0, 1) for _ in range(DIM)]
        for u in fam_vec.values():
            d = _dot(v, u)
            v = [x - d * y for x, y in zip(v, u)]
        fam_vec[f] = _norm(v)

    def off_family_noise(scale: float) -> list[float]:
        v = [rng.gauss(0, 1) for _ in range(DIM)]
        for u in fam_vec.values():
            d = _dot(v, u)
            v = [x - d * y for x, y in zip(v, u)]
        return [scale * x for x in _norm(v)]

    # genre = family direction + a genre-specific direction outside the family subspace:
    # genres of one family have cosine ~0.5, genres of different families ~0 (+/- 0.12).
    genre_vecs = {}
    for g, f, _ in GENRES:
        noise = off_family_noise(0.85)
        genre_vecs[g] = _norm([0.85 * fv + n for fv, n in zip(fam_vec[f], noise)])
    used: set[str] = set()
    artists: list[SynthArtist] = []
    genre_names = [g for g, _, _ in GENRES]
    tags_of = {g: t for g, _, t in GENRES}
    family_of = {g: f for g, f, _ in GENRES}
    while len(artists) < n_artists:
        r = rng.random()
        if r < 0.2:
            name = f"The {rng.choice(_ADJ)} {rng.choice(_NOUN)}" if rng.random() < 0.5 else \
                f"{rng.choice(_ADJ)} {rng.choice(_NOUN)}"
        elif r < 0.35:
            name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        elif r < 0.45:
            name = f"{rng.choice(_FIRST)} & the {rng.choice(_NOUN)}"
        elif r < 0.75:
            name = _coined(rng)
        else:
            name = f"{_coined(rng)} {rng.choice(_NOUN) if rng.random() < 0.5 else rng.choice(_LAST)}"
        key = artist_key(name)
        if key in used:
            continue
        used.add(key)
        g = genre_names[len(artists) % len(genre_names)]
        vec = _norm([gv + 0.13 * rng.gauss(0, 1) for gv in genre_vecs[g]])
        listeners = math.exp(rng.gauss(10.5, 1.5))
        tags = {t: round(w * rng.uniform(0.8, 1.0), 3) for t, w in zip(tags_of[g], (1.0, 0.7, 0.5))}
        tags[family_of[g]] = max(tags.get(family_of[g], 0.0), 0.35)
        nearest = max((h for h in genre_names if h != g), key=lambda h: _dot(vec, genre_vecs[h]))
        if rng.random() < 0.35:
            t = tags_of[nearest][0]
            tags[t] = max(tags.get(t, 0.0), 0.3)
        titles: list[str] = []
        while len(titles) < 12:
            t = f"{rng.choice(_TITLE_A)} {rng.choice(_TITLE_B)}"
            if t not in titles:
                titles.append(t)
        artists.append(SynthArtist(name, key, g, family_of[g], vec, listeners, tags, titles))

    world = World(artists, genre_vecs)
    logpop = [math.log(a.listeners) for a in artists]
    mu = sum(logpop) / len(logpop)
    sd = math.sqrt(sum((x - mu) ** 2 for x in logpop) / len(logpop)) or 1.0
    popz = [(lp - mu) / sd for lp in logpop]
    # Real CF similarity is noisy and biased toward popular artists; mimic both.
    for a, row in zip(artists, _similar_candidates(artists, popz, seed)):
        top = row[:60]
        hi, lo = top[0][0], top[-1][0]
        world.lfm[a.key] = [Neighbor(artists[j].name, round(((x - lo) / (hi - lo + 1e-9)) ** 1.5 * 0.99 + 0.01, 4))
                            for x, _, j in top]
        alt = sorted(((s + rng.gauss(0, 0.07), j) for _, s, j in row), key=lambda x: -x[0])[:20]
        world.dz[a.key] = [Neighbor(artists[j].name, round(0.95 * (1 - i2 / 21), 4)) for i2, (_, j) in enumerate(alt)]
    return world


# --------------------------------------------------------------------------------------------------
@dataclass
class Listener:
    taste_start: list[float]
    taste_end: list[float]
    drift_start_frac: float
    sharpness: float = 10.0
    center: float = 0.35

    def taste_at(self, frac: float) -> list[float]:
        lam = 0.0 if frac < self.drift_start_frac else (frac - self.drift_start_frac) / (1 - self.drift_start_frac)
        lam = min(1.0, lam) * 0.55
        return _norm([(1 - lam) * a + lam * b for a, b in zip(self.taste_start, self.taste_end)])

    def like_prob(self, artist: SynthArtist, frac: float = 1.0) -> float:
        return _sigmoid(self.sharpness * (_dot(self.taste_at(frac), artist.vec) - self.center))


def make_listener(world: World, genres=("indie rock", "dream pop", "techno"), drift_to: str = "jazz fusion",
                  seed: int = 3) -> Listener:
    rng = random.Random(seed)
    weights = [0.45, 0.33, 0.22][: len(genres)]
    start = _norm([sum(w * world.genre_vecs[g][i] for w, g in zip(weights, genres)) + 0.05 * rng.gauss(0, 1)
                   for i in range(DIM)])
    end = _norm([0.5 * s + 0.5 * x for s, x in zip(start, world.genre_vecs[drift_to])])
    return Listener(start, end, drift_start_frac=0.65)


def simulate_history(world: World, listener: Listener, days: int = 720, plays_per_day: float = 30.0,
                     discovery_rate: float = 0.02, seed: int = 11,
                     end: datetime = datetime(2026, 9, 30, tzinfo=timezone.utc)) -> list[dict]:
    """Generate Extended-Streaming-History rows (same JSON fields Spotify exports)."""
    rng = random.Random(seed)
    start = end - timedelta(days=days)
    artists = world.artists
    pop_weights = [a.listeners ** 0.5 for a in artists]
    habit: dict[str, float] = {}
    rejected: set[str] = set()
    # initial library: artists the listener already loves on day 0
    ranked = sorted(artists, key=lambda a: -listener.like_prob(a, 0.0) * (1 + 0.05 * rng.random()))
    for a in ranked[:18]:
        habit[a.key] = rng.uniform(0.5, 2.0)
    rows: list[dict] = []

    def emit(ts: datetime, a: SynthArtist, title: str, ms: int, rs: str, re_: str, skipped: bool) -> None:
        rows.append({
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "platform": "synthetic", "ms_played": ms,
            "conn_country": "ZZ", "master_metadata_track_name": title,
            "master_metadata_album_artist_name": a.name, "master_metadata_album_album_name": f"{a.name} LP",
            "spotify_track_uri": f"spotify:track:{zlib.crc32((a.key + title).encode()):010d}",
            "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None,
            "reason_start": rs, "reason_end": re_, "shuffle": rng.random() < 0.3, "skipped": skipped,
            "offline": False, "offline_timestamp": None, "incognito_mode": False,
        })

    for day in range(days):
        frac = day / days
        for k in list(habit):
            habit[k] *= 0.997
        n = max(0, int(rng.gauss(plays_per_day, plays_per_day * 0.35)))
        t = start + timedelta(days=day, hours=rng.uniform(7, 12))
        for _ in range(n):
            t += timedelta(seconds=rng.uniform(120, 300))
            if habit and rng.random() > discovery_rate:
                keys = list(habit)
                a = world.by_key[rng.choices(keys, weights=[habit[k] for k in keys])[0]]
                p = listener.like_prob(a, frac)
                title = a.tracks[min(int(rng.expovariate(0.35)), len(a.tracks) - 1)]
                rs = rng.choices(["clickrow", "trackdone", "fwdbtn", "backbtn"], [0.3, 0.55, 0.12, 0.03])[0]
                u = rng.random()
                if u < 0.78 * (0.4 + 0.6 * p):
                    emit(t, a, title, rng.randint(150_000, 260_000), rs, "trackdone", False)
                    habit[a.key] += 0.02 * p
                elif u < 0.9:
                    emit(t, a, title, rng.randint(35_000, 140_000), rs, "fwdbtn", True)
                else:
                    emit(t, a, title, rng.randint(2_000, 25_000), rs, "fwdbtn", True)
                    habit[a.key] *= 0.97
                continue
            # discovery: similarity-driven radio (mostly) or a random popular artist
            if habit and rng.random() < 0.75:
                keys = list(habit)
                src = rng.choices(keys, weights=[habit[k] for k in keys])[0]
                pool = [nb for nb in world.lfm[src][:40] if artist_key(nb.name) not in habit
                        and artist_key(nb.name) not in rejected]
                if not pool:
                    continue
                a = world.by_key[artist_key(rng.choice(pool[:25]).name)]
            else:
                a = rng.choices(artists, weights=pop_weights)[0]
                if a.key in habit or a.key in rejected:
                    continue
            p = listener.like_prob(a, frac)
            title = a.tracks[min(int(rng.expovariate(0.6)), len(a.tracks) - 1)]
            if rng.random() < p:
                emit(t, a, title, rng.randint(150_000, 260_000), "trackdone", "trackdone", False)
                habit[a.key] = rng.uniform(0.4, 1.4) * (0.5 + p)
            else:
                emit(t, a, title, rng.randint(2_000, 22_000), "trackdone", "fwdbtn", True)
                if rng.random() < 0.85:
                    rejected.add(a.key)
    return rows


# --------------------------------------------------------------------------------------------------
class SyntheticKnowledge:
    """Implements the :class:`~musicfinder.sources.base.Knowledge` protocol over a :class:`World`."""

    sources = ["synthetic", "synthetic_b"]

    def __init__(self, world: World):
        self.world = world
        self.calls = 0

    def _get(self, name: str) -> SynthArtist | None:
        self.calls += 1
        return self.world.by_key.get(artist_key(name))

    def neighbors(self, name: str) -> dict[str, list[Neighbor]]:
        a = self._get(name)
        if not a:
            return {}
        return {"synthetic": list(self.world.lfm[a.key]), "synthetic_b": list(self.world.dz[a.key])}

    def tags(self, name: str) -> dict[str, float]:
        a = self._get(name)
        return dict(a.tags) if a else {}

    def popularity(self, name: str) -> float | None:
        a = self._get(name)
        return a.listeners if a else None

    def top_tracks(self, name: str, limit: int = 10) -> list[TrackInfo]:
        a = self._get(name)
        if not a:
            return []
        return [TrackInfo(t, a.name, popularity=a.listeners / (i + 1)) for i, t in enumerate(a.tracks[:limit])]

    def similar_tracks(self, artist: str, track: str, limit: int = 50) -> list[tuple[str, str, float]]:
        a = self._get(artist)
        if not a:
            return []
        out = []
        for nb in self.world.lfm[a.key][:20]:
            b = self.world.by_key[artist_key(nb.name)]
            for i, t in enumerate(b.tracks[:3]):
                out.append((b.name, t, round(nb.score / (1 + i), 4)))
        h = sum(map(ord, track_key(track)))
        out.sort(key=lambda x: (-x[2], (sum(map(ord, x[1])) + h) % 7))
        return out[:limit]

    def preview(self, artist: str, track: str) -> TrackInfo | None:
        return None

    def search_artists(self, query: str, limit: int = 8) -> list[dict]:
        q = artist_key(query)
        if not q:
            return []
        hits = [a for a in self.world.artists if q in a.key]
        hits.sort(key=lambda a: (a.key != q, not a.key.startswith(q), -a.listeners))
        return [{"name": a.name, "fans": round(a.listeners / 10), "image": None} for a in hits[:limit]]

    def tag_artists(self, tag: str, limit: int = 50) -> list[str]:
        hits = [a for a in self.world.artists if a.tags.get(tag, 0) >= 0.45]
        hits.sort(key=lambda a: -a.listeners)
        return [a.name for a in hits[:limit]]

    def status(self) -> dict:
        return {"sources": self.sources, "unavailable": {}, "http": {"requests": self.calls}, "synthetic": True}
