"""Observed app interest stays weaker than ratings and separate from listening data."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from musicfinder.api import dispatch_steps
from musicfinder.app import MusicFinder
from musicfinder.backup import export_backup, restore_backup
from musicfinder.interactions import (MAX_ARTIST_WEIGHT, MAX_TRACK_WEIGHT, Interaction,
                                      apply_interactions, make_interaction)
from musicfinder.models import Feedback, LibraryItem
from musicfinder.steps import run
from musicfinder.store import Store
from musicfinder.taste import build_profile

NOW = datetime(2026, 10, 13, 20, tzinfo=timezone.utc)


def event(kind="preview_listen", artist="New Artist", track="New Song", **kwargs):
    return Interaction(str(uuid4()), artist, kind, track, kwargs.pop("ts", NOW),
                       kwargs.pop("duration_ms", 30_000 if kind == "preview_listen" else 0), **kwargs)


def post(app, data):
    return run(dispatch_steps(app, "POST", "/api/interactions", {}, json.dumps(data).encode()))


def payload(kind="preview_listen", **kwargs):
    return {"artist": "New Artist", "track": "New Song", "kind": kind,
            "duration_ms": 30_000 if kind == "preview_listen" else 0,
            "event_id": str(uuid4()), **kwargs}


def test_event_retries_and_normalized_item_day_caps_are_neutral():
    store = Store(":memory:")
    first = event(kind="external_open", artist="Björk")
    assert store.add_interaction(first)
    assert not store.add_interaction(first)
    assert not store.add_interaction(event(kind="external_open", artist="BJORK"))
    assert store.add_interaction(event(artist="Björk"))
    assert store.add_interaction(event(artist="BJORK"))
    assert not store.add_interaction(event(artist="Björk"))
    assert store.add_interaction(event(artist="Björk", ts=NOW + timedelta(days=1)))
    assert len(store.interactions()) == 4
    assert store.plays() == store.feedback() == []
    store.close()


def test_event_day_caps_use_utc():
    store = Store(":memory:")
    # These clock times differ by date locally but identify the same UTC day.
    eastern = timezone(timedelta(hours=-4))
    assert store.add_interaction(event(kind="external_open", ts=NOW))
    assert not store.add_interaction(event(kind="external_open", ts=NOW.astimezone(eastern)))
    store.close()


def test_store_event_log_keeps_only_most_recent_bounded_events(monkeypatch):
    import musicfinder.store as storage
    monkeypatch.setattr(storage, "MAX_EVENTS", 5)
    store = Store(":memory:")
    events = [event(artist=f"Artist {i}", ts=NOW + timedelta(minutes=i)) for i in range(7)]
    for item in events:
        assert store.add_interaction(item)
    assert [i.event_id for i in store.interactions()] == [i.event_id for i in events[-5:]]
    store.close()


def test_actual_five_thousand_event_limit():
    store = Store(":memory:")
    rows = [(str(uuid4()), f"Artist {i}", "Song", "preview_listen", NOW.isoformat(),
             30_000, f"artist {i}", "song") for i in range(5_000)]
    store._db.executemany("INSERT INTO main.interactions VALUES (?,?,?,?,?,?,?,?)", rows)
    store._db.commit()
    newest = event(artist="Another Artist", ts=NOW + timedelta(seconds=1))
    assert store.add_interaction(newest)
    assert len(store.interactions()) == 5_000
    assert store.interactions()[-1] == newest
    assert store._db.execute("SELECT 1 FROM main.interactions WHERE event_id=?", (rows[0][0],)).fetchone() is None
    store.close()


@pytest.mark.parametrize("bad", [
    {"artist": []}, {"artist": ""}, {"artist": "x" * 201}, {"artist": "Artist\nOther"},
    {"track": {}}, {"track": "x" * 201}, {"track": ""},
    {"kind": "search"}, {"kind": "skip"}, {"kind": "preview_play"}, {"kind": []},
    {"event_id": ""}, {"event_id": []}, {"event_id": "not-a-uuid"},
    {"duration_ms": -1}, {"duration_ms": "30000"}, {"duration_ms": True},
    {"duration_ms": float("nan")}, {"duration_ms": float("inf")}, {"duration_ms": None},
])
def test_bad_events_never_create_any_preference(bad):
    app = MusicFinder(Store(":memory:"))
    status, response = post(app, payload(**bad))
    assert status == 400 and response["error"]
    assert app.store.interactions() == app.store.plays() == app.store.feedback() == []
    app.store.close()


def test_brief_preview_is_neutral_and_duration_is_capped():
    app = MusicFinder(Store(":memory:"))
    assert post(app, payload(duration_ms=9_999)) == (200, {"accepted": False})
    assert app.store.writes == 0
    data = payload(duration_ms=1e100)
    assert post(app, data) == (200, {"accepted": True})
    assert app.store.interactions()[0].duration_ms == 60_000
    writes = app.store.writes
    assert post(app, data) == (200, {"accepted": False})
    assert app.store.writes == writes
    # Link opens deliberately carry no duration or claim that Spotify played.
    assert post(app, payload(kind="external_open", track="")) == (200, {"accepted": True})
    assert app.store.interactions()[-1].duration_ms == 0
    assert app.store.plays() == app.store.feedback() == []
    app.store.close()


def test_interaction_invalidates_cached_taste_without_faking_plays_or_ratings():
    app = MusicFinder(Store(":memory:"))
    app.set_pick("Existing Favourite", "love")
    before = app.profile()
    assert post(app, payload()) == (200, {"accepted": True})
    after = app.profile()
    assert before is not after
    # The separate events never enter streaming history, satisfaction or measured accuracy.
    assert app.plays() == app.store.feedback() == []
    assert after.n_plays == after.n_streams == after.total_ms == 0
    assert 0 < after.artists["new artist"].affinity < 1
    assert "new artist" not in after.known_artists()
    assert ("new artist", "new song") not in after.known_tracks()
    assert not app.personalization_status()["can_evaluate"]
    app.store.close()


def test_explicit_song_dislike_wins_over_repeated_observed_interest():
    app = MusicFinder(Store(":memory:"))
    app.set_pick("Existing Favourite", "love")
    for i in range(30):
        app.store.add_interaction(event(ts=NOW - timedelta(days=i)))
    app.add_feedback("New Artist", "dislike", "New Song")
    profile = app.profile()
    song = profile.tracks[("new artist", "new song")]
    assert song.feedback == "dislike" and song.affinity == 0
    assert song not in profile.top_tracks()
    assert app.store.plays() == []
    app.store.close()


def test_weak_interest_is_decayed_capped_and_idempotent():
    fresh = event(duration_ms=60_000)
    profile = build_profile([])
    apply_interactions(profile, [fresh], cutoff=NOW + timedelta(seconds=1))
    initial = profile.artists["new artist"].affinity
    assert 0 < initial < 0.36
    apply_interactions(profile, [fresh], cutoff=NOW + timedelta(days=45))
    assert profile.artists["new artist"].affinity == pytest.approx(0.175)
    repeated = [event(ts=NOW - timedelta(days=i)) for i in range(30)]
    apply_interactions(profile, repeated, cutoff=NOW + timedelta(seconds=1))
    assert profile.artists["new artist"].affinity == MAX_ARTIST_WEIGHT
    assert profile.tracks[("new artist", "new song")].affinity == MAX_TRACK_WEIGHT
    apply_interactions(profile, repeated, cutoff=NOW + timedelta(seconds=1))
    assert profile.artists["new artist"].affinity == MAX_ARTIST_WEIGHT
    assert profile.n_plays == profile.n_streams == profile.total_ms == 0
    assert profile.artists["new artist"].plays == profile.artists["new artist"].streams == 0
    assert profile.tracks[("new artist", "new song")].streams == 0


def test_explicit_artist_dislike_and_library_bans_override_weak_interest():
    for profile in (
        build_profile([], feedback=[Feedback("New Artist", "dislike", ts=NOW)]),
        build_profile([], library=[LibraryItem("banned_artist", "New Artist")]),
        build_profile([], library=[LibraryItem("banned_track", "New Artist", "New Song")]),
    ):
        apply_interactions(profile, [event(ts=NOW - timedelta(days=i)) for i in range(20)], cutoff=NOW + timedelta(seconds=1))
        assert not profile.positive_seeds()
        assert not profile.top_tracks()


def test_future_events_never_leak_into_historical_taste():
    profile = build_profile([])
    apply_interactions(profile, [event(ts=NOW), event(ts=NOW + timedelta(days=1))], cutoff=NOW)
    assert profile.artists == profile.tracks == {}


def test_existing_database_creates_new_table_without_losing_preferences(tmp_path):
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT); INSERT INTO settings VALUES ('keep', 'true');")
    db.close()
    store = Store(path)
    assert store.get_setting("keep") is True
    assert store.add_interaction(event())
    store.close()
    reopened = Store(path)
    assert len(reopened.interactions()) == 1
    reopened.close()


def test_events_survive_backup_restore_and_reopening(tmp_path):
    path = tmp_path / "taste.db"
    app = MusicFinder(Store(path))
    app.set_pick("Favourite", "love")
    saved_event = event()
    app.store.add_interaction(saved_event)
    app.store.set_setting("lastfm_api_key", "do-not-export")
    backup = export_backup(app)
    assert backup["version"] == 2 and "do-not-export" not in json.dumps(backup)
    app.clear("all")
    assert app.store.interactions() == []
    restore_backup(app, json.dumps(backup).encode())
    assert app.store.interactions() == [saved_event]
    app.store.close()
    reopened = Store(path)
    assert reopened.interactions() == [saved_event]
    assert not reopened.add_interaction(saved_event)
    reopened.close()


def test_old_version_one_backup_restores_with_no_learned_interactions():
    app = MusicFinder(Store(":memory:"))
    app.set_pick("Keep Old Favourite", "love")
    old = export_backup(app)
    old["version"] = 1
    del old["tables"]["interactions"]
    app.store.add_interaction(event())
    restore_backup(app, json.dumps(old).encode())
    assert app.picks()["loved"] == ["Keep Old Favourite"]
    assert app.store.interactions() == []
    app.store.close()


@pytest.mark.parametrize("invalid", [
    lambda row: row.__setitem__(0, "bad-id"),
    lambda row: row.__setitem__(3, "search"),
    lambda row: row.__setitem__(4, "bad-time"),
    lambda row: row.__setitem__(5, 9_999),
    lambda row: row.__setitem__(6, "spoofed artist"),
])
def test_invalid_interaction_backup_keeps_previous_data(invalid):
    app = MusicFinder(Store(":memory:"))
    item = event()
    app.store.add_interaction(item)
    backup = export_backup(app)
    invalid(backup["tables"]["interactions"][0])
    with pytest.raises(ValueError):
        restore_backup(app, json.dumps(backup).encode())
    assert app.store.interactions() == [item]
    app.store.close()


@pytest.mark.parametrize("what", ["feedback", "data", "all"])
def test_privacy_clear_also_removes_learned_interactions(what):
    app = MusicFinder(Store(":memory:"))
    app.store.add_interaction(event())
    app.clear(what)
    assert app.store.interactions() == []
    app.store.close()
