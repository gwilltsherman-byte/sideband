"""MusicBrainz (artist IDs + community genre tags) and ListenBrainz (listening-session similarity). No keys."""

from __future__ import annotations

from typing import Any

from musicfinder.normalize import artist_key, clean_tag
from musicfinder.sources.base import Neighbor, to_float
from musicfinder.sources.http import DAY, HttpClient, Req, default_classify

MB_URL = "https://musicbrainz.org/ws/2/artist/"
LB_SIMILAR_URL = "https://labs.api.listenbrainz.org/similar-artists/json"
# The session-based similarity model ListenBrainz uses for its own radio feature.
LB_ALGORITHM = "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"


BATCH = 10  # artists per MusicBrainz search (the service allows 1 request per second)
LOOKUP_TTL = 60 * DAY


def classify_search(status: int, body: Any) -> str:
    """A 200 that is not a search result (an error page, "busy", an empty body) is retried, not cached."""
    if status == 200 and not (isinstance(body, dict) and isinstance(body.get("artists"), list)):
        return "retry"
    return default_classify(status, body)


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


class MusicBrainz:
    name = "musicbrainz"

    def __init__(self, http: HttpClient):
        self.http = http

    # One cache entry per artist ("mb-artist:<key>"), whether it came from a single or a batched search.
    @staticmethod
    def lookup_key(name: str) -> str:
        return f"mb-artist:{artist_key(name)}"

    def cached_lookup(self, name: str) -> tuple[bool, dict | None]:
        return self.http.derived_get(self.lookup_key(name), LOOKUP_TTL)

    def lookup(self, name: str) -> dict | None:
        """MBID, canonical name and genre tags for an artist (exact-name match), or None."""
        hit, value = self.cached_lookup(name)
        if hit:
            return value
        found = self.search(name)
        self.http.derived_put(self.lookup_key(name), found)
        return found

    def batch_req(self, names: list[str]) -> Req:
        """One search answering up to ``BATCH`` artists; each answer is cached under its own lookup key."""
        names = list(dict.fromkeys(names))
        query = " OR ".join(f"artist:{_quote(n)}" for n in names)

        def derive(body: Any) -> dict[str, Any]:
            if not (isinstance(body, dict) and isinstance(body.get("artists"), list) and "count" in body):
                return {}  # not a proper search answer: record nothing
            # If the answer was cut off at the result limit, an artist missing from it may still exist:
            # leave it unanswered (it is then looked up on its own) rather than record it as unknown.
            complete = to_float(body.get("count")) <= len(body["artists"])
            out = {}
            for n in names:
                found = self.parse_search(body, n)
                if found is not None or complete:
                    out[self.lookup_key(n)] = found
            return out

        return Req.make(MB_URL, {"query": query, "fmt": "json", "limit": 100}, LOOKUP_TTL, classify_search,
                        derive=derive)

    @staticmethod
    def tag_req(tag: str, limit: int = 50) -> Req:
        return Req.make(MB_URL, {"query": f"tag:{_quote(tag)}", "fmt": "json", "limit": min(100, limit)}, 30 * DAY,
                        classify_search)

    def tag_artists(self, tag: str, limit: int = 50) -> list[str]:
        d = self.http.fetch(self.tag_req(tag, limit)) or {}
        return [a["name"] for a in (d.get("artists") or []) if isinstance(a, dict) and a.get("name")][:limit]

    @staticmethod
    def search_req(name: str) -> Req:
        return Req.make(MB_URL, {"query": f"artist:{_quote(name)}", "fmt": "json", "limit": 5}, LOOKUP_TTL,
                        classify_search)

    def search(self, name: str) -> dict | None:
        return self.parse_search(self.http.fetch(self.search_req(name)) or {}, name)

    @staticmethod
    def parse_search(d: dict, name: str) -> dict | None:
        d = d if isinstance(d, dict) else {}
        want = artist_key(name)
        best = None
        for a in d.get("artists") or []:
            if not isinstance(a, dict):
                continue
            names = [a.get("name", "")] + [al.get("name", "") for al in a.get("aliases") or [] if isinstance(al, dict)]
            if any(artist_key(n) == want for n in names):
                if best is None or to_float(a.get("score")) > to_float(best.get("score")):
                    best = a
        if best is None:
            return None
        tags: dict[str, float] = {}
        raw = [(clean_tag(str(t.get("name", ""))), to_float(t.get("count"))) for t in best.get("tags") or []
               if isinstance(t, dict)]
        top = max((c for _, c in raw), default=0.0)
        for tag, count in raw:
            if tag and count > 0 and top > 0:
                tags[tag] = max(tags.get(tag, 0.0), count / top)
        return {"mbid": best.get("id"), "name": best.get("name"), "tags": tags}


def _flatten(obj: Any) -> list[dict]:
    """The labs API has changed shape over time (flat list, nested lists, {"data": ...}); accept all."""
    if isinstance(obj, list):
        out: list[dict] = []
        for el in obj:
            out.extend(_flatten(el))
        return out
    if isinstance(obj, dict):
        if "artist_mbid" in obj or ("name" in obj and "score" in obj):
            return [obj]
        if "data" in obj:
            return _flatten(obj["data"])
    return []


class ListenBrainz:
    name = "listenbrainz"

    def __init__(self, http: HttpClient, algorithm: str = LB_ALGORITHM):
        self.http = http
        self.algorithm = algorithm

    def similar_req(self, mbid: str) -> Req:
        return Req.make(LB_SIMILAR_URL, {"artist_mbids": mbid, "algorithm": self.algorithm}, 30 * DAY)

    def similar_artists(self, mbid: str) -> list[Neighbor]:
        d = self.http.fetch(self.similar_req(mbid))
        items = [it for it in _flatten(d) if it.get("name") and it.get("artist_mbid") != mbid
                 and it.get("type") not in ("markup",)]
        top = max((to_float(it.get("score")) for it in items), default=0.0)
        if top <= 0:
            return []
        return [Neighbor(str(it["name"]), to_float(it.get("score")) / top, it.get("artist_mbid")) for it in items]
