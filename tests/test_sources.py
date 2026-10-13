import json
from urllib.parse import parse_qs, urlsplit

import pytest

from musicfinder.sources import LiveKnowledge
from musicfinder.sources.brainz import ListenBrainz, MusicBrainz
from musicfinder.sources.deezer import Deezer
from musicfinder.sources.http import HttpClient, SourceError
from musicfinder.sources.lastfm import LastFm
from musicfinder.store import Store


class FakeTransport:
    """Routes requests to canned (status, json) responses; records calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        for match, resp in self.routes:
            if match(parts, q):
                status, body = resp(q) if callable(resp) else resp
                return status, json.dumps(body).encode() if not isinstance(body, bytes) else body
        return 404, b"{}"


def client(routes, store=None):
    t = FakeTransport(routes)
    return HttpClient(store, transport=t, sleep=lambda s: None, rates={h: 1000 for h in (
        "ws.audioscrobbler.com", "api.deezer.com", "musicbrainz.org", "labs.api.listenbrainz.org")}), t


LFM_SIMILAR = {"similarartists": {"artist": [
    {"name": "Thom Yorke", "mbid": "m1", "match": "1", "url": "u"},
    {"name": "Portishead", "mbid": "", "match": "0.42", "url": "u"},
], "@attr": {"artist": "Radiohead"}}}


def lastfm_route(method):
    return lambda p, q: p.hostname == "ws.audioscrobbler.com" and q.get("method") == method


def test_lastfm_parsing_and_cache(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    http, t = client([
        (lastfm_route("artist.getsimilar"), (200, LFM_SIMILAR)),
        (lastfm_route("artist.gettoptags"), (200, {"toptags": {"tag": [
            {"name": "alternative", "count": 100}, {"name": "seen live", "count": 60},
            {"name": "Electronic", "count": 40}, {"name": "90s", "count": 30}]}})),
        # Last.fm returns a bare object when a list has one element
        (lastfm_route("artist.gettoptracks"), (200, {"toptracks": {"track": {"name": "Creep", "listeners": "100",
                                                                              "artist": {"name": "Radiohead"}}}})),
        (lastfm_route("artist.getinfo"), (200, {"artist": {"name": "Radiohead", "mbid": "rh",
                                                            "stats": {"listeners": "5000000"}}})),
    ], store)
    lfm = LastFm(http, "KEY")
    sims = lfm.similar_artists("Radiohead")
    assert [(n.name, n.score, n.mbid) for n in sims] == [("Thom Yorke", 1.0, "m1"), ("Portishead", 0.42, None)]
    assert lfm.top_tags("Radiohead") == {"alternative rock": 1.0, "electronic": 0.4}
    assert [x.title for x in lfm.top_tracks("Radiohead")] == ["Creep"]
    assert lfm.info("Radiohead")["listeners"] == 5_000_000
    n = len(t.calls)
    lfm.similar_artists("Radiohead")
    assert len(t.calls) == n  # served from the SQLite cache
    assert all("KEY" not in k for k, in store._db.execute("SELECT key FROM http_cache"))  # secrets never cached


def test_lastfm_errors():
    http, t = client([(lastfm_route("artist.getsimilar"), (200, {"error": 6, "message": "not found"})),
                      (lastfm_route("artist.gettoptags"), (403, {"error": 10, "message": "Invalid API key"}))])
    lfm = LastFm(http, "KEY")
    assert lfm.similar_artists("Nobody") == []
    with pytest.raises(SourceError, match="Invalid API key"):
        lfm.top_tags("x")


def test_retry_then_success():
    state = {"n": 0}

    def flaky(q):
        state["n"] += 1
        return (503, {}) if state["n"] < 3 else (200, LFM_SIMILAR)

    http, t = client([(lastfm_route("artist.getsimilar"), flaky)])
    assert len(LastFm(http, "K").similar_artists("Radiohead")) == 2
    assert state["n"] == 3


def test_deezer_exact_match_only_and_related():
    search = {"data": [{"id": 1, "name": "Radiohead Tribute Band", "nb_fan": 10},
                       {"id": 2, "name": "Radiohead", "nb_fan": 1000, "picture_medium": "img"}]}
    related = {"data": [{"id": 3, "name": "Muse"}, {"id": 4, "name": "Coldplay"}]}
    http, _ = client([
        (lambda p, q: p.path == "/search/artist", lambda q: (200, search if q["q"] == "Radiohead" else {"data": []})),
        (lambda p, q: p.path == "/artist/2/related", (200, related)),
        (lambda p, q: p.path == "/search/track", (200, {"data": [
            {"id": 9, "title": "Creep (Remastered)", "preview": "https://p/x.mp3", "artist": {"name": "Radiohead"},
             "album": {"title": "Pablo Honey", "cover_medium": "c"}}]})),
    ])
    dz = Deezer(http)
    assert dz.find_artist("Radiohead")["fans"] == 1000
    assert dz.find_artist("Unknown Artist") is None
    rel = dz.related("Radiohead")
    assert [n.name for n in rel] == ["Muse", "Coldplay"] and rel[0].score > rel[1].score
    tr = dz.find_track("Radiohead", "Creep")
    assert tr.preview_url == "https://p/x.mp3" and tr.album == "Pablo Honey"


def test_listenbrainz_tolerates_shapes():
    items = [{"artist_mbid": "a", "name": "Self", "score": 50}, {"artist_mbid": "b", "name": "B", "score": 100},
             {"artist_mbid": "c", "name": "C", "score": 25}]
    for shape in (items, [items], {"data": items}):
        http, _ = client([(lambda p, q: p.hostname == "labs.api.listenbrainz.org", (200, shape))])
        out = ListenBrainz(http).similar_artists("a")
        assert [(n.name, n.score) for n in out] == [("B", 1.0), ("C", 0.25)]


def test_musicbrainz_search_tags():
    body = {"artists": [{"id": "x", "name": "Björk", "score": 100,
                         "tags": [{"count": 10, "name": "electronic"}, {"count": 5, "name": "art pop"}]}]}
    http, _ = client([(lambda p, q: p.hostname == "musicbrainz.org", (200, body))])
    out = MusicBrainz(http).search("Bjork")
    assert out["mbid"] == "x" and out["tags"] == {"electronic": 1.0, "art pop": 0.5}


def test_live_knowledge_degrades_when_a_source_dies():
    http, t = client([
        (lambda p, q: p.hostname == "api.deezer.com", (500, {})),
        (lastfm_route("artist.getsimilar"), (200, LFM_SIMILAR)),
        (lastfm_route("artist.getinfo"), (200, {"artist": {"name": "R", "mbid": "", "stats": {"listeners": "1"}}})),
        (lambda p, q: p.hostname == "musicbrainz.org", (200, {"artists": []})),
    ])
    http.retries = 0
    k = LiveKnowledge(lastfm_key="K", http=http)
    for i in range(6):
        out = k.neighbors(f"Artist {i}")
        assert "lastfm" in out and "deezer" not in out
    assert "deezer" in k.status()["unavailable"]
    deezer_calls = sum("deezer" in c for c in t.calls)
    k.neighbors("Another")
    assert sum("deezer" in c for c in t.calls) == deezer_calls  # circuit breaker: no more calls


def test_real_urllib_transport_against_local_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hits = {"flaky": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/ok"):
                body, code = b'{"hello": "world"}', 200
            elif self.path.startswith("/flaky"):
                hits["flaky"] += 1
                body, code = (b"{}", 503) if hits["flaky"] < 2 else (b'{"fine": true}', 200)
            else:
                body, code = b'{"error": "nope"}', 404
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        http = HttpClient(None, sleep=lambda s: None)
        assert http.get_json(f"{base}/ok", {"q": "x"}) == {"hello": "world"}
        assert http.get_json(f"{base}/missing", {}) is None
        assert http.get_json(f"{base}/flaky", {}) == {"fine": True}
    finally:
        srv.shutdown()


def test_relay_and_non_json_failures_are_never_cached(tmp_path):
    from musicfinder.sources import lastfm as lfm_mod
    from musicfinder.sources.http import Req

    store = Store(tmp_path / "db.sqlite")
    http, _ = client([], store)
    lfm = LastFm(http, "K")
    req = lfm.similar_req("Radiohead")
    relay_timeout = json.dumps({"relay_error": "ws.audioscrobbler.com did not respond"}).encode()
    old_style = json.dumps({"error": "ws.audioscrobbler.com did not respond"}).encode()
    assert lfm_mod.classify(502, json.loads(old_style)) == "retry"  # a non-numeric "error" is not Last.fm's
    assert lfm_mod.classify(200, {"error": 6, "message": "not found"}) == "missing"
    assert lfm_mod.classify(200, {"error": "29"}) == "retry"
    for status, raw in ((502, relay_timeout), (502, old_style), (404, b"<html>Page not found</html>"), (0, b"")):
        assert http.ingest(req, status, raw) == "retry"
        assert http.peek(req) == (False, None)
    assert http.ingest(req, 200, json.dumps({"error": 6, "message": "not found"}).encode()) == "missing"
    assert http.peek(req) == (True, None)
    assert isinstance(req, Req)


def test_musicbrainz_batches_never_record_bad_or_cut_off_answers(tmp_path):
    from musicfinder.sources.brainz import MusicBrainz

    store = Store(tmp_path / "db.sqlite")
    low = {"artists": [{"id": "low-id", "name": "Low", "score": 100, "tags": [{"count": 3, "name": "slowcore"}]}],
           "count": 1}

    def mb(q):
        if " OR " in q["query"]:  # a batch whose answer was cut off at the limit, without Low in it
            return 200, {"artists": [{"id": "x", "name": "Lower Than Atlantis", "score": 90}], "count": 500}
        return 200, low

    http, t = client([(lambda p, q: p.hostname == "musicbrainz.org", mb)], store)
    k = LiveKnowledge(store, http=http, use_deezer=False, use_listenbrainz=False)
    names = ["Low", "Nobody Else"]
    # A 200 that isn't a search answer is retried, and records nothing about the artists in it.
    batch = k.musicbrainz.batch_req(names)
    for raw in (b"", b'{"error": "busy"}', b"<html>maintenance</html>"):
        assert http.ingest(batch, 200, raw) == "retry"
    assert k.musicbrainz.cached_lookup("Low") == (False, None)
    # The prefetch plan: first the batch; since Low is missing from its cut-off answer, then Low on
    # its own; after that the lookups need no network at all.
    rounds = []
    while plan := k.plan("annotate", names):
        rounds.append(plan)
        for r in plan:
            status, raw = t(r.full_url, {}, 0)
            http.ingest(r, status, raw)
    assert len(rounds) == 2 and " OR " in dict(rounds[0][0].params)["query"]
    assert all(" OR " not in dict(r.params)["query"] for r in rounds[1])
    before = len(t.calls)
    assert k.tags("Low") == {"slowcore": 1.0}
    assert len(t.calls) == before
