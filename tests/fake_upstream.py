"""A stand-in for Last.fm, Deezer, MusicBrainz and ListenBrainz, generated from the synthetic world.

Responses use the real services' JSON shapes (including Last.fm's one-element-list quirk, Deezer's
error objects and decoy search results), so the production source clients, the prefetch planner and
the browser build can be exercised end to end without network access.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from urllib.parse import parse_qs, urlsplit

from musicfinder.normalize import artist_key, track_key
from musicfinder.synthetic import SyntheticKnowledge, World


# Deezer's real genre list (ids and names as the service returns them).
DEEZER_GENRES = [(0, "All"), (132, "Pop"), (116, "Rap/Hip Hop"), (152, "Rock"), (113, "Dance"), (165, "R&B"),
                 (85, "Alternative"), (106, "Electro"), (466, "Folk"), (144, "Reggae"), (129, "Jazz"),
                 (84, "Country"), (98, "Classical"), (173, "Films/Games"), (464, "Metal"), (169, "Soul & Funk"),
                 (2, "African Music"), (16, "Asian Music"), (153, "Blues"), (75, "Brazilian Music"),
                 (197, "Latin Music")]


def fake_mbid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "musicfinder:" + key))


class FakeUpstream:
    def __init__(self, world: World, fail_rate: float = 0.0, seed: int = 0, api_key: str = "KEY"):
        self.world = world
        self.know = SyntheticKnowledge(world)
        self.index = {a.key: i for i, a in enumerate(world.artists)}
        self.by_mbid = {fake_mbid(a.key): a for a in world.artists}
        self.fail_rate = fail_rate
        self.rng = random.Random(seed)
        self.api_key = api_key
        self.calls: list[str] = []

    # transport(url, headers, timeout) -> (status, raw bytes): plugs straight into HttpClient
    def __call__(self, url: str, headers: dict | None = None, timeout: float = 0) -> tuple[int, bytes]:
        self.calls.append(url)
        if self.fail_rate and self.rng.random() < self.fail_rate:
            return 503, b'{"error": "temporarily unavailable"}'
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        host = parts.hostname
        if host == "ws.audioscrobbler.com":
            status, body = self.lastfm(q)
        elif host == "api.deezer.com":
            status, body = self.deezer(parts.path, q)
        elif host == "musicbrainz.org":
            status, body = self.musicbrainz(q)
        elif host == "labs.api.listenbrainz.org":
            status, body = self.listenbrainz(q)
        else:
            status, body = 404, {"error": "unknown host"}
        return status, json.dumps(body).encode("utf-8")

    def artist(self, name: str):
        return self.world.by_key.get(artist_key(name or ""))

    # ---- Last.fm ---------------------------------------------------------------------------------
    def lastfm(self, q: dict) -> tuple[int, dict]:
        if q.get("api_key") != self.api_key:
            return 403, {"error": 10, "message": "Invalid API key - You must be granted a valid key by last.fm"}
        method = q.get("method", "")
        limit = int(q.get("limit", 50))
        not_found = (200, {"error": 6, "message": "The artist you supplied could not be found", "links": []})
        if method == "tag.gettopartists":
            names = self.know.tag_artists(q.get("tag", ""), limit)
            return 200, {"topartists": {"artist": [{"name": n, "mbid": fake_mbid(artist_key(n)), "url": "",
                                                    "@attr": {"rank": str(i + 1)}} for i, n in enumerate(names)],
                                        "@attr": {"tag": q.get("tag", "")}}}
        a = self.artist(q.get("artist", ""))
        if a is None:
            return not_found
        url = f"https://www.last.fm/music/{a.name.replace(' ', '+')}"
        if method == "artist.getsimilar":
            items = [{"name": nb.name, "mbid": fake_mbid(artist_key(nb.name)), "match": f"{nb.score:.6f}",
                      "url": "", "image": [], "streamable": "0"} for nb in self.world.lfm[a.key][:limit]]
            # Last.fm renders a one-element list as a bare object
            return 200, {"similarartists": {"artist": items[0] if len(items) == 1 else items,
                                            "@attr": {"artist": a.name}}}
        if method == "artist.gettoptags":
            tags = [{"count": int(round(w * 100)), "name": t, "url": ""} for t, w in a.tags.items()]
            tags.append({"count": 40, "name": "seen live", "url": ""})  # noise the client must drop
            tags.sort(key=lambda t: -t["count"])
            return 200, {"toptags": {"tag": tags, "@attr": {"artist": a.name}}}
        if method == "artist.getinfo":
            return 200, {"artist": {"name": a.name, "mbid": fake_mbid(a.key), "url": url, "image": [],
                                    "stats": {"listeners": str(int(a.listeners)), "playcount": str(int(a.listeners * 30))}}}
        if method == "artist.gettoptracks":
            tracks = [{"name": t, "playcount": str(int(a.listeners * 3 / (i + 1))), "listeners": str(int(a.listeners / (i + 1))),
                       "mbid": "", "url": f"{url}/_/{t.replace(' ', '+')}", "artist": {"name": a.name, "mbid": "", "url": url},
                       "@attr": {"rank": str(i + 1)}} for i, t in enumerate(a.tracks[:limit])]
            return 200, {"toptracks": {"track": tracks, "@attr": {"artist": a.name}}}
        if method == "track.getsimilar":
            if track_key(q.get("track", "")) not in {track_key(t) for t in a.tracks}:
                return 200, {"error": 6, "message": "Track not found", "links": []}
            sims = self.know.similar_tracks(a.name, q.get("track", ""), limit)
            return 200, {"similartracks": {"track": [{"name": t, "match": m, "playcount": 1000,
                                                      "artist": {"name": art, "mbid": "", "url": ""}}
                                                     for art, t, m in sims], "@attr": {"artist": a.name}}}
        return 200, {"error": 3, "message": "Invalid Method"}

    # ---- Deezer ----------------------------------------------------------------------------------
    def _dz_artist(self, a) -> dict:
        i = self.index[a.key]
        return {"id": i + 1, "name": a.name, "nb_fan": int(a.listeners / 10), "picture_medium": "",
                "link": f"https://www.deezer.com/artist/{i + 1}", "type": "artist"}

    def _dz_track(self, a, j: int) -> dict:
        i = self.index[a.key]
        return {"id": i * 100 + j, "title": a.tracks[j], "rank": int(a.listeners / (j + 1)), "preview": "",
                "link": "", "artist": {"id": i + 1, "name": a.name},
                "album": {"title": f"{a.name} LP", "cover_medium": ""}}

    def deezer(self, path: str, q: dict) -> tuple[int, dict]:
        no_data = (200, {"error": {"type": "DataException", "message": "no data", "code": 800}})
        if path == "/search/artist":
            a = self.artist(q.get("q", ""))
            data = []
            if a is not None:
                # a decoy with a similar name and more fans: exact-name matching must still pick the real one
                data.append({"id": 9_000_000 + self.index[a.key], "name": f"{a.name} Tribute",
                             "nb_fan": int(a.listeners), "type": "artist"})
                data.append(self._dz_artist(a))
            elif len(artist_key(q.get("q", ""))) >= 2:  # what someone has typed so far: name contains it
                part = artist_key(q["q"])
                hits = sorted((b for b in self.world.artists if part in b.key), key=lambda b: -b.listeners)
                data = [self._dz_artist(b) for b in hits[: int(q.get("limit", 25))]]
            return 200, {"data": data, "total": len(data)}
        if path == "/search/track":
            raw = q.get("q", "")
            art = raw.split('artist:"', 1)[-1].split('"', 1)[0]
            title = raw.split('track:"', 1)[-1].split('"', 1)[0]
            a = self.artist(art)
            if a is None:
                return 200, {"data": [], "total": 0}
            data = [{"id": 1, "title": t, "rank": 1000, "preview": "", "link": "", "artist": {"name": a.name},
                     "album": {"title": f"{a.name} LP", "cover_medium": ""}}
                    for t in a.tracks if track_key(t) == track_key(title)]
            return 200, {"data": data, "total": len(data)}
        if path == "/genre":
            return 200, {"data": [{"id": i, "name": n, "picture": "", "type": "genre"} for i, n in DEEZER_GENRES]}
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "genre" and parts[2] == "artists":
            names = {i: n for i, n in DEEZER_GENRES}
            if not parts[1].isdigit() or int(parts[1]) not in names:
                return no_data
            words = {w.strip().lower() for w in re.split(r"/| & ", names[int(parts[1])])}
            words |= {"rnb"} if "r&b" in words else set()
            hits = [b for b in self.world.artists if any(b.tags.get(w, 0) >= 0.45 for w in words)]
            hits.sort(key=lambda b: -b.listeners)
            return 200, {"data": [self._dz_artist(b) for b in hits[:30]], "total": min(30, len(hits))}
        if len(parts) == 3 and parts[0] == "artist" and parts[1].isdigit():
            i = int(parts[1]) - 1
            if not 0 <= i < len(self.world.artists):
                return no_data
            a = self.world.artists[i]
            if parts[2] == "related":
                data = [self._dz_artist(self.world.by_key[artist_key(nb.name)]) for nb in self.world.dz[a.key]]
                return 200, {"data": data[: int(q.get("limit", 20))], "total": len(data)}
            if parts[2] == "radio":
                # the artist's own songs interleaved with songs by related artists, like Deezer's radio
                pool = [a] + [self.world.by_key[artist_key(nb.name)] for nb in self.world.dz[a.key][:12]]
                data = [self._dz_track(b, j) for j in range(3) for b in pool if j < len(b.tracks)]
                return 200, {"data": data[: int(q.get("limit", 25))]}
            if parts[2] == "top":
                data = [{"id": i * 100 + j, "title": t, "rank": int(a.listeners / (j + 1)), "preview": "", "link": "",
                         "artist": {"id": i + 1, "name": a.name}, "album": {"title": f"{a.name} LP", "cover_medium": ""}}
                        for j, t in enumerate(a.tracks[: int(q.get("limit", 5))])]
                return 200, {"data": data, "total": len(data)}
        return no_data

    # ---- MusicBrainz / ListenBrainz --------------------------------------------------------------
    def _mb_artist(self, a, score: int) -> dict:
        tags = [{"count": int(w * 10) + 1, "name": t} for t, w in a.tags.items()]
        return {"id": fake_mbid(a.key), "name": a.name, "score": score, "tags": tags}

    def musicbrainz(self, q: dict) -> tuple[int, dict]:
        """Lucene-style search: ``artist:"A" OR artist:"B"`` (with decoys) or ``tag:"jazz"``."""
        query = q.get("query", "")
        limit = int(q.get("limit", 25))
        results: list[dict] = []
        tag = re.match(r'^tag:"((?:[^"\\]|\\.)*)"$', query)
        if tag:
            want = re.sub(r"\\(.)", r"\1", tag.group(1)).lower()
            hits = sorted((a for a in self.world.artists if a.tags.get(want, 0) >= 0.45),
                          key=lambda a: -a.tags[want])
            results = [self._mb_artist(a, 100 - min(i, 60)) for i, a in enumerate(hits)]
        else:
            names = [re.sub(r"\\(.)", r"\1", m) for m in re.findall(r'"((?:[^"\\]|\\.)*)"', query)]
            for name in names:
                a = self.artist(name)
                if a is None:
                    continue
                results.append(self._mb_artist(a, 100))
                # a weaker partial-name match that exact-name matching must skip
                results.append({"id": fake_mbid("decoy:" + a.key), "name": f"{a.name} Experience", "score": 71,
                                "tags": [{"count": 3, "name": "cover band"}]})
            results.sort(key=lambda r: -r["score"])
        return 200, {"artists": results[:limit], "count": len(results), "offset": 0}

    def listenbrainz(self, q: dict) -> tuple[int, object]:
        a = self.by_mbid.get(q.get("artist_mbids", ""))
        if a is None:
            return 200, []
        items = [{"artist_mbid": fake_mbid(artist_key(nb.name)), "name": nb.name, "comment": "", "type": "Group",
                  "gender": None, "score": int(nb.score * 1000), "reference_mbid": fake_mbid(a.key)}
                 for nb in self.world.lfm[a.key][:50]]
        return 200, items
