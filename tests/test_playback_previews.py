"""Playback lookup is strict, resumable, and distinguishes absence from outages."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from musicfinder.api import dispatch_steps
from musicfinder.app import MusicFinder
from musicfinder.browser import BrowserBackend
from musicfinder.sources.base import TrackInfo
from musicfinder.sources.http import SourceError
from musicfinder.steps import run
from musicfinder.store import Store


FAST = {"retries": 0, "sleep": lambda _: None, "rates": {"api.deezer.com": 1e6}}


def song(artist="Bruce Springsteen", title="Downbound Train", preview="https://audio.example/clip.mp3"):
    return {"title": title, "artist": {"name": artist}, "preview": preview,
            "link": "https://www.deezer.com/track/1", "album": {"title": "Album"}}


class Transport:
    def __init__(self, respond):
        self.respond = respond
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append(url)
        q = parse_qs(urlsplit(url).query).get("q", [""])[0]
        status, payload = self.respond(q)
        return status, json.dumps(payload).encode()


def application(tmp_path, respond):
    transport = Transport(respond)
    app = MusicFinder(Store(tmp_path / "db.sqlite"), transport=transport, http_options=FAST, lastfm_key="")
    return app, transport


def request(app, artist="Bruce Springsteen", track="Downbound Train"):
    return run(dispatch_steps(app, "GET", "/api/preview", {"artist": [artist], "track": [track]}))


@pytest.mark.parametrize("artist,title,returned", [
    ("Jackson Browne", "You Love the Thunder (Remastered)", "You Love the Thunder"),
    ("Bruce Springsteen", "Downbound Train", "Downbound Train"),
    ("The B-52's", "Roam", "Roam"),
])
def test_plain_search_finds_screenshot_songs_and_remaster_variants(tmp_path, artist, title, returned):
    def upstream(query):
        # The live provider returns [] for the former advanced artist:/track: search.
        return 200, {"data": [] if 'artist:"' in query else [song(artist, returned)]}
    app, transport = application(tmp_path, upstream)
    status, payload = request(app, artist, title)
    assert status == 200 and payload["preview_url"] == "https://audio.example/clip.mp3"
    assert payload["title"] == returned and payload["artist"] == artist
    assert len(transport.calls) == 1


@pytest.mark.parametrize("wrong", [
    song(title="Born in the U.S.A."),
    song(artist="Bruce Springsteen Tribute Band"),
    song(artist="Other Artist"),
])
def test_search_never_substitutes_another_song_or_cover_artist(tmp_path, wrong):
    app, _ = application(tmp_path, lambda _: (200, {"data": [wrong]}))
    assert request(app) == (200, {})


def test_selects_playable_duplicate_instead_of_first_version_without_audio(tmp_path):
    app, _ = application(tmp_path, lambda _: (200, {"data": [song(preview=""), song()]}))
    assert request(app)[1]["preview_url"] == "https://audio.example/clip.mp3"


def test_matching_song_without_audio_is_genuine_absence(tmp_path):
    app, _ = application(tmp_path, lambda _: (200, {"data": [song(preview="")]}))
    status, payload = request(app)
    assert status == 200 and payload["preview_url"] is None
    assert payload["title"] == "Downbound Train"


def test_base_title_query_can_find_matching_audio_when_original_version_search_cannot(tmp_path):
    def upstream(query):
        return 200, {"data": [] if "(Live)" in query else [song(title="Downbound Train (Live)")]}
    app, transport = application(tmp_path, upstream)
    status, payload = request(app, track="Downbound Train (Live)")
    assert status == 200 and payload["preview_url"]
    assert len(transport.calls) == 2


@pytest.mark.parametrize("status,body", [(503, {}), (200, {"error": {"code": 4}})])
def test_lookup_outage_is_retryable_failure_not_no_preview(tmp_path, status, body):
    app, _ = application(tmp_path, lambda _: (status, body))
    code, payload = request(app)
    assert code == 503 and "try again" in payload["error"]


def test_fresh_user_lookup_recovers_even_after_graph_source_circuit_breaker(tmp_path):
    app, transport = application(tmp_path, lambda _: (200, {"data": [song()]}))
    app.knowledge._down["deezer"] = "previous graph lookup failed"
    assert request(app)[1]["preview_url"]
    assert len(transport.calls) == 1


def test_browser_prefetch_covers_preview_with_no_synchronous_request(tmp_path):
    transport = Transport(lambda _: (200, {"data": [song()]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen&track=Downbound+Train")
    assert not task.step()
    plan = task.plan()
    assert len(plan) == 1 and task.need.kind == "preview"
    assert "artist%3A" not in plan[0]["url"]
    status, body = transport(plan[0]["url"])
    task.ingest(plan[0]["key"], status, body.decode())
    assert task.plan() == []
    assert task.step()
    assert task.result[0] == 200 and task.result[1]["preview_url"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status,body", [(0, ""), (503, "{}"), (200, "not JSON")])
def test_browser_failed_prefetch_reports_unavailable_without_blocking_sync_retry(tmp_path, status, body):
    transport = Transport(lambda _: (200, {"data": [song()]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen&track=Downbound+Train")
    assert not task.step()
    item = task.plan()[0]
    task.ingest(item["key"], status, body)
    assert task.plan() == [] and task.step()
    assert task.result[0] == 503
    assert transport.calls == []


def test_custom_knowledge_fallback_is_identity_checked(tmp_path):
    class WrongKnowledge:
        def preview(self, artist, track):
            return TrackInfo("Wrong Song", artist, preview_url="https://audio.example/clip.mp3")
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=WrongKnowledge())
    assert request(app) == (200, {})


def test_custom_knowledge_errors_are_not_mistaken_for_absence(tmp_path):
    class DownKnowledge:
        def preview(self, artist, track):
            raise SourceError("Service offline")
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=DownKnowledge())
    assert request(app)[0] == 503


@pytest.mark.parametrize("artist,title", [("", "Song"), ("", ""), ("A" * 201, "Song"), ("A", "Song\n")])
def test_preview_input_validation(tmp_path, artist, title):
    app, transport = application(tmp_path, lambda _: (200, {"data": []}))
    # Surrounding whitespace is accepted, embedded controls are rejected.
    if title == "Song\n":
        title = "So\nng"
    assert request(app, artist, title)[0] == 400
    assert transport.calls == []


def test_non_https_candidate_does_not_block_later_playable_version(tmp_path):
    def upstream(query):
        return 200, {"data": [song(title="Downbound Train (Live)",
                                  preview="javascript:x" if "(Live)" in query else "https://audio.example/clip.mp3")]}
    app, _ = application(tmp_path, upstream)
    assert request(app, track="Downbound Train (Live)")[1]["preview_url"].startswith("https://")


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": "bad"}, []])
def test_malformed_successful_response_is_lookup_failure(tmp_path, payload):
    app, _ = application(tmp_path, lambda _: (200, payload))
    assert request(app)[0] == 503


def test_expired_url_retry_fetches_new_media_without_touching_other_cached_lookups(tmp_path):
    current = {"url": "https://audio.example/old.mp3"}
    app, transport = application(tmp_path, lambda _: (200, {"data": [song(preview=current["url"])]}))
    app.store.cache_put("unrelated-public-lookup", {"preserved": True})
    assert app.preview("Bruce Springsteen", "Downbound Train")["preview_url"] == current["url"]
    current["url"] = "https://audio.example/new.mp3"
    assert app.preview("Bruce Springsteen", "Downbound Train")["preview_url"].endswith("old.mp3")
    assert app.preview("Bruce Springsteen", "Downbound Train", fresh=True)["preview_url"] == current["url"]
    assert len(transport.calls) == 2
    assert app.store.cache_get("unrelated-public-lookup", 3600) == (True, {"preserved": True})


def test_browser_expired_media_retry_refetches_asynchronously(tmp_path):
    transport = Transport(lambda _: (200, {"data": [song(preview="https://audio.example/new.mp3")]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    req = browser.app.knowledge.deezer.req("/search/track", 10800, q="Bruce Springsteen Downbound Train", limit=20)
    browser.app.store.cache_put(req.cache_key, {"data": [song(preview="https://audio.example/old.mp3")]})
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen&track=Downbound+Train&fresh=1")
    assert not task.step()
    plan = task.plan()
    assert len(plan) == 1
    status, body = transport(plan[0]["url"])
    task.ingest(plan[0]["key"], status, body.decode())
    assert task.step() and task.result[0] == 200
    assert task.result[1]["preview_url"].endswith("new.mp3")
    assert len(transport.calls) == 1


def test_browser_cached_preview_needs_no_network(tmp_path):
    transport = Transport(lambda _: (200, {"data": [song()]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    req = browser.app.knowledge.deezer.req("/search/track", 10800, q="Bruce Springsteen Downbound Train", limit=20)
    browser.app.store.cache_put(req.cache_key, {"data": [song()]})
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen&track=Downbound+Train")
    assert not task.step() and task.plan() == []
    assert task.step() and task.result[0] == 200 and task.result[1]["preview_url"]
    assert transport.calls == []


def test_exact_requested_recording_precedes_another_playable_live_or_remaster_version(tmp_path):
    app, _ = application(tmp_path, lambda _: (200, {"data": [
        song(title="Downbound Train (Live)", preview="https://audio.example/live.mp3"),
        song(title="Downbound Train", preview="https://audio.example/original.mp3"),
    ]}))
    assert request(app)[1]["preview_url"].endswith("original.mp3")


def test_artist_only_lookup_returns_playable_song_by_exact_artist(tmp_path):
    app, transport = application(tmp_path, lambda _: (200, {"data": [
        song(artist="Bruce Springsteen Tribute Band", title="Popular Cover"),
        song(title="Silent Version", preview=""), song(),
    ]}))
    status, payload = request(app, track="")
    assert status == 200 and payload["artist"] == "Bruce Springsteen"
    assert payload["title"] == "Downbound Train" and payload["preview_url"]
    assert len(transport.calls) == 1
    assert parse_qs(urlsplit(transport.calls[0]).query)["q"] == ["Bruce Springsteen"]


def test_artist_only_lookup_rejects_other_artists(tmp_path):
    app, _ = application(tmp_path, lambda _: (200, {"data": [song(artist="Other Artist")]}))
    assert request(app, track="") == (200, {})


def test_artist_only_outage_is_retryable_failure(tmp_path):
    app, _ = application(tmp_path, lambda _: (503, {}))
    assert request(app, track="")[0] == 503


def test_browser_artist_only_lookup_fetches_once_without_synchronous_fallback(tmp_path):
    transport = Transport(lambda _: (200, {"data": [song()]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen")
    assert not task.step()
    plan = task.plan()
    assert len(plan) == 1
    status, body = transport(plan[0]["url"])
    task.ingest(plan[0]["key"], status, body.decode())
    assert task.step() and task.result[0] == 200 and task.result[1]["preview_url"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status,payload", [
    (401, {"error": "not authorized"}),
    (403, {"error": "forbidden"}),
    (404, {"error": "search service gone"}),
    (200, {"error": {"code": 100, "message": "permission error"}}),
])
def test_denied_or_invalid_lookup_is_not_cached_as_absence(tmp_path, status, payload):
    app, transport = application(tmp_path, lambda _: (status, payload))
    assert request(app)[0] == 503
    assert request(app)[0] == 503
    assert len(transport.calls) == 2


def test_explicit_upstream_no_data_is_genuine_absence(tmp_path):
    app, _ = application(tmp_path, lambda _: (200, {"error": {"code": 800, "message": "no data"}}))
    assert request(app) == (200, {})


def test_browser_denied_response_is_not_cached_or_retried_synchronously(tmp_path):
    transport = Transport(lambda _: (200, {"data": [song()]}))
    browser = BrowserBackend(db_path=str(tmp_path / "browser.db"), transport=transport, http_options=FAST)
    task = browser.request("GET", "/api/preview", "artist=Bruce+Springsteen&track=Downbound+Train")
    assert not task.step()
    item = task.plan()[0]
    task.ingest(item["key"], 403, '{"error":"forbidden"}')
    assert task.step() and task.result[0] == 503
    assert transport.calls == []
    assert browser.app.store.cache_get(item["key"], 10800)[0] is False
