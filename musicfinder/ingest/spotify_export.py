"""Parse the files in a Spotify "Download your data" export.

Supported (detected by content, not file name, so renamed files still work):

* Extended streaming history  -- ``Streaming_History_Audio_*.json`` / older ``endsong_*.json``.
  Every play with ``ms_played``, ``reason_start``, ``reason_end``, ``skipped``, ``shuffle``...
  This is by far the most informative source because it records *skips*.
* Account-data streaming history -- ``StreamingHistory_music_*.json`` / ``StreamingHistory*.json``
  (``endTime``, ``artistName``, ``trackName``, ``msPlayed``; last 12 months only, no skip flags).
* ``YourLibrary.json`` -- liked songs, saved albums, followed artists, hidden ("banned") songs/artists.
* ``Playlist*.json`` -- songs the user put into their own playlists.

Podcasts, audiobooks and videos are ignored.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from musicfinder.models import LibraryItem, Play, parse_ts
from musicfinder.normalize import is_various

MAX_JSON_BYTES = 512 * 1024 * 1024


@dataclass
class ImportResult:
    plays: list[Play] = field(default_factory=list)
    library: list[LibraryItem] = field(default_factory=list)
    recognized: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    non_music_rows: int = 0

    def extend(self, other: "ImportResult") -> None:
        self.plays.extend(other.plays)
        self.library.extend(other.library)
        self.recognized.extend(other.recognized)
        self.ignored.extend(other.ignored)
        self.non_music_rows += other.non_music_rows

    def summary(self) -> dict:
        kinds: dict[str, int] = {}
        for item in self.library:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        formats: dict[str, int] = {}
        for p in self.plays:
            formats[p.fmt] = formats.get(p.fmt, 0) + 1
        return {
            "plays": len(self.plays),
            "play_formats": formats,
            "library": kinds,
            "files_recognized": self.recognized,
            "files_ignored": self.ignored,
            "non_music_rows_skipped": self.non_music_rows,
        }


def _bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes"}
    return bool(v)


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _parse_extended(rows: list[dict]) -> tuple[list[Play], int]:
    plays, skipped_rows = [], 0
    for r in rows:
        track = r.get("master_metadata_track_name")
        artist = r.get("master_metadata_album_artist_name")
        ts = parse_ts(r.get("ts") or "")
        if not track or not artist or ts is None or is_various(artist):
            skipped_rows += 1  # podcast episode, audiobook, video, or missing metadata
            continue
        plays.append(
            Play(
                ts=ts,
                artist=str(artist),
                track=str(track),
                album=str(r.get("master_metadata_album_album_name") or ""),
                ms_played=_int(r.get("ms_played")),
                track_uri=r.get("spotify_track_uri"),
                reason_start=r.get("reason_start"),
                reason_end=r.get("reason_end"),
                skipped=_bool(r.get("skipped")),
                shuffle=_bool(r.get("shuffle")),
                fmt="extended",
            )
        )
    return plays, skipped_rows


def _parse_basic(rows: list[dict]) -> tuple[list[Play], int]:
    plays, skipped_rows = [], 0
    for r in rows:
        artist, track = r.get("artistName"), r.get("trackName")
        ts = parse_ts(r.get("endTime") or "")
        if not artist or not track or ts is None or is_various(artist):
            skipped_rows += 1
            continue
        plays.append(
            Play(ts=ts, artist=str(artist), track=str(track), ms_played=_int(r.get("msPlayed")), fmt="basic")
        )
    return plays, skipped_rows


def _parse_library(doc: dict) -> list[LibraryItem]:
    items: list[LibraryItem] = []
    for t in doc.get("tracks") or []:
        if t.get("artist") and t.get("track"):
            items.append(LibraryItem("saved_track", t["artist"], t["track"], t.get("uri")))
    for a in doc.get("albums") or []:
        if a.get("artist"):
            items.append(LibraryItem("saved_album", a["artist"], a.get("album", ""), a.get("uri")))
    for a in doc.get("artists") or []:
        name = a.get("name") if isinstance(a, dict) else a
        if name:
            items.append(LibraryItem("followed_artist", name, "", a.get("uri") if isinstance(a, dict) else None))
    for t in doc.get("bannedTracks") or []:
        if t.get("artist"):
            items.append(LibraryItem("banned_track", t["artist"], t.get("track", ""), t.get("uri")))
    for a in doc.get("bannedArtists") or []:
        name = a.get("name") if isinstance(a, dict) else a
        if name:
            items.append(LibraryItem("banned_artist", name, "", a.get("uri") if isinstance(a, dict) else None))
    return [i for i in items if not is_various(i.artist)]


def _parse_playlists(doc: dict) -> list[LibraryItem]:
    items: list[LibraryItem] = []
    for pl in doc.get("playlists") or []:
        for entry in pl.get("items") or []:
            t = entry.get("track") or {}
            if t.get("artistName") and t.get("trackName") and not is_various(t["artistName"]):
                items.append(
                    LibraryItem(
                        "playlist_track",
                        t["artistName"],
                        t["trackName"],
                        t.get("trackUri"),
                        parse_ts(entry.get("addedDate") or ""),
                    )
                )
    return items


def parse_document(name: str, doc: Any) -> ImportResult:
    """Classify a decoded JSON document and convert it into plays / library items."""
    res = ImportResult()
    if isinstance(doc, list) and doc and isinstance(doc[0], dict):
        first = doc[0]
        if "ms_played" in first and "ts" in first:
            res.plays, res.non_music_rows = _parse_extended(doc)
        elif "msPlayed" in first and "endTime" in first and ("trackName" in first or "artistName" in first):
            res.plays, res.non_music_rows = _parse_basic(doc)
        elif "podcastName" in first or "episodeName" in first:
            res.ignored.append(name)
            return res
        else:
            res.ignored.append(name)
            return res
    elif isinstance(doc, dict) and any(k in doc for k in ("tracks", "bannedTracks", "artists", "bannedArtists")):
        res.library = _parse_library(doc)
    elif isinstance(doc, dict) and "playlists" in doc:
        res.library = _parse_playlists(doc)
    else:
        res.ignored.append(name)
        return res
    res.recognized.append(name)
    return res


def parse_bytes(name: str, data: bytes) -> ImportResult:
    """Parse one uploaded file: a ``.zip`` export or a single ``.json`` file."""
    lower = name.lower()
    if lower.endswith(".zip") or data[:2] == b"PK":
        return _parse_zip(data)
    if not lower.endswith(".json"):
        return ImportResult(ignored=[name])
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ImportResult(ignored=[name])
    return parse_document(name, doc)


def _parse_zip(data: bytes) -> ImportResult:
    res = ImportResult()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if info.is_dir() or "__MACOSX" in info.filename or base.startswith("."):
                continue
            if not base.lower().endswith(".json") or info.file_size > MAX_JSON_BYTES:
                if not info.is_dir():
                    res.ignored.append(info.filename)
                continue
            res.extend(parse_bytes(info.filename, zf.read(info)))
    return res


def load_paths(paths: Iterable[str | Path]) -> ImportResult:
    """Load any mix of export folders, ``.zip`` archives and ``.json`` files from disk."""
    res = ImportResult()
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            files = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in {".json", ".zip"})
            for f in files:
                res.extend(parse_bytes(str(f.relative_to(p)), f.read_bytes()))
        elif p.is_file():
            res.extend(parse_bytes(p.name, p.read_bytes()))
        else:
            raise FileNotFoundError(f"No such file or folder: {p}")
    return res


def reconcile(plays: list[Play]) -> list[Play]:
    """Drop duplicates and, where extended history exists, the overlapping (less detailed) basic rows."""
    ext = [p for p in plays if p.fmt == "extended"]
    basic = [p for p in plays if p.fmt != "extended"]
    if ext and basic:
        lo, hi = min(p.ts for p in ext), max(p.ts for p in ext)
        basic = [p for p in basic if p.ts < lo or p.ts > hi]
    seen: set[tuple] = set()
    out: list[Play] = []
    for p in sorted(ext + basic, key=lambda p: p.ts):
        k = (p.ts, p.artist, p.track, p.ms_played)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out
