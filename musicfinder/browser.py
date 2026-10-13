"""Backend for the browser build: the same app, running under Pyodide inside a Web Worker.

The worker's JavaScript calls :meth:`BrowserBackend.request` for every API call the page makes and gets
back a :class:`Task`. It drives the task with this loop::

    while not task.step():            # run Python until it needs the network (or finishes)
        while plan := task.plan():    # what to fetch (dependent requests appear in later rounds)
            fetch plan in parallel through /api/proxy, task.ingest(...) each response
    task.result_json()

so lookups happen many at a time even though Python itself runs synchronously. Anything the plan
did not cover is fetched by :func:`xhr_transport`, a synchronous request through the same relay
(allowed in workers). Data lives in an SQLite file on an IndexedDB-backed folder that the worker
saves periodically.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.parse import quote

from musicfinder.api import dispatch_steps, parse_query
from musicfinder.app import Job, MusicFinder
from musicfinder.graph import CrawlConfig
from musicfinder.sources.http import Req
from musicfinder.steps import Need, Steps
from musicfinder.store import Store

PROXY = "/api/proxy?url="
RELAY_KEY = "relay"  # placeholder: the relay puts the site's real Last.fm key in its place
DB_PATH = "/data/musicfinder.db"
# One worker thread in the browser; the crawl is a little smaller than on a computer to keep the
# first build of the map to a few minutes on a phone.
BROWSER_CRAWL = CrawlConfig(seeds=50, recent_seeds=15, negative_seeds=15, expand_candidates=90, tag_candidates=240,
                            explore_candidates=90, workers=1)


def xhr_transport(url: str, headers: dict, timeout: float, proxy_prefix: str = PROXY) -> tuple[int, bytes]:
    """Synchronous GET through the site's relay (only possible inside a Web Worker)."""
    from js import XMLHttpRequest  # type: ignore[import-not-found]  # provided by Pyodide

    req = XMLHttpRequest.new()
    req.open("GET", proxy_prefix + quote(url, safe=""), False)
    try:
        req.timeout = int(timeout * 1000)
    except Exception:  # some engines refuse timeouts on synchronous requests
        pass
    try:
        req.send()
    except Exception as e:
        raise OSError(f"network error: {e}") from e
    if not req.status:
        raise OSError("network error")
    if req.getResponseHeader("X-Relay-Error"):
        raise OSError(f"relay: {req.responseText}")  # the relay's own failure: retry, never cache
    return int(req.status), str(req.responseText or "").encode("utf-8")


class Task:
    """One request (or background job), advanced step by step by the worker."""

    def __init__(self, gen: Steps, knowledge: Callable[[], Any]):
        self._gen = gen
        self._knowledge = knowledge
        self.need: Need | None = None
        self.finished = False
        self.result: tuple[int, Any] = (500, {"error": "Task did not run"})
        self._reqs: dict[str, Req] = {}
        self._attempted: set[str] = set()

    @property
    def label(self) -> str:
        return self.need.label if self.need else ""

    def step(self) -> bool:
        """Run until the next network step. Returns True once the task has finished."""
        self._reqs.clear()
        self._attempted.clear()
        try:
            self.need = next(self._gen)
            return False
        except StopIteration as stop:
            self.result = stop.value if stop.value is not None else (200, None)
        except Exception as e:  # dispatch_steps reports errors itself; this is a last resort
            self.result = (500, {"error": f"{type(e).__name__}: {e}"})
        self.need = None
        self.finished = True
        return True

    def plan(self) -> list[dict]:
        """Requests to fetch now for the current step (each offered once per step)."""
        if self.need is None:
            return []
        planner = getattr(self._knowledge(), "plan", None)
        if planner is None:  # e.g. the demo's simulated sources: nothing to fetch
            return []
        out = []
        for r in planner(self.need.kind, self.need.items):
            key = r.cache_key
            if key in self._attempted:
                continue
            self._attempted.add(key)
            self._reqs[key] = r
            out.append({"key": key, "url": r.full_url, "host": r.host})
        return out

    def ingest(self, key: str, status: int, text: str) -> None:
        req = self._reqs.get(key)
        http = getattr(self._knowledge(), "http", None)
        if req is not None and http is not None:
            http.ingest(req, int(status or 0), (text or "").encode("utf-8"))

    def result_json(self) -> str:
        status, payload = self.result
        return json.dumps({"status": status, "payload": payload}, default=str)


class BrowserBackend:
    def __init__(self, demo: bool = False, db_path: str = DB_PATH, transport=xhr_transport,
                 http_options: dict | None = None, demo_artists: int = 3000, lastfm: bool = False,
                 lookup_available: bool = True, relay_url: str = "/api/proxy"):
        """``lastfm``: the site's relay adds its own Last.fm key (set by the site's owner on the lookup server)."""
        if demo:
            self.app = MusicFinder.demo_instance(n_artists=demo_artists, crawl_cfg=BROWSER_CRAWL)
        else:
            if transport is xhr_transport:
                prefix = relay_url + ("&" if "?" in relay_url else "?") + "url="
                transport = lambda url, headers, timeout: xhr_transport(url, headers, timeout, prefix)
            store = Store(db_path)
            if store.get_setting("lastfm_api_key"):
                store.set_setting("lastfm_api_key", "")  # earlier versions asked listeners for a key: forget it
            self.app = MusicFinder(store, transport=transport, crawl_cfg=BROWSER_CRAWL,
                                   http_options=http_options, lastfm_key=RELAY_KEY if lastfm else "")
        self.job_task: Task | None = None
        self._new_job: Task | None = None
        self.app.lookup_available = bool(demo or lookup_available)

    def _knowledge(self):
        return self.app.knowledge

    def request(self, method: str, path: str, query: str = "", body: Any = None,
                filename: str = "upload.json") -> Task:
        if body is not None and type(body).__name__ in ("JsNull", "JsUndefined"):  # JavaScript null
            body = None
        if body is not None and hasattr(body, "to_py"):  # a JavaScript Uint8Array
            body = body.to_py()
        data = bytes(body) if body is not None else b""
        gen = dispatch_steps(self.app, method.upper(), path, parse_query(query), data, filename or "upload.json",
                             start_job=self._start_job)
        return Task(gen, self._knowledge)

    # ---- background jobs ("build" the music map, "evaluate" accuracy) ----------------------------
    def _start_job(self, name: str) -> bool:
        if self.job_task is not None and not self.job_task.finished:
            return False
        self.app.job = Job(name=name, running=True, started=time.time(), step="Starting…")
        inner = {"build": self.app.build_graph_steps, "evaluate": self.app.evaluate_steps,
                 "prepare": self.app.prepare_steps}[name]()
        self.job_task = self._new_job = Task(self._job(inner), self._knowledge)
        return True

    def _job(self, inner: Steps) -> Steps[tuple[int, Any]]:
        job = self.app.job
        try:
            yield from inner
        except Exception as e:
            job.error = str(e) if isinstance(e, (RuntimeError, ValueError)) else f"{type(e).__name__}: {e}"
        finally:
            job.running = False
            job.finished = time.time()
        return 200, {"ok": job.error is None}

    def writes(self) -> int:
        """Number of committed database writes so far: the worker saves to the device only when it grows."""
        return self.app.store.writes

    def take_job(self) -> Task | None:
        """The job started by the last request, if any (the worker then drives it in the background)."""
        task, self._new_job = self._new_job, None
        return task

    def report(self, label: str, done: int, total: int) -> None:
        """Progress of the worker's parallel fetching, shown in the page's progress bar."""
        job = self.app.job
        if job.running:
            job.step, job.done, job.total = label or job.step, int(done), int(total)
