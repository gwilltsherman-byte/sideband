"""The browser build's Python backend, driven exactly the way worker.js drives it (fake network)."""

import json

import pytest

from fake_upstream import FakeUpstream
from musicfinder.browser import BrowserBackend

FAST = {"sleep": lambda s: None, "rates": {h: 1e6 for h in (
    "ws.audioscrobbler.com", "api.deezer.com", "musicbrainz.org", "labs.api.listenbrainz.org")}}


def drive(task, fake, progress=None):
    """worker.js's drive(): step, fetch each plan in 'parallel' (here: in order), ingest, repeat."""
    fetched = 0
    while not task.step():
        for _ in range(8):
            plan = task.plan()
            if not plan:
                break
            for i, item in enumerate(plan, 1):
                status, raw = fake(item["url"])
                task.ingest(item["key"], status, raw.decode("utf-8"))
                fetched += 1
                if progress:
                    progress(task.label, i, len(plan))
    out = json.loads(task.result_json())
    return out["status"], out["payload"], fetched


def call(be, fake, method, path, query="", body=None, filename="upload.json"):
    raw = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    status, payload, _ = drive(be.request(method, path, query, raw, filename), fake)
    return status, payload


@pytest.mark.parametrize("lastfm", [False, True], ids=["keyless", "site-lastfm-key"])
def test_full_flow_persistence_and_jobs(tmp_path, world, listener, history_rows, lastfm):
    # With lastfm=True the page sends the placeholder key "relay" and the site's relay swaps in the real
    # key; this fake Last.fm accepts exactly what the relay would forward.
    fake = FakeUpstream(world, api_key="relay")
    db = str(tmp_path / "musicfinder.db")
    be = BrowserBackend(db_path=db, transport=fake, http_options=FAST, lastfm=lastfm)

    state = call(be, fake, "GET", "/api/state")[1]
    assert state["has_data"] is False and state["settings"]["lastfm"] is lastfm
    assert call(be, fake, "POST", "/api/settings", body={"lastfm_api_key": "MINE"})[0] == 404  # nothing to set
    status, summary = call(be, fake, "POST", "/api/import", body=json.dumps(history_rows).encode(),
                           filename="Streaming_History_Audio_2024.json")
    assert status == 200 and summary["new_plays_added"] > 10_000
    assert call(be, fake, "GET", "/api/recommendations", "n=5")[0] == 409  # no map yet

    status, started = call(be, fake, "POST", "/api/build", body={})
    assert started["started"] and started["job"]["running"]
    assert call(be, fake, "POST", "/api/build", body={})[1]["started"] is False  # one job at a time
    job = be.take_job()
    assert job is not None and be.take_job() is None
    seen = []
    _, _, first_build = drive(job, fake, lambda label, d, t: (be.report(label, d, t), seen.append(be.app.job.step)))
    assert first_build > 300 and any("favourites" in s for s in seen)
    state = call(be, fake, "GET", "/api/job")[1]
    assert not state["running"] and state["error"] is None

    status, recs = call(be, fake, "GET", "/api/recommendations", "n=10&exploration=0.2")
    assert status == 200 and len(recs["items"]) == 10
    status, songs = call(be, fake, "GET", "/api/songs")
    assert status == 200 and songs["similar_song"]
    assert call(be, fake, "POST", "/api/feedback",
                body={"artist": recs["items"][0]["name"], "verdict": "like", "context": recs["items"][0]["context"]})[0] == 200
    assert call(be, fake, "GET", "/api/nope")[0] == 404
    assert call(be, fake, "POST", "/api/feedback", body=b"not json")[0] == 400

    # A new page load (new backend on the same database file) keeps everything, and a rebuild is
    # served from the saved cache: only the few lookups the new "like" made necessary are fetched.
    be2 = BrowserBackend(db_path=db, transport=fake, http_options=FAST, lastfm=lastfm)
    st = call(be2, fake, "GET", "/api/state")[1]
    assert st["has_data"] and st["settings"]["lastfm"] is lastfm
    assert any("audioscrobbler" in c for c in fake.calls) is lastfm
    assert call(be2, fake, "GET", "/api/feedback")[1]["overall"]["likes"] == 1
    call(be2, fake, "POST", "/api/build", body={})
    _, _, fetched = drive(be2.take_job(), fake)
    assert fetched < 0.05 * first_build
    assert call(be2, fake, "GET", "/api/job")[1]["error"] is None
    call(be2, fake, "POST", "/api/build", body={})
    before = len(fake.calls)
    _, _, fetched = drive(be2.take_job(), fake)
    assert fetched == 0 and len(fake.calls) == before  # nothing changed: entirely from the cache


def test_job_errors_are_reported(tmp_path, world, history_rows):
    def offline(url, headers=None, timeout=0):
        raise OSError("offline")

    be = BrowserBackend(db_path=str(tmp_path / "db"), transport=offline, http_options={**FAST, "retries": 0})
    call(be, None, "POST", "/api/import", body=json.dumps(history_rows[:3000]).encode())

    class Offline:
        def __call__(self, url):
            return 0, b""

    call(be, Offline(), "POST", "/api/build", body={})
    drive(be.take_job(), Offline())
    job = call(be, None, "GET", "/api/job")[1]
    assert not job["running"] and "Couldn't get similar-artist data" in job["error"]


def test_demo_backend(world):
    be = BrowserBackend(demo=True, demo_artists=2500)
    st = call(be, None, "GET", "/api/state")[1]
    assert st["demo"] and st["has_data"]
    call(be, None, "POST", "/api/build", body={})
    drive(be.take_job(), None)
    status, recs = call(be, None, "GET", "/api/recommendations", "n=5")
    assert status == 200 and recs["items"][0]["true_like_probability"] is not None


def test_a_key_saved_by_an_earlier_version_is_forgotten(tmp_path):
    from musicfinder.store import Store

    db = str(tmp_path / "musicfinder.db")
    Store(db).set_setting("lastfm_api_key", "OLD-PERSONAL-KEY")
    be = BrowserBackend(db_path=db, transport=lambda *a: (404, b"{}"), http_options=FAST)
    assert be.app.settings()["lastfm"] is False
    assert not Store(db).get_setting("lastfm_api_key")
