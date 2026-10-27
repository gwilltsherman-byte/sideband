"""Deezer public API client (no key needed): related artists, fan counts, top tracks and 30 s previews."""

from __future__ import annotations

import re
from typing import Any

from musicfinder.normalize import artist_key, clean_tag, track_key
from musicfinder.sources.base import Neighbor, TrackInfo, to_float
from musicfinder.sources.http import DAY, HttpClient, Req

BASE = "https://api.deezer.com"
PREVIEW_TTL = 3 * 3600.0  # preview URLs are signed and expire


def classify(status: int, body: Any) -> str:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = int(to_float(body["error"].get("code"), -1))
        if code in (4, 700):  # quota exceeded / service busy
            return "retry"
        return "missing"  # 800 = no data, etc.
    if status == 200:
        return "ok"
    if status == 429 or status >= 500:
        return "retry"
    return "missing"


class Deezer:
    name = "deezer"

    def __init__(self, http: HttpClient):
        self.http = http

    @staticmethod
    def req(path: str, ttl: float = 30 * DAY, **params: Any) -> Req:
        return Req.make(BASE + path, params, ttl, classify)

    def _fetch(self, req: Req) -> dict:
        d = self.http.fetch(req)
        return d if isinstance(d, dict) else {}

    # Request builders: the exact requests the methods below make (used to plan parallel prefetches).
    def search_artist_req(self, name: str) -> Req:
        return self.req("/search/artist", q=name, limit=10)

    def related_req(self, artist_id: Any, limit: int = 50) -> Req:
        return self.req(f"/artist/{artist_id}/related", limit=limit)

    def top_req(self, artist_id: Any, limit: int = 10) -> Req:
        return self.req(f"/artist/{artist_id}/top", PREVIEW_TTL, limit=limit)

    def search_track_req(self, artist: str, title: str) -> Req:
        return self.req("/search/track", PREVIEW_TTL, q=f'artist:"{artist}" track:"{title}"', limit=10)

    def radio_req(self, artist_id: Any, limit: int = 50) -> Req:
        return self.req(f"/artist/{artist_id}/radio", 7 * DAY, limit=limit)

    def genres_req(self) -> Req:
        return self.req("/genre", 30 * DAY)

    def genre_artists_req(self, genre_id: Any) -> Req:
        return self.req(f"/genre/{genre_id}/artists", 7 * DAY)

    def radio(self, name: str, limit: int = 50) -> list[TrackInfo]:
        """Deezer's artist radio: songs by the artist and by similar artists."""
        a = self.find_artist(name)
        if not a or a.get("id") is None:
            return []
        data = self._fetch(self.radio_req(a["id"], limit)).get("data") or []
        return [self._track(t) for t in data if isinstance(t, dict) and t.get("title")]

    @staticmethod
    def match_genre(d: dict, tag: str) -> Any:
        """Deezer genre id whose name ("Rap/Hip Hop", "Soul & Funk"...) matches a genre tag, or None."""
        want = clean_tag(tag) or tag.strip().casefold()
        for g in (d or {}).get("data") or []:
            if not isinstance(g, dict) or not g.get("id"):
                continue
            name = str(g.get("name", ""))
            parts = {clean_tag(p) or p.strip().casefold() for p in re.split(r"[/&,]", name) if p.strip()}
            if want in parts or want == (clean_tag(name) or name.casefold()):
                return g["id"]
        return None

    def genre_artists(self, tag: str, limit: int = 50) -> list[str] | None:
        """Most popular artists of the Deezer genre matching ``tag``; None if no Deezer genre matches."""
        genre_id = self.match_genre(self._fetch(self.genres_req()), tag)
        if genre_id is None:
            return None
        return self.parse_genre_artists(self._fetch(self.genre_artists_req(genre_id)), limit)

    @staticmethod
    def parse_genre_artists(d: dict, limit: int = 50) -> list[str]:
        data = (d if isinstance(d, dict) else {}).get("data") or []
        return [a["name"] for a in data if isinstance(a, dict) and a.get("name")][:limit]

    def search_artists(self, query: str, limit: int = 8) -> list[dict]:
        """Artists whose names match what someone typed, most popular first (for picking favourites)."""
        d = self._fetch(self.search_artist_req(query.strip()))
        want = artist_key(query)
        out, seen = [], set()
        # The artist whose name is exactly what was typed comes first ("Air" before "Air Supply").
        for a in sorted((a for a in d.get("data") or [] if isinstance(a, dict) and a.get("name")),
                        key=lambda a: (artist_key(str(a["name"])) != want, -to_float(a.get("nb_fan")))):
            k = artist_key(str(a["name"]))
            if k in seen:
                continue
            seen.add(k)
            out.append({"name": a["name"], "fans": to_float(a.get("nb_fan")),
                        "image": a.get("picture_medium") or a.get("picture")})
        return out[:limit]

    def cached_artist_id(self, name: str) -> tuple[bool, Any]:
        """(known, id) from the cache only; known is False if the search has not been fetched yet."""
        hit, d = self.http.peek(self.search_artist_req(name))
        if not hit:
            return False, None
        found = self.pick_artist(d if isinstance(d, dict) else {}, name)
        return True, (found or {}).get("id")

    def find_artist(self, name: str) -> dict | None:
        return self.pick_artist(self._fetch(self.search_artist_req(name)), name)

    @staticmethod
    def pick_artist(d: dict, name: str) -> dict | None:
        """Exact-name match only: recommending the wrong artist is worse than recommending none."""
        want = artist_key(name)
        best = None
        for a in d.get("data") or []:
            if isinstance(a, dict) and artist_key(str(a.get("name", ""))) == want:
                if best is None or to_float(a.get("nb_fan")) > to_float(best.get("nb_fan")):
                    best = a
        if best is None:
            return None
        return {
            "id": best.get("id"),
            "name": best.get("name"),
            "fans": to_float(best.get("nb_fan")),
            "image": best.get("picture_medium") or best.get("picture"),
            "link": best.get("link"),
        }

    def related(self, name: str, limit: int = 50) -> list[Neighbor]:
        a = self.find_artist(name)
        if not a or a.get("id") is None:
            return []
        items = [r for r in self._fetch(self.related_req(a["id"], limit)).get("data") or []
                 if isinstance(r, dict) and r.get("name")]
        n = len(items)
        # Deezer returns related artists ordered by relevance without a score: use a rank-based score.
        return [Neighbor(r["name"], round(0.95 * (1 - i / (n + 1)), 4)) for i, r in enumerate(items)]

    def _track(self, t: dict) -> TrackInfo:
        album = t.get("album") or {}
        artist = t.get("artist") or {}
        return TrackInfo(
            title=t.get("title") or "",
            artist=artist.get("name", ""),
            popularity=to_float(t.get("rank")),
            preview_url=t.get("preview") or None,
            link=t.get("link"),
            image=album.get("cover_medium"),
            album=album.get("title", ""),
            extra={"deezer_id": t.get("id"), "duration": t.get("duration")},
        )

    def top_tracks(self, name: str, limit: int = 10) -> list[TrackInfo]:
        a = self.find_artist(name)
        if not a or a.get("id") is None:
            return []
        data = self._fetch(self.top_req(a["id"], limit)).get("data") or []
        return [self._track(t) for t in data if isinstance(t, dict) and t.get("title")]

    def find_track(self, artist: str, title: str) -> TrackInfo | None:
        data = self._fetch(self.search_track_req(artist, title)).get("data") or []
        want_a, want_t = artist_key(artist), track_key(title)
        fallback = None
        for t in data:
            if not isinstance(t, dict):
                continue
            if artist_key((t.get("artist") or {}).get("name", "")) != want_a:
                continue
            if track_key(t.get("title") or "") == want_t:
                return self._track(t)
            fallback = fallback or t
        return self._track(fallback) if fallback else None
