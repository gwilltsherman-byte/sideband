import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from musicfinder.app import MusicFinder, NotReady
from musicfinder.server import make_server
from musicfinder.store import Store


def test_empty_app_is_not_ready(tmp_path):
    app = MusicFinder(Store(tmp_path / "x.db"), knowledge=object())  # knowledge unused here
    assert not app.has_data()
    with pytest.raises(NotReady):
        app.profile()


def test_import_feedback_and_clear(tmp_path, world, history_rows):
    from musicfinder.synthetic import SyntheticKnowledge

    app = MusicFinder(Store(tmp_path / "x.db"), knowledge=SyntheticKnowledge(world))
    payload = json.dumps(history_rows[:4000]).encode()
    s = app.import_files([("Streaming_History_Audio_2023.json", payload)])
    assert s["new_plays_added"] > 3000
    assert app.import_files([("again.json", payload)])["new_plays_added"] == 0  # idempotent
    app.build_graph()
    recs = app.recommendations(5)
    top = recs[0]
    app.add_feedback(top["name"], "dislike", context=top["context"])
    assert top["name"] not in [r["name"] for r in app.recommendations(20)]
    stats = app.feedback_summary()
    assert stats["overall"]["rated"] == 1 and stats["recent"][0]["verdict"] == "dislike"
    app.clear("all")
    assert not app.has_data()


@pytest.fixture(scope="module")
def server(demo_app):
    srv = make_server(demo_app, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_api_roundtrip(server):
    st, state = call(f"{server}/api/state")
    assert st == 200 and state["demo"] and state["has_data"] and state["graph_ready"]
    st, recs = call(f"{server}/api/recommendations?n=5&exploration=0.3")
    assert st == 200 and len(recs["items"]) == 5 and "because" in recs["items"][0]
    st, prof = call(f"{server}/api/profile")
    assert st == 200 and prof["top_artists"]
    st, ex = call(f"{server}/api/explore?seed=1")
    assert st == 200 and "territories" in ex and "far_genres" in ex
    st, songs = call(f"{server}/api/songs")
    assert st == 200 and songs["similar_song"]
    st, body = call(f"{server}/api/feedback", "POST", json.dumps({"artist": "X", "verdict": "like"}).encode())
    assert st == 403  # missing anti-CSRF header
    st, body = call(f"{server}/api/feedback", "POST", json.dumps({"artist": recs["items"][0]["name"],
                                                                  "verdict": "like"}).encode(),
                    {"X-MusicFinder": "1", "Content-Type": "application/json"})
    assert st == 200 and body["overall"]["likes"] >= 1
    st, _ = call(f"{server}/api/state", headers={"Host": "evil.example.com"})
    assert st == 403  # DNS-rebinding guard
    st, page = None, None
    with urllib.request.urlopen(f"{server}/") as r:
        assert b"sideband" in r.read().lower()


def test_api_evaluate_job(server):
    st, body = call(f"{server}/api/evaluate", "POST", b"{}", {"X-MusicFinder": "1"})
    assert st == 200
    for _ in range(240):
        st, job = call(f"{server}/api/job")
        if not job["running"]:
            break
        time.sleep(0.5)
    assert job["error"] is None, job
    st, rep = call(f"{server}/api/evaluation")
    assert rep["ok"]
    m, b = rep["model"], rep["baselines"]
    assert m["recall@50"] > 2 * b["random"]["recall@50"]
    assert m["recall@50"] > b["popularity"]["recall@50"]
    assert min(m["auc_n"]) >= 2 and 0 <= m["auc"] <= 1
    assert m["auc_ci"] and 0 <= m["auc_ci"][0] <= m["auc_ci"][1] <= 1
    assert m["preference_available"] == [sum(m["auc_n"]),
                                         rep["ground_truth"]["test_adopted"] + rep["ground_truth"]["test_rejected"]]
    assert m["preference_available"][0] <= m["preference_available"][1]


def test_build_fails_clearly_when_every_source_is_unreachable(tmp_path, history_rows):
    from urllib.error import URLError

    from musicfinder.graph import CrawlConfig
    from musicfinder.sources import LiveKnowledge
    from musicfinder.sources.http import HttpClient

    def offline(url, headers, timeout):
        raise URLError("network unreachable")

    store = Store(tmp_path / "x.db")
    http = HttpClient(store, transport=offline, sleep=lambda s: None, rates={h: 1000 for h in (
        "api.deezer.com", "musicbrainz.org", "labs.api.listenbrainz.org", "ws.audioscrobbler.com")})
    app = MusicFinder(store, knowledge=LiveKnowledge(store, lastfm_key="K", http=http),
                      crawl_cfg=CrawlConfig(seeds=10, recent_seeds=2, negative_seeds=2, expand_candidates=5,
                                            tag_candidates=5, explore_candidates=0))
    app.import_files([("Streaming_History_Audio_2023.json", json.dumps(history_rows[:3000]).encode())])
    with pytest.raises(RuntimeError, match="Couldn't get similar-artist data"):
        app.build_graph()
    assert not app.graph_ready()
    assert set(app.knowledge.status()["unavailable"]) >= {"lastfm", "deezer"}


def test_phone_mode_requires_the_private_key(demo_app):
    import http.client

    srv = make_server(demo_app, "127.0.0.1", 0, token="s3cret-key")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    phone = {"Host": f"192.168.1.20:{port}"}  # what a phone on the Wi-Fi sends

    def req(method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request(method, path, body=body, headers={**phone, **(headers or {})})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    try:
        assert req("GET", "/api/state")[0].status == 403
        r, body = req("GET", "/")
        assert r.status == 403 and b"?key=" in body  # friendly explanation, not a blank error
        assert req("GET", "/?key=wrong")[0].status == 403
        r, _ = req("GET", "/?key=s3cret-key")
        assert r.status == 303 and r.getheader("Location") == "/"
        cookie = r.getheader("Set-Cookie")
        assert "mf_key=s3cret-key" in cookie and "HttpOnly" in cookie
        auth = {"Cookie": "mf_key=s3cret-key"}
        assert req("GET", "/api/state", auth)[0].status == 200
        assert req("GET", "/static/app.js", auth)[0].status == 200
        r, _ = req("POST", "/api/feedback", {**auth, "X-MusicFinder": "1", "Content-Type": "application/json"},
                   json.dumps({"artist": "Somebody", "verdict": "known"}))
        assert r.status == 200
        r, _ = req("POST", "/api/feedback", {**auth, "Content-Type": "application/json"},
                   json.dumps({"artist": "Somebody", "verdict": "known"}))
        assert r.status == 403  # anti-CSRF header still required
        # the computer itself still works without any key
        assert req("GET", "/api/state", {"Host": f"127.0.0.1:{port}"})[0].status == 200
    finally:
        srv.shutdown()


def test_music_map_survives_restart(tmp_path, world, history_rows):
    from musicfinder.graph import KnowledgeGraph
    from musicfinder.synthetic import SyntheticKnowledge

    db = tmp_path / "x.db"
    app = MusicFinder(Store(db), knowledge=SyntheticKnowledge(world))
    app.import_files([("Streaming_History_Audio_2023.json", json.dumps(history_rows[:6000]).encode())])
    kg = app.build_graph()
    before = [r["name"] for r in app.recommendations(10)]
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".db") == ["x-cache.db", "x-data.db", "x.db"]

    again = MusicFinder(Store(db), knowledge=SyntheticKnowledge(world))
    assert again.state()["graph_exists"] and again.graph_ready()
    assert [r["name"] for r in again.recommendations(10)] == before
    restored = again.graph()
    assert restored.to_dict() == kg.to_dict() and isinstance(restored, KnowledgeGraph)
    again.import_files([("more.json", json.dumps(history_rows[6000:7000]).encode())])
    assert not MusicFinder(Store(db), knowledge=SyntheticKnowledge(world)).graph_ready()  # stale flag persisted
