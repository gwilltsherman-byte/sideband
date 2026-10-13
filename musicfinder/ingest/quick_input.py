"""Small, explicit music-preference lists; parsing never contacts a music service.

Artist lists, favourite-song lines and named-column CSV/TSV tables become LibraryItems. They never
become listening events: a playlist cannot establish when, how often, or how much somebody played.
The result is a reviewable preview, including any rows that need correction before saving.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from musicfinder.models import LibraryItem
from musicfinder.normalize import artist_key, is_various, track_key

MAX_QUICK_BYTES = 200 * 1024
MAX_QUICK_ENTRIES = 500
MAX_NAME_CHARS = 200
MODES = {"auto", "artists", "songs", "csv", "tsv"}
_SONG_SEPARATOR = re.compile(r"\s*[—–]\s*|\s+-\s+")
_LINK = re.compile(r"^(?:https?://|spotify:|www\.|open\.spotify\.com/)", re.IGNORECASE)
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ARTIST_HEADERS = {"artist", "artists", "artistname", "artistnames",
                   "mastermetadataalbumartistname"}
_TRACK_HEADERS = {"track", "trackname", "name", "title", "song", "songname", "tracktitle", "songtitle",
                  "mastermetadatatrackname"}
_URI_HEADERS = {"trackuri", "spotifytrackuri", "spotifyuri", "uri", "trackurl", "spotifyurl"}
_EXPLICIT_WARNING = "These are favourites and saved songs, not listening or skip history. They do not create plays for the accuracy test."


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().casefold())


def _clean(value: str) -> str:
    return " ".join(value.strip().split())


@dataclass
class QuickInputResult:
    library: list[LibraryItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    format: str = "artists"
    duplicates: int = 0

    def to_dict(self) -> dict:
        return {
            "items": [{"kind": i.kind, "artist": i.artist, "track": i.track, "uri": i.uri}
                      for i in self.library],
            "counts": {"artists": len({artist_key(i.artist) for i in self.library}),
                       "tracks": sum(bool(i.track) for i in self.library), "total": len(self.library)},
            "warnings": list(self.warnings), "errors": list(self.errors), "format": self.format,
            "duplicates": self.duplicates, "can_save": bool(self.library) and not self.errors,
        }


def _table_header(first_line: str, delimiters: list[str]) -> tuple[str, list[str]] | None:
    """Recognize column names instead of guessing that every comma separates artist names."""
    found = []
    for delimiter in delimiters:
        try:
            row = next(csv.reader([first_line], delimiter=delimiter, strict=True))
        except (csv.Error, StopIteration):
            continue
        headers = [_header(cell) for cell in row]
        if any(h in _ARTIST_HEADERS for h in headers):
            found.append((sum(h in _ARTIST_HEADERS | _TRACK_HEADERS for h in headers), delimiter, row))
    if not found:
        return None
    _, delimiter, row = max(found, key=lambda item: item[0])
    return delimiter, row


def parse_quick_input(text: str, mode: str = "auto", name: str = "") -> QuickInputResult:
    """Preview a preference list, returning errors instead of silently guessing malformed rows.

    ``auto`` recognizes named-column tables or a complete set of ``Artist — Song`` lines;
    otherwise it keeps one artist per line. CSV filenames require recognizable headers. Artist
    names containing commas are preserved. A semicolon-separated *Artists* column can carry
    multiple credited artists; a comma-separated cell is kept intact because commas also occur in
    real artist names. Input limits apply before deduplication and to expanded credited artists.
    """
    result = QuickInputResult()
    if not isinstance(text, str):
        result.errors.append("Paste text or choose a UTF-8 text, CSV or TSV file.")
        return result
    if mode not in MODES:
        result.errors.append("Choose automatic, artist names, song names, CSV or TSV format.")
        return result
    if len(text) > MAX_QUICK_BYTES or len(text.encode("utf-8")) > MAX_QUICK_BYTES:
        result.errors.append("This list is too large. Use a file or paste up to 200 KB and 500 entries at a time.")
        return result
    if _CONTROLS.search(text):
        result.errors.append("This input contains binary or control characters. Export or save it as UTF-8 text, CSV or TSV.")
        return result
    text = text.lstrip("\ufeff")
    lines = [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1) if line.strip()]
    if not lines:
        result.errors.append("Add at least one artist or favourite song.")
        return result
    if mode == "auto" and name.lower().endswith((".csv", ".tsv")):
        mode = "tsv" if name.lower().endswith(".tsv") else "csv"
    header = _table_header(lines[0][1], ["\t"] if mode == "tsv" else [",", "\t", ";"])
    if mode in {"csv", "tsv"} and header is None:
        result.format = mode
        result.errors.append("The table needs an Artist or Artist Name(s) column; songs also need Track Name, Song or Title. Use names rather than links.")
        return result
    if header is not None and mode not in {"artists", "songs"}:
        delimiter, columns = header
        result.format = "tsv" if delimiter == "\t" else "csv"
        _parse_table(text, delimiter, columns, result)
    else:
        if len(lines) > MAX_QUICK_ENTRIES:
            result.errors.append("Use up to 500 entries at a time. Split this list into smaller batches.")
            return result
        if mode == "auto":
            song_lines = sum(bool(_SONG_SEPARATOR.search(line)) for _, line in lines)
            mode = "songs" if song_lines == len(lines) else "artists"
            if 0 < song_lines < len(lines):
                result.errors.append("This mixes song lines and artist names. Choose Artist names to keep each full line, or use Artist — Song for every song.")
                return result
        result.format = mode
        for number, line in lines:
            if mode == "songs":
                parts = _SONG_SEPARATOR.split(line, maxsplit=1)
                if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                    result.errors.append(f"Line {number}: use Artist — Song with both names, and spaces around a plain hyphen.")
                    continue
                _add_item(result, parts[0], parts[1], number)
            else:
                _add_item(result, line, "", number)
    _deduplicate(result)
    if result.library:
        result.warnings.insert(0, _EXPLICIT_WARNING)
    elif not result.errors:
        result.errors.append("No artist or song names were found. Use names rather than Spotify links or URIs.")
    return result


def _parse_table(text: str, delimiter: str, columns: list[str], result: QuickInputResult) -> None:
    headers = [_header(c) for c in columns]
    artist_cols = [i for i, h in enumerate(headers) if h in _ARTIST_HEADERS]
    track_cols = [i for i, h in enumerate(headers) if h in _TRACK_HEADERS]
    if len(artist_cols) != 1 or len(track_cols) > 1:
        result.errors.append("Use one artist-name column and, for songs, one track-name column; the current headers are ambiguous.")
        return
    artist_col = artist_cols[0]
    track_col = track_cols[0] if track_cols else None
    uri_col = next((i for i, h in enumerate(headers) if h in _URI_HEADERS), None)
    plural = headers[artist_col] in {"artists", "artistnames"}
    rows = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    entries = 0
    try:
        # csv.reader supports quoted fields with embedded newlines; its line_num supplies useful
        # physical row locations in errors instead of treating those fields as extra artists.
        for header_row in rows:
            if header_row and any(cell.strip() for cell in header_row):
                break
        for row in rows:
            if not row or all(not cell.strip() for cell in row):
                continue
            entries += 1
            if entries > MAX_QUICK_ENTRIES:
                result.errors.append("Use up to 500 entries at a time. Split this table into smaller batches.")
                return
            number = rows.line_num
            if len(row) != len(columns):
                result.errors.append(f"Row {number}: has {len(row)} fields but the header has {len(columns)}. Quote names containing the separator.")
                continue
            artists = row[artist_col].split(";") if plural and ";" in row[artist_col] else [row[artist_col]]
            title = row[track_col] if track_col is not None else ""
            if track_col is not None and not title.strip():
                result.errors.append(f"Row {number}: add a track title, or remove the track column for an artist-only list.")
                continue
            uri = row[uri_col].strip() if uri_col is not None else None
            # URI metadata can accompany real names; it is not itself an artist or song preference.
            if uri and not re.match(r"^(?:spotify:track:[a-zA-Z0-9]+|https://open\.spotify\.com/track/[a-zA-Z0-9]+)(?:[?/#].*)?$", uri):
                uri = None
            for artist in artists:
                _add_item(result, artist, title, number, uri)
                if len(result.library) > MAX_QUICK_ENTRIES:
                    result.errors.append("This expands to more than 500 artist/song entries. Split it into smaller batches.")
                    return
    except csv.Error:
        result.errors.append(f"Row {rows.line_num}: the CSV/TSV quoting is incomplete. Export the table again or fix the quoted field.")


def _add_item(result: QuickInputResult, artist: str, title: str, number: int, uri: str | None = None) -> None:
    artist, title = _clean(artist), _clean(title)
    if not artist or not artist_key(artist) or is_various(artist):
        result.errors.append(f"Line {number}: add a specific artist name instead of a blank or Various Artists.")
        return
    if _LINK.match(artist) or _LINK.match(title):
        result.errors.append(f"Line {number}: Spotify links and URIs do not contain music names. Paste artist names, Artist — Song lines, or a CSV/TSV with artist and track-name columns.")
        return
    if len(artist) > MAX_NAME_CHARS or len(title) > MAX_NAME_CHARS:
        result.errors.append(f"Line {number}: artist names and song titles must each be 200 characters or fewer.")
        return
    result.library.append(LibraryItem("saved_track" if title else "picked_artist", artist, title, uri,
                                      datetime.now(timezone.utc)))


def _deduplicate(result: QuickInputResult) -> None:
    seen = set()
    out = []
    for item in result.library:
        key = (item.kind, artist_key(item.artist), track_key(item.track))
        if key in seen:
            result.duplicates += 1
        else:
            seen.add(key)
            out.append(item)
    result.library = out
    if result.duplicates:
        result.warnings.append(f"Removed {result.duplicates} duplicate entr{'y' if result.duplicates == 1 else 'ies'} after normalizing artist and song names.")
