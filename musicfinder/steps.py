"""Resumable network-heavy operations.

Operations that make many web requests (building the music map, the accuracy test, song lookups) are
written as generators that ``yield`` a :class:`Need` just before each batch of lookups. Run them with
:func:`run` and the yields are ignored: the code simply fetches what it needs, as before. A caller
that can do better -- the browser version, which can fetch in parallel but cannot block -- pauses at
each ``Need``, prefetches everything in it concurrently into the cache, and then resumes; the
synchronous code that follows is then served almost entirely from the cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generator, TypeVar

T = TypeVar("T")


@dataclass
class Need:
    kind: str  # "neighbors" | "annotate" | "top_tracks" | "similar_tracks" | "tag_artists"
    items: list = field(default_factory=list)
    label: str = ""


Steps = Generator[Need, None, T]


def run(gen: "Steps[T]") -> T:
    """Drive a step generator synchronously and return its result."""
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def done(value: T) -> "Steps[T]":
    """A step generator that needs nothing and returns ``value`` (for uniform call sites)."""
    return value
    yield  # pragma: no cover  (makes this function a generator)
