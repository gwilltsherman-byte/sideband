"""Fast music inputs are reviewed preferences, never manufactured listening histories."""

from datetime import datetime, timedelta, timezone

import pytest

from musicfinder.ingest import load_paths, parse_bytes, parse_quick_input
from musicfinder.ingest.quick_input import MAX_QUICK_BYTES
from musicfinder.taste import build_profile


def names(result):
    return [(i.kind, i.artist, i.track) for i in result.library]


def test_artist_lines_preserve_commas_ampersands_and_unicode():
    result = parse_quick_input(" Earth, Wind & Fire \nBjörk\nSimon & Garfunkel\n방탄소년단\n", "artists")
    assert names(result) == [("picked_artist", "Earth, Wind & Fire", ""), ("picked_artist", "Björk", ""),
                             ("picked_artist", "Simon & Garfunkel", ""), ("picked_artist", "방탄소년단", "")]
    assert result.to_dict()["can_save"] and result.to_dict()["counts"] == {"artists": 4, "tracks": 0, "total": 4}


def test_artist_lines_deduplicate_normalized_names():
    result = parse_quick_input("Björk\nBJORK\nThe Beatles\nBeatles", "artists")
    assert len(result.library) == 2 and result.duplicates == 2
    assert any("duplicate" in warning for warning in result.warnings)


@pytest.mark.parametrize("dash", ["—", "–", "-"])
def test_explicit_song_lines_accept_spaced_separators(dash):
    result = parse_quick_input(f"Björk {dash} Jóga\nRadiohead {dash} Everything In Its Right Place", "songs")
    assert names(result) == [("saved_track", "Björk", "Jóga"),
                             ("saved_track", "Radiohead", "Everything In Its Right Place")]
    assert result.to_dict()["counts"] == {"artists": 2, "tracks": 2, "total": 2}


def test_song_title_can_contain_another_dash_and_versions_deduplicate():
    result = parse_quick_input("Björk — Song - Remastered 2011\nBJORK — Song\nA — Title — Part 2", "songs")
    assert names(result) == [("saved_track", "Björk", "Song - Remastered 2011"),
                             ("saved_track", "A", "Title — Part 2")]
    assert result.duplicates == 1


@pytest.mark.parametrize("line", ["Björk—Jóga", "Björk–Jóga"])
def test_typographic_song_separator_does_not_need_spaces(line):
    assert names(parse_quick_input(line, "songs")) == [("saved_track", "Björk", "Jóga")]


@pytest.mark.parametrize("line", ["Björk —", "— Jóga", "Björk-Jóga"])
def test_missing_song_side_or_unspaced_plain_hyphen_is_not_an_artist_pick(line):
    result = parse_quick_input(line, "songs")
    assert result.errors and not result.library


def test_auto_recognizes_complete_song_lines_and_requires_review_for_mixed_input():
    assert parse_quick_input("Björk — Jóga\nA - B").format == "songs"
    ambiguous = parse_quick_input("Björk — Jóga\nRadiohead")
    assert ambiguous.errors and not ambiguous.to_dict()["can_save"]
    explicit = parse_quick_input("Björk — Jóga\nRadiohead", "artists")
    assert explicit.to_dict()["can_save"] and len(explicit.library) == 2


def test_song_only_text_is_not_guessed_in_song_mode():
    result = parse_quick_input("Jóga\nParanoid Android", "songs")
    assert len(result.errors) == 2 and not result.library
    assert "Artist — Song" in result.errors[0]


@pytest.mark.parametrize("text", ["https://open.spotify.com/playlist/123", "spotify:track:123", "www.example.com/music"])
def test_bare_links_and_uris_have_actionable_errors(text):
    result = parse_quick_input(text)
    assert not result.library and not result.to_dict()["can_save"]
    assert "names" in result.errors[0] and "CSV/TSV" in result.errors[0]


def test_song_fields_must_be_names_not_links():
    result = parse_quick_input("Björk — spotify:track:123", "songs")
    assert result.errors and not result.library


def test_exportify_columns_support_names_uri_and_quoted_band_commas():
    text = '\ufeffTrack URI,Track Name,Album Name,Artist Name(s),Added At\nspotify:track:123,Jóga,Homogenic,Björk,2020-01-01\n'
    text += 'spotify:track:456,September,Best Of,"Earth, Wind & Fire",2020-01-01\n'
    result = parse_quick_input(text, name="liked.csv")
    assert names(result) == [("saved_track", "Björk", "Jóga"), ("saved_track", "Earth, Wind & Fire", "September")]
    assert result.library[0].uri == "spotify:track:123" and result.format == "csv"
    assert not result.errors


def test_plural_credited_artist_column_splits_semicolons_only():
    text = 'Artist Name(s),Track Name\n"A;B",Duet\n"Earth, Wind & Fire",September'
    result = parse_quick_input(text)
    assert names(result) == [("saved_track", "A", "Duet"), ("saved_track", "B", "Duet"),
                             ("saved_track", "Earth, Wind & Fire", "September")]


@pytest.mark.parametrize("text", ["\nArtist,Track\nBjörk,Jóga", "\n \nArtist,Track\nBjörk,Jóga"])
def test_leading_blank_rows_never_import_the_header_as_a_song(text):
    assert names(parse_quick_input(text)) == [("saved_track", "Björk", "Jóga")]


def test_tsv_and_common_spotify_columns_are_detected():
    result = parse_quick_input("Artist Names\tTrack Name\tTrack URI\nBjörk\tJóga\tspotify:track:123", name="songs.tsv")
    assert result.format == "tsv" and names(result) == [("saved_track", "Björk", "Jóga")]
    assert names(parse_quick_input("Name,Artist,Album\nJóga,Björk,Homogenic")) == [("saved_track", "Björk", "Jóga")]


def test_semicolon_delimited_csv_and_artist_only_table():
    assert names(parse_quick_input("Artist;Title\nBjörk;Jóga", name="songs.csv")) == [("saved_track", "Björk", "Jóga")]
    assert names(parse_quick_input("Artist,Genre\nBjörk,Art Pop", name="artists.csv")) == [("picked_artist", "Björk", "")]


def test_headered_csv_preserves_quoted_multiline_titles():
    result = parse_quick_input('Artist,Track\nBjörk,"Song\nPart Two"')
    assert names(result) == [("saved_track", "Björk", "Song Part Two")]


@pytest.mark.parametrize("text", ["spotify:track:123\nspotify:track:456", "Title,URL\nJóga,https://example.com"])
def test_csv_file_requires_names_in_recognized_columns(text):
    result = parse_quick_input(text, name="songs.csv")
    assert result.errors and not result.library
    with pytest.raises(ValueError, match="column"):
        parse_bytes("songs.csv", text.encode())


@pytest.mark.parametrize("text", ['Artist,Track\nBjörk,"Jóga', 'Artist,Track\nEarth, Wind & Fire,September',
                                  'Artist,Track\nBjörk,', 'Artist,Artist Name,Track\nBjörk,Björk,Jóga'])
def test_malformed_or_ambiguous_csv_does_not_allow_save(text):
    result = parse_quick_input(text, name="songs.csv")
    assert result.errors and not result.to_dict()["can_save"]


def test_a_valid_row_cannot_hide_an_invalid_row():
    result = parse_quick_input("Artist,Track\nBjörk,Jóga\nRadiohead,", name="songs.csv")
    assert len(result.library) == 1 and not result.to_dict()["can_save"]
    with pytest.raises(ValueError):
        parse_bytes("songs.csv", "Artist,Track\nBjörk,Jóga\nRadiohead,".encode())


def test_byte_and_entry_limits_apply_before_deduplication():
    assert parse_quick_input("Björk\n" * 501).errors
    assert parse_quick_input("x" * (MAX_QUICK_BYTES + 1)).errors
    assert parse_quick_input("방" * (MAX_QUICK_BYTES // 3 + 1)).errors
    assert parse_quick_input("Artist,Track\n" + "Björk,Jóga\n" * 501).errors
    within = parse_quick_input("Björk\n" * 500)
    assert within.to_dict()["can_save"] and within.duplicates == 499


def test_name_and_control_character_limits_are_actionable():
    assert parse_quick_input("A" * 201).errors
    assert parse_quick_input("Björk\x00").errors
    assert parse_quick_input("Björk", "unsupported").errors
    assert parse_quick_input(123).errors
    assert parse_quick_input("   ").errors


def test_explicit_preferences_produce_seeds_without_fabricated_history():
    artists = parse_quick_input("Björk\nRadiohead", "artists")
    songs = parse_quick_input("Björk — Jóga", "songs")
    prof = build_profile([], artists.library + songs.library)
    assert {"bjork", "radiohead"} <= set(prof.positive_seeds())
    assert ("bjork", "joga") in prof.known_tracks()
    assert prof.n_plays == prof.n_streams == prof.n_early_skips == prof.total_ms == 0
    assert prof.first is None and prof.last is None
    assert all(a.first is None and a.last is None for a in prof.artists.values())
    assert all(i.added is not None for i in artists.library + songs.library)
    before_declaration = datetime.now(timezone.utc) - timedelta(days=1)
    assert not build_profile([], artists.library + songs.library, as_of=before_declaration).positive_seeds()
    assert any("not listening" in warning for warning in songs.warnings)


def test_selected_csv_tsv_text_and_directory_integration(tmp_path):
    for name, data in [("songs.csv", b"Artist,Track\nBjoerk,Joga"),
                       ("songs.tsv", b"Artist\tSong\nRadiohead\tIdioteque"), ("artists.txt", b"Radiohead\nBjork")]:
        res = parse_bytes(name, data)
        assert res.library and res.recognized == [name] and not res.plays
        (tmp_path / name).write_bytes(data)
    (tmp_path / "notes.txt").write_text("Not a music list")
    directory = load_paths([tmp_path])
    assert len(directory.library) == 2  # unrelated text notes in a folder are never imported
    assert len(load_paths([tmp_path / "artists.txt"]).library) == 2
    with pytest.raises(ValueError, match="UTF-8"):
        parse_bytes("songs.csv", b"Artist,Track\nBj\xf6rk,Joga")
