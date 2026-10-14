"""Song ratings remain distinct, reversible, and useful for the next recommendations."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from musicfinder.app import MusicFinder, NotReady
from musicfinder.feedback import calibration, feedback_stats, latest_by_artist, latest_by_item
from musicfinder.graph import KnowledgeGraph
from musicfinder.interactions import Interaction
from musicfinder.models import Feedback, LibraryItem, Play
from musicfinder.recommender import Candidate, score_pool
from musicfinder.sources.base import Neighbor, TrackInfo
from musicfinder.store import Store
from musicfinder.taste import apply_feedback, build_profile
from musicfinder.tracks import recommend_tracks, song_seeds

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def vote(artist, track, verdict, seconds=0, **context):
    return Feedback(artist, verdict, track, NOW + timedelta(seconds=seconds), context)


def favs():
    return [LibraryItem("picked_artist", "Loved", added=NOW - timedelta(days=1))]


def test_latest_song_verdict_does_not_replace_artist_or_another_song():
    ratings = [vote("Loved", "", "like"), vote("Loved", "First", "like", 1),
               vote("Loved", "Second", "like", 2), vote("LOVED", "First (Remastered)", "dislike", 3)]
    latest = latest_by_item(reversed(ratings))
    assert len(latest) == 3 and latest["loved", "first"].verdict == "dislike"
    assert latest_by_artist(ratings)["loved"].verdict == "like"
    profile = build_profile([], feedback=ratings)
    assert profile.artists["loved"].feedback == "like"
    assert profile.tracks["loved", "first"].feedback == "dislike"
    assert profile.tracks["loved", "second"].feedback == "like"


def test_song_ratings_have_separate_statistics_and_do_not_calibrate_artist_rank():
    ratings = [vote("Same", f"Song {i}", "like" if i > 14 else "dislike", i,
                    match=i * 3, kind="similar_song") for i in range(30)]
    stats = feedback_stats(ratings)
    assert stats["overall"]["rated"] == 0 and stats["song_overall"]["rated"] == 30
    assert stats["songs_by_kind"]["similar_song"]["likes"] == 15
    assert stats["calibration"] is None and calibration(ratings) is None
    assert len(stats["saved_items"]) == 30 and stats["saved_items"][0]["track"] == "Song 29"
    assert stats["saved_items"][0]["context"]["match"] == 87


def test_song_dislike_keeps_artist_love_and_other_song_seeds():
    ratings = [vote("Loved", "Bad", "dislike"), vote("Loved", "Good", "like", 1)]
    profile = build_profile([], favs(), feedback=ratings)
    assert "loved" in profile.positive_seeds() and "loved" not in profile.negative_seeds()
    assert profile.blocked_artists() == set()
    assert [t.name for t in song_seeds(profile, 10)] == ["Good"]
    assert ("loved", "bad") in profile.known_tracks()
    assert profile.n_plays == profile.n_streams == profile.total_ms == 0


def test_distinct_song_ratings_accumulate_but_repeated_same_song_is_idempotent():
    first = vote("Artist", "One", "like")
    one = build_profile([], feedback=[first])
    many = build_profile([], feedback=[first, vote("Artist", "Two", "like", 1),
                                       vote("Artist", "Three", "like", 2)])
    repeats = build_profile([], feedback=[vote("Artist", "One", "like", i) for i in range(100)])
    assert 0 < one.artists["artist"].affinity < many.artists["artist"].affinity < 3
    assert repeats.artists["artist"].affinity == pytest.approx(one.artists["artist"].affinity)
    assert repeats.tracks["artist", "one"].affinity == one.tracks["artist", "one"].affinity


def test_clearing_song_reverses_its_seed_and_artist_adjustment():
    profile = build_profile([], feedback=[vote("Artist", "One", "like")])
    initial = profile.artists["artist"].affinity
    apply_feedback(profile, [vote("Artist", "Two", "like", 1)])
    assert profile.artists["artist"].affinity > initial
    apply_feedback(profile, [vote("Artist", "Two - 2022 Remaster", "clear", 2)])
    assert profile.artists["artist"].affinity == pytest.approx(initial)
    assert ("artist", "two") not in profile.known_tracks()
    apply_feedback(profile, [vote("Artist", "One", "clear", 3)])
    assert not profile.positive_seeds() and not profile.known_tracks() and not profile.known_artists()


def test_dislike_and_clear_replace_like_without_fake_listening():
    play = Play(NOW - timedelta(days=2), "Artist", "Other", ms_played=180_000, reason_end="trackdone")
    base = build_profile([play])
    ratings = [vote("Artist", "One", "like"), vote("Artist", "One", "dislike", 1)]
    profile = build_profile([play], feedback=ratings)
    assert profile.artists["artist"].affinity < base.artists["artist"].affinity
    assert "artist" not in profile.blocked_artists()
    cleared = build_profile([play], feedback=ratings + [vote("Artist", "One", "clear", 2)])
    assert cleared.artists["artist"].affinity == pytest.approx(base.artists["artist"].affinity)
    assert (cleared.n_plays, cleared.n_streams, cleared.total_ms) == (base.n_plays, base.n_streams, base.total_ms)


def test_song_and_known_feedback_respect_historical_cutoff():
    ratings = [vote("Past", "One", "like", -1), vote("Future", "Two", "dislike", 1),
               vote("At", "Three", "known")]
    profile = build_profile([], as_of=NOW, feedback=ratings)
    assert set(profile.tracks) == {("past", "one")}
    assert set(profile.artists) == {"past"}


def test_latest_artist_decision_wins_across_setup_and_recommendations_then_undo_restores_pick():
    old_love = LibraryItem("picked_artist", "Artist", added=NOW)
    newer_dislike = vote("Artist", "", "dislike", 1)
    profile = build_profile([], [old_love], feedback=[newer_dislike])
    assert "artist" in profile.blocked_artists() and "artist" not in profile.positive_seeds()
    cleared = build_profile([], [old_love], feedback=[newer_dislike, vote("Artist", "", "clear", 2)])
    assert "artist" in cleared.positive_seeds() and "artist" not in cleared.blocked_artists()
    newer_love = LibraryItem("picked_artist", "Artist", added=NOW + timedelta(seconds=2))
    restored = build_profile([], [newer_love], feedback=[newer_dislike])
    assert "artist" in restored.positive_seeds() and "artist" not in restored.negative_seeds()
    old_dislike = LibraryItem("picked_dislike", "Artist", added=NOW)
    assert "artist" in build_profile([], [old_dislike], feedback=[vote("Artist", "", "like", 1)]).positive_seeds()


class LearningSongs:
    def top_tracks(self, artist, n):
        return [TrackInfo("First choice", artist), TrackInfo("Second choice", artist)]

    def similar_tracks(self, artist, title, n):
        if title.startswith("Rejected"):
            return [("Near", "First choice", 1), ("Gateway", "First choice", 1), ("Loved", "First choice", 1)]
        return [("Near", "First choice", 1), ("Other", "Alternative", 0.9), ("Loved", "First choice", 0.8)]


def learned_songs(ratings):
    profile = build_profile([], favs(), feedback=[vote("Loved", "Seed", "like", -1)] + ratings)
    return recommend_tracks(profile, LearningSongs(), [Candidate("gateway", "Gateway", {}, score=1)], workers=1)


def test_disliked_song_neighbors_lower_future_rank_in_all_three_song_sections():
    before = learned_songs([])
    after = learned_songs([vote("Reject", "Rejected", "dislike")])
    assert before["similar_song"][0]["artist"] == "Near"
    assert after["similar_song"][0]["artist"] == "Other"
    assert before["new_artist"][0]["title"] == before["deep_cut"][0]["title"] == "First choice"
    assert after["new_artist"][0]["title"] == after["deep_cut"][0]["title"] == "Second choice"
    assert after["similar_song"][1]["learned_penalty"] > 0
    undone = learned_songs([vote("Reject", "Rejected", "dislike"), vote("Reject", "Rejected", "clear", 1)])
    assert undone == before


@pytest.mark.parametrize("verdict", ["like", "dislike", "known"])
def test_rated_song_remasters_stay_out_of_every_section_without_banning_other_songs(verdict):
    ratings = [vote("Loved", "First choice (Remastered 2024)", verdict)]
    groups = learned_songs(ratings)
    assert all(not (song["artist"] == "Loved" and song["title"] == "First choice")
               for group in groups.values() for song in group)
    assert any(song["artist"] == "Loved" and song["title"] == "Second choice"
               for group in groups.values() for song in group)


def test_song_dislike_transfer_penalizes_related_artists_without_hard_banning():
    kg = KnowledgeGraph()
    kg.add_neighbors("Loved", {"test": [Neighbor("Near", 1), Neighbor("Far", 1)]})
    kg.add_neighbors("Rejected", {"test": [Neighbor("Near", 1)]})
    before = score_pool(build_profile([], favs()), kg).by_key()
    profile = build_profile([], favs(), feedback=[vote("Rejected", "Song", "dislike")])
    after = score_pool(profile, kg).by_key()
    assert set(after) == set(before)
    assert after["near"].score - after["far"].score < before["near"].score - before["far"].score
    assert after["near"].contributions["neg"] < after["far"].contributions["neg"]
    assert profile.blocked_artists() == set() and profile.negative_seeds()["rejected"] < 3


def test_weak_click_interest_does_not_mark_song_or_artist_already_known():
    click = Interaction(str(uuid4()), "Gateway", "external_open", "Fresh", NOW)
    profile = build_profile([], favs(), interactions=[click])
    assert "gateway" not in profile.known_artists() and ("gateway", "fresh") not in profile.known_tracks()
    assert profile.artists["gateway"].affinity > 0
    assert profile.n_plays == profile.n_streams == 0


def test_app_feedback_persists_song_scope_and_recent_verdict_across_reopen(tmp_path):
    class OfflineKnowledge:
        pass

    path = tmp_path / "taste.sqlite"
    app = MusicFinder(Store(path), knowledge=OfflineKnowledge())
    app.set_pick("Loved", "love")
    result = app.add_feedback("Loved", "dislike", "First (Remastered)", {"source": "songs", "kind": "deep_cut"})
    assert result["overall"]["rated"] == 0 and result["song_overall"]["rated"] == 1
    again = MusicFinder(Store(path), knowledge=OfflineKnowledge())
    summary = again.feedback_summary()
    assert summary["recent"][0]["track"] == "First (Remastered)"
    assert summary["saved_items"][0]["track_key"] == "first"
    assert "loved" in again.profile().positive_seeds()
    again.add_feedback("Loved", "clear", "First")
    assert again.feedback_summary()["song_overall"]["rated"] == 0
    assert ("loved", "first") not in again.profile().known_tracks()


def test_profile_listening_statistics_exclude_weak_actions_and_ratings(tmp_path):
    app = MusicFinder(Store(tmp_path / "stats.sqlite"), knowledge=object())
    app.set_pick("Loved", "love")
    app.store.add_interaction(Interaction(str(uuid4()), "Gateway", "preview_listen", "Fresh", NOW, 30_000))
    app.add_feedback("Other", "like", "Explicit")
    summary = app.profile_summary()
    assert summary["plays"] == summary["streams"] == summary["artists_heard"] == summary["hours"] == 0
    assert all(a["trend"] is None for a in summary["top_artists"])


@pytest.mark.parametrize("track", ["", "New favourite song"])
def test_learned_likes_stay_usable_after_original_setup_favourites_are_removed(tmp_path, track):
    app = MusicFinder(Store(tmp_path / "learned.sqlite"), knowledge=object())
    app.set_pick("Original", "love")
    app.add_feedback("New Favourite", "like", track)
    app.set_pick("Original", "remove")
    assert app.has_data()
    assert "new favourite" in app.profile().positive_seeds()
    assert app.input_summary()["positive_artists"] == 1
    assert app.input_summary()["liked_songs"] == bool(track)
    assert app.input_summary()["liked_artists"] == (not track)
    assert app.personalization_status()["next_action"] == "prepare"
    assert app.profile_summary()["plays"] == app.profile_summary()["streams"] == 0
    again = MusicFinder(Store(tmp_path / "learned.sqlite"), knowledge=object())
    assert again.has_data() and "new favourite" in again.profile().positive_seeds()
    again.add_feedback("New Favourite", "clear", track)
    assert not again.has_data() and again.input_summary()["positive_artists"] == 0


@pytest.mark.parametrize("verdict", ["known", "dislike", "clear"])
def test_neutral_or_negative_only_ratings_do_not_masquerade_as_positive_starting_taste(tmp_path, verdict):
    app = MusicFinder(Store(tmp_path / "neutral.sqlite"), knowledge=object())
    app.add_feedback("Artist", verdict, "Song")
    assert not app.has_data() and app.input_summary()["positive_artists"] == 0
    with pytest.raises(NotReady):
        app.profile()
    assert app.feedback_summary()["saved_items"] or verdict == "clear"


def test_input_summary_excludes_an_older_setup_love_overridden_by_artist_dislike(tmp_path):
    app = MusicFinder(Store(tmp_path / "choices.sqlite"), knowledge=object())
    app.set_pick("Artist", "love")
    assert app.input_summary()["positive_artists"] == 1
    app.add_feedback("Artist", "dislike")
    assert app.input_summary()["positive_artists"] == 0
    app.add_feedback("Artist", "clear")
    assert app.input_summary()["positive_artists"] == 1


def test_new_song_like_overrides_old_imported_hide_and_undo_restores_hide():
    library = favs() + [LibraryItem("banned_track", "Loved", "Hidden", added=NOW - timedelta(days=1))]
    liked = build_profile([], library, feedback=[vote("Loved", "Hidden", "like")])
    assert not liked.tracks["loved", "hidden"].banned
    assert [t.name for t in song_seeds(liked, 10)] == ["Hidden"]
    undone = build_profile([], library, feedback=[vote("Loved", "Hidden", "like"), vote("Loved", "Hidden", "clear", 1)])
    assert undone.tracks["loved", "hidden"].banned and not song_seeds(undone, 10)
    newer_hide = LibraryItem("banned_track", "Loved", "Hidden", added=NOW + timedelta(seconds=1))
    still_hidden = build_profile([], favs() + [newer_hide], feedback=[vote("Loved", "Hidden", "like")])
    assert still_hidden.tracks["loved", "hidden"].banned and not song_seeds(still_hidden, 10)
    hidden_only = build_profile([], [newer_hide], feedback=[vote("Loved", "Hidden", "like")])
    assert not hidden_only.positive_seeds()
    artist_hidden = build_profile([], [LibraryItem("picked_dislike", "Loved")], feedback=[vote("Loved", "Hidden", "like")])
    assert not song_seeds(artist_hidden, 10)  # a whole-artist decision still takes priority


@pytest.mark.parametrize("verdict", ["like", "dislike", "known", "clear"])
def test_song_rating_finishes_locally_without_artist_graph_lookups(tmp_path, verdict):
    class NoNetwork:
        def neighbors(self, *args, **kwargs):
            pytest.fail("A song verdict must save without whole-artist graph lookups")

    app = MusicFinder(Store(tmp_path / "local-rating.sqlite"), knowledge=NoNetwork())
    app._kg = KnowledgeGraph()
    app._kg_loaded = True
    assert app.lookup_available
    pending = app.add_feedback_steps("Fiona Apple", verdict, "Criminal")
    with pytest.raises(StopIteration) as finished:
        next(pending)
    stats = finished.value.value
    assert stats["song_overall"]["rated"] == (verdict in ("like", "dislike"))
    assert app.store.feedback()[0].track == "Criminal"
    assert app.feedback_summary()["saved_items"] or verdict == "clear"


def test_artist_only_rating_keeps_artist_graph_expansion(tmp_path):
    from musicfinder.steps import Need

    app = MusicFinder(Store(tmp_path / "artist-rating.sqlite"), knowledge=object())
    app._kg = KnowledgeGraph()
    app._kg_loaded = True
    pending = app.add_feedback_steps("Fiona Apple", "like", "  ")
    step = next(pending)
    assert isinstance(step, Need)
    assert app.store.feedback()[0].track == ""
    pending.close()
