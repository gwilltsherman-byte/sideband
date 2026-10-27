"""Shared types for music-knowledge sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Neighbor:
    """A similar artist as reported by one source. ``score`` is in [0, 1]."""

    name: str
    score: float
    mbid: str | None = None


@dataclass
class TrackInfo:
    title: str
    artist: str
    popularity: float = 0.0  # listeners / rank, source-specific scale
    preview_url: str | None = None
    link: str | None = None
    image: str | None = None
    album: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Knowledge(Protocol):
    """Everything the recommender needs to know about the world's music."""

    sources: list[str]

    def neighbors(self, name: str) -> dict[str, list[Neighbor]]: ...

    def tags(self, name: str) -> dict[str, float]: ...

    def popularity(self, name: str) -> float | None: ...

    def top_tracks(self, name: str, limit: int = 10) -> list[TrackInfo]: ...

    def similar_tracks(self, artist: str, track: str, limit: int = 50) -> list[tuple[str, str, float]]: ...

    def preview(self, artist: str, track: str) -> TrackInfo | None: ...

    def tag_artists(self, tag: str, limit: int = 50) -> list[str]: ...

    def status(self) -> dict[str, Any]: ...


def as_list(value: Any) -> list:
    """Last.fm renders one-element lists as a bare object; normalise to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
