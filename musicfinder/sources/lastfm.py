"""Last.fm API client.

Last.fm's "similar artists" and "similar tracks" are collaborative-filtering signals mined from
billions of scrobbles, which makes them the single best public similarity source. Requires a free
API key: https://www.last.fm/api/account/create
"""

from __future__ import annotations

from typing import Any

from musicfinder.normalize import clean_tag
from musicfinder.sources.base import Neighbor, TrackInfo, as_list, to_float
from musicfinder.sources.http import DAY, HttpClient, Req, SourceError

BASE = "https://ws.audioscrobbler.com/2.0/"

# https://www.last.fm/api/errorcodes
_RETRY = {8, 11, 16, 29}
_FATAL = {4, 9, 10, 13, 14, 15, 26}


def _error_code(body: Any) -> int | None:
    """Last.fm's numeric error code, or None. Other {"error": "..."} bodies (e.g. from a relay) don't count."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, bool):
        return None
    if isinstance(err, int):
        return err
    if isinstance(err, str) and err.strip().isdigit():
        return int(err)
    return None


def classify(status: int, body: Any) -> str:
    code = _error_code(body)
    if code is not None:
        if code in _RETRY:
            return "retry"
        if code in _FATAL:
            return "fatal"
        return "missing"  # 6 = artist/track not found, etc.
    if status == 200 and isinstance(body, dict):
        return "ok"
    if status == 429 or status >= 500:
        return "retry"
    return "missing" if status in (400, 404) else "fatal"


def _image(images: Any) -> str | None:
    for img in reversed(as_list(images)):
        url = img.get("#text") if isinstance(img, dict) else None
        # Last.fm replaced artist photos with a generic star placeholder; skip it.
        if url and "2a96cbd8b46e442fc41c2b86b821562f" not in url:
            return url
    return None


class LastFm:
    name = "lastfm"

    def __init__(self, http: HttpClient, api_key: str):
        if not api_key:
            raise ValueError("Last.fm API key is required")
        self.http = http
        self.api_key = api_key

    def req(self, method: str, ttl: float = 30 * DAY, **params: Any) -> Req:
        q = {"method": method, "api_key": self.api_key, "format": "json", **params}
        return Req.make(BASE, q, ttl, classify)

    def _call(self, method: str, ttl: float = 30 * DAY, **params: Any) -> Any:
        return self.http.fetch(self.req(method, ttl, **params)) or {}

    # Request builders: the exact requests the methods below make (used to plan parallel prefetches).
    def similar_req(self, artist: str, limit: int = 100) -> Req:
        return self.req("artist.getsimilar", artist=artist, limit=limit, autocorrect=1)

    def tags_req(self, artist: str) -> Req:
        return self.req("artist.gettoptags", artist=artist, autocorrect=1)

    def info_req(self, artist: str) -> Req:
        return self.req("artist.getinfo", artist=artist, autocorrect=1)

    def top_tracks_req(self, artist: str, limit: int = 10) -> Req:
        return self.req("artist.gettoptracks", artist=artist, limit=limit, autocorrect=1)

    def similar_tracks_req(self, artist: str, track: str, limit: int = 50) -> Req:
        return self.req("track.getsimilar", artist=artist, track=track, limit=limit, autocorrect=1)

    def tag_artists_req(self, tag: str, limit: int = 50) -> Req:
        return self.req("tag.gettopartists", tag=tag, limit=limit)

    def check_key(self) -> bool:
        try:
            self._call("artist.getinfo", ttl=0, artist="Radiohead")
            return True
        except SourceError:
            return False

    def similar_artists(self, artist: str, limit: int = 100) -> list[Neighbor]:
        d = self.http.fetch(self.similar_req(artist, limit)) or {}
        out = []
        for it in as_list((d.get("similarartists") or {}).get("artist")):
            if isinstance(it, dict) and it.get("name"):
                out.append(Neighbor(it["name"], min(1.0, max(0.0, to_float(it.get("match")))), it.get("mbid") or None))
        return out

    def top_tags(self, artist: str, max_tags: int = 20) -> dict[str, float]:
        return self.parse_tags(self.http.fetch(self.tags_req(artist)) or {}, max_tags)

    @staticmethod
    def parse_tags(d: dict, max_tags: int = 20) -> dict[str, float]:
        d = d if isinstance(d, dict) else {}
        out: dict[str, float] = {}
        for t in as_list((d.get("toptags") or {}).get("tag")):
            if not isinstance(t, dict):
                continue
            tag = clean_tag(str(t.get("name") or ""))
            weight = to_float(t.get("count")) / 100.0
            if tag and weight >= 0.05:
                out[tag] = max(out.get(tag, 0.0), min(weight, 1.0))
        return dict(sorted(out.items(), key=lambda kv: -kv[1])[:max_tags])

    def info(self, artist: str) -> dict[str, Any] | None:
        return self.parse_info(self.http.fetch(self.info_req(artist)) or {}, artist)

    @staticmethod
    def parse_info(d: dict, artist: str) -> dict[str, Any] | None:
        a = d.get("artist") if isinstance(d, dict) else None
        if not isinstance(a, dict):
            return None
        stats = a.get("stats") or {}
        return {
            "name": a.get("name") or artist,
            "mbid": a.get("mbid") or None,
            "listeners": to_float(stats.get("listeners"), 0.0),
            "url": a.get("url"),
            "image": _image(a.get("image")),
        }

    def top_tracks(self, artist: str, limit: int = 10) -> list[TrackInfo]:
        return self.parse_top_tracks(self.http.fetch(self.top_tracks_req(artist, limit)) or {}, artist)

    @staticmethod
    def parse_top_tracks(d: dict, artist: str) -> list[TrackInfo]:
        d = d if isinstance(d, dict) else {}
        out = []
        for t in as_list((d.get("toptracks") or {}).get("track")):
            if isinstance(t, dict) and t.get("name"):
                art = t.get("artist") or {}
                out.append(TrackInfo(
                    title=t["name"],
                    artist=art.get("name", artist) if isinstance(art, dict) else artist,
                    popularity=to_float(t.get("listeners")),
                    link=t.get("url"),
                ))
        return out

    def similar_tracks(self, artist: str, track: str, limit: int = 50) -> list[tuple[str, str, float]]:
        return self.parse_similar_tracks(self.http.fetch(self.similar_tracks_req(artist, track, limit)) or {})

    @staticmethod
    def parse_similar_tracks(d: dict) -> list[tuple[str, str, float]]:
        d = d if isinstance(d, dict) else {}
        out = []
        for t in as_list((d.get("similartracks") or {}).get("track")):
            if not isinstance(t, dict) or not t.get("name"):
                continue
            art = t.get("artist") or {}
            name = art.get("name") if isinstance(art, dict) else None
            if name:
                out.append((name, t["name"], min(1.0, max(0.0, to_float(t.get("match"))))))
        return out

    def tag_top_artists(self, tag: str, limit: int = 50) -> list[str]:
        return self.parse_tag_artists(self.http.fetch(self.tag_artists_req(tag, limit)) or {})

    @staticmethod
    def parse_tag_artists(d: dict) -> list[str]:
        d = d if isinstance(d, dict) else {}
        return [a["name"] for a in as_list((d.get("topartists") or {}).get("artist"))
                if isinstance(a, dict) and a.get("name")]
