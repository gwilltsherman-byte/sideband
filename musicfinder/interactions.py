"""Small, bounded interest signals from actions actually observed inside Sideband.

An external link is interest, not a Spotify play. A preview is only a short listen, not
a stream or an explicit rating. Neither contributes to measured listening accuracy.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable
from uuid import UUID

from musicfinder.normalize import artist_key, track_key

if TYPE_CHECKING:
    from musicfinder.taste import TasteProfile

KINDS = ("external_open", "preview_listen")
DAILY_CAP = {"external_open": 1, "preview_listen": 2}
MAX_EVENTS = 5_000
MIN_PREVIEW_MS = 10_000
MAX_PREVIEW_MS = 60_000
HALF_LIFE_DAYS = 45.0
MAX_ARTIST_WEIGHT = 1.5
MAX_TRACK_WEIGHT = 0.8


@dataclass(frozen=True, slots=True)
class Interaction:
    event_id: str
    artist: str
    kind: str
    track: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0

    @property
    def artist_key(self) -> str:
        return artist_key(self.artist)

    @property
    def track_key(self) -> str:
        return track_key(self.track)


def _name(value: object, field_name: str, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    value = unicodedata.normalize("NFC", value.strip())
    if len(value) > 200 or (required and not value) or any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError(f"{field_name} must be a name of at most 200 characters")
    return value


def make_interaction(data: dict, now: datetime | None = None) -> Interaction | None:
    """Validate an observed action; very brief previews carry no taste signal."""
    artist = _name(data.get("artist", ""), "artist")
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("kind must be external_open or preview_listen")
    track = _name(data.get("track", ""), "track", required=kind == "preview_listen")
    raw_id = data.get("event_id")
    if not isinstance(raw_id, str) or len(raw_id) > 36:
        raise ValueError("event_id must be a UUID")
    try:
        event_id = str(UUID(raw_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("event_id must be a UUID") from exc
    duration = data.get("duration_ms", 0)
    if type(duration) not in (int, float) or (type(duration) is float and not math.isfinite(duration)) or duration < 0:
        raise ValueError("duration_ms must be a finite, non-negative number")
    duration = int(min(duration, MAX_PREVIEW_MS)) if kind == "preview_listen" else 0
    if kind == "preview_listen" and duration < MIN_PREVIEW_MS:
        return None
    timestamp = now or datetime.now(timezone.utc)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("An interaction needs a UTC timestamp")
    return Interaction(event_id, artist, kind, track, timestamp.astimezone(timezone.utc), duration)


def apply_interactions(profile: TasteProfile, events: Iterable[Interaction],
                       cutoff: datetime | None = None) -> None:
    """Apply decayed weak interest. Explicit rejections always have priority.

    Capped weights prevent repeated clicks/replays from outweighing a deliberate rating.
    Reapplying to a cached profile replaces its previous weak adjustment.
    """
    from musicfinder.taste import ArtistTaste, TrackTaste

    for a in profile.artists.values():
        old = getattr(a, "_interaction_bonus", 0.0)
        a.engagement -= old
        a.recent_engagement -= old
        a._interaction_bonus = 0.0
    for t in profile.tracks.values():
        t.engagement -= getattr(t, "_interaction_bonus", 0.0)
        t._interaction_bonus = 0.0

    now = cutoff or datetime.now(timezone.utc)
    artist_weights: dict[str, float] = defaultdict(float)
    song_weights: dict[tuple[str, str], float] = defaultdict(float)
    names: dict[str, str] = {}
    titles: dict[tuple[str, str], str] = {}
    seen: set[str] = set()
    daily: dict[tuple, int] = defaultdict(int)
    for event in events:
        if event.event_id in seen or event.kind not in KINDS or (cutoff is not None and event.ts >= cutoff):
            continue
        seen.add(event.event_id)
        akey, tkey = event.artist_key, event.track_key
        day_key = (akey, tkey, event.kind, event.ts.astimezone(timezone.utc).date())
        if daily[day_key] >= DAILY_CAP[event.kind]:
            continue
        daily[day_key] += 1
        a = profile.artists.get(akey)
        t = profile.tracks.get((akey, tkey)) if tkey else None
        if (a is not None and (a.banned or a.feedback == "dislike")) or (
            t is not None and (t.banned or getattr(t, "feedback", None) in ("dislike", "known"))
        ):
            continue
        if event.kind == "preview_listen":
            if event.duration_ms < MIN_PREVIEW_MS:
                continue
            weight = 0.15 + 0.20 * (min(event.duration_ms, MAX_PREVIEW_MS) - MIN_PREVIEW_MS) / (MAX_PREVIEW_MS - MIN_PREVIEW_MS)
        else:
            weight = 0.05
        age_days = max(0.0, (now - event.ts).total_seconds() / 86_400)
        weight *= 0.5 ** (age_days / HALF_LIFE_DAYS)
        artist_weights[akey] += weight
        names.setdefault(akey, event.artist)
        if tkey:
            song_weights[(akey, tkey)] += weight
            titles.setdefault((akey, tkey), event.track)

    for key, weight in artist_weights.items():
        a = profile.artists.setdefault(key, ArtistTaste(key, names[key]))
        a._interaction_bonus = min(MAX_ARTIST_WEIGHT, weight)
        a.engagement += a._interaction_bonus
        a.recent_engagement += a._interaction_bonus
    for (akey, tkey), weight in song_weights.items():
        t = profile.tracks.setdefault((akey, tkey), TrackTaste(akey, tkey, titles[(akey, tkey)], names[akey]))
        t._interaction_bonus = min(MAX_TRACK_WEIGHT, weight)
        t.engagement += t._interaction_bonus
