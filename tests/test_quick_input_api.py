"""Immediate inputs work without lookup accounts and never become fake listening history."""

import json

import pytest

from musicfinder.api import dispatch_steps
from musicfinder.app import MusicFinder
from musicfinder.browser import BrowserBackend
from musicfinder.models import LibraryItem
from musicfinder.steps import run
from musicfinder.store import Store


def app_at(tmp_path):
    app = MusicFinder(Store(tmp_path / "taste.db"))
    app.lookup_available = False
    return app


def request(app, **data):
    return run(dispatch_steps(app, "POST", "/api/quick-input", {}, json.dumps(data).encode()))


def test_preview_is_read_only_and_save_works_without_service(tmp_path):
    app = app_at(tmp_path)
    status, preview = request(app, text="Radiohead\nBjörk\nTyler, The Creator", kind="artists")
    assert status == 200 and preview["can_save"] and preview["counts"]["artists"] == 3
    assert not app.has_data()
    status, saved = request(app, text="Radiohead\nBjörk\nTyler, The Creator", kind="artists", preview=False)
    assert status == 200 and saved["added_library_items"] == 3
    assert app.picks()["loved"] == ["Radiohead", "Björk", "Tyler, The Creator"]
    assert app.profile().positive_seeds(10) and app.plays() == []
    assert not app.personalization_status()["can_evaluate"]


def test_song_only_input_creates_artist_and_song_seeds_without_statistics(tmp_path):
    app = app_at(tmp_path)
    status, saved = request(app, text="Radiohead — Weird Fishes\nBjörk — Joga", kind="songs", preview=False)
    assert status == 200 and saved["input_summary"]["saved_tracks"] == 2
    profile = app.profile_summary()
    assert profile["plays"] == profile["streams"] == profile["hours"] == 0
    assert profile["first"] is None and profile["last"] is None
    assert len(app.profile().positive_seeds(10)) == 2
    assert len(app.profile().top_tracks(10)) == 2
    assert profile["input_summary"]["positive_artists"] == 2


def test_normalized_repeated_save_does_not_stack_affinity_or_invalidate_map(tmp_path):
    app = app_at(tmp_path)
    request(app, text="Björk — Joga", kind="songs", preview=False)
    first = app.profile().top_artists()[0].affinity
    app._graph_stale = False
    version = app._version
    status, saved = request(app, text="BJORK — Joga (Remastered 2011)", kind="songs", preview=False)
    assert status == 200 and saved["added_library_items"] == 0 and not saved["changed"]
    assert app.profile().top_artists()[0].affinity == first
    assert app._version == version and not app._graph_stale


def test_artist_favourite_replaces_old_dislike_and_preserves_other_preferences(tmp_path):
    app = app_at(tmp_path)
    app.set_pick("Radiohead", "dislike")
    app.set_pick("Other", "love")
    status, saved = request(app, text="RADIOHEAD", kind="artists", preview=False)
    assert status == 200 and saved["removed_disliked_picks"] == 1
    assert app.picks() == {"loved": ["Other", "RADIOHEAD"], "disliked": []}
    assert "radiohead" in app.profile().positive_seeds(10)


def test_invalid_mixed_input_cannot_partially_save(tmp_path):
    app = app_at(tmp_path)
    status, preview = request(app, text="Radiohead\nhttps://open.spotify.com/artist/abc", kind="artists")
    assert status == 200 and preview["errors"] and not preview["can_save"]
    status, error = request(app, text="Radiohead\nhttps://open.spotify.com/artist/abc", kind="artists", preview=False)
    assert status == 400 and error["error"]
    assert app.library() == []


@pytest.mark.parametrize("bad", [{"text": []}, {"text": "Radiohead", "preview": "false"}])
def test_request_validation_does_not_turn_wrong_types_into_preferences(tmp_path, bad):
    app = app_at(tmp_path)
    assert request(app, **bad)[0] == 400
    assert not app.has_data()


def test_browser_backend_shares_the_fast_input_route(tmp_path):
    be = BrowserBackend(db_path=str(tmp_path / "browser.db"), lookup_available=False)
    task = be.request("POST", "/api/quick-input", body=json.dumps({
        "text": "Artist,Track Name\nRadiohead,Weird Fishes", "kind": "auto", "name": "favourites.csv", "preview": False,
    }).encode())
    while not task.step():
        pass
    response = json.loads(task.result_json())
    assert response["status"] == 200 and response["payload"]["added_library_items"] == 1
    assert be.app.profile().n_plays == 0 and be.app.profile().top_tracks()[0].name == "Weird Fishes"


def test_csv_file_import_matches_quick_input_and_stays_idempotent(tmp_path):
    app = app_at(tmp_path)
    first = app.import_files([("favorites.csv", b"Artist,Track Name\nBjork,Joga")])
    assert first["new_library_items_added"] == 1 and first["new_plays_added"] == 0
    again = app.import_files([("favorites.tsv", "Artist\tSong\nBjörk\tJoga (Remastered 2011)".encode())])
    assert again["new_library_items_added"] == 0
    assert len(app.library()) == 1


def test_quick_store_transaction_rolls_back_conflict_changes_on_write_failure(tmp_path):
    app = app_at(tmp_path)
    app.set_pick("Radiohead", "dislike")
    with app.store._lock:
        app.store._db.execute("CREATE TRIGGER data.fail_quick BEFORE INSERT ON library BEGIN SELECT RAISE(FAIL, 'test failure'); END")
        app.store._db.commit()
    with pytest.raises(Exception, match="test failure"):
        app.store.apply_quick_input([LibraryItem("picked_artist", "Radiohead")])
    assert app.picks()["disliked"] == ["Radiohead"] and app.picks()["loved"] == []
