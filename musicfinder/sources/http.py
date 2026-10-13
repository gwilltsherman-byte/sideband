"""A small HTTP client with an SQLite response cache, per-host rate limits and retry with backoff."""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from musicfinder import __version__

DAY = 86_400.0
USER_AGENT = f"musicfinder/{__version__} ( https://github.com/gwilltsherman-byte/sideband )"

# requests per second, per host -- at or below each service's published guidance
DEFAULT_RATES = {
    "ws.audioscrobbler.com": 5.0,
    "api.deezer.com": 8.0,
    "musicbrainz.org": 1.0,
    "labs.api.listenbrainz.org": 2.0,
    "api.listenbrainz.org": 2.0,
}

# classify(status, body) -> "ok" | "missing" | "retry" | "fatal"
Classifier = Callable[[int, Any], str]
# transport(url, headers, timeout) -> (status, raw_body)
Transport = Callable[[str, dict, float], "tuple[int, bytes]"]


class SourceError(Exception):
    """A data source failed in a way that retrying will not fix (bad API key, service gone...)."""


def default_classify(status: int, body: Any) -> str:
    if status == 200:
        return "ok"
    if status in (404, 410):
        return "missing"
    if status == 429 or status >= 500:
        return "retry"
    return "fatal"


def urllib_transport(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read() or b""


@dataclass(frozen=True)
class Req:
    """A fully described GET request, so it can be cached, planned and prefetched by someone else."""

    url: str
    params: tuple[tuple[str, str], ...]
    ttl: float = 30 * DAY
    classify: Classifier = field(default=default_classify, compare=False)
    secret_params: tuple[str, ...] = ("api_key",)
    # For batched requests: turns a successful response into extra cache entries {key: value}, e.g. one
    # entry per artist answered by a 10-artist MusicBrainz query.
    derive: Callable[[Any], dict[str, Any]] | None = field(default=None, compare=False)

    @staticmethod
    def make(url: str, params: dict[str, Any], ttl: float = 30 * DAY, classify: Classifier = default_classify,
             secret_params: tuple[str, ...] = ("api_key",),
             derive: Callable[[Any], dict[str, Any]] | None = None) -> "Req":
        return Req(url, tuple((k, str(v)) for k, v in params.items()), ttl, classify, secret_params, derive)

    @property
    def cache_key(self) -> str:
        public = sorted((k, v) for k, v in self.params if k not in self.secret_params)
        return f"{self.url}?{urlencode(public)}"

    @property
    def full_url(self) -> str:
        return f"{self.url}?{urlencode(self.params)}"

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""


def decode_body(raw: bytes) -> tuple[bool, Any]:
    """(ok, decoded JSON); ok is False for undecodable non-empty bodies."""
    if not raw:
        return True, None
    try:
        return True, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, None


class RateLimiter:
    def __init__(self, per_second: float, sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.sleep = sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            self.sleep(slot - now)


class HttpClient:
    def __init__(
        self,
        store=None,
        *,
        transport: Transport = urllib_transport,
        rates: dict[str, float] | None = None,
        timeout: float = 20.0,
        retries: int = 3,
        user_agent: str = USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.store = store
        self.transport = transport
        self.rates = {**DEFAULT_RATES, **(rates or {})}
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.sleep = sleep
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}
        self._memory: dict[str, Any] = {}  # derived entries when there is no store

    def _limiter(self, host: str) -> RateLimiter:
        with self._lock:
            lim = self._limiters.get(host)
            if lim is None:
                lim = self._limiters[host] = RateLimiter(self.rates.get(host, 4.0), self.sleep)
            return lim

    def fetch(self, req: Req) -> Any:
        return self.get_json(req.url, dict(req.params), req.ttl, req.classify, req.secret_params, req.derive)

    def peek(self, req: Req) -> tuple[bool, Any]:
        """Cache lookup only: (hit, value). Never touches the network."""
        if self.store is None:
            return False, None
        return self.store.cache_get(req.cache_key, req.ttl)

    # ---- derived entries (values computed from a response rather than a response itself) --------
    def derived_get(self, key: str, ttl: float) -> tuple[bool, Any]:
        if self.store is not None:
            return self.store.cache_get(key, ttl)
        with self._lock:
            return (key in self._memory), self._memory.get(key)

    def derived_put(self, key: str, value: Any) -> None:
        if self.store is not None:
            self.store.cache_put(key, value)
        else:
            with self._lock:
                self._memory[key] = value

    def _store_derived(self, derive: Callable[[Any], dict[str, Any]] | None, body: Any) -> None:
        if derive is None:
            return
        try:
            extra = derive(body) or {}
        except Exception:  # a malformed batch answer must not break the request that carried it
            return
        for key, value in extra.items():
            self.derived_put(key, value)

    def ingest(self, req: Req, status: int, raw: bytes) -> str:
        """Store a response fetched by someone else (e.g. the browser, in parallel) as if we had fetched it.

        Returns the verdict; only "ok" and "missing" are cached, so failures are retried normally later.
        """
        ok, body = decode_body(raw)
        if not status or not ok:
            # No answer, or not JSON (e.g. a web page from a missing or broken relay): never cache that.
            return "retry"
        verdict = req.classify(status, body)
        if self.store is not None and verdict in ("ok", "missing"):
            self.store.cache_put(req.cache_key, body if verdict == "ok" else None)
        if verdict == "ok":
            self._store_derived(req.derive, body)
        return verdict

    def get_json(
        self,
        url: str,
        params: dict[str, Any],
        ttl: float = 30 * DAY,
        classify: Classifier = default_classify,
        secret_params: tuple[str, ...] = ("api_key",),
        derive: Callable[[Any], dict[str, Any]] | None = None,
    ) -> Any:
        """GET ``url`` and return decoded JSON, ``None`` if the resource does not exist.

        Raises :class:`SourceError` for permanent failures or when retries are exhausted.
        """
        key = Req.make(url, params, ttl, classify, secret_params).cache_key
        if self.store is not None:
            hit, value = self.store.cache_get(key, ttl)
            if hit:
                with self._lock:
                    self.stats["cache_hits"] += 1
                return value
        full = f"{url}?{urlencode(params)}"
        host = urlsplit(url).hostname or ""
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        last_problem = "unknown error"
        for attempt in range(self.retries + 1):
            self._limiter(host).wait()
            with self._lock:
                self.stats["requests"] += 1
            try:
                status, raw = self.transport(full, headers, self.timeout)
            except (URLError, TimeoutError, OSError) as e:
                last_problem = f"network error: {e}"
                self._backoff(attempt)
                continue
            ok, body = decode_body(raw)
            if not ok and status == 200:
                last_problem = "invalid JSON"
                self._backoff(attempt)
                continue
            verdict = classify(status, body)
            if verdict == "ok":
                if self.store is not None:
                    self.store.cache_put(key, body)
                self._store_derived(derive, body)
                return body
            if verdict == "missing":
                if self.store is not None:
                    self.store.cache_put(key, None)
                return None
            if verdict == "retry":
                last_problem = f"HTTP {status}"
                self._backoff(attempt)
                continue
            with self._lock:
                self.stats["errors"] += 1
            detail = body.get("message") if isinstance(body, dict) else None
            raise SourceError(f"{host}: HTTP {status}" + (f" ({detail})" if detail else ""))
        with self._lock:
            self.stats["errors"] += 1
        raise SourceError(f"{host}: gave up after {self.retries + 1} attempts ({last_problem})")

    def _backoff(self, attempt: int) -> None:
        if attempt >= self.retries:
            return
        self.sleep(min(30.0, (2**attempt) * 0.5 + random.random() * 0.25))
