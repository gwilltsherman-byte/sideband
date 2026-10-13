"""Core data records shared across the app."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from musicfinder.normalize import artist_key, track_key


@dataclass(frozen=True, slots=True)
class Play:
    """One playback event from Spotify (one row of a streaming-history file)."""

    ts: datetime  # when playback *ended*, UTC
    artist: str
    track: str
    album: str = ""
    ms_played: int = 0
    track_uri: str | None = None
    reason_start: str | None = None
    reason_end: str | None = None
    skipped: bool | None = None
    shuffle: bool | None = None
    fmt: str = "extended"  # "extended" (Extended Streaming History) or "basic" (Account data)

    @property
    def artist_key(self) -> str:
        return artist_key(self.artist)

    @property
    def track_key(self) -> str:
        return track_key(self.track)


LIBRARY_KINDS = ("saved_track", "saved_album", "followed_artist", "playlist_track", "banned_track", "banned_artist")


@dataclass(frozen=True, slots=True)
class LibraryItem:
    """An explicit signal: a saved song/album, a followed artist, a playlist add, or a hidden ("banned") item."""

    kind: str
    artist: str
    track: str = ""
    uri: str | None = None
    added: datetime | None = None


@dataclass(slots=True)
class Feedback:
    """A rating the user gave inside musicfinder."""

    artist: str
    verdict: str  # "like" | "dislike" | "known"
    track: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict = field(default_factory=dict)

    @property
    def artist_key(self) -> str:
        return artist_key(self.artist)


def parse_ts(value: str) -> datetime | None:
    """Parse the timestamp formats found in Spotify exports into an aware UTC datetime."""
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    for candidate in (v, v.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None
