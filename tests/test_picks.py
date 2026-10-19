"""Instant start: a listener who has only named a few favourite artists (no Spotify export yet)."""

import json
import statistics
from collections import Counter

import pytest

from fake_upstream import FakeUpstream
from musicfinder.app import MusicFinder, NotReady
from musicfinder.normalize import artist_key
from musicfinder.store import Store
from musicfinder.synthetic import SyntheticKnowledge
from test_live_path import FAST, SMALL, drive_with_prefetch


def favourites(world, history_rows, n=8, per_style=2):
    """What this listener would name when asked for favourites, mixing styles as the app asks:
    their most-played artists, at most ``per_style`` from any one genre."""
    counts = Counter(r["master_metadata_album_artist_name"] for r in history_rows if r.get("ms_played", 0) > 60_000)
    out, styles = [], Counter()
    for name, _ in counts.most_common():
        genre = world.by_key[artist_key(name)].genre
        if styles[genre] < per_style:
            styles[genre] += 1
            out.append(name)
        if len(out) == n:
            break
    return out


def lift(app, world, listener, n=20):
    prof = app.profile()
    unknown = [a for a in world.artists if a.key not in prof.known_artists()]
    recs = app.recommendations(n)
    assert len(recs) == n
    rec_p = statistics.mean(listener.like_prob(world.by_key[r["key"]]) for r in recs)
    return rec_p / statistics.mean(listener.like_prob(a) for a in unknown)


def test_picks_alone_give_accurate_recommendations(tmp_path, world, listener, history_rows):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    assert not app.has_data()
    with pytest.raises(NotReady, match="Pick a few artists"):
        app.profile()

    favs = favourites(world, history_rows)
    found = app.search_artists(favs[0][:5])
    assert found["items"] and all(it["picked"] is None for it in found["items"])
    for name in favs:
        app.set_pick(name, "love")
    hated = next(a.name for a in sorted(world.artists, key=lambda a: listener.like_prob(a)) if a.listeners > 1e4)
    picks = app.set_pick(hated, "dislike")
    assert picks == {"loved": favs, "disliked": [hated]}
    assert app.search_artists(favs[0])["items"][0]["picked"] == "love"
    assert app.state()["picks"] == {"loved": len(favs), "disliked": 1}

    app.build_graph()
    assert lift(app, world, listener) > 2.5  # versus recommending unknown artists at random
    names = {r["name"] for r in app.recommendations(30)}
    assert not names & set(favs) and hated not in names

    songs = app.songs()
    assert songs["new_artist"] and songs["similar_song"] and songs["deep_cut"]
    assert "you picked" in songs["deep_cut"][0]["because"]
    # New kinds of music: the simulated similarity data never crosses genres, so with only picked
    # artists the nearby-genre suggestions can be empty here; the far genres and genre search are not.
    explore = app.explore()
    assert "jazz" in explore["far_genres"]
    jazz = app.explore_tag("jazz")
    assert jazz["found"] > 0 and jazz["gateways"]
    summary = app.profile_summary()
    assert summary["plays"] == 0 and summary["picks"]["loved"] == favs
    assert all(a["trend"] is None for a in summary["top_artists"])
    report = app.evaluate()
    assert not report["ok"] and "listening history" in report["reason"]

    # Changing a pick marks the map out of date; removing works by name, whatever the capitalisation.
    assert app.graph_ready()
    app.set_pick(favs[0].upper(), "remove")
    assert not app.graph_ready() and app.picks()["loved"] == favs[1:]
    app.set_pick(favs[1], "dislike")  # changing your mind replaces the earlier verdict
    assert app.picks() == {"loved": favs[2:], "disliked": [hated, favs[1]]}
    with pytest.raises(ValueError):
        app.set_pick("", "love")
    with pytest.raises(ValueError):
        app.set_pick("Someone", "adore")

    # Picks survive a restart (a new page load) and coexist with an imported history later.
    app2 = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    assert app2.picks()["loved"] == favs[2:]
    app2.import_files([("Streaming_History_Audio_2024.json", json.dumps(history_rows).encode())])
    prof = app2.profile()
    assert prof.n_plays > 10_000 and all(prof.artists[k].picked for k in prof.positive_seeds(None) if
                                         prof.artists[k].name in favs[2:])


def test_only_dislikes_is_not_enough(tmp_path, world):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    app.set_pick(world.artists[0].name, "dislike")
    with pytest.raises(NotReady, match="at least one artist you love"):
        app.build_graph()


def test_picks_after_the_export_still_count(tmp_path, world, history_rows):
    """Picks made today are newer than the last play in the export; they must not be ignored."""
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    app.import_files([("Streaming_History_Audio_2024.json", json.dumps(history_rows).encode())])
    played = {r["master_metadata_album_artist_name"] for r in history_rows}
    new = next(a.name for a in world.artists if a.name not in played)
    app.set_pick(new, "love")
    a = app.profile().artists[world.artists[[x.name for x in world.artists].index(new)].key]
    assert a.picked and a.affinity > 0 and a.key in app.profile().positive_seeds(None)


@pytest.mark.parametrize("key", [None, "KEY"], ids=["keyless", "lastfm"])
def test_picks_through_the_real_clients_and_prefetch(tmp_path, world, listener, history_rows, key):
    """The hosted version's path: search, pick, build and songs, with every lookup prefetched."""
    fake = FakeUpstream(world)
    app = MusicFinder(Store(tmp_path / "db.sqlite"), transport=fake, http_options=FAST, crawl_cfg=SMALL)
    if key:
        app.update_settings(lastfm_api_key=key)
    favs = favourites(world, history_rows)
    for name in favs:
        res, sync = drive_with_prefetch(app.search_artists_steps(name.lower()), app, fake)
        assert sync == 0
        assert res["items"][0]["name"] == name, res  # the exact name first, above a decoy with more fans
        app.set_pick(res["items"][0]["name"], "love")
    kg, sync = drive_with_prefetch(app.build_graph_steps(), app, fake)
    assert sync == 0 and any(kg.adj.values())
    assert lift(app, world, listener) > 2.5
    songs, sync = drive_with_prefetch(app.songs_steps(0.0), app, fake)
    assert sync == 0 and songs["similar_song"] and songs["new_artist"]
    # "Goes with" a picked artist's song never means that same song, or more by the same artist.
    assert not {s["artist"] for s in songs["similar_song"]} & set(favs)


def test_pick_from_the_command_line(tmp_path, capsys):
    from musicfinder.cli import main

    home = str(tmp_path / "home")
    assert main(["pick", "--home", home, "--exact", "Radiohead", "Björk"]) == 0
    assert main(["pick", "--home", home, "--exact", "--dislike", "Nickelback"]) == 0
    assert main(["pick", "--home", home, "--remove", "radiohead"]) == 0
    out = capsys.readouterr().out
    assert "Loved: Björk" in out.splitlines()[-3] and "Not for you: Nickelback" in out


def test_picks_made_during_a_build_keep_the_map_out_of_date(tmp_path, world, history_rows):
    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    favs = favourites(world, history_rows)
    app.set_pick(favs[0], "love")
    build = app.build_graph_steps()
    next(build)  # the build has started (it pauses before its first lookups)...
    app.set_pick(favs[1], "love")  # ...and meanwhile the listener picks another artist
    with pytest.raises(StopIteration):
        while True:
            next(build)
    assert app.graph() is not None and not app.graph_ready()  # still offers "Update my recommendations"
    app.build_graph()
    assert app.graph_ready()
    # Deleting ratings keeps the map; it is only marked out of date.
    app.clear("feedback")
    assert app.graph() is not None and not app.graph_ready()


def test_a_failed_search_says_so_and_never_disables_search(tmp_path):
    from musicfinder.api import dispatch_steps
    from musicfinder.steps import run

    calls = []

    def offline(url, headers=None, timeout=0):
        calls.append(url)
        raise OSError("no network")

    app = MusicFinder(Store(tmp_path / "db.sqlite"), transport=offline, http_options={**FAST, "retries": 0})
    for _ in range(8):  # more than the circuit breaker's limit
        status, payload = run(dispatch_steps(app, "GET", "/api/search/artists", {"q": ["Radiohead"]}))
        assert status == 503 and "connection" in payload["error"]
    assert len(calls) == 8  # every search was really tried
    assert "deezer" not in app.knowledge.status()["unavailable"]


def test_a_pick_overrides_earlier_ratings_and_spotify_hiding(tmp_path, world):
    from musicfinder.models import LibraryItem

    app = MusicFinder(Store(tmp_path / "db.sqlite"), knowledge=SyntheticKnowledge(world), crawl_cfg=SMALL)
    a, b = world.artists[0], world.artists[1]
    app.store.add_library([LibraryItem("banned_artist", b.name, "", None, None)])  # hidden in Spotify years ago
    app.add_feedback(a.name, "dislike")  # rated "Not for me" once...
    app.set_pick(a.name, "love")  # ...but now picked as a favourite
    app.set_pick(b.name, "love")
    prof = app.profile()
    for x in (a, b):
        assert x.key in prof.positive_seeds(None) and x.key not in prof.negative_seeds()
    app.set_pick(a.name, "dislike")
    assert a.key in app.profile().negative_seeds() and a.key not in app.profile().positive_seeds(None)
