"""The JSON API, independent of how requests arrive.

Both the local web server (``server.py``) and the in-browser build (``browser.py``) route requests
through :func:`dispatch_steps`, so the two behave identically. Network-heavy routes are step
generators (see ``steps.py``); everything else returns immediately.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

from musicfinder.app import MusicFinder, NotReady, Unavailable
from musicfinder.steps import Steps

Response = tuple[int, Any]


def _q(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0]


def _float(query: dict, key: str, default: float) -> float:
    try:
        return float(_q(query, key, str(default)))
    except (TypeError, ValueError):
        return default


def _int(query: dict, key: str, default: int, lo: int = 1, hi: int = 200) -> int:
    try:
        return max(lo, min(hi, int(_q(query, key, str(default)))))
    except (TypeError, ValueError):
        return default


def parse_query(query_string: str) -> dict[str, list[str]]:
    return parse_qs(query_string or "")


def dispatch_steps(app: MusicFinder, method: str, path: str, query: dict[str, list[str]],
                   body: bytes = b"", filename: str = "upload.json",
                   start_job=None) -> Steps[Response]:
    """Handle one API request; returns (HTTP status, JSON-serialisable payload).

    ``start_job(name)`` starts a background job ("build", "evaluate" or "prepare") and returns whether it
    started; it defaults to the app's threaded jobs.
    """
    start_job = start_job or (lambda name: {"build": app.start_build, "evaluate": app.start_evaluation,
                                         "prepare": app.start_prepare}[name]())
    try:
        if method == "GET":
            if path == "/api/state":
                return 200, app.state()
            if path == "/api/job":
                return 200, app.job.to_dict()
            if path == "/api/profile":
                return 200, app.profile_summary()
            if path == "/api/recommendations":
                return 200, {"items": app.recommendations(_int(query, "n", 30), _float(query, "exploration", 0.0))}
            if path == "/api/songs":
                return 200, (yield from app.songs_steps(_float(query, "exploration", 0.0)))
            if path == "/api/explore":
                seed = _q(query, "seed")
                return 200, app.explore(_int(query, "n", 8, 1, 20), int(seed) if seed.isdigit() else None)
            if path == "/api/explore/tag":
                return 200, (yield from app.explore_tag_steps(_q(query, "tag"), _int(query, "n", 12, 1, 40)))
            if path == "/api/artist/tracks":
                return 200, {"items": (yield from app.artist_tracks_steps(_q(query, "name"), _int(query, "n", 5, 1, 20)))}
            if path == "/api/preview":
                return 200, app.preview(_q(query, "artist"), _q(query, "track")) or {}
            if path == "/api/feedback":
                return 200, app.feedback_summary()
            if path == "/api/evaluation":
                return 200, app.evaluation() or {}
            if path == "/api/search/artists":
                return 200, (yield from app.search_artists_steps(_q(query, "q"), _int(query, "n", 8, 1, 20)))
            if path == "/api/picks":
                return 200, app.picks()
        elif method == "POST":
            if path == "/api/import":
                return 200, app.import_files([(filename or "upload.json", body)])
            data = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if path in ("/api/build", "/api/evaluate", "/api/prepare"):
                started = start_job(path.rsplit("/", 1)[-1])
                return 200, {"started": started, "job": app.job.to_dict()}
            if path == "/api/feedback":
                return 200, (yield from app.add_feedback_steps(
                    str(data.get("artist", "")), str(data.get("verdict", "")), str(data.get("track", "")),
                    data.get("context") or {}))
            if path == "/api/picks":
                return 200, app.set_pick(str(data.get("artist", "")), str(data.get("verdict", "")))
            if path == "/api/clear":
                app.clear(str(data.get("what", "data")))
                return 200, {"ok": True}
        return 404, {"error": "Not found"}
    except NotReady as e:
        return 409, {"error": str(e)}
    except Unavailable as e:
        return 503, {"error": str(e)}
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return 400, {"error": str(e)}
    except Exception as e:  # last resort: report instead of crashing the request
        return 500, {"error": f"{type(e).__name__}: {e}"}
