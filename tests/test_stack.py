"""This week: ten unfamiliar artists a week, sorted with Keep / Pass / Know them / Not now."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from musicfinder.api import dispatch_steps
from musicfinder.app import MusicFinder
from musicfinder.backup import export_backup, restore_backup
from musicfinder.normalize import artist_key
from musicfinder.steps import run
from musicfinder.store import Store
from musicfinder.synthetic import SyntheticKnowledge
from test_live_path import SMALL
from test_picks import favourites

WEEK = "2026-10-18"  # a Sunday
NEXT, LATER = "2026-10-25", "2026-11-01"


def picked_app(tmp_path, world, history_rows, knowledge=None, n=8):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=knowledge or SyntheticKnowledge(world), crawl_cfg=SMALL)
    for name in favourites(world, history_rows, n=n):
        app.set_pick(name, "love")
    app.build_graph()
    return app


def post(app, path, **data):
    return run(dispatch_steps(app, "POST", path, {}, json.dumps(data).encode()))


def keys(payload):
    return [c["key"] for c in payload["items"]]


@pytest.mark.parametrize("exploration,wild", [(0.0, 1), (0.15, 2), (0.5, 3), (1.0, 5)])
def test_a_deal_of_ten_mixes_in_wildcards(tmp_path, world, history_rows, exploration, wild):
    app = picked_app(tmp_path, world, history_rows)
    status, stack = post(app, "/api/stack", week=WEEK, exploration=exploration)
    assert status == 200 and stack["week"] == WEEK and stack["exploration"] == exploration
    items = stack["items"]
    assert len(items) == 10 and len(set(keys(stack))) == 10 and not stack["exhausted"]
    slots = [c["slot"] for c in items]
    assert slots.count("wildcard") == wild and slots.count("close") == 10 - wild
    assert slots[-wild:] != ["wildcard"] * wild or wild == 10  # spread through the batch, not all at the end
    assert stack["counts"] == {"total": 10, "open": 10, "kept": 0, "passed": 0, "known": 0, "snoozed": 0}
    assert stack["score"] == {"shown": 10, "kept": 0, "passed": 0, "known": 0, "since": WEEK}
    assert not stack["graph_stale"] and datetime.fromisoformat(stack["dealt_at"]).tzinfo is not None
    wild_exploration = max(0.75, min(1.0, exploration + 0.5))
    for c in items:
        assert c["status"] == "open" and c["extra"] is False and c["second_look"] is False
        assert c["context"]["source"] == "stack" and c["context"]["week"] == WEEK and c["context"]["slot"] == c["slot"]
        assert c["context"]["exploration"] == (wild_exploration if c["slot"] == "wildcard" else exploration)
        assert c["because"] is not None and "match" in c and "evidence" in c  # decorated like recommendations
    saved = app.store.get_setting("stack")
    assert all("status" not in c for c in saved["items"])  # computed on every read, never stored


def test_every_card_is_unfamiliar(tmp_path, world, history_rows):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    app.import_files([("Streaming_History_Audio_2024.json", json.dumps(history_rows[:4000]).encode())])
    played = {artist_key(r["master_metadata_album_artist_name"]) for r in history_rows[:4000]}
    picked = [a.name for a in world.artists if a.key not in played][:3]
    for name in picked:
        app.set_pick(name, "love")
    app.build_graph()
    rated = app.recommendations(6)
    for rec, verdict in zip(rated, ("like", "dislike", "known", "like", "dislike", "known")):
        app.add_feedback(rec["name"], verdict, context=rec["context"])
    stack = app.stack(WEEK, 0.5)
    dealt = set(keys(stack))
    assert len(dealt) == 10
    assert not dealt & played
    assert not dealt & {artist_key(n) for n in picked}
    assert not dealt & {r["key"] for r in rated}
    assert not dealt & app.profile().known_artists()


def test_one_batch_per_week_and_unanswered_artists_come_back_once(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    first = app.stack(WEEK, 0.15)
    assert app.stack(WEEK, 1.0)["items"] == first["items"]  # same week: the identical batch, dial or not
    assert app.stack("2026-10-11", 0.15)["items"] == first["items"]  # an older week never re-deals
    assert app.stack(WEEK, 0.15)["dealt_at"] == first["dealt_at"]

    left = first["items"][0]
    for c in first["items"][1:]:
        app.add_feedback(c["name"], "dislike", context=c["context"])
    second = app.stack(NEXT, 0.15)
    assert second["week"] == NEXT and len(second["items"]) == 10
    fresh = [c for c in second["items"] if c["key"] != left["key"]]
    assert fresh and not {c["key"] for c in fresh} & set(keys(first))  # new artists
    assert all(not c["second_look"] for c in fresh)
    assert [c["second_look"] for c in second["items"] if c["key"] == left["key"]] == [True]

    log = app.store.get_setting("stack_log")
    assert log[left["key"]]["times"] == 2 and log[left["key"]]["first_week"] == WEEK
    assert log[left["key"]]["last_week"] == NEXT and log[left["key"]]["name"] == left["name"]
    third = app.stack(LATER, 0.15)
    assert left["key"] not in keys(third)  # retired after two unanswered showings
    assert all(log.get(k, {}).get("times", 0) < 2 for k in keys(third))
    assert app.store.get_setting("stack_log")[left["key"]]["times"] == 2


def test_keep_pass_and_know_them_are_feedback_and_undo_reopens(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    a, b, c = app.stack(WEEK, 0.15)["items"][:3]
    for card, verdict in ((a, "like"), (b, "dislike"), (c, "known")):
        status, _ = post(app, "/api/feedback", artist=card["name"], verdict=verdict, track="", context=card["context"])
        assert status == 200
    stack = app.stack(WEEK, 0.15)
    assert [i["status"] for i in stack["items"][:3]] == ["kept", "passed", "known"]
    assert stack["counts"] == {"total": 10, "open": 7, "kept": 1, "passed": 1, "known": 1, "snoozed": 0}
    assert stack["score"] == {"shown": 10, "kept": 1, "passed": 1, "known": 1, "since": WEEK}

    status, kept = run(dispatch_steps(app, "GET", "/api/kept", {}))
    assert status == 200 and kept["score"] == stack["score"]
    assert kept["items"] == [{"artist": a["name"], "ts": kept["items"][0]["ts"], "source": "stack", "week": WEEK}]
    app.add_feedback("Someone Else", "like", context={"source": "recommendations"})
    assert [(i["artist"], i["source"], i["week"]) for i in app.kept()["items"]] == [
        ("Someone Else", "recommendations", None), (a["name"], "stack", WEEK)]  # newest first, any source

    app.add_feedback(a["name"], "clear", context=a["context"])  # Undo
    app.add_feedback(b["name"], "clear", context=b["context"])
    stack = app.stack(WEEK, 0.15)
    assert [i["status"] for i in stack["items"][:3]] == ["open", "open", "known"]
    assert a["name"] not in [i["artist"] for i in app.kept()["items"]]


def test_not_now_snoozes_without_rating(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    first = app.stack(WEEK, 0.15)
    card = first["items"][0]
    status, res = post(app, "/api/stack/snooze", artist=f"  {card['name']} ", on=True)
    assert status == 200 and res == {"ok": True, "status": "snoozed"}
    assert not app.store.feedback()  # Not now is not a verdict
    until = datetime.fromisoformat(app.store.get_setting("stack_log")[card["key"]]["snooze_until"])
    assert timedelta(days=27) < until - datetime.now(timezone.utc) <= timedelta(days=28)
    stack = app.stack(WEEK, 0.15)
    assert stack["items"][0]["status"] == "snoozed" and stack["counts"]["snoozed"] == 1
    assert card["key"] not in keys(app.stack(NEXT, 0.15))  # snoozed artists are not dealt

    status, res = post(app, "/api/stack/snooze", artist=card["name"], on=False)
    assert res == {"ok": True, "status": "open"}
    assert app.store.get_setting("stack_log")[card["key"]]["snooze_until"] is None
    assert app.stack(NEXT, 0.15)["items"][0]["key"] != card["key"]  # this week's batch is unchanged
    later = app.stack(LATER, 0.15)
    assert card["key"] in keys(later)  # eligible again: the only one of week one left with a showing to spare
    assert [c["second_look"] for c in later["items"] if c["key"] == card["key"]] == [True]

    # Snoozing an artist that was never dealt creates an entry that does not count as shown.
    res = app.stack_snooze("Never Dealt", True)
    assert res["status"] == "snoozed"
    log = app.store.get_setting("stack_log")
    assert log["never dealt"]["times"] == 0 and app.kept()["score"]["shown"] == len(log) - 1


def test_more_appends_unique_extra_cards_up_to_the_cap(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    status, more = post(app, "/api/stack/more", week=WEEK, exploration=0.5, n=5)  # deals the batch first
    assert status == 200 and len(more["items"]) == 15 and len(set(keys(more))) == 15
    assert [c["extra"] for c in more["items"]] == [False] * 10 + [True] * 5
    assert sum(c["slot"] == "wildcard" for c in more["items"][10:]) == 2
    assert app.stack(WEEK, 0.5)["items"] == more["items"]
    assert all(app.store.get_setting("stack_log")[k]["times"] == 1 for k in keys(more))
    assert len(app.stack_more(WEEK, 0.5, 99)["items"]) == 25  # n is clamped to 10
    assert len(app.stack_more(WEEK, 0.5, 0)["items"]) == 26  # ... and to at least 1
    for _ in range(5):
        stack = app.stack_more(WEEK, 0.5, 10)
    assert len(stack["items"]) == 50 and stack["exhausted"] and len(set(keys(stack))) == 50
    assert len(app.stack_more(WEEK, 0.5, 5)["items"]) == 50


def test_invalid_requests_are_rejected(tmp_path, world, history_rows):
    empty = MusicFinder(Store(tmp_path / "empty.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    assert post(empty, "/api/stack", week=WEEK, exploration=0.0)[0] == 409
    app = picked_app(tmp_path, world, history_rows)
    empty.set_pick("Someone", "love")
    assert post(empty, "/api/stack", week=WEEK, exploration=0.0)[0] == 409  # no music map yet
    for body in ({}, {"week": "2026-02-30"}, {"week": "18/10/2026"}, {"week": "2026-10-18T00:00"},
                 {"week": 20261018}, {"week": WEEK, "exploration": "lots"}, {"week": WEEK, "exploration": None},
                 {"week": WEEK, "exploration": True}, {"week": WEEK, "exploration": [0.5]}):
        assert post(app, "/api/stack", **body)[0] == 400, body
        assert post(app, "/api/stack/more", **body)[0] == 400, body
    assert post(app, "/api/stack/more", week=WEEK, n="many")[0] == 400
    assert post(app, "/api/stack/more", week=WEEK, n=True)[0] == 400
    for body in ({"artist": "", "on": True}, {"artist": "   ", "on": True}, {"artist": "x" * 201, "on": True},
                 {"artist": "Someone", "on": "yes"}, {"artist": "Someone"}):
        assert post(app, "/api/stack/snooze", **body)[0] == 400, body
    assert run(dispatch_steps(app, "POST", "/api/stack", {}, b"[1]"))[0] == 400
    assert app.store.get_setting("stack") is None
    status, stack = post(app, "/api/stack", week=WEEK, exploration=7)
    assert status == 200 and stack["exploration"] == 1.0


def test_clearing_ratings_resets_the_stack(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    first = app.stack(WEEK, 0.15)
    app.add_feedback(first["items"][0]["name"], "like", context=first["items"][0]["context"])
    app.stack_snooze(first["items"][1]["name"], True)
    assert post(app, "/api/clear", what="feedback")[0] == 200
    assert app.store.get_setting("stack") is None and app.store.get_setting("stack_log") is None
    again = app.stack(WEEK, 0.15)
    assert again["counts"]["open"] == 10 and again["score"]["shown"] == 10
    assert all(not c["second_look"] for c in again["items"])


def test_backup_round_trip_keeps_the_stack(tmp_path, world, history_rows):
    app = picked_app(tmp_path, world, history_rows)
    first = app.stack(WEEK, 0.15)
    app.add_feedback(first["items"][0]["name"], "like", context=first["items"][0]["context"])
    app.stack_snooze(first["items"][1]["name"], True)
    saved = json.dumps(export_backup(app)).encode()
    stack, log = app.store.get_setting("stack"), app.store.get_setting("stack_log")
    app.clear("all")
    assert app.store.get_setting("stack") is None
    restore_backup(app, saved)
    assert app.store.get_setting("stack") == stack and app.store.get_setting("stack_log") == log
    restored = app.stack(WEEK, 0.15)
    assert [c["status"] for c in restored["items"][:3]] == ["kept", "snoozed", "open"]
    assert restored["items"][0]["name"] == first["items"][0]["name"]


def test_an_interaction_keeps_cached_plays(tmp_path, world, history_rows):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    app.import_files([("Streaming_History_Audio_2024.json", json.dumps(history_rows[:2000]).encode())])
    plays, signature = app.plays(), app.history_signature()
    profile, version = app.profile(), app._version
    status, res = post(app, "/api/interactions", artist="Somebody New", kind="external_open", event_id=str(uuid4()))
    assert status == 200 and res["accepted"]
    assert app.plays() is plays and app._history_signature_cache == signature
    assert app._version == version + 1 and app.profile() is not profile  # the signal still counts
    assert app.profile().artists[artist_key("Somebody New")]


class CountingKnowledge:
    """Counts similar-artist lookups; everything else goes straight through."""

    def __init__(self, inner):
        self.inner = inner
        self.neighbor_calls = 0

    def neighbors(self, name):
        self.neighbor_calls += 1
        return self.inner.neighbors(name)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_an_update_extends_the_saved_map(tmp_path, world, history_rows):
    counting = CountingKnowledge(SyntheticKnowledge(world))
    favs = favourites(world, history_rows, n=9)
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=counting, crawl_cfg=SMALL)
    for name in favs[:8]:
        app.set_pick(name, "love")
    old = app.build_graph()
    fresh_calls, before = counting.neighbor_calls, set(old.expanded)
    assert app.store.get_setting("graph_fresh_at")

    counting.neighbor_calls = 0
    app.set_pick(favs[8], "love")
    assert not app.graph_ready()
    kg = app.build_graph()
    assert app.graph_ready() and kg is not old and artist_key(favs[8]) in kg.expanded
    assert before <= kg.expanded and set(old.expanded) == before  # extended a copy; the old map is untouched
    assert 0 < counting.neighbor_calls < fresh_calls / 4

    # A change of sources, or a map last built from scratch over a month ago, starts again.
    counting.neighbor_calls = 0
    app.update_settings(use_listenbrainz=True)
    assert app.store.get_setting("graph_fresh_at") is None
    app.build_graph()
    assert counting.neighbor_calls >= fresh_calls
    counting.neighbor_calls = 0
    app.store.set_setting("graph_fresh_at", (datetime.now(timezone.utc) - timedelta(days=31)).isoformat())
    app.set_pick(favs[0], "remove")
    app.build_graph()
    assert counting.neighbor_calls >= fresh_calls / 2
    assert datetime.fromisoformat(app.store.get_setting("graph_fresh_at")) > datetime.now(timezone.utc) - timedelta(minutes=5)

    app.clear("data")
    assert app.store.get_setting("graph_fresh_at") is None
