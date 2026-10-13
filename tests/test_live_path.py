"""The production source clients and prefetch planner, end to end, against a fake Last.fm/Deezer/etc."""

import json
import statistics

import pytest

from fake_upstream import FakeUpstream
from musicfinder.app import MusicFinder
from musicfinder.evaluation import EvalConfig
from musicfinder.graph import CrawlConfig
from musicfinder.store import Store

FAST = {"sleep": lambda s: None, "rates": {h: 1e6 for h in (
    "ws.audioscrobbler.com", "api.deezer.com", "musicbrainz.org", "labs.api.listenbrainz.org")}}
SMALL = CrawlConfig(seeds=40, recent_seeds=10, negative_seeds=10, expand_candidates=60, tag_candidates=150,
                    explore_candidates=40, workers=1)
EVAL = EvalConfig(half_lives=(90.0, 365.0), seed_powers=(0.5,), alphas=(0.3,), bootstrap=100)


def make_app(tmp_path, world, history_rows, fake=None, key="KEY", crawl_cfg=SMALL):
    fake = fake or FakeUpstream(world)
    app = MusicFinder(Store(tmp_path / "db.sqlite"), transport=fake, http_options=FAST, crawl_cfg=crawl_cfg,
                      eval_cfg=EVAL)
    if key:
        app.update_settings(lastfm_api_key=key)
    app.import_files([("Streaming_History_Audio_2024.json", json.dumps(history_rows).encode())])
    return app, fake


def drive_with_prefetch(gen, app, fake):
    """Do what the browser does: at every Need, fetch the plan (repeatedly, for dependent requests) and
    store the responses, then resume. Returns (result, network calls made by the synchronous code)."""
    knowledge = app.knowledge
    sync_calls = 0
    need = None
    while True:
        before = len(fake.calls)
        try:
            need = gen.send(None)
        except StopIteration as stop:
            return stop.value, sync_calls + len(fake.calls) - before
        sync_calls += len(fake.calls) - before
        for _ in range(10):
            reqs = knowledge.plan(need.kind, need.items)
            if not reqs:
                break
            for r in reqs:
                status, raw = fake(r.full_url)
                knowledge.http.ingest(r, status, raw)


def test_build_and_recommend_through_real_clients(tmp_path, world, listener, history_rows):
    app, fake = make_app(tmp_path, world, history_rows)
    app.build_graph()
    assert app.knowledge.status()["unavailable"] == {}
    recs = app.recommendations(20)
    prof = app.profile()
    unknown = [a for a in world.artists if a.key not in prof.known_artists()]
    rec_p = statistics.mean(listener.like_prob(world.by_key[r["key"]]) for r in recs)
    base_p = statistics.mean(listener.like_prob(a) for a in unknown)
    assert rec_p > 2.5 * base_p
    kg = app.graph()
    tagged = [t for t in kg.tags.values() if t]
    assert tagged and not any("seen live" in t for t in tagged)  # Last.fm noise tags were dropped
    assert len(kg.popularity) > 50
    songs = app.songs()
    assert songs["similar_song"] and songs["new_artist"]
    jazz = app.explore_tag("jazz")
    assert jazz["found"] > 0 and jazz["gateways"]


def test_without_lastfm_the_free_sources_do_the_whole_job(tmp_path, world, listener, history_rows):
    """No Last.fm key at all: Deezer, ListenBrainz and MusicBrainz must still give accurate results."""
    app, fake = make_app(tmp_path, world, history_rows, key=None)
    app.build_graph()
    assert app.knowledge.status()["unavailable"] == {}
    assert not any("audioscrobbler" in c for c in fake.calls)
    recs = app.recommendations(20)
    prof = app.profile()
    unknown = [a for a in world.artists if a.key not in prof.known_artists()]
    rec_p = statistics.mean(listener.like_prob(world.by_key[r["key"]]) for r in recs)
    base_p = statistics.mean(listener.like_prob(a) for a in unknown)
    assert rec_p > 2.5 * base_p
    kg = app.graph()
    assert sum(1 for t in kg.tags.values() if t) > 50  # genres from MusicBrainz
    assert len(kg.popularity) > 50  # popularity from Deezer fans
    assert any(edge for edge in kg.adj.values())
    # MusicBrainz allows one request a second: lookups are batched, ten artists per request.
    mb = [c for c in fake.calls if "musicbrainz.org" in c]
    assert len(mb) * 5 < len(kg.tagged), (len(mb), len(kg.tagged))
    songs = app.songs()
    assert songs["similar_song"] and songs["new_artist"]  # Deezer radio stands in for Last.fm's similar songs
    jazz = app.explore_tag("jazz")  # a Deezer genre
    assert jazz["found"] > 0 and jazz["gateways"]
    shoegaze = app.explore_tag("shoegaze")  # not a Deezer genre: MusicBrainz tag search
    assert shoegaze["found"] > 0


@pytest.mark.parametrize("key", ["KEY", None], ids=["lastfm", "keyless"])
@pytest.mark.parametrize("operation", ["build", "songs", "explore_tag", "feedback", "artist_tracks", "evaluate"])
def test_prefetch_plan_covers_every_request(tmp_path, world, history_rows, operation, key):
    """After prefetching each step's plan, the synchronous code must not need the network at all.

    This is what makes the phone version fast: it fetches the plan in parallel, then resumes."""
    app, fake = make_app(tmp_path, world, history_rows, key=key)
    if operation != "build" and operation != "evaluate":
        app.build_graph()
    gens = {
        "build": lambda: app.build_graph_steps(),
        "songs": lambda: app.songs_steps(0.0),
        "explore_tag": lambda: app.explore_tag_steps("jazz"),
        "feedback": lambda: app.add_feedback_steps(app.recommendations(1)[0]["name"], "like"),
        "artist_tracks": lambda: app.artist_tracks_steps(app.recommendations(1)[0]["name"], 5),
        "evaluate": lambda: app.evaluate_steps(),
    }
    if operation == "feedback":
        app.build_graph()  # feedback expands an artist not yet expanded
    result, sync_calls = drive_with_prefetch(gens[operation](), app, fake)
    assert result
    assert sync_calls == 0, f"{sync_calls} requests were not covered by the prefetch plan"


def test_flaky_upstream_and_bad_key_still_work(tmp_path, world, history_rows):
    # 15% of requests fail with 503: prefetch failures aren't cached, the synchronous path retries them.
    app, fake = make_app(tmp_path, world, history_rows, fake=FakeUpstream(world, fail_rate=0.15, seed=4))
    kg, _ = drive_with_prefetch(app.build_graph_steps(), app, fake)
    assert any(kg.adj.values()) and app.recommendations(5)
    # A wrong Last.fm key: Last.fm is switched off after a few failures; Deezer and ListenBrainz carry on.
    (tmp_path / "bad").mkdir()
    app2, _ = make_app(tmp_path / "bad", world, history_rows, key="WRONG")
    app2.build_graph()
    assert "lastfm" in app2.knowledge.status()["unavailable"]
    assert app2.recommendations(5)
