"""Turn raw Spotify plays into a quantitative model of the listener's taste.

Plays are *implicit feedback*: exposure and repetition do not prove preference (Hu, Koren &
Volinsky, "Collaborative Filtering for Implicit Feedback Datasets", ICDM 2008). This app uses
transparent heuristics for completion, deliberate selection and skips. An early skip can mean
poor fit or a change of context; pauses, app closure and connection loss are kept neutral.

Per artist we keep

* ``affinity``      time-decayed sum of engagement (exponential half-life, tunable by backtest)
* ``satisfaction``  posterior probability that a play is *not* an early skip, using a Beta prior
                    fitted to the whole history by the method of moments (empirical Bayes), so an
                    artist heard twice is not judged as harshly/kindly as one heard 200 times.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

from musicfinder.feedback import latest_by_item
from musicfinder.models import Feedback, LibraryItem, Play
from musicfinder.normalize import artist_key, track_key

INTENT_STARTS = {"clickrow", "backbtn"}  # user picked the song / went back to replay it
SKIP_ENDS = {"fwdbtn"}  # user pressed "next"
SWITCH_ENDS = {"clickrow"}  # user picked another song while this one played
TYPICAL_TRACK_MS = 210_000


@dataclass(frozen=True)
class TasteParams:
    half_life_days: float | None = 365.0  # None = no decay (all-time taste)
    recent_half_life_days: float = 45.0
    qualify_ms: int = 30_000  # Spotify's "stream" threshold
    noise_ms: int = 1_500  # shorter plays are glitches/preloads: no signal
    intent_bonus: float = 0.3
    skip_penalty: float = 1.0
    late_skip_factor: float = 0.6
    seed_power: float = 0.5  # seed weight = affinity ** seed_power (compresses obsessions)
    saved_track_bonus: float = 2.0
    saved_album_bonus: float = 4.0
    followed_artist_bonus: float = 6.0
    playlist_bonus: float = 1.0
    picked_bonus: float = 8.0  # artists picked as loved in the app (at least a typical favourite's weight)
    use_library: bool = True

    def with_(self, **kw) -> "TasteParams":
        return replace(self, **kw)


@dataclass
class TrackTaste:
    artist_key: str
    key: str
    name: str
    artist: str
    streams: int = 0
    early_skips: int = 0
    engagement: float = 0.0
    last: datetime | None = None
    uri: str | None = None
    explicit: float = 0.0
    banned: bool = False
    feedback: str | None = None
    feedback_ts: datetime | None = None
    _feedback_bonus: float = field(default=0.0, repr=False)
    _library_banned: bool = field(default=False, repr=False)
    _library_ban_ts: datetime | None = field(default=None, repr=False)

    @property
    def affinity(self) -> float:
        return max(0.0, self.engagement + self.explicit)


@dataclass
class ArtistTaste:
    key: str
    name: str
    plays: int = 0
    streams: int = 0
    early_skips: int = 0
    completes: int = 0
    intent_plays: int = 0
    ms_played: int = 0
    first: datetime | None = None
    last: datetime | None = None
    engagement: float = 0.0  # decayed with half_life_days
    recent_engagement: float = 0.0  # decayed with recent_half_life_days
    explicit: float = 0.0
    banned: bool = False
    feedback: str | None = None
    picked: bool = False  # picked as a favourite in the app
    satisfaction: float = 0.5
    _days: set = field(default_factory=set, repr=False)
    _feedback_bonus: float = field(default=0.0, repr=False)
    _song_feedback_bonus: float = field(default=0.0, repr=False)
    _song_dislike_weight: float = field(default=0.0, repr=False)
    _library_banned: bool = field(default=False, repr=False)
    _preference_ts: datetime | None = field(default=None, repr=False)
    _preference_verdict: str | None = field(default=None, repr=False)

    @property
    def affinity(self) -> float:
        return max(0.0, self.engagement + self.explicit)

    @property
    def recent_affinity(self) -> float:
        return max(0.0, self.recent_engagement)

    @property
    def active_days(self) -> int:
        return len(self._days)

    @property
    def skip_rate(self) -> float:
        n = self.streams + self.early_skips
        return self.early_skips / n if n else 0.0


@dataclass
class TasteProfile:
    as_of: datetime
    params: TasteParams
    artists: dict[str, ArtistTaste]
    tracks: dict[tuple[str, str], TrackTaste]
    prior: tuple[float, float]
    n_plays: int
    n_streams: int
    n_early_skips: int
    total_ms: int
    first: datetime | None
    last: datetime | None
    formats: dict[str, int]
    _feedback_items: dict[tuple[str, str], Feedback] = field(default_factory=dict, repr=False)

    # ---- seeds ----------------------------------------------------------
    def positive_seeds(self, n: int | None = None, recent: bool = False) -> dict[str, float]:
        """Artist -> seed weight for the graph walk. Banned/disliked artists never seed."""
        p = self.params.seed_power
        items = []
        for a in self.artists.values():
            if a.banned or a.feedback == "dislike":
                continue
            aff = a.recent_affinity if recent else a.affinity
            if aff > 0:
                items.append((a.key, aff ** p))
        items.sort(key=lambda kv: -kv[1])
        if n is not None:
            items = items[:n]
        return dict(items)

    def negative_seeds(self) -> dict[str, float]:
        """Artists the listener demonstrably rejects (hidden, disliked, or skipped again and again)."""
        out: dict[str, float] = {}
        for a in self.artists.values():
            if a.banned or a.feedback == "dislike":
                out[a.key] = 3.0
            elif a.picked or a.feedback == "like":
                continue  # the listener's explicit preference outweighs old/contextual skips
            elif a._song_dislike_weight:
                out[a.key] = a._song_dislike_weight  # weak transfer, never a whole-artist ban
            elif a.early_skips >= 2 and a.streams == 0:
                out[a.key] = math.log1p(a.early_skips)
            elif a.early_skips >= 3 and a.satisfaction < 0.35:
                out[a.key] = 0.5 * math.log1p(a.early_skips)
        return out

    def known_artists(self) -> set[str]:
        song_artists = {a for a, _ in self.known_tracks()}
        return {a.key for a in self.artists.values()
                if a.plays or a.explicit or a.picked or a.banned or a.feedback or a.key in song_artists}

    def known_tracks(self) -> set[tuple[str, str]]:
        return {key for key, t in self.tracks.items()
                if (t.streams or t.early_skips or t.last
                    or abs(t.engagement - getattr(t, "_interaction_bonus", 0.0)) > 1e-9
                    or t.explicit or t.banned or t.feedback)}

    def blocked_artists(self) -> set[str]:
        """Only explicit whole-artist rejection blocks all songs; weak negatives change rank."""
        return {a.key for a in self.artists.values() if a.banned or a.feedback == "dislike"}

    @property
    def global_satisfaction(self) -> float:
        a, b = self.prior
        return a / (a + b)

    def top_artists(self, n: int = 50) -> list[ArtistTaste]:
        return sorted(
            (a for a in self.artists.values() if a.affinity > 0 and not a.banned and a.feedback != "dislike"),
            key=lambda a: -a.affinity,
        )[:n]

    def top_tracks(self, n: int = 50) -> list[TrackTaste]:
        blocked = {a.key for a in self.artists.values() if a.banned or a.feedback == "dislike"}
        return sorted((t for t in self.tracks.values()
                       if t.affinity > 0 and not t.banned and t.feedback != "dislike" and t.artist_key not in blocked),
                      key=lambda t: -t.affinity)[:n]

    def diversity(self) -> float:
        """Effective number of artists: exp(Shannon entropy) of the affinity distribution."""
        weights = [a.affinity for a in self.artists.values() if a.affinity > 0]
        total = sum(weights)
        if total <= 0:
            return 0.0
        h = -sum((w / total) * math.log(w / total) for w in weights)
        return math.exp(h)


def _decay(age_days: float, half_life: float | None) -> float:
    if half_life is None or half_life <= 0:
        return 1.0
    return 0.5 ** (max(age_days, 0.0) / half_life)


def estimate_durations(plays: Iterable[Play]) -> dict[tuple[str, str], int]:
    """Spotify exports omit track length, so infer it: longest play that ended naturally, else longest play."""
    done: dict[tuple[str, str], int] = {}
    longest: dict[tuple[str, str], int] = {}
    for p in plays:
        k = (p.artist_key, p.track_key)
        if p.ms_played > longest.get(k, 0):
            longest[k] = p.ms_played
        if p.reason_end == "trackdone" and p.ms_played > done.get(k, 0):
            done[k] = p.ms_played
    return {k: done.get(k, v) for k, v in longest.items()}


def play_engagement(p: Play, duration_ms: int | None, params: TasteParams) -> tuple[float, str]:
    """Score one play. Returns (engagement, outcome) where outcome is 'stream', 'early_skip' or 'neutral'."""
    ms = p.ms_played
    skipped = p.skipped is True or p.reason_end in SKIP_ENDS
    if ms < params.noise_ms and not skipped:
        return 0.0, "neutral"
    if ms < params.qualify_ms:
        if p.fmt == "basic":
            # Account-data exports have no skip flags; a sub-30 s play is *probably* a skip.
            return -0.5 * params.skip_penalty, "early_skip"
        if skipped:
            return -params.skip_penalty, "early_skip"
        if p.reason_end in SWITCH_ENDS:
            return -0.5 * params.skip_penalty, "early_skip"
        return 0.0, "neutral"  # paused, app closed, connection lost: not about the song
    dur = duration_ms if duration_ms and duration_ms >= params.qualify_ms else TYPICAL_TRACK_MS
    frac = 1.0 if p.reason_end == "trackdone" else min(1.0, ms / dur)
    value = frac
    if skipped:
        value *= params.late_skip_factor
    if p.reason_start in INTENT_STARTS:
        value *= 1.0 + params.intent_bonus
    return value, "stream"


def fit_beta_prior(successes_failures: list[tuple[int, int]], min_n: int = 5) -> tuple[float, float]:
    """Method-of-moments Beta prior over per-artist 'not skipped' rates (empirical Bayes)."""
    rates = [s / (s + f) for s, f in successes_failures if s + f >= min_n]
    total_s = sum(s for s, _ in successes_failures)
    total_n = sum(s + f for s, f in successes_failures)
    mean = total_s / total_n if total_n else 0.8
    mean = min(max(mean, 0.02), 0.98)
    if len(rates) >= 5:
        mu = sum(rates) / len(rates)
        var = sum((r - mu) ** 2 for r in rates) / (len(rates) - 1)
        strength = mean * (1 - mean) / var - 1 if var > 1e-9 else 50.0
    else:
        strength = 4.0
    strength = min(max(strength, 2.0), 50.0)
    return mean * strength, (1 - mean) * strength


def build_profile(
    plays: Iterable[Play],
    library: Iterable[LibraryItem] = (),
    params: TasteParams = TasteParams(),
    as_of: datetime | None = None,
    feedback: Iterable[Feedback] = (),
    interactions: Iterable = (),
) -> TasteProfile:
    """Build a :class:`TasteProfile` from plays strictly before ``as_of`` (default: all plays).

    With an explicit ``as_of`` (a backtest), library items added after it are ignored too; otherwise
    everything counts, including artists picked in the app after the last play in the export.
    """
    cutoff = as_of
    plays = sorted((p for p in plays if as_of is None or p.ts < as_of), key=lambda p: p.ts)
    if as_of is None:
        as_of = (plays[-1].ts + timedelta(seconds=1)) if plays else datetime.now(timezone.utc)
    durations = estimate_durations(plays)

    artists: dict[str, ArtistTaste] = {}
    tracks: dict[tuple[str, str], TrackTaste] = {}
    formats: dict[str, int] = defaultdict(int)
    n_streams = n_skips = total_ms = 0

    def artist(name: str) -> ArtistTaste:
        k = artist_key(name)
        a = artists.get(k)
        if a is None:
            a = artists[k] = ArtistTaste(k, name)
        return a

    def track(a: ArtistTaste, title: str, artist_name: str) -> TrackTaste:
        k = (a.key, track_key(title))
        t = tracks.get(k)
        if t is None:
            t = tracks[k] = TrackTaste(a.key, k[1], title, artist_name)
        return t

    for p in plays:
        formats[p.fmt] += 1
        tk = (p.artist_key, p.track_key)
        value, outcome = play_engagement(p, durations.get(tk), params)
        if outcome == "neutral" and p.ms_played < params.noise_ms:
            continue
        a = artist(p.artist)
        t = track(a, p.track, p.artist)
        age = (as_of - p.ts).total_seconds() / 86400.0
        a.plays += 1
        a.ms_played += p.ms_played
        total_ms += p.ms_played
        a.first = a.first or p.ts
        a.last = p.ts
        t.last = p.ts
        t.uri = t.uri or p.track_uri
        if outcome == "stream":
            a.streams += 1
            t.streams += 1
            n_streams += 1
            a._days.add(p.ts.date())
            if p.reason_end == "trackdone":
                a.completes += 1
            if p.reason_start in INTENT_STARTS:
                a.intent_plays += 1
        elif outcome == "early_skip":
            a.early_skips += 1
            t.early_skips += 1
            n_skips += 1
        a.engagement += value * _decay(age, params.half_life_days)
        a.recent_engagement += value * _decay(age, params.recent_half_life_days)
        t.engagement += value * _decay(age, params.half_life_days)

    if params.use_library:
        bonus = {
            "saved_track": params.saved_track_bonus,
            "saved_album": params.saved_album_bonus,
            "followed_artist": params.followed_artist_bonus,
            "playlist_track": params.playlist_bonus,
        }
        picked: list[ArtistTaste] = []
        for item in library:
            if cutoff is not None and item.added is not None and item.added >= cutoff:
                continue
            a = artist(item.artist)
            if item.kind in ("picked_artist", "picked_dislike"):
                pref_ts = item.added or datetime.min.replace(tzinfo=timezone.utc)
                if a._preference_ts is None or pref_ts >= a._preference_ts:
                    a._preference_ts = pref_ts
                    a._preference_verdict = "like" if item.kind == "picked_artist" else "dislike"
            if item.kind in ("banned_artist", "picked_dislike"):
                a.banned = True
            elif item.kind == "picked_artist":
                picked.append(a)
            elif item.kind == "banned_track":
                if item.track:
                    t = track(a, item.track, item.artist)
                    t.banned = True
                    ts = item.added or datetime.min.replace(tzinfo=timezone.utc)
                    if t._library_ban_ts is None or ts >= t._library_ban_ts:
                        t._library_ban_ts = ts
            elif item.kind in bonus:
                a.explicit += bonus[item.kind]
                if item.kind in ("saved_track", "playlist_track") and item.track:
                    t = track(a, item.track, item.artist)
                    t.explicit += bonus[item.kind]
                    t.uri = t.uri or item.uri
        if picked:
            # A pick counts like a solid current favourite: the median of the top 50 artists' weight.
            top = sorted((a.affinity for a in artists.values() if a.affinity > 0), reverse=True)[:50]
            pick = max(params.picked_bonus, top[len(top) // 2] if top else 0.0)
            for a in picked:
                if not a.picked and a._preference_verdict == "like":
                    a.picked = True
                    a.banned = False  # picking overrides an artist hidden in Spotify long ago
                    a.explicit += max(pick, pick - a.engagement - a.explicit)
                    a.recent_engagement += max(pick, pick - a.recent_engagement)

    prior = fit_beta_prior([(a.streams, a.early_skips) for a in artists.values()])
    for a in artists.values():
        a.satisfaction = (a.streams + prior[0]) / (a.streams + a.early_skips + prior[0] + prior[1])

    profile = TasteProfile(
        as_of=as_of, params=params, artists=artists, tracks=tracks, prior=prior, n_plays=len(plays),
        n_streams=n_streams, n_early_skips=n_skips, total_ms=total_ms,
        first=plays[0].ts if plays else None, last=plays[-1].ts if plays else None, formats=dict(formats),
    )
    for a in artists.values():
        a._library_banned = a.banned
    for t in tracks.values():
        t._library_banned = t.banned
    apply_feedback(profile, (fb for fb in feedback if cutoff is None or fb.ts < cutoff))
    from musicfinder.interactions import apply_interactions
    apply_interactions(profile, interactions, cutoff=cutoff)
    return profile


def apply_feedback(profile: TasteProfile, feedback: Iterable[Feedback]) -> None:
    """Recompute reversible preferences from latest item verdicts, without fabricating plays.

    Explicit artist choices dominate weaker song-to-artist transfer. A song like is a strong song
    seed; distinct song verdicts accumulate a saturating artist adjustment. One rejected song never
    declares that every song by its artist is unwanted.
    """
    for key, fb in latest_by_item(feedback).items():
        old = profile._feedback_items.get(key)
        if old is None or fb.ts >= old.ts:
            profile._feedback_items[key] = fb
    latest = profile._feedback_items
    if not latest:
        return
    for a in profile.artists.values():
        adjustment = a._feedback_bonus + a._song_feedback_bonus
        a.explicit -= adjustment
        a.recent_engagement -= adjustment
        a._feedback_bonus = a._song_feedback_bonus = a._song_dislike_weight = 0.0
        a.feedback = None
        a.banned = a._library_banned
    for t in profile.tracks.values():
        t.explicit -= t._feedback_bonus
        t._feedback_bonus = 0.0
        t.feedback = None
        t.feedback_ts = None
        t.banned = t._library_banned
    top = sorted((a.affinity for a in profile.artists.values()
                  if a.affinity > 0 and not a.banned), reverse=True)[:50]
    like_bonus = max(3.0, top[len(top) // 2]) if top else 3.0
    song_top = sorted((t.affinity for t in profile.tracks.values() if t.affinity > 0 and not t.banned),
                      reverse=True)[:50]
    song_bonus = max(4.0, song_top[len(song_top) // 2]) if song_top else 4.0
    song_votes: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (key, song_key), fb in latest.items():
        if fb.verdict == "clear":
            continue
        a = profile.artists.get(key)
        if a is None:
            a = profile.artists[key] = ArtistTaste(key, fb.artist)
        if song_key:
            t = profile.tracks.get((key, song_key))
            if t is None:
                t = profile.tracks[key, song_key] = TrackTaste(key, song_key, fb.track, fb.artist)
            t.feedback, t.feedback_ts = fb.verdict, fb.ts
            if fb.verdict == "like":
                if t._library_ban_ts is None or fb.ts > t._library_ban_ts:
                    t.banned = False
                if t.banned:
                    continue  # a newer imported rejection also withdraws this older positive seed
                bonus = max(song_bonus, song_bonus - t.engagement - t.explicit)
                t.explicit += bonus
                t._feedback_bonus = bonus
                song_votes[key][0] += 1
            elif fb.verdict == "dislike":
                song_votes[key][1] += 1
            continue
        if (a._preference_ts is not None and a._preference_ts >= fb.ts
                and a._preference_verdict in ("like", "dislike")):
            continue  # a newer Setup choice supersedes an older recommendation verdict
        a.feedback = fb.verdict
        if fb.verdict == "like":
            a.banned = False  # a new explicit like can overturn an old hidden/disliked artist
            bonus = max(like_bonus, like_bonus - a.engagement - a.explicit,
                        like_bonus - a.recent_engagement)
            a.explicit += bonus
            a.recent_engagement += bonus
            a._feedback_bonus = bonus
    for key, (likes, dislikes) in song_votes.items():
        a = profile.artists[key]
        if a.feedback in ("like", "dislike") or a.picked or a.banned:
            continue
        # Distinct tracks supply evidence, repeated clicks on one verdict do not. Saturation keeps
        # an album's many ratings from drowning out deliberate artist choices or a long history.
        adjustment = 3.0 * (1 - math.exp(-0.4 * likes)) - 2.0 * (1 - math.exp(-0.5 * dislikes))
        a.explicit += adjustment
        a.recent_engagement += adjustment
        a._song_feedback_bonus = adjustment
        if dislikes > likes:
            a._song_dislike_weight = min(1.5, 0.35 * math.sqrt(dislikes - likes))
