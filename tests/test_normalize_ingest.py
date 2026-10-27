import io
import json
import zipfile
from datetime import datetime, timezone

from musicfinder.ingest import load_paths, parse_bytes, parse_document, reconcile
from musicfinder.models import Play, parse_ts
from musicfinder.normalize import artist_key, clean_tag, is_various, track_key


def test_artist_key_collapses_case_accents_and_the():
    assert artist_key("The Beatles") == artist_key("beatles") == "beatles"
    assert artist_key("Beyoncé") == artist_key("BEYONCE")
    assert artist_key("Simon & Garfunkel") == artist_key("Simon and Garfunkel")
    assert artist_key("AC/DC") == "ac dc"
    assert artist_key("방탄소년단") == "방탄소년단"  # non-Latin names survive
    assert artist_key("ガガ") != artist_key("カカ")  # kana voicing marks are not "accents"
    assert artist_key(artist_key("The The")) == artist_key("The The")  # idempotent


def test_track_key_drops_versions_and_features():
    base = track_key("Bohemian Rhapsody")
    assert track_key("Bohemian Rhapsody - Remastered 2011") == base
    assert track_key("Bohemian Rhapsody (Live Aid)") == base
    assert track_key("Song (feat. Someone)") == track_key("Song")
    assert track_key("Song feat. Someone") == track_key("Song")
    assert track_key("Under Pressure") != base


def test_clean_tag():
    assert clean_tag("Hip-Hop") == "hip hop"
    assert clean_tag("seen live") is None
    assert clean_tag("80s") is None
    assert clean_tag("1999") is None
    assert clean_tag("Shoegaze") == "shoegaze"
    assert is_various("Various Artists")


def test_parse_ts_formats():
    assert parse_ts("2023-05-01T10:00:00Z") == datetime(2023, 5, 1, 10, tzinfo=timezone.utc)
    assert parse_ts("2023-05-01 10:00") == datetime(2023, 5, 1, 10, tzinfo=timezone.utc)
    assert parse_ts("") is None


EXT = [
    {"ts": "2024-01-01T10:00:00Z", "ms_played": 200000, "master_metadata_track_name": "A",
     "master_metadata_album_artist_name": "Artist", "master_metadata_album_album_name": "LP",
     "spotify_track_uri": "spotify:track:1", "reason_start": "clickrow", "reason_end": "trackdone",
     "shuffle": False, "skipped": None},
    {"ts": "2024-01-01T10:05:00Z", "ms_played": 5000, "master_metadata_track_name": None,
     "master_metadata_album_artist_name": None, "episode_name": "Pod ep", "reason_end": "fwdbtn"},
    {"ts": "2024-01-01T10:06:00Z", "ms_played": 4000, "master_metadata_track_name": "B",
     "master_metadata_album_artist_name": "Various Artists", "reason_end": "fwdbtn"},
]
BASIC = [{"endTime": "2023-06-01 09:00", "artistName": "Old", "trackName": "Song", "msPlayed": 180000}]
LIB = {"tracks": [{"artist": "Artist", "album": "LP", "track": "A", "uri": "spotify:track:1"}],
       "artists": [{"name": "Followed", "uri": "x"}], "bannedArtists": [{"name": "Nope"}],
       "bannedTracks": [{"artist": "Artist", "track": "Bad"}], "albums": []}
PLAYLISTS = {"playlists": [{"name": "Mix", "items": [
    {"track": {"trackName": "P", "artistName": "Plist", "albumName": "X", "trackUri": "u"}, "addedDate": "2024-01-02"},
    {"track": None, "episode": {"episodeName": "e"}}]}]}


def test_parse_extended_skips_podcasts_and_various():
    res = parse_document("Streaming_History_Audio_2024.json", EXT)
    assert len(res.plays) == 1
    p = res.plays[0]
    assert (p.artist, p.track, p.reason_start, p.reason_end, p.fmt) == ("Artist", "A", "clickrow", "trackdone", "extended")
    assert res.non_music_rows == 2


def test_parse_basic_library_playlists():
    assert parse_document("StreamingHistory_music_0.json", BASIC).plays[0].fmt == "basic"
    lib = parse_document("YourLibrary.json", LIB).library
    kinds = sorted(i.kind for i in lib)
    assert kinds == ["banned_artist", "banned_track", "followed_artist", "saved_track"]
    pl = parse_document("Playlist1.json", PLAYLISTS).library
    assert len(pl) == 1 and pl[0].kind == "playlist_track" and pl[0].added is not None
    podcast = parse_document("StreamingHistory_podcast_0.json", [{"endTime": "2023-01-01 00:00", "podcastName": "x",
                                                                  "episodeName": "y", "msPlayed": 1}])
    assert podcast.plays == [] and podcast.ignored


def test_zip_and_directory_import(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Spotify Extended Streaming History/Streaming_History_Audio_2024.json", json.dumps(EXT))
        zf.writestr("Spotify Account Data/YourLibrary.json", json.dumps(LIB))
        zf.writestr("__MACOSX/._junk.json", "garbage")
        zf.writestr("ReadMeFirst.pdf", b"%PDF")
    res = parse_bytes("my_spotify_data.zip", buf.getvalue())
    assert len(res.plays) == 1 and len(res.library) == 4
    d = tmp_path / "export"
    d.mkdir()
    (d / "StreamingHistory_music_0.json").write_text(json.dumps(BASIC))
    (d / "notes.txt").write_text("hi")
    assert len(load_paths([d]).plays) == 1


def test_reconcile_prefers_extended_and_dedupes():
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ext = Play(t, "A", "x", ms_played=1000)
    dup = Play(t, "A", "x", ms_played=1000)
    basic_inside = Play(t, "A", "x", ms_played=1000, fmt="basic")
    basic_outside = Play(datetime(2020, 1, 1, tzinfo=timezone.utc), "B", "y", ms_played=1, fmt="basic")
    out = reconcile([ext, dup, basic_inside, basic_outside])
    assert out == [basic_outside, ext]
