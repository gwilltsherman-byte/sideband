"""SQLite persistence: imported listening data, user feedback, settings and the HTTP response cache."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from musicfinder.models import Feedback, LibraryItem, Play, parse_ts
from musicfinder.normalize import artist_key

# Three files, so that saving one kind of change does not rewrite the others (this matters in the
# browser, where storage is saved a whole file at a time): listening data, the web-lookup cache, and
# the small things (settings, ratings, the saved music map).
SCHEMAS = {
    "main": """
CREATE TABLE IF NOT EXISTS main.feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, artist TEXT NOT NULL, track TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL, ts TEXT NOT NULL, context TEXT
);
CREATE TABLE IF NOT EXISTS main.settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS main.blobs (key TEXT PRIMARY KEY, value BLOB);
""",
    "data": """
CREATE TABLE IF NOT EXISTS data.plays (
    ts TEXT NOT NULL, artist TEXT NOT NULL, track TEXT NOT NULL, album TEXT, ms INTEGER,
    uri TEXT, reason_start TEXT, reason_end TEXT, skipped INTEGER, shuffle INTEGER, fmt TEXT,
    UNIQUE(ts, artist, track, ms)
);
CREATE TABLE IF NOT EXISTS data.library (
    kind TEXT NOT NULL, artist TEXT NOT NULL, track TEXT NOT NULL DEFAULT '', uri TEXT, added TEXT,
    UNIQUE(kind, artist, track)
);
""",
    "cache": """
CREATE TABLE IF NOT EXISTS cache.http_cache (key TEXT PRIMARY KEY, body BLOB, fetched REAL NOT NULL);
""",
}


def default_home() -> Path:
    return Path(os.environ.get("MUSICFINDER_HOME") or Path.home() / ".musicfinder")


def _b(v: bool | None) -> int | None:
    return None if v is None else int(v)


def _ub(v: int | None) -> bool | None:
    return None if v is None else bool(v)


def _pack(value: Any) -> bytes:
    return zlib.compress(json.dumps(value, separators=(",", ":")).encode("utf-8"), 6)


def _unpack(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return json.loads(zlib.decompress(bytes(raw)).decode("utf-8"))
    return json.loads(raw)  # older uncompressed rows


class Store:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            home = default_home()
            home.mkdir(parents=True, exist_ok=True)
            path = home / "musicfinder.db"
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        if self.path == ":memory:":
            others = {"data": ":memory:", "cache": ":memory:"}
        else:
            base, ext = os.path.splitext(self.path)
            others = {"data": f"{base}-data{ext or '.db'}", "cache": f"{base}-cache{ext or '.db'}"}
        for schema, file in others.items():
            self._db.execute(f"ATTACH DATABASE ? AS {schema}", (file,))
        for script in SCHEMAS.values():
            self._db.executescript(script)
        self._migrate_single_file()
        self._db.commit()
        self.writes = 0  # committed writes since start-up (the browser build saves only when this changes)

    def _migrate_single_file(self) -> None:
        """Databases from before the three-file layout kept everything in the main file: move it."""
        have = {r[0] for r in self._db.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        for table, schema in (("plays", "data"), ("library", "data"), ("http_cache", "cache")):
            if table in have:
                self._db.execute(f"INSERT OR IGNORE INTO {schema}.{table} SELECT * FROM main.{table}")
                self._db.execute(f"DROP TABLE main.{table}")

    def _commit(self) -> None:
        self._db.commit()
        self.writes += 1

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- listening data -------------------------------------------------
    def add_plays(self, plays: list[Play]) -> int:
        rows = [
            (p.ts.isoformat(), p.artist, p.track, p.album, p.ms_played, p.track_uri, p.reason_start,
             p.reason_end, _b(p.skipped), _b(p.shuffle), p.fmt)
            for p in plays
        ]
        with self._lock:
            before = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO data.plays VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            self._commit()
            return self._db.total_changes - before

    def plays(self) -> list[Play]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM data.plays ORDER BY ts").fetchall()
        out = []
        for ts, artist, track, album, ms, uri, rs, re_, sk, sh, fmt in rows:
            out.append(Play(parse_ts(ts), artist, track, album or "", ms or 0, uri, rs, re_, _ub(sk), _ub(sh), fmt))
        return out

    def add_library(self, items: list[LibraryItem]) -> int:
        rows = [(i.kind, i.artist, i.track or "", i.uri, i.added.isoformat() if i.added else None) for i in items]
        with self._lock:
            before = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO data.library VALUES (?,?,?,?,?)", rows)
            self._commit()
            return self._db.total_changes - before

    def library(self) -> list[LibraryItem]:
        with self._lock:
            rows = self._db.execute("SELECT kind, artist, track, uri, added FROM data.library").fetchall()
        return [LibraryItem(k, a, t, u, parse_ts(d) if d else None) for k, a, t, u, d in rows]

    def remove_library(self, kinds: tuple[str, ...], artist: str) -> int:
        """Delete the artist's items of these kinds (names compared the way artists are matched everywhere)."""
        want = artist_key(artist)
        with self._lock:
            marks = ",".join("?" * len(kinds))
            rows = self._db.execute(f"SELECT rowid, artist FROM data.library WHERE kind IN ({marks})", kinds).fetchall()
            ids = [(rid,) for rid, name in rows if artist_key(name) == want]
            self._db.executemany("DELETE FROM data.library WHERE rowid = ?", ids)
            self._commit()
            return len(ids)

    def clear_listening_data(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM data.plays")
            self._db.execute("DELETE FROM data.library")
            self._commit()
            self._db.execute("VACUUM data")  # really remove the deleted rows from the file

    # ---- feedback -------------------------------------------------------
    def add_feedback(self, fb: Feedback) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO main.feedback (artist, track, verdict, ts, context) VALUES (?,?,?,?,?)",
                (fb.artist, fb.track or "", fb.verdict, fb.ts.isoformat(), json.dumps(fb.context)),
            )
            self._commit()

    def feedback(self) -> list[Feedback]:
        with self._lock:
            rows = self._db.execute("SELECT artist, track, verdict, ts, context FROM main.feedback ORDER BY id").fetchall()
        return [Feedback(a, v, t, parse_ts(ts) or datetime.now().astimezone(), json.loads(c or "{}"))
                for a, t, v, ts, c in rows]

    def clear_feedback(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM main.feedback")
            self._commit()
            self._db.execute("VACUUM main")

    # ---- settings -------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM main.settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO main.settings VALUES (?,?)", (key, json.dumps(value)))
            self._commit()

    # ---- HTTP cache -----------------------------------------------------
    def cache_get(self, key: str, max_age: float) -> tuple[bool, Any]:
        with self._lock:
            row = self._db.execute("SELECT body, fetched FROM cache.http_cache WHERE key=?", (key,)).fetchone()
        if not row or time.time() - row[1] > max_age:
            return False, None
        return True, _unpack(row[0])

    def cache_put(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO cache.http_cache VALUES (?,?,?)", (key, _pack(value), time.time()))
            self._commit()

    # ---- larger saved objects (the music map) ---------------------------------------------------
    def put_blob(self, key: str, value: Any) -> None:
        with self._lock:
            if value is None:
                self._db.execute("DELETE FROM main.blobs WHERE key=?", (key,))
            else:
                self._db.execute("INSERT OR REPLACE INTO main.blobs VALUES (?,?)", (key, _pack(value)))
            self._commit()

    def get_blob(self, key: str) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM main.blobs WHERE key=?", (key,)).fetchone()
        return _unpack(row[0]) if row else None
