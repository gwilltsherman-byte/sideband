"""Live accuracy: how often you actually like what musicfinder shows you, with honest error bars.

Backtests can only grade artists you happened to hear. Your thumbs-up/down describe the artists you
chose to rate: the like rate is reported with a Wilson 95% interval, broken down by how
adventurous the setting was, and once there are enough ratings the match score is calibrated into a
rough in-sample estimate with Platt scaling (a 1-feature logistic regression of 'liked' on rank).
This is not an unbiased accuracy measure or a guarantee about the next artist.
"""

from __future__ import annotations

import math
from typing import Iterable

from musicfinder.models import Feedback
from musicfinder.stats import fit_logistic, wilson_interval

MIN_FOR_CALIBRATION = 20


def _rate(likes: int, n: int) -> dict:
    ci = wilson_interval(likes, n)
    return {
        "likes": likes, "rated": n, "like_rate": round(likes / n, 3) if n else None,
        "ci95": [round(ci[0], 3), round(ci[1], 3)] if ci else None,
    }


def latest_by_item(feedback: Iterable[Feedback]) -> dict[tuple[str, str], Feedback]:
    """One current verdict per artist or song; remasters share the canonical song key."""
    out: dict[tuple[str, str], Feedback] = {}
    for fb in feedback:
        key = fb.item_key
        if key[0] and (key not in out or fb.ts >= out[key].ts):
            out[key] = fb
    return out


def latest_by_artist(feedback: Iterable[Feedback]) -> dict[str, Feedback]:
    """Current artist-only verdicts; song ratings must not calibrate artist scores."""
    return {key[0]: fb for key, fb in latest_by_item(feedback).items() if not key[1]}


def feedback_stats(feedback: Iterable[Feedback]) -> dict:
    items = list(latest_by_item(feedback).values())
    latest = [f for f in items if not f.track_key and f.verdict in ("like", "dislike")]
    songs = [f for f in items if f.track_key and f.verdict in ("like", "dislike")]
    likes = sum(1 for f in latest if f.verdict == "like")
    out = {"overall": _rate(likes, len(latest)),
           "song_overall": _rate(sum(f.verdict == "like" for f in songs), len(songs)),
           "by_source": {}, "by_exploration": {}, "songs_by_kind": {}}
    kinds: dict[str, list[int]] = {}
    for f in songs:
        kind = (f.context or {}).get("kind", "other")
        kind = kind if isinstance(kind, str) else "other"
        rec = kinds.setdefault(kind, [0, 0])
        rec[0] += f.verdict == "like"
        rec[1] += 1
    out["songs_by_kind"] = {k: _rate(*v) for k, v in kinds.items()}
    out["saved_items"] = [
        {"artist": f.artist, "track": f.track, "artist_key": f.artist_key, "track_key": f.track_key,
         "verdict": f.verdict, "ts": f.ts.isoformat(), "kind": (f.context or {}).get("kind"),
         "context": f.context or {}}
        for f in sorted(items, key=lambda f: f.ts, reverse=True) if f.verdict != "clear"
    ]
    by_src: dict[str, list[int]] = {}
    by_exp: dict[str, list[int]] = {}
    for f in latest:
        src = (f.context or {}).get("source", "other")
        rec = by_src.setdefault(src, [0, 0])
        rec[0] += f.verdict == "like"
        rec[1] += 1
        e = (f.context or {}).get("exploration")
        if isinstance(e, (int, float)) and not isinstance(e, bool) and math.isfinite(e) and 0 <= e <= 1:
            bucket = "safe (0–0.33)" if e < 0.34 else "balanced (0.34–0.66)" if e < 0.67 else "adventurous (0.67–1)"
            rec = by_exp.setdefault(bucket, [0, 0])
            rec[0] += f.verdict == "like"
            rec[1] += 1
    out["by_source"] = {k: _rate(*v) for k, v in by_src.items()}
    out["by_exploration"] = {k: _rate(*v) for k, v in sorted(by_exp.items())}
    out["calibration"] = calibration(latest)
    return out


def calibration(feedback: Iterable[Feedback]) -> dict | None:
    """Provisional in-sample fit; ratings are self-selected and the rank is not a probability."""
    pts = [((f.context or {}).get("match"), 1 if f.verdict == "like" else 0)
           for f in latest_by_artist(feedback).values()
           if f.verdict in ("like", "dislike")]
    pts = [(m / 100.0, y) for m, y in pts
           if isinstance(m, (int, float)) and not isinstance(m, bool) and math.isfinite(m) and 0 <= m <= 100]
    n_pos = sum(y for _, y in pts)
    if (len(pts) < MIN_FOR_CALIBRATION or n_pos < 3 or len(pts) - n_pos < 3
            or max((m for m, _ in pts), default=0) - min((m for m, _ in pts), default=0) < 0.2):
        return None
    (a,), b = fit_logistic([[m] for m, _ in pts], [y for _, y in pts], prior_mean=[0.0], prior_precision=0.1)
    if not math.isfinite(a) or not math.isfinite(b) or a <= 0:
        return None  # these ratings do not support an increasing rank-to-like mapping
    return {"a": round(a, 4), "b": round(b, 4), "n": len(pts), "kind": "in_sample_estimate",
            "validated": False, "basis": "Latest self-selected artist ratings; not a held-out forecast"}


def like_probability(match: float, cal: dict | None) -> float | None:
    if not cal or not math.isfinite(match) or not 0 <= match <= 100:
        return None
    z = cal["a"] * match / 100.0 + cal["b"]
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))
