"""Combine the public music-knowledge sources behind one interface, degrading gracefully when one fails."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable, TypeVar

from musicfinder.normalize import artist_key
from musicfinder.sources.base import Knowledge, Neighbor, TrackInfo
from musicfinder.sources.brainz import BATCH, ListenBrainz, MusicBrainz
from musicfinder.sources.deezer import Deezer
from musicfinder.sources.http import HttpClient, Req, SourceError
from musicfinder.sources.lastfm import LastFm

__all__ = ["Knowledge", "LiveKnowledge", "Neighbor", "TrackInfo", "SOURCE_WEIGHTS", "SourceError"]

# How much each source's similarity judgement counts when they are blended into one graph edge.
# Last.fm: CF over scrobbles (strongest); ListenBrainz: CF over listening sessions; Deezer: related artists.
SOURCE_WEIGHTS = {"lastfm": 1.0, "listenbrainz": 0.8, "deezer": 0.6, "synthetic": 1.0, "synthetic_b": 0.6}

T = TypeVar("T")
MAX_CONSECUTIVE_FAILURES = 5


class LiveKnowledge:
    """Last.fm (if a key is configured) + Deezer + ListenBrainz + MusicBrainz."""

    def __init__(
        self,
        store=None,
        lastfm_key: str | None = None,
        use_deezer: bool = True,
        use_listenbrainz: bool = True,
        http: HttpClient | None = None,
    ):
        self.http = http or HttpClient(store)
        self.lastfm = LastFm(self.http, lastfm_key) if lastfm_key else None
        self.deezer = Deezer(self.http) if use_deezer else None
        self.musicbrainz = MusicBrainz(self.http)
        self.listenbrainz = ListenBrainz(self.http) if use_listenbrainz else None
        self.sources = [s.name for s in (self.lastfm, self.deezer, self.listenbrainz) if s is not None]
        self._mbids: dict[str, str] = {}
        self._lock = threading.Lock()
        self._failures: dict[str, int] = defaultdict(int)
        self._down: dict[str, str] = {}

    # ---- resilience -----------------------------------------------------
    def _guard(self, source: str, fn: Callable[[], T], default: T) -> T:
        if source in self._down:
            return default
        try:
            result = fn()
        except SourceError as e:
            with self._lock:
                self._failures[source] += 1
                if self._failures[source] >= MAX_CONSECUTIVE_FAILURES:
                    self._down[source] = str(e)
            return default
        with self._lock:
            self._failures[source] = 0
        return result

    def status(self) -> dict[str, Any]:
        return {"sources": self.sources, "unavailable": dict(self._down), "http": dict(self.http.stats)}

    def retry_unavailable(self) -> list[str]:
        """Give an explicit new job a fresh attempt after a temporary outage.

        The breaker still prevents a failing source from being tried for every artist within one
        job. A user's later retry must be able to recover without restarting the app. Retain all
        successful cached responses and identity lookups; only clear failure/breaker state.
        """
        with self._lock:
            retrying = sorted(self._down)
            self._down.clear()
            self._failures.clear()
        return retrying

    # ---- identity -------------------------------------------------------
    def mbid(self, name: str) -> str | None:
        """MusicBrainz id, from cached lookups only (never from other answers, which could name a
        different artist of the same name and make the prefetch plan and the lookups disagree)."""
        k = artist_key(name)
        with self._lock:
            if self._mbids.get(k):
                return self._mbids[k]
        mbid = None
        if self.lastfm:
            info = self._guard("lastfm", lambda: self.lastfm.info(name), None)
            mbid = (info or {}).get("mbid")
        if not mbid:
            found = self._guard("musicbrainz", lambda: self.musicbrainz.lookup(name), None)
            mbid = (found or {}).get("mbid")
        if mbid:
            with self._lock:
                self._mbids[k] = mbid
        return mbid

    # ---- Knowledge protocol ----------------------------------------------
    def neighbors(self, name: str) -> dict[str, list[Neighbor]]:
        out: dict[str, list[Neighbor]] = {}
        if self.lastfm:
            out["lastfm"] = self._guard("lastfm", lambda: self.lastfm.similar_artists(name), [])
        if self.deezer:
            out["deezer"] = self._guard("deezer", lambda: self.deezer.related(name), [])
        if self.listenbrainz and "listenbrainz" not in self._down:
            mbid = self.mbid(name)
            if mbid:
                out["listenbrainz"] = self._guard("listenbrainz", lambda: self.listenbrainz.similar_artists(mbid), [])
        return {k: v for k, v in out.items() if v}

    def tags(self, name: str) -> dict[str, float]:
        tags: dict[str, float] = {}
        if self.lastfm:
            tags = self._guard("lastfm", lambda: self.lastfm.top_tags(name), {})
        if not tags:
            found = self._guard("musicbrainz", lambda: self.musicbrainz.lookup(name), None)
            tags = (found or {}).get("tags") or {}
        return tags

    def popularity(self, name: str) -> float | None:
        if self.lastfm:
            info = self._guard("lastfm", lambda: self.lastfm.info(name), None)
            if info and info.get("listeners"):
                return float(info["listeners"])
            return None
        if self.deezer:
            found = self._guard("deezer", lambda: self.deezer.find_artist(name), None)
            if found and found.get("fans"):
                return float(found["fans"])
        return None

    def artist_image(self, name: str) -> str | None:
        if not self.deezer:
            return None
        found = self._guard("deezer", lambda: self.deezer.find_artist(name), None)
        return (found or {}).get("image")

    def search_artists(self, query: str, limit: int = 8) -> list[dict]:
        """Artists matching what the listener typed (for picking favourites), most popular first.

        Raises SourceError when the search could not be done, so it is never mistaken for "no such
        artist"; and a person searching always gets a fresh attempt (no circuit breaker here).
        """
        if not self.deezer or not query.strip():
            return []
        return self.deezer.search_artists(query, limit)

    def top_tracks(self, name: str, limit: int = 10) -> list[TrackInfo]:
        tracks: list[TrackInfo] = []
        if self.lastfm:
            tracks = self._guard("lastfm", lambda: self.lastfm.top_tracks(name, limit), [])
        if not tracks and self.deezer:
            tracks = self._guard("deezer", lambda: self.deezer.top_tracks(name, limit), [])
        return tracks

    def similar_tracks(self, artist: str, track: str, limit: int = 50) -> list[tuple[str, str, float]]:
        sims: list[tuple[str, str, float]] = []
        if self.lastfm:
            sims = self._guard("lastfm", lambda: self.lastfm.similar_tracks(artist, track, limit), [])
        if not sims and self.deezer:
            # Without Last.fm: Deezer's radio for the song's artist (songs by it and by similar artists).
            radio = self._guard("deezer", lambda: self.deezer.radio(artist, limit), [])
            n = len(radio)
            sims = [(t.artist, t.title, round(0.9 * (1 - i / (n + 1)), 4)) for i, t in enumerate(radio) if t.artist]
        return sims

    def preview(self, artist: str, track: str) -> TrackInfo | None:
        if not self.deezer:
            return None
        return self._guard("deezer", lambda: self.deezer.find_track(artist, track), None)

    def tag_artists(self, tag: str, limit: int = 50) -> list[str]:
        names: list[str] = []
        if self.lastfm:
            names = self._guard("lastfm", lambda: self.lastfm.tag_top_artists(tag, limit), [])
        if not names and self.deezer:
            names = self._guard("deezer", lambda: self.deezer.genre_artists(tag, limit), None) or []
        if not names:
            names = self._guard("musicbrainz", lambda: self.musicbrainz.tag_artists(tag, limit), [])
        return names

    def prefetch(self, kind: str, items: list) -> None:
        """Fetch the batched MusicBrainz lookups a step will need (10 artists per request instead of 1).

        Called by the crawl before each step; in the browser build the worker has usually fetched
        everything already, so this does nothing there.
        """
        for req in self.plan(kind, items):
            if req.derive is not None and "musicbrainz" not in self._down:
                self._guard("musicbrainz", lambda req=req: self.http.fetch(req), None)

    # ---- prefetch planning ----------------------------------------------------------------------
    def plan(self, kind: str, items: list) -> list[Req]:
        """The not-yet-cached requests the methods above would make for ``items``.

        Mirrors each method exactly (same endpoints, same parameters). Requests that depend on an
        earlier response (Deezer's related artists need the artist id from a search; ListenBrainz needs
        a MusicBrainz id) are included once that earlier response is in the cache, so a caller that
        repeatedly fetches the plan and stores the results reaches a point where the synchronous code
        runs entirely from the cache. MusicBrainz lookups are grouped ten artists per request. This is
        how the browser version gets parallel network access.
        """
        out: dict[str, Req] = {}
        mb_names: dict[str, str] = {}

        def want(source: str, req: Req) -> None:
            if source not in self._down and req.cache_key not in out and not self.http.peek(req)[0]:
                out[req.cache_key] = req

        def peek(req: Req) -> tuple[bool, object]:
            return self.http.peek(req)

        def deezer_then(name: str, follow) -> None:
            if not self.deezer or "deezer" in self._down:
                return
            want("deezer", self.deezer.search_artist_req(name))
            known, artist_id = self.deezer.cached_artist_id(name)
            if known and artist_id is not None:
                want("deezer", follow(artist_id))

        def mb_lookup(name: str) -> tuple[bool, dict | None]:
            hit, value = self.musicbrainz.cached_lookup(name)
            if not hit and "musicbrainz" not in self._down:
                mb_names.setdefault(artist_key(name), name)
            return hit, value

        def mbid_from_cache(name: str) -> str | None:
            k = artist_key(name)
            if self._mbids.get(k):
                return self._mbids[k]
            if self.lastfm and "lastfm" not in self._down:
                req = self.lastfm.info_req(name)
                want("lastfm", req)
                hit, d = peek(req)
                if not hit:
                    return None
                mbid = (self.lastfm.parse_info(d or {}, name) or {}).get("mbid")
                if mbid:
                    return mbid
            hit, found = mb_lookup(name)
            return (found or {}).get("mbid") if hit else None

        for item in items:
            if kind == "search_artists":
                if self.deezer and str(item).strip():
                    want("deezer", self.deezer.search_artist_req(str(item).strip()))
            elif kind == "neighbors":
                name = item
                if self.lastfm:
                    want("lastfm", self.lastfm.similar_req(name))
                deezer_then(name, lambda aid: self.deezer.related_req(aid))
                if self.listenbrainz and "listenbrainz" not in self._down:
                    mbid = mbid_from_cache(name)
                    if mbid:
                        want("listenbrainz", self.listenbrainz.similar_req(mbid))
            elif kind == "annotate":
                name = item
                if self.lastfm and "lastfm" not in self._down:
                    tags = self.lastfm.tags_req(name)
                    want("lastfm", tags)
                    want("lastfm", self.lastfm.info_req(name))
                    hit, d = peek(tags)
                    if hit and not self.lastfm.parse_tags(d or {}):
                        mb_lookup(name)
                else:
                    mb_lookup(name)
                    if self.deezer and not self.lastfm:
                        want("deezer", self.deezer.search_artist_req(name))
            elif kind == "top_tracks":
                name, limit = item
                if self.lastfm and "lastfm" not in self._down:
                    req = self.lastfm.top_tracks_req(name, limit)
                    want("lastfm", req)
                    hit, d = peek(req)
                    if hit and not self.lastfm.parse_top_tracks(d or {}, name):
                        deezer_then(name, lambda aid: self.deezer.top_req(aid, limit))
                else:
                    deezer_then(name, lambda aid: self.deezer.top_req(aid, limit))
            elif kind == "similar_tracks":
                artist, track, limit = item
                keyless = not self.lastfm or "lastfm" in self._down
                if not keyless:
                    req = self.lastfm.similar_tracks_req(artist, track, limit)
                    want("lastfm", req)
                    hit, d = peek(req)
                    keyless = hit and not self.lastfm.parse_similar_tracks(d or {})
                if keyless:
                    deezer_then(artist, lambda aid: self.deezer.radio_req(aid, limit))
            elif kind == "tag_artists":
                tag, limit = item
                keyless = not self.lastfm or "lastfm" in self._down
                if not keyless:
                    req = self.lastfm.tag_artists_req(tag, limit)
                    want("lastfm", req)
                    hit, d = peek(req)
                    keyless = hit and not self.lastfm.parse_tag_artists(d or {})
                if keyless:
                    genre_id = None
                    if self.deezer and "deezer" not in self._down:
                        genres = self.deezer.genres_req()
                        want("deezer", genres)
                        hit, d = peek(genres)
                        if not hit:
                            continue
                        genre_id = self.deezer.match_genre(d or {}, tag)
                    if genre_id is not None:
                        req = self.deezer.genre_artists_req(genre_id)
                        want("deezer", req)
                        hit, d = peek(req)
                        if hit and not self.deezer.parse_genre_artists(d or {}, limit):
                            want("musicbrainz", self.musicbrainz.tag_req(tag, limit))  # empty chart
                    else:
                        want("musicbrainz", self.musicbrainz.tag_req(tag, limit))
        names = list(mb_names.values())
        for i in range(0, len(names), BATCH):
            chunk = names[i:i + BATCH]
            batch = self.musicbrainz.batch_req(chunk)
            if self.http.peek(batch)[0]:
                # This exact batch was fetched and these artists are still unanswered (it was cut
                # off at the result limit): look them up one by one, exactly as lookup() will.
                for n in chunk:
                    want("musicbrainz", self.musicbrainz.search_req(n))
            else:
                want("musicbrainz", batch)
        return list(out.values())
