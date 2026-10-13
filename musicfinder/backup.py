"""Portable backups of listening data and preferences, without credentials or SQL."""
from __future__ import annotations

import base64
import json
import math
import sqlite3
import zlib
from datetime import datetime, timezone

TABLES = {
    "feedback": ("main.feedback", 6),
    "settings": ("main.settings", 2),
    "blobs": ("main.blobs", 2),
    "plays": ("data.plays", 11),
    "library": ("data.library", 5),
}
PRIVATE_SETTINGS = {"phone_key", "lastfm_api_key"}
MAX_BYTES = 128 * 1024 * 1024


def export_backup(app):
    if app.demo:
        raise ValueError("Demo data is simulated. Open the full app to save your own backup.")
    with app._lock, app.store._lock:
        tables = {}
        for name, (table, _) in TABLES.items():
            rows = app.store._db.execute(f"SELECT * FROM {table}").fetchall()
            if name == "settings":
                rows = [r for r in rows if r[0] not in PRIVATE_SETTINGS]
            tables[name] = [[{"bytes": base64.b64encode(v).decode("ascii")} if isinstance(v, bytes)
                             else v for v in row] for row in rows]
        return {"app": "sideband", "version": 1,
                "saved": datetime.now(timezone.utc).isoformat(), "tables": tables}


def restore_backup(app, raw):
    if app.demo or app.job.running:
        raise ValueError("Leave the demo and wait for any music-map job to finish before restoring.")
    if len(raw) > MAX_BYTES:
        raise ValueError("That backup is too large (maximum 128 MB).")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("app") != "sideband" or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Choose a supported Sideband backup.")
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError("The backup is missing listening data or has unknown tables.")
    decoded = {}
    for name, rows in tables.items():
        if not isinstance(rows, list) or len(rows) > 1_000_000:
            raise ValueError("Invalid backup rows.")
        result = []
        for row in rows:
            if not isinstance(row, list) or len(row) != TABLES[name][1]:
                raise ValueError("Invalid backup row.")
            values = []
            for index, v in enumerate(row):
                if isinstance(v, dict):
                    if name != "blobs" or index != 1 or set(v) != {"bytes"} or not isinstance(v["bytes"], str):
                        raise ValueError("Invalid backup value.")
                    try:
                        v = base64.b64decode(v["bytes"], validate=True)
                    except (ValueError, TypeError) as exc:
                        raise ValueError("Invalid stored music map.") from exc
                    try:
                        packed = zlib.decompressobj()
                        unpacked = packed.decompress(v, MAX_BYTES)
                        if packed.unconsumed_tail or not packed.eof: raise ValueError("Stored map is too large or incomplete.")
                        json.loads(unpacked)
                    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError("Invalid stored music map.") from exc
                elif v is not None and type(v) not in (str, int, float):
                    raise ValueError("Invalid backup value.")
                if type(v) is int and not -(2**63) <= v < 2**63:
                    raise ValueError("Invalid backup integer.")
                if isinstance(v, float) and not math.isfinite(v):
                    raise ValueError("Invalid backup number.")
                values.append(v)
            if name in ("settings", "blobs") and not isinstance(values[0], str):
                raise ValueError("Invalid backup key.")
            if name == "settings" and (values[0] in PRIVATE_SETTINGS or not isinstance(values[1], str)):
                raise ValueError("Backups cannot replace keys or credentials.")
            result.append(values)
        decoded[name] = result
    with app._lock, app.store._lock:
        db = app.store._db
        try:
            db.execute("BEGIN IMMEDIATE")
            for name, (table, count) in TABLES.items():
                if name == "settings":
                    db.execute("DELETE FROM main.settings WHERE key NOT IN (?, ?)", tuple(PRIVATE_SETTINGS))
                else:
                    db.execute(f"DELETE FROM {table}")
                db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in range(count))})", decoded[name])
            db.commit()
        except sqlite3.Error as exc:
            db.rollback()
            raise ValueError("The backup could not be restored. Your previous data was kept.") from exc
        app.store.writes += 1
        app._invalidate()
        app._kg = None
        app._kg_loaded = False
        app._knowledge = None
        app._graph_stale = bool(app.store.get_setting("graph_stale", False))
    return {"ok": True}
