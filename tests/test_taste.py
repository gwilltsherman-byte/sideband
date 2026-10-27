from datetime import datetime, timedelta, timezone

import pytest

from musicfinder.models import Feedback, LibraryItem, Play
from musicfinder.taste import TasteParams, build_profile, fit_beta_prior, play_engagement

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
P = TasteParams()


def play(artist="A", track="t", ms=200_000, rs="trackdone", re="trackdone", skipped=False, days=0, fmt="extended"):
    return Play(T0 + timedelta(days=days), artist, track, ms_played=ms, reason_start=rs, reason_end=re,
                skipped=skipped, fmt=fmt)


def test_engagement_outcomes():
    assert play_engagement(play(), 200_000, P) == (1.0, "stream")
    v, o = play_engagement(play(ms=8_000, re="fwdbtn", skipped=True), 200_000, P)
    assert o == "early_skip" and v < 0
    assert play_engagement(play(ms=8_000, re="endplay"), 200_000, P) == (0.0, "neutral")  # stopped, not a verdict
    assert play_engagement(play(ms=500, re="logout"), 200_000, P)[1] == "neutral"
    v_intent, _ = play_engagement(play(rs="clickrow"), 200_000, P)
    assert v_intent > 1.0  # deliberately chosen songs count more
    v_late, o_late = play_engagement(play(ms=100_000, re="fwdbtn", skipped=True), 200_000, P)
    assert o_late == "stream" and 0 < v_late < 0.5
    assert play_engagement(play(ms=10_000, fmt="basic", rs=None, re=None), None, P)[1] == "early_skip"


def test_profile_ranks_loved_over_skipped():
    plays = [play("Loved", f"s{i}", days=i % 30) for i in range(40)]
    plays += [play("Meh", "x", ms=5_000, re="fwdbtn", skipped=True, days=i) for i in range(10)]
    plays += [play("Meh", "y", days=3)]
    prof = build_profile(plays)
    loved, meh = prof.artists["loved"], prof.artists["meh"]
    assert loved.affinity > 10 * max(meh.affinity, 1e-9)
    assert loved.satisfaction > 0.8 > 0.3 > meh.satisfaction
    assert "meh" in prof.negative_seeds()
    assert "loved" in prof.positive_seeds() and "meh" not in prof.positive_seeds()
    assert prof.known_artists() == {"loved", "meh"}


def test_recency_decay_and_as_of_cutoff():
    plays = [play("Old", "o", days=0)] * 1 + [play("New", "n", days=700)]
    prof = build_profile(plays, params=TasteParams(half_life_days=100))
    assert prof.artists["new"].affinity > 50 * prof.artists["old"].affinity
    flat = build_profile(plays, params=TasteParams(half_life_days=None))
    assert flat.artists["new"].affinity == pytest.approx(flat.artists["old"].affinity)
    before = build_profile(plays, as_of=T0 + timedelta(days=10))
    assert "new" not in before.artists  # nothing from the future leaks in


def test_library_signals_and_bans():
    lib = [LibraryItem("followed_artist", "Followed"), LibraryItem("banned_artist", "Hated"),
           LibraryItem("saved_track", "A", "t")]
    prof = build_profile([play("A")], lib)
    assert prof.artists["followed"].affinity > 0
    assert prof.artists["hated"].banned and "hated" in prof.negative_seeds()
    assert "hated" not in prof.positive_seeds()
    assert prof.artists["a"].affinity > build_profile([play("A")]).artists["a"].affinity


def test_feedback_like_dislike_clear():
    base = [play("A", days=i) for i in range(5)]
    fbs = [Feedback("New Band", "like"), Feedback("Bad Band", "dislike")]
    prof = build_profile(base, feedback=fbs)
    assert "new band" in prof.positive_seeds()
    assert "bad band" in prof.negative_seeds()
    later = fbs + [Feedback("New Band", "clear", ts=fbs[0].ts + timedelta(seconds=1))]
    prof2 = build_profile(base, feedback=later)
    assert "new band" not in prof2.positive_seeds()


def test_beta_prior_reasonable():
    a, b = fit_beta_prior([(9, 1)] * 20 + [(5, 5)] * 5)
    assert 0.7 < a / (a + b) < 0.9
    assert 2 <= a + b <= 50
