"""Feedback, discovery-rank and song-list regressions."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from musicfinder.explore import genre_shares, territories, territory_feedback
from musicfinder.feedback import calibration, feedback_stats, latest_by_artist, like_probability
from musicfinder.graph import KnowledgeGraph
from musicfinder.models import Feedback, LibraryItem, Play
from musicfinder.recommender import ScoringParams, diversify, recommend, score_pool
from musicfinder.sources.base import Neighbor, TrackInfo
from musicfinder.taste import apply_feedback, build_profile
from musicfinder.tracks import recommend_tracks, song_seeds

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rating(artist, verdict, day=0, **context):
    return Feedback(artist, verdict, ts=NOW + timedelta(days=day), context=context)


def picked(*names):
    return build_profile([], [LibraryItem("picked_artist", name) for name in names])


def connected_graph():
    kg = KnowledgeGraph()
    kg.add_neighbors("Loved", {"source": [Neighbor("One", 1), Neighbor("Two", 1)]})
    kg.add_neighbors("Remote", {"source": [Neighbor("Unrelated", 1)]})
    return kg


def test_latest_feedback_uses_timestamp_and_clear_overrides():
    fbs = [rating("Artist", "clear", 2), rating("Artist", "like", 0), rating("Artist", "dislike", 1)]
    assert latest_by_artist(fbs)["artist"].verdict == "clear"
    assert feedback_stats(fbs)["overall"]["rated"] == 0
    assert "artist" not in build_profile([], feedback=fbs).positive_seeds()


def test_feedback_after_historical_cutoff_cannot_leak():
    fbs = [rating("Past", "like", -3), rating("Future", "like", 3), rating("At Cutoff", "like")]
    assert set(build_profile([], as_of=NOW, feedback=fbs).positive_seeds()) == {"past"}
    assert set(build_profile([], feedback=fbs).positive_seeds()) == {"past", "future", "at cutoff"}


def test_feedback_application_is_idempotent_and_clear_removes_bonus():
    prof = picked("Loved")
    fb = rating("New", "like")
    apply_feedback(prof, [fb])
    first = (prof.artists["new"].affinity, prof.artists["new"].recent_affinity)
    apply_feedback(prof, [fb])
    assert (prof.artists["new"].affinity, prof.artists["new"].recent_affinity) == pytest.approx(first)
    apply_feedback(prof, [rating("New", "clear", 1)])
    assert "new" not in prof.positive_seeds() and "new" not in prof.positive_seeds(recent=True)


def test_feedback_dislike_removes_artist_and_tracks_from_favourites():
    plays = [Play(NOW, "Artist", "Song", ms_played=200_000, reason_end="trackdone")]
    prof = build_profile(plays, feedback=[rating("Artist", "dislike", 1)])
    assert not prof.top_artists() and not prof.top_tracks()
    assert "artist" in prof.negative_seeds()


def test_hidden_songs_do_not_reject_the_entire_artist():
    prof = build_profile([], [LibraryItem("banned_track", "Artist", "Song1"),
                              LibraryItem("banned_track", "Artist", "Song2")])
    assert "artist" not in prof.negative_seeds()
    assert all(t.banned for t in prof.tracks.values())


def test_explicit_favourite_outweighs_a_history_of_skips():
    plays = [Play(NOW, "Artist", "Song", ms_played=8_000, skipped=True, reason_end="fwdbtn")] * 50
    assert "artist" in build_profile(plays).negative_seeds()
    for prof in (build_profile(plays, [LibraryItem("picked_artist", "Artist")]),
                 build_profile(plays, feedback=[rating("Artist", "like", 1)])):
        assert "artist" in prof.positive_seeds()
        assert "artist" in prof.positive_seeds(recent=True)
        assert "artist" not in prof.negative_seeds()


def test_include_never_bypasses_known_or_excluded_and_normalizes_names():
    pool = score_pool(picked("Loved"), connected_graph(), exclude=["One"], include=["Loved", "ONE", "Two"])
    assert pool.ranked_keys() == ["two"] and pool.candidates[0].percentile == 50


def test_unconnected_search_results_are_not_personalized_discovery():
    kg, prof = connected_graph(), picked("Loved")
    assert {"remote", "unrelated"}.isdisjoint(score_pool(prof, kg, hops=2).ranked_keys())
    explicit = score_pool(prof, kg, hops=2, include=["Unrelated"])
    assert explicit.by_key()["unrelated"].to_dict()["evidence"]["basis"] == "genre_search"


def test_identical_scores_have_equal_midpoint_ranks_not_100_percent():
    pool = score_pool(picked("Loved"), connected_graph())
    assert [c.percentile for c in pool.candidates] == [50, 50]
    d = pool.candidates[0].to_dict()
    assert d["rank_percentile"] == 50 and d["evidence"]["calibrated"] is False
    assert "Relative rank" in d["rank_label"]


def test_empty_requested_lists_do_not_return_an_item():
    prof, kg = picked("Loved"), connected_graph()
    pool = score_pool(prof, kg)
    assert not recommend(prof, kg, n=0) and not diversify(pool, kg, n=-1, lam=0.8)
    assert not territories(prof, kg, pool, n=0) and not territories(prof, kg, pool, per_territory=0)


def test_adventure_contribution_is_bounded_and_explained():
    kg = connected_graph()
    kg.popularity = {"one": 1e200, "two": 1}
    pool = score_pool(picked("Loved"), kg, ScoringParams(exploration=1))
    for c in pool.candidates:
        assert abs(c.contributions["novelty"]) <= 1.5
        assert "Adventure setting" in c.to_dict()["contributions"] and math.isfinite(c.score)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -1])
def test_invalid_remote_popularity_is_missing_not_broken_ranking(bad):
    kg = connected_graph()
    kg.popularity = {"one": bad, "two": 0}
    pool = score_pool(picked("Loved"), kg)
    assert all(math.isfinite(c.score) for c in pool.candidates)
    assert pool.by_key()["one"].popularity is None
    assert pool.by_key()["two"].popularity == 0


def test_territory_feedback_counts_one_current_vote_and_clear_removes_it():
    fbs = [rating("A", "like", territory="Jazz"), rating("A", "dislike", 1, territory="Jazz"),
           rating("B", "like", territory="Jazz"), rating("B", "clear", 2),
           rating("C", "like", territory="jazz")]
    assert territory_feedback(fbs) == {"jazz": (1, 1)}


def test_zero_weight_genre_tags_do_not_divide_by_zero():
    kg = connected_graph()
    kg.tags["loved"] = {"empty": 0}
    assert genre_shares(picked("Loved"), kg) == {}


def test_calibration_does_not_count_same_artist_as_independent_observations():
    fbs = [rating("Same artist", "like" if i % 2 else "dislike", i, match=i * 3) for i in range(30)]
    assert calibration(fbs) is None


def test_calibration_requires_score_variation_and_rejects_invalid_input():
    fbs = [rating(f"A{i}", "like" if i % 2 else "dislike", match=50) for i in range(30)]
    assert calibration(fbs) is None
    bad = [rating(f"A{i}", "like" if i % 2 else "dislike", match=float("nan")) for i in range(30)]
    assert calibration(bad) is None
    assert like_probability(float("nan"), {"a": 1, "b": 0}) is None
    assert like_probability(101, {"a": 1, "b": 0}) is None


def test_calibration_is_explicitly_provisional_and_can_be_withdrawn():
    fbs = [rating(f"A{i}", "like" if i > 14 else "dislike", match=i * 3) for i in range(30)]
    cal = calibration(fbs)
    assert cal and cal["validated"] is False and cal["kind"] == "in_sample_estimate"
    fbs += [rating(f"A{i}", "clear", 1) for i in range(20)]
    assert calibration(fbs) is None


def test_song_seeds_include_other_artists_despite_one_repeat_album():
    plays = []
    for artist, songs, repeats in [("Obsessed", 12, 20), ("Other", 4, 5), ("Third", 4, 4), ("Fourth", 4, 3)]:
        for i in range(songs):
            plays += [Play(NOW, artist, f"Song{i}", ms_played=200_000, reason_end="trackdone")] * repeats
    seeds = song_seeds(build_profile(plays), 12)
    assert len(seeds) == 12 and len({t.artist_key for t in seeds}) == 4
    assert sum(t.artist_key == "obsessed" for t in seeds) == 3


class SongKnowledge:
    def top_tracks(self, artist, n):
        if artist == "Loved":
            return [TrackInfo("Familiar", "Loved"), TrackInfo("Hidden", "Loved", 4), TrackInfo("Fresh", "Loved", 3)]
        return [TrackInfo("Gateway", artist, 5)]

    def similar_tracks(self, artist, title, n):
        return [("One", "Gateway", 1), ("Loved", "Fresh", 0.8), ("Blocked", "No", 1),
                ("Different", "Okay", 0.6), ("Broken", "NaN", float("nan"))]


def test_song_sections_never_repeat_or_recommend_hidden_tracks():
    plays = [Play(NOW, "Loved", "Familiar", ms_played=200_000, reason_end="trackdone")]
    prof = build_profile(plays, [LibraryItem("banned_track", "Loved", "Hidden")],
                         feedback=[rating("Blocked", "dislike")])
    recs = recommend(prof, connected_graph(), n=2)
    songs = recommend_tracks(prof, SongKnowledge(), recs, workers=1)
    flattened = [t for group in songs.values() for t in group]
    keys = [(t["artist"], t["title"]) for t in flattened]
    assert len(keys) == len(set(keys))
    assert ("One", "Gateway") in keys and ("Loved", "Fresh") in keys
    assert not {"Blocked", "Broken"} & {t["artist"] for t in flattened}
    assert ("Loved", "Hidden") not in keys
    empty = recommend_tracks(prof, SongKnowledge(), recs, n_new=0, n_similar=0, n_deep=0, workers=1)
    assert all(not group for group in empty.values())
