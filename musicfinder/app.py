"""Application service: owns the data, the model and background jobs. Used by the web server and the CLI."""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

from musicfinder.evaluation import EvalConfig, ModelConfig, backtest_steps
from musicfinder.explore import genre_shares, territories
from musicfinder.feedback import calibration, feedback_stats, latest_by_artist, latest_by_item, like_probability
from musicfinder.graph import CrawlConfig, KnowledgeGraph, annotate_steps, crawl_steps, expand_steps
from musicfinder.ingest import ImportResult, load_paths, parse_bytes, parse_document, reconcile, parse_quick_input
from musicfinder.models import Feedback, LibraryItem, Play, parse_ts
from musicfinder.normalize import artist_key, track_key
from musicfinder.recommender import FEATURES, Candidate, ScoredPool, diversify, score_pool
from musicfinder.sources import LiveKnowledge
from musicfinder.sources.base import Knowledge
from musicfinder.sources.deezer import PREVIEW_TTL
from musicfinder.sources.http import HttpClient, SourceError, Transport
from musicfinder.steps import Need, Steps, run
from musicfinder.store import Store
from musicfinder.taste import TasteParams, TasteProfile, build_profile
from musicfinder.tracks import recommend_tracks_steps


BROAD_GENRES = (
    "jazz", "classical", "hip hop", "electronic", "folk", "metal", "soul", "reggae", "latin", "k-pop", "country",
    "ambient", "punk", "blues", "funk", "house", "techno", "rnb", "indie rock", "post-rock", "bossa nova",
    "afrobeats", "shoegaze", "dream pop", "singer songwriter", "j-pop", "drum and bass", "gospel", "flamenco",
    "psychedelic rock", "trip-hop", "new wave", "disco", "opera", "world",
)


PICK_KINDS = {"love": "picked_artist", "dislike": "picked_dislike"}

# "This week": a small batch of unfamiliar artists, kept in settings so backups carry it.
STACK_SIZE = 10
STACK_CAP = 50  # a batch never grows beyond this, however often "more" is asked for
STACK_SNOOZE_DAYS = 28
STACK_MAX_SHOWINGS = 2  # an artist left unanswered twice is not dealt again
STACK_STATUSES = ("open", "kept", "passed", "known", "snoozed")
STACK_VERDICTS = {"like": "kept", "dislike": "passed", "known": "known"}
FRESH_MAP_DAYS = 30  # rebuild the map from scratch at least this often


class Unavailable(Exception):
    """Raised when a music service needed right now cannot be reached."""


class NotReady(Exception):
    """Raised when an operation needs data or a graph that does not exist yet."""


@dataclass
class Job:
    name: str = ""
    running: bool = False
    step: str = ""
    done: int = 0
    total: int = 0
    error: str | None = None
    started: float | None = None
    finished: float | None = None
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "running": self.running, "step": self.step, "done": self.done, "total": self.total,
            "error": self.error, "started": self.started, "finished": self.finished,
            "elapsed": round((self.finished or time.time()) - self.started, 1) if self.started else None,
        }


class MusicFinder:
    def __init__(self, store: Store, knowledge: Knowledge | None = None, demo: bool = False,
                 crawl_cfg: CrawlConfig = CrawlConfig(), eval_cfg: EvalConfig = EvalConfig(),
                 transport: Transport | None = None, http_options: dict | None = None,
                 lastfm_key: str | None = None):
        self.store = store
        # Last.fm key supplied by whoever runs this copy: the LASTFM_API_KEY environment variable on a
        # computer, or "relay" in the hosted version when the site's relay adds its own key. Listeners
        # never need one: without it the free sources (Deezer, ListenBrainz, MusicBrainz) do the job.
        self._lastfm_key = (os.environ.get("LASTFM_API_KEY", "") if lastfm_key is None else lastfm_key).strip()
        self._transport = transport  # how web requests are made (the browser build supplies its own)
        self._http_options = http_options or {}
        self.demo = demo
        self.lookup_available = True
        self.crawl_cfg = crawl_cfg
        self.eval_cfg = eval_cfg
        self._knowledge_override = knowledge
        self._knowledge: Knowledge | None = None
        self._lock = threading.RLock()
        self._job_lock = threading.Lock()
        self.job = Job()
        self._plays: list[Play] | None = None
        self._library: list[LibraryItem] | None = None
        self._profile: TasteProfile | None = None
        self._kg: KnowledgeGraph | None = None
        self._kg_loaded = False  # the saved map is read from the store on first use
        self._graph_stale = bool(store.get_setting("graph_stale", True))
        self._pool_cache: tuple[tuple, ScoredPool] | None = None
        self._version = 0  # bumped whenever anything that affects scoring changes
        self._data_generation = 0  # bumped whenever the map's inputs change (picks, imports, sources)
        self._history_signature_cache: str | None = None
        self._reset_generation = 0  # deletion cancels installation of artifacts from an earlier job
        self._sources_generation = 0  # a source change means the next map starts from scratch

    # ---- construction helpers -------------------------------------------------------------------
    @classmethod
    def demo_instance(cls, seed: int = 7, n_artists: int = 8000, crawl_cfg: CrawlConfig = CrawlConfig(),
                      store_path: str = ":memory:") -> "MusicFinder":
        """A self-contained demo: a simulated catalogue and a simulated listener, no network needed."""
        from musicfinder.synthetic import SyntheticKnowledge, make_listener, make_world, simulate_history

        world = make_world(n_artists=n_artists, seed=seed)
        listener = make_listener(world)
        rows = simulate_history(world, listener)
        app = cls(Store(store_path), knowledge=SyntheticKnowledge(world), demo=True, crawl_cfg=crawl_cfg)
        res = parse_document("Streaming_History_Audio_demo.json", rows)
        app.store.add_plays(res.plays)
        app._demo_listener = listener  # type: ignore[attr-defined]
        app._demo_world = world  # type: ignore[attr-defined]
        return app

    # ---- knowledge sources ----------------------------------------------------------------------
    @property
    def knowledge(self) -> Knowledge:
        if self._knowledge_override is not None:
            return self._knowledge_override
        with self._lock:
            if self._knowledge is None:
                self._knowledge = LiveKnowledge(
                    self.store,
                    lastfm_key=self.lastfm_key() or None,
                    use_listenbrainz=bool(self.store.get_setting("use_listenbrainz", True)),
                    http=HttpClient(self.store, transport=self._transport, **self._http_options)
                    if self._transport else None,
                )
            return self._knowledge

    def lastfm_key(self) -> str:
        """A key saved with ``musicfinder config --lastfm-key`` wins over the one this copy was started with."""
        return (self.store.get_setting("lastfm_api_key") or "").strip() or self._lastfm_key

    def settings(self) -> dict:
        return {
            "lastfm": bool(self.lastfm_key()) and not self.demo,
            "use_listenbrainz": bool(self.store.get_setting("use_listenbrainz", True)),
        }

    def update_settings(self, lastfm_api_key: str | None = None, use_listenbrainz: bool | None = None) -> dict:
        """Change the sources (command line only; the app itself needs no configuration)."""
        with self._lock:
            if lastfm_api_key is not None:
                self.store.set_setting("lastfm_api_key", lastfm_api_key.strip())
            if use_listenbrainz is not None:
                self.store.set_setting("use_listenbrainz", bool(use_listenbrainz))
            self._knowledge = None
            self._history_signature_cache = None
            self._data_generation += 1
            self._sources_generation += 1
            self.store.set_setting("graph_fresh_at", None)  # other sources: don't extend the old map
            self._set_stale(True)
        return self.settings()

    # ---- data -----------------------------------------------------------------------------------
    def _invalidate(self, graph: bool = False) -> None:
        with self._lock:
            if graph:
                self._data_generation += 1  # a build that started earlier no longer covers everything
            self._version += 1
            self._plays = None
            self._history_signature_cache = None
            self._library = None
            self._profile = None
            self._pool_cache = None
            if graph:
                self._set_stale(True)

    def _taste_changed(self) -> None:
        """Ratings and interest signals change scoring only: keep the cached plays and library."""
        with self._lock:
            self._version += 1
            self._profile = None
            self._pool_cache = None

    # ---- the saved music map --------------------------------------------------------------------
    def _set_stale(self, stale: bool) -> None:
        if stale != self._graph_stale:
            self._graph_stale = stale
            self.store.set_setting("graph_stale", stale)

    def _current_kg(self) -> KnowledgeGraph | None:
        with self._lock:
            if not self._kg_loaded:
                self._kg_loaded = True
                saved = self.store.get_blob("graph")
                if saved and self._kg is None:
                    try:
                        self._kg = KnowledgeGraph.from_dict(saved)
                    except (KeyError, TypeError, ValueError):
                        self._kg = None
            return self._kg

    def _save_graph(self) -> None:
        kg = self._current_kg()
        if kg is not None:
            self.store.put_blob("graph", kg.to_dict())

    def import_files(self, files: list[tuple[str, bytes]]) -> dict:
        res = ImportResult()
        for name, data in files:
            res.extend(parse_bytes(name, data))
        return self._store_import(res)

    def import_paths(self, paths: list[str]) -> dict:
        return self._store_import(load_paths(paths))

    def _store_import(self, res: ImportResult) -> dict:
        added_plays = self.store.add_plays(res.plays)
        quick_kinds = ("picked_artist", "saved_track", "playlist_track")
        quick = [i for i in res.library if i.kind in quick_kinds]
        regular = [i for i in res.library if i.kind not in quick_kinds]
        applied = self.store.apply_quick_input(quick) if quick else {"added_library_items": 0, "changed": False}
        added_lib = self.store.add_library(regular) + applied["added_library_items"]
        if added_plays or added_lib or applied["changed"]:
            self._invalidate(graph=True)
        summary = res.summary()
        summary.update({"new_plays_added": added_plays, "new_library_items_added": added_lib})
        return summary

    def quick_input(self, text: str, kind: str = "artists", preview: bool = True, name: str = "") -> dict:
        """Review/save immediate taste signals; these are never represented as listening history."""
        parsed = parse_quick_input(text, mode=kind, name=name)
        result = parsed.to_dict()
        if preview:
            return result
        if not result["can_save"]:
            raise ValueError(" ".join(parsed.errors) or "Add at least one artist or song before saving")
        with self._lock:
            added = self.store.apply_quick_input(parsed.library)
            if added["changed"]:
                self._invalidate(graph=True)
        return {**result, **added, "picks": self.picks(), "input_summary": self.input_summary()}

    def input_summary(self) -> dict:
        library = self.library()
        ratings = list(latest_by_item(self.store.feedback()).values())
        explicit_profile = build_profile([], library, feedback=ratings)
        blocked = explicit_profile.blocked_artists()
        counts = {kind: sum(i.kind == kind for i in library) for kind in
                  ("picked_artist", "saved_track", "playlist_track", "followed_artist")}
        positive = [i for i in library if i.kind in ("picked_artist", "saved_track", "playlist_track", "saved_album", "followed_artist")
                    and artist_key(i.artist) not in blocked]
        songs: dict[tuple[str, str], dict] = {}
        artists: dict[str, str] = {}
        for i in positive:
            artists.setdefault(artist_key(i.artist), i.artist)
            if i.kind in ("saved_track", "playlist_track") and i.track:
                key = (artist_key(i.artist), track_key(i.track))
                t = explicit_profile.tracks.get(key)
                if t and not t.banned and t.feedback != "dislike":
                    songs.setdefault(key, {"artist": i.artist, "track": i.track})
        likes = [f for f in ratings if f.verdict == "like" and f.artist_key not in blocked
                 and (not f.track_key or not explicit_profile.tracks[f.item_key].banned)]
        for f in likes:
            artists.setdefault(f.artist_key, f.artist)
            if f.track_key:
                songs.setdefault(f.item_key, {"artist": f.artist, "track": f.track})
        return {"picked_artists": counts["picked_artist"], "saved_tracks": counts["saved_track"],
                "playlist_tracks": counts["playlist_track"], "followed_artists": counts["followed_artist"],
                "library_items": len(positive), "positive_artists": len(artists),
                "liked_artists": sum(not f.track_key for f in likes),
                "liked_songs": sum(bool(f.track_key) for f in likes),
                "artists": list(artists.values())[:12], "songs": list(songs.values())[:12]}

    def clear(self, what: str = "data") -> None:
        if what in ("data", "all"):
            with self._lock:
                self._reset_generation += 1
            self.store.clear_listening_data()
        if what in ("feedback", "all"):
            self.store.clear_feedback()
        if what in ("data", "all"):
            self.store.set_setting("model", None)
            self.store.set_setting("evaluation", None)
        if what in ("data", "all"):  # deleting ratings keeps the map (it is only marked out of date)
            with self._lock:
                self._kg = None
                self._kg_loaded = True
                self.store.put_blob("graph", None)
                self.store.set_setting("graph_fresh_at", None)
        if what in ("feedback", "data", "all"):  # the weekly batch is made of those decisions
            with self._lock:
                self.store.set_setting("stack", None)
                self.store.set_setting("stack_log", None)
        self._invalidate(graph=True)

    def plays(self) -> list[Play]:
        with self._lock:
            if self._plays is None:
                self._plays = reconcile(self.store.plays())
            return self._plays

    def library(self) -> list[LibraryItem]:
        with self._lock:
            if self._library is None:
                self._library = self.store.library()
            return self._library

    def has_data(self) -> bool:
        return (bool(self.plays()) or bool(self.library())
                or any(f.verdict == "like" for f in latest_by_item(self.store.feedback()).values()))

    # ---- picked favourites (the instant start: no export needed) --------------------------------
    def search_artists(self, query: str, limit: int = 8) -> dict:
        return run(self.search_artists_steps(query, limit))

    def search_artists_steps(self, query: str, limit: int = 8) -> Steps[dict]:
        q = " ".join(query.split())[:100]
        if not q:
            return {"query": q, "items": []}
        self._require_lookup()
        yield Need("search_artists", [q], "Searching")
        finder = getattr(self.knowledge, "search_artists", None)
        try:
            found = finder(q, limit) if finder else []
        except SourceError as e:
            raise Unavailable("Couldn’t reach the artist search. Check your connection and try again.") from e
        picks = self._pick_index()
        for item in found:
            item["picked"] = picks.get(artist_key(item["name"]))
        return {"query": q, "items": found}

    def _pick_index(self) -> dict[str, str]:
        out = {}
        for item in self.library():
            if item.kind in PICK_KINDS.values():
                out[artist_key(item.artist)] = "love" if item.kind == "picked_artist" else "dislike"
        return out

    def picks(self) -> dict:
        loved, disliked = [], []
        for item in sorted(self.library(), key=lambda i: i.added or datetime.min.replace(tzinfo=timezone.utc)):
            if item.kind == "picked_artist":
                loved.append(item.artist)
            elif item.kind == "picked_dislike":
                disliked.append(item.artist)
        return {"loved": loved, "disliked": disliked}

    def set_pick(self, artist: str, verdict: str) -> dict:
        """Mark an artist as a favourite ("love"), as unwanted ("dislike"), or forget it ("remove")."""
        name = " ".join(str(artist).split())
        if not name or len(name) > 200:
            raise ValueError("artist is required")
        if verdict not in ("love", "dislike", "remove"):
            raise ValueError("verdict must be love, dislike or remove")
        self.store.remove_library(tuple(PICK_KINDS.values()), name)
        if verdict != "remove":
            self.store.add_library([LibraryItem(PICK_KINDS[verdict], name, "", None, datetime.now(timezone.utc))])
        self._invalidate(graph=True)
        return self.picks()

    def model(self) -> ModelConfig:
        saved = self.store.get_setting("model")
        if not saved:
            return ModelConfig(TasteParams(), 0.3)
        taste = TasteParams(half_life_days=saved.get("half_life_days"), seed_power=saved.get("seed_power", 0.5))
        weights = tuple((f, float(saved.get("weights", {}).get(f, 0.0))) for f in FEATURES)
        return ModelConfig(taste, float(saved.get("alpha", 0.3)), weights)

    def profile(self) -> TasteProfile:
        with self._lock:
            if self._profile is None:
                if not self.has_data():
                    raise NotReady("Pick a few artists you love first.")
                self._profile = build_profile(self.plays(), self.library(), self.model().taste,
                                              feedback=self.store.feedback(), interactions=self.store.interactions())
            return self._profile

    # ---- background jobs ------------------------------------------------------------------------
    def _progress(self, step: str, done: int, total: int) -> None:
        self.job.step, self.job.done, self.job.total = step, done, total

    def start_job(self, name: str, fn: Callable[[], object]) -> bool:
        with self._job_lock:
            if self.job.running:
                return False
            self.job = Job(name=name, running=True, started=time.time(), step="Starting…")

        def run() -> None:
            try:
                fn()
            except Exception as e:  # surfaced to the UI
                plain = isinstance(e, (RuntimeError, NotReady, ValueError))
                self.job.error = str(e) if plain else f"{type(e).__name__}: {e}"
                self.job.log.append(traceback.format_exc())
            finally:
                self.job.running = False
                self.job.finished = time.time()

        threading.Thread(target=run, name=f"job-{name}", daemon=True).start()
        return True

    def graph_ready(self) -> bool:
        return self._current_kg() is not None and not self._graph_stale

    def _require_lookup(self) -> None:
        if not self.lookup_available:
            raise Unavailable("Music lookups are not connected in this copy. Your history and saved results are still available. "
                              "Open Sideband in Codespaces or run it on your computer for new recommendations.")

    def build_graph(self, progress: Callable[[str, int, int], None] | None = None) -> KnowledgeGraph:
        return run(self.build_graph_steps(progress))

    def build_graph_steps(self, progress: Callable[[str, int, int], None] | None = None) -> Steps[KnowledgeGraph]:
        self._require_lookup()
        reset = self._reset_generation
        generation = self._data_generation
        sources = self._sources_generation
        retry = getattr(self.knowledge, "retry_unavailable", None)
        if retry:
            retry()
        profile = self.profile()
        if not profile.positive_seeds(1):
            raise NotReady("Pick at least one artist you love first.")
        # Extend a recent map instead of crawling it again: only artists new to it are looked up.
        # Starting from scratch now and then lets it forget artists that no longer matter.
        started = datetime.now(timezone.utc)
        fresh_at = parse_ts(str(self.store.get_setting("graph_fresh_at") or ""))
        with self._lock:
            saved = self._current_kg()
            base = (saved.copy() if saved is not None and fresh_at is not None
                    and timedelta(0) <= started - fresh_at < timedelta(days=FRESH_MAP_DAYS) else None)
        kg = yield from crawl_steps(profile, self.knowledge, self.crawl_cfg, progress or self._progress, kg=base)
        if not any(kg.adj.values()):
            down = self.knowledge.status().get("unavailable") or {}
            detail = "; ".join(f"{k}: {v}" for k, v in down.items())
            raise RuntimeError(
                "Couldn't get similar-artist data from any source"
                + (f" ({detail})" if detail else "")
                + ". Check your internet connection (and the Last.fm key, if you set one), then try again."
            )
        with self._lock:
            if self._reset_generation != reset:
                return kg  # history was deleted while lookups ran: never republish its map
            self._kg = kg
            self._kg_loaded = True
            if base is None and self._sources_generation == sources:
                self.store.set_setting("graph_fresh_at", started.isoformat())
            # Picks or imports made while this ran are not in it: keep offering an update.
            self._set_stale(self._data_generation != generation)
            self._pool_cache = None
            self._version += 1
            self._save_graph()
        return kg

    def graph(self) -> KnowledgeGraph:
        kg = self._current_kg()
        if kg is None:
            raise NotReady("The music map has not been built yet.")
        return kg

    def start_build(self) -> bool:
        return self.start_job("build", self.build_graph)

    def start_evaluation(self) -> bool:
        return self.start_job("evaluate", self.evaluate)

    def start_prepare(self) -> bool:
        return self.start_job("prepare", self.prepare)

    def history_signature(self) -> str:
        """Identify the reconciled history and evaluation protocol, without storing its contents twice."""
        with self._lock:
            if self._history_signature_cache is None:
                digest = hashlib.sha256(b"sideband-history-model-v2\n")
                digest.update(repr((self.settings(), self.eval_cfg, self.crawl_cfg)).encode("utf-8"))
                for p in self.plays():
                    digest.update(repr((p.ts.isoformat(), p.artist_key, p.track_key, p.ms_played,
                                        p.reason_start, p.reason_end, p.skipped, p.shuffle, p.fmt)).encode("utf-8"))
                    digest.update(b"\n")
                self._history_signature_cache = digest.hexdigest()
            return self._history_signature_cache

    def personalization_status(self) -> dict:
        plays = self.plays()
        first = min((p.ts for p in plays), default=None)
        last = max((p.ts for p in plays), default=None)
        days = (last - first).days if first and last else 0
        can_evaluate = len(plays) >= 100 and days >= self.eval_cfg.min_span_days
        signature = self.history_signature()
        report = self.evaluation() or {}
        model = self.store.get_setting("model") or {}
        tested = bool(plays and report.get("history_signature") == signature)
        current = bool(plays and model.get("history_signature") == signature)
        if not plays:
            status = "picks"
            action = "prepare" if self.has_data() and not self.graph_ready() else "listen" if self.has_data() else "import"
            reason = ("Your favourite artists and your Keep and Pass choices are all Sideband needs. "
                      "Listening history is an optional extra.")
        elif not self.graph_ready():
            status, action = "needs_update", "prepare"
            reason = "Update recommendations to include your latest history and favourites."
        elif current:
            status, action = "ready", "listen"
            reason = "Your personal settings were checked on separate parts of this history. Ratings also update your taste."
        elif not can_evaluate:
            status, action = "limited", "import"
            reason = (f"Your plays already shape recommendations. Personal settings need at least 100 plays across "
                      f"{self.eval_cfg.min_span_days} days; you have {len(plays):,} plays across {days} days.")
        elif tested:
            status, action = "limited", "listen"
            reason = "This history was tested, but it did not support a reliable settings change. Your plays and skips still shape recommendations."
        else:
            status, action = "history", "prepare"
            reason = "Test personal settings against this history, then use a change only when validation supports it."
        return {"history_plays": len(plays), "history_days": days,
                "first": first.date().isoformat() if first else None,
                "last": last.date().isoformat() if last else None,
                "has_skip_data": any(p.fmt == "extended" for p in plays),
                "can_evaluate": can_evaluate, "tested_current": tested, "model_current": current,
                "status": status, "next_action": action, "reason": reason}

    def prepare(self, progress: Callable[[str, int, int], None] | None = None) -> dict:
        return run(self.prepare_steps(progress))

    def prepare_steps(self, progress: Callable[[str, int, int], None] | None = None) -> Steps[dict]:
        """Bring recommendations up to date and test new eligible history once, under one job."""
        reset = self._reset_generation
        if not self.graph_ready():
            yield from self.build_graph_steps(progress)
        if self._reset_generation != reset:
            return self.personalization_status()
        status = self.personalization_status()
        if status["can_evaluate"] and not status["tested_current"]:
            yield from self.evaluate_steps(progress)
        return self.personalization_status()

    # ---- recommendations ------------------------------------------------------------------------
    def _pool(self, exploration: float, hops: int = 1) -> ScoredPool:
        profile, kg = self.profile(), self.graph()
        key = (self._version, len(kg.names), round(exploration, 3), hops)
        with self._lock:
            if self._pool_cache and self._pool_cache[0] == key:
                return self._pool_cache[1]
            pool = score_pool(profile, kg, self.model().scoring(exploration), hops=hops)
            self._pool_cache = (key, pool)
            return pool

    def _decorate(self, cands: list[Candidate], exploration: float, source: str) -> list[dict]:
        cal = calibration(self.store.feedback())
        out = []
        for c in cands:
            d = c.to_dict()
            d["like_probability"] = like_probability(c.percentile, cal)
            d["context"] = {"source": source, "exploration": exploration, "match": round(c.percentile, 1),
                            "score": round(c.score, 4)}
            if self.demo:
                d["true_like_probability"] = round(self._demo_listener.like_prob(  # type: ignore[attr-defined]
                    self._demo_world.by_key[c.key]), 3) if c.key in self._demo_world.by_key else None  # type: ignore
            out.append(d)
        return out

    def recommendations(self, n: int = 30, exploration: float = 0.0) -> list[dict]:
        exploration = max(0.0, min(1.0, exploration))
        pool = self._pool(exploration)
        sp = self.model().scoring(exploration)
        with self._lock:
            picks = diversify(pool, self.graph(), n, min(0.8, sp.diversity + 0.45 * exploration))
        return self._decorate(picks, exploration, "recommendations")

    def songs(self, exploration: float = 0.0) -> dict:
        return run(self.songs_steps(exploration))

    def songs_steps(self, exploration: float = 0.0) -> Steps[dict]:
        self._require_lookup()
        pool = self._pool(exploration)
        sp = self.model().scoring(exploration)
        picks = diversify(pool, self.graph(), 20, min(0.8, sp.diversity + 0.45 * exploration))
        return (yield from recommend_tracks_steps(self.profile(), self.knowledge, picks,
                                                  workers=self.crawl_cfg.workers))

    def explore(self, n: int = 8, seed: int | None = None) -> dict:
        profile, kg = self.profile(), self.graph()
        pool = self._pool(0.0, hops=2)
        terrs = territories(profile, kg, pool, self.store.feedback(), n=n, rng=random.Random(seed))
        shares = genre_shares(profile, kg)
        shown = {t.tag for t in terrs}
        far = [g for g in BROAD_GENRES if shares.get(g, 0.0) < 0.01 and g not in shown]
        return {
            "your_genres": [{"tag": t, "share": round(s, 4)} for t, s in list(shares.items())[:15]],
            "far_genres": far[:14],
            "territories": [
                {**t.to_dict(), "gateways": self._decorate(t.gateways, 0.0, "explore")}
                for t in terrs
            ],
        }

    def explore_tag(self, tag: str, n: int = 12) -> dict:
        return run(self.explore_tag_steps(tag, n))

    def explore_tag_steps(self, tag: str, n: int = 12) -> Steps[dict]:
        self._require_lookup()
        tag = tag.strip()
        if not tag:
            raise ValueError("Enter a genre or style to explore.")
        profile, kg = self.profile(), self.graph()
        yield Need("tag_artists", [(tag.lower(), 40)], f"Finding {tag} artists")
        names = self.knowledge.tag_artists(tag.lower(), 40)
        if not names:
            # fall back to artists in the graph carrying the tag
            names = [kg.names[k] for k, tags in kg.tags.items() if tags.get(tag.lower(), 0) >= 0.4][:40]
        with self._lock:
            yield from expand_steps(kg, self.knowledge, names, self.crawl_cfg.workers)
            yield from annotate_steps(kg, self.knowledge, names, self.crawl_cfg.workers)
            self._pool_cache = None
            self._save_graph()
            keys = {artist_key(n) for n in names}
            pool = score_pool(profile, kg, self.model().scoring(0.0), include=[k for k in keys if k in kg.adj])
        known = profile.known_artists()
        gateways = [c for c in pool.candidates if c.key in keys and c.key not in known][:n]
        already = [kg.names.get(k, k) for k in keys if k in known][:10]
        return {
            "tag": tag,
            "found": len(names),
            "you_already_know": already,
            "gateways": self._decorate(gateways, 0.0, "explore_tag"),
        }

    def artist_tracks(self, name: str, limit: int = 5) -> list[dict]:
        return run(self.artist_tracks_steps(name, limit))

    def artist_tracks_steps(self, name: str, limit: int = 5) -> Steps[list[dict]]:
        self._require_lookup()
        yield Need("top_tracks", [(name, limit)], "Looking up songs")
        tops = self.knowledge.top_tracks(name, limit)
        return [{"title": t.title, "artist": t.artist or name, "link": t.link} for t in tops]

    def preview(self, artist: str, track: str = "", fresh: bool = False) -> dict | None:
        return run(self.preview_steps(artist, track, fresh))

    def preview_steps(self, artist: str, track: str = "", fresh: bool = False) -> Steps[dict | None]:
        """Find this song's audio, never a different song by the same artist.

        Deezer's track search can return no results for its advanced artist/track query even when
        its plain search finds playable audio. Search the artist and title, then validate
        both identities locally. With no title, return a playable song by that exact artist.
        Each lookup yields before fetching so browser playback checks
        use the asynchronous relay and report outages instead of blocking in worker XHR retries.
        """
        self._require_lookup()
        artist, track = artist.strip(), track.strip()
        if not artist or len(artist) > 200 or len(track) > 200:
            raise ValueError("Choose an artist to check for a preview")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in artist + track):
            raise ValueError("Song and artist names must not contain control characters")
        knowledge = self.knowledge
        want_artist, want_track = artist_key(artist), track_key(track)
        info = None
        try:
            if isinstance(knowledge, LiveKnowledge):
                if knowledge.deezer is None:
                    return None
                # Keep signed media URLs under the source's existing three-hour cache lifetime.
                # A later user retry bypasses the graph crawler's circuit breaker.
                queries = [f"{artist} {track}".strip()]
                if want_track != track.casefold():
                    queries.append(f"{artist} {want_track}")
                requests = [replace(knowledge.deezer.req("/search/track", PREVIEW_TTL, q=query, limit=20),
                                    classify=self._preview_response) for query in queries]
                if fresh and knowledge.http.store is not None:
                    for req in requests:
                        knowledge.http.store.cache_forget(req.cache_key)
                for req in requests:
                    need = Need("preview", [(artist, track)], "Checking song preview", requests=[req])
                    yield need
                    if need.error:
                        raise Unavailable("Song previews could not be checked. Please try again.")
                    response = knowledge.http.fetch(req)
                    if response is None:  # a genuine upstream 'not found' response
                        data = []
                    elif isinstance(response, dict) and isinstance(response.get("data"), list):
                        data = response["data"]
                    else:
                        raise Unavailable("Song previews could not be checked. Please try again.")
                    matches = [t for t in data if isinstance(t, dict)
                               and isinstance(t.get("artist"), dict)
                               and artist_key(str(t["artist"].get("name", ""))) == want_artist
                               and str(t.get("title", "")).strip()
                               and (not want_track or track_key(str(t.get("title", ""))) == want_track)]
                    # Prefer the requested recording when both live/remaster versions appear.
                    matches.sort(key=lambda t: str(t.get("title", "")).strip().casefold() != track.casefold())
                    for candidate in matches:
                        if not isinstance(candidate.get("album", {}), dict):
                            candidate = {**candidate, "album": {}}
                        found = knowledge.deezer._track(candidate)
                        found.preview_url = self._preview_url(found.preview_url)
                        if found.preview_url:
                            info = found
                            break
                        info = info or found
                    if info and info.preview_url:
                        break
            else:
                info = knowledge.preview(artist, track)
        except SourceError as e:
            raise Unavailable("Song previews could not be checked. Please try again.") from e
        if not info:
            return None
        if artist_key(info.artist) != want_artist or not info.title or (want_track and track_key(info.title) != want_track):
            return None
        preview_url = self._preview_url(info.preview_url)
        return {"title": info.title, "artist": info.artist, "preview_url": preview_url, "link": info.link,
                "image": info.image, "album": info.album}

    @staticmethod
    def _preview_url(url: str | None) -> str | None:
        if not isinstance(url, str):
            return None
        try:
            parsed = urlsplit(url)
            return url if parsed.scheme == "https" and parsed.hostname else None
        except ValueError:
            return None

    @staticmethod
    def _preview_response(status: int, body: object) -> str:
        """A denied or malformed lookup is not proof that this song lacks a clip."""
        if status == 429 or status >= 500:
            return "retry"
        if status != 200 or not isinstance(body, dict):
            return "fatal"
        error = body.get("error")
        if error is not None:
            code = str(error.get("code", "")) if isinstance(error, dict) else ""
            if code in ("4", "700"):
                return "retry"
            return "missing" if code == "800" else "fatal"
        return "ok" if isinstance(body.get("data"), list) else "fatal"

    # ---- feedback -------------------------------------------------------------------------------
    def add_feedback(self, artist: str, verdict: str, track: str = "", context: dict | None = None) -> dict:
        return run(self.add_feedback_steps(artist, verdict, track, context))

    def add_feedback_steps(self, artist: str, verdict: str, track: str = "",
                           context: dict | None = None) -> Steps[dict]:
        if verdict not in ("like", "dislike", "known", "clear"):
            raise ValueError("verdict must be like, dislike, known or clear")
        if not artist.strip():
            raise ValueError("artist is required")
        if not isinstance(track, str):
            raise ValueError("track must be a song title")
        self.store.add_feedback(Feedback(artist.strip(), verdict, track.strip(), datetime.now(timezone.utc), context or {}))
        self._taste_changed()
        kg = self._current_kg()
        if not track.strip() and kg is not None and self.lookup_available and verdict in ("like", "dislike"):
            try:  # one lookup: makes the newly liked/disliked artist count in the very next scoring
                with self._lock:
                    yield from expand_steps(kg, self.knowledge, [artist], 1)
                self._save_graph()
            except Exception:
                pass
        return feedback_stats(self.store.feedback())

    def feedback_summary(self) -> dict:
        fbs = self.store.feedback()
        stats = feedback_stats(fbs)
        latest = latest_by_item(fbs)
        stats["recent"] = [
            {"artist": f.artist, "track": f.track, "verdict": f.verdict, "ts": f.ts.isoformat(),
             "kind": (f.context or {}).get("kind"), "source": (f.context or {}).get("source")}
            for f in sorted(latest.values(), key=lambda f: f.ts, reverse=True)[:30] if f.verdict != "clear"
        ]
        return stats

    # ---- this week: a small batch of unfamiliar artists -----------------------------------------
    @staticmethod
    def _stack_week(week: object) -> str:
        """The client's local week start (its most recent Sunday), as YYYY-MM-DD."""
        if not isinstance(week, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week):
            raise ValueError("week must be a date like 2026-01-04")
        try:
            date.fromisoformat(week)
        except ValueError as e:
            raise ValueError("week must be a real calendar date") from e
        return week

    @staticmethod
    def _stack_exploration(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("exploration must be a number from 0 to 1")
        try:
            e = float(value)
        except ValueError as err:
            raise ValueError("exploration must be a number from 0 to 1") from err
        if not math.isfinite(e):
            raise ValueError("exploration must be a number from 0 to 1")
        return max(0.0, min(1.0, e))

    @staticmethod
    def _snoozed(entry: dict | None, now: datetime) -> bool:
        until = parse_ts(str((entry or {}).get("snooze_until") or ""))
        return until is not None and until > now

    def _stack_status(self, key: str, verdicts: dict[str, Feedback], log: dict, now: datetime) -> str:
        """Computed on every read from the latest verdict, so Undo and ratings elsewhere stay in step."""
        fb = verdicts.get(key)
        if fb is not None and fb.verdict in STACK_VERDICTS:
            return STACK_VERDICTS[fb.verdict]
        return "snoozed" if self._snoozed(log.get(key), now) else "open"

    def _stack_score(self, verdicts: dict[str, Feedback], log: dict) -> dict:
        shown = [k for k, e in log.items() if e.get("times", 0) >= 1]
        decided = [verdicts[k].verdict for k in shown if k in verdicts]
        weeks = [e["first_week"] for e in log.values() if e.get("first_week")]
        return {"shown": len(shown), "kept": decided.count("like"), "passed": decided.count("dislike"),
                "known": decided.count("known"), "since": min(weeks) if weeks else None}

    def _require_map(self) -> None:
        self.profile()  # NotReady without any favourites...
        self.graph()  # ...or before the music map is built, exactly like the recommendations

    def _deal(self, n: int, exploration: float, week: str, taken: set[str], log: dict, extra: bool) -> list[dict]:
        """Up to ``n`` artists the listener has not told Sideband about, a few of them wildcards."""
        if n <= 0:
            return []
        known = self.profile().known_artists()
        kg = self.graph()
        now = datetime.now(timezone.utc)

        def eligible(c: Candidate, chosen: set[str]) -> bool:
            entry = log.get(c.key) or {}
            return (c.key not in known and c.key not in taken and c.key not in chosen
                    and entry.get("times", 0) < STACK_MAX_SHOWINGS and not self._snoozed(entry, now))

        wild_exploration = max(0.75, min(1.0, exploration + 0.5))
        sides = {"close": exploration, "wildcard": wild_exploration}
        chosen: dict[str, list[Candidate]] = {"close": [], "wildcard": []}

        def take(slot: str, k: int) -> None:
            e = sides[slot]
            pool = self._pool(e)
            keys = {c.key for cs in chosen.values() for c in cs}
            rest = ScoredPool([c for c in pool.candidates if eligible(c, keys)], pool.user_tags, pool.tag_vectors)
            lam = min(0.8, self.model().scoring(e).diversity + 0.45 * e)
            chosen[slot] += diversify(rest, kg, k, lam)

        n_wild = max(1, round(n * (0.1 + 0.4 * exploration)))
        if n > 1:
            n_wild = min(n_wild, n - 1)
        take("close", n - n_wild)
        take("wildcard", n_wild)
        for slot in ("close", "wildcard"):  # when one side runs out, fill from the other
            short = n - len(chosen["close"]) - len(chosen["wildcard"])
            if short > 0:
                take(slot, short)

        # Spread the wildcards evenly through the batch rather than leaving them at the end.
        close, wild = chosen["close"], chosen["wildcard"]
        total = len(close) + len(wild)
        spots = {(i + 1) * total // (len(wild) + 1) for i in range(len(wild))}
        cards = []
        decorated = {"close": iter(self._decorate(close, exploration, "stack")),
                     "wildcard": iter(self._decorate(wild, wild_exploration, "stack"))}
        for i in range(total):
            slot = "wildcard" if i in spots else "close"
            card = next(decorated[slot])
            card.update(slot=slot, extra=extra, second_look=(log.get(card["key"]) or {}).get("times", 0) >= 1)
            card["context"].update(week=week, slot=slot)
            cards.append(card)
        for card in cards:
            entry = log.setdefault(card["key"], {"name": card["name"], "first_week": week, "last_week": week,
                                                 "times": 0, "snooze_until": None})
            entry["name"] = card["name"]
            entry["first_week"] = entry.get("first_week") or week
            entry["last_week"] = week
            entry["times"] = entry.get("times", 0) + 1
        return cards

    def _current_stack(self, week: str, exploration: float) -> dict:
        """The saved batch, unless it belongs to an earlier week: then deal a fresh one."""
        saved = self.store.get_setting("stack")
        if saved and str(saved.get("week", "")) >= week:
            return saved
        log = self.store.get_setting("stack_log") or {}
        items = self._deal(STACK_SIZE, exploration, week, set(), log, extra=False)
        stack = {"week": week, "dealt_at": datetime.now(timezone.utc).isoformat(), "exploration": exploration,
                 "items": items, "exhausted": len(items) < STACK_SIZE}
        self.store.set_setting("stack", stack)
        self.store.set_setting("stack_log", log)
        return stack

    def _stack_payload(self, stack: dict) -> dict:
        log = self.store.get_setting("stack_log") or {}
        verdicts = latest_by_artist(self.store.feedback())
        now = datetime.now(timezone.utc)
        items = [{**c, "status": self._stack_status(c["key"], verdicts, log, now)} for c in stack["items"]]
        counts = {"total": len(items), **{s: sum(i["status"] == s for i in items) for s in STACK_STATUSES}}
        return {"week": stack["week"], "dealt_at": stack["dealt_at"], "exploration": stack["exploration"],
                "items": items, "counts": counts, "exhausted": bool(stack.get("exhausted")),
                "graph_stale": not self.graph_ready(), "score": self._stack_score(verdicts, log)}

    def stack(self, week: object, exploration: object = 0.0) -> dict:
        """This week's batch; asking again in the same week never deals a new one."""
        week, exploration = self._stack_week(week), self._stack_exploration(exploration)
        with self._lock:
            self._require_map()
            return self._stack_payload(self._current_stack(week, exploration))

    def stack_more(self, week: object, exploration: object = 0.0, n: object = 5) -> dict:
        week, exploration = self._stack_week(week), self._stack_exploration(exploration)
        if isinstance(n, bool) or not isinstance(n, (int, str)):
            raise ValueError("n must be a whole number")
        try:
            n = max(1, min(10, int(n)))
        except ValueError as e:
            raise ValueError("n must be a whole number") from e
        with self._lock:
            self._require_map()
            stack = self._current_stack(week, exploration)
            want = min(n, STACK_CAP - len(stack["items"]))
            log = self.store.get_setting("stack_log") or {}
            cards = self._deal(want, exploration, stack["week"], {c["key"] for c in stack["items"]}, log, extra=True)
            stack["items"] = stack["items"] + cards
            stack["exhausted"] = len(cards) < n or len(stack["items"]) >= STACK_CAP
            self.store.set_setting("stack", stack)
            self.store.set_setting("stack_log", log)
            return self._stack_payload(stack)

    def stack_snooze(self, artist: object, on: object) -> dict:
        """"Not now": keep this artist out of the next four weeks' batches. No rating is recorded."""
        name = " ".join(str(artist).split())
        key = artist_key(name)
        if not name or not key or len(name) > 200:
            raise ValueError("artist is required")
        if not isinstance(on, bool):
            raise ValueError("on must be true or false")
        with self._lock:
            self._require_map()
            log = self.store.get_setting("stack_log") or {}
            now = datetime.now(timezone.utc)
            if on:
                entry = log.setdefault(key, {"name": name, "first_week": None, "last_week": None,
                                             "times": 0, "snooze_until": None})
                entry["snooze_until"] = (now + timedelta(days=STACK_SNOOZE_DAYS)).isoformat()
            elif key in log:
                log[key]["snooze_until"] = None
            self.store.set_setting("stack_log", log)
            return {"ok": True, "status": self._stack_status(key, latest_by_artist(self.store.feedback()), log, now)}

    def kept(self) -> dict:
        """Every artist you currently keep, from any part of the app, newest first."""
        with self._lock:
            verdicts = latest_by_artist(self.store.feedback())
            log = self.store.get_setting("stack_log") or {}
            likes = sorted((f for f in verdicts.values() if f.verdict == "like"), key=lambda f: f.ts, reverse=True)
            items = [{"artist": f.artist, "ts": f.ts.isoformat(), "source": (f.context or {}).get("source"),
                      "week": (f.context or {}).get("week")} for f in likes[:200]]
            return {"items": items, "score": self._stack_score(verdicts, log)}

    # ---- accuracy -------------------------------------------------------------------------------
    def evaluate(self, progress: Callable[[str, int, int], None] | None = None) -> dict:
        return run(self.evaluate_steps(progress))

    def evaluate_steps(self, progress: Callable[[str, int, int], None] | None = None) -> Steps[dict]:
        self._require_lookup()
        reset = self._reset_generation
        retry = getattr(self.knowledge, "retry_unavailable", None)
        if retry:
            retry()
        signature = self.history_signature()
        report = yield from backtest_steps(self.plays(), self.knowledge, self.eval_cfg, self.crawl_cfg,
                                           progress or self._progress)
        report["generated"] = datetime.now(timezone.utc).isoformat()
        report["history_signature"] = signature
        if self.demo:
            report["demo"] = True
        with self._lock:
            if reset != self._reset_generation:
                return report  # deleting history wins over every background result
            self.store.set_setting("evaluation", report)
        # Only validation chooses settings; held-out test outcomes never decide deployment.
        # Imports made during the test must not install settings fitted to an obsolete history.
        with self._lock:
            install = (reset == self._reset_generation and report.get("ok")
                       and report.get("selection", {}).get("validated") and signature == self.history_signature())
            if install:
                ch = report["chosen"]
                self.store.set_setting("model", {
                    "half_life_days": ch["memory_half_life_days"], "seed_power": ch["seed_power"],
                    "alpha": ch["restart_probability"], "weights": ch["weights"],
                    "history_signature": signature,
                })
                self._invalidate(graph=True)
        if install:
            # Rebuilding is cheap now: every lookup is cached.
            yield from self.build_graph_steps(progress or self._progress)
        return report

    def evaluation(self) -> dict | None:
        return self.store.get_setting("evaluation")

    # ---- profile summary ------------------------------------------------------------------------
    def profile_summary(self) -> dict:
        p = self.profile()
        hours = p.total_ms / 3_600_000
        top = p.top_artists(40)
        max_aff = top[0].affinity if top else 1.0
        span = max(1.0, (p.as_of - p.first).total_seconds() / 86400) if p.first else 365.0

        def mass(half_life: float | None) -> float:  # decayed weight of steady listening over the whole span
            if not half_life:
                return span
            return half_life * (1 - 0.5 ** (span / half_life))

        steady = mass(p.params.recent_half_life_days) / mass(p.params.half_life_days)
        artists = []
        for a in top:
            trend = None
            heard_engagement = a.engagement - getattr(a, "_interaction_bonus", 0.0)
            heard_recent = (a.recent_engagement - a._feedback_bonus - a._song_feedback_bonus
                            - getattr(a, "_interaction_bonus", 0.0))
            if a.plays and heard_engagement > 0:
                ratio = max(0.0, heard_recent) / max(heard_engagement, 1e-9) / steady
                trend = "rising" if ratio > 1.6 else "steady" if ratio > 0.5 else "fading"
            artists.append({
                "name": a.name, "streams": a.streams, "early_skips": a.early_skips,
                "hours": round(a.ms_played / 3_600_000, 1), "affinity": round(a.affinity / max_aff, 3),
                "skip_rate": round(a.skip_rate, 3), "satisfaction": round(a.satisfaction, 3),
                "first": a.first.date().isoformat() if a.first else None,
                "last": a.last.date().isoformat() if a.last else None,
                "trend": trend, "liked_in_app": a.feedback == "like", "picked": a.picked,
            })
        tracks = [{"title": t.name, "artist": t.artist, "streams": t.streams, "skips": t.early_skips}
                  for t in p.top_tracks(25)]
        out = {
            "demo": self.demo,
            "plays": p.n_plays, "streams": p.n_streams, "early_skips": p.n_early_skips,
            "skip_rate": round(p.n_early_skips / max(1, p.n_streams + p.n_early_skips), 3),
            "hours": round(hours, 1), "artists_heard": sum(a.plays > 0 for a in p.artists.values()),
            "effective_artists": round(p.diversity(), 1),
            "first": p.first.date().isoformat() if p.first else None,
            "last": p.last.date().isoformat() if p.last else None,
            "formats": p.formats,
            "has_skip_data": p.formats.get("extended", 0) > 0,
            "library_items": sum(1 for i in self.library() if i.kind not in PICK_KINDS.values()),
            "picks": self.picks(),
            "top_artists": artists, "top_tracks": tracks,
            "model": self.model().describe(),
            "personalised_model": bool(self.store.get_setting("model")),
            "personalization": self.personalization_status(),
            "input_summary": self.input_summary(),
        }
        kg = self._current_kg()
        if kg is not None:
            out["genres"] = [{"tag": t, "share": round(s, 4)} for t, s in list(genre_shares(p, kg).items())[:15]]
            pops = sorted(kg.popularity[a.key] for a in top if a.key in kg.popularity)
            if pops:
                out["median_listeners_of_top_artists"] = round(pops[len(pops) // 2])
        return out

    def state(self) -> dict:
        has = self.has_data()
        ev = self.evaluation()
        return {
            "demo": self.demo,
            "has_data": has,
            "plays": len(self.plays()) if has else 0,
            "picks": {k: len(v) for k, v in self.picks().items()},
            "graph_ready": self.graph_ready(),
            "graph_exists": self._current_kg() is not None,
            "graph_size": len(self._current_kg().names) if self._current_kg() is not None else 0,
            "job": self.job.to_dict(),
            "settings": self.settings(),
            "lookup_available": self.lookup_available,
            "sources": self.knowledge.status(),
            "evaluation_available": bool(ev and ev.get("ok")),
            "personalised_model": bool(self.store.get_setting("model")),
            "personalization": self.personalization_status(),
            "input_summary": self.input_summary(),
        }
