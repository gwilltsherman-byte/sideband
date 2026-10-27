"""An explicit retry recovers live sources while preserving successful cached answers."""

from musicfinder.sources import LiveKnowledge
from musicfinder.sources.base import Neighbor
from musicfinder.sources.http import HttpClient, Req, SourceError
from musicfinder.store import Store


def test_explicit_retry_recovers_source_after_circuit_breaks(tmp_path, monkeypatch):
    store = Store(tmp_path / "recovery.db")
    http = HttpClient(store, retries=0, sleep=lambda _: None)
    source = LiveKnowledge(store, use_listenbrainz=False, http=http)
    saved = Req.make("https://api.deezer.com/artist/123", {})
    store.cache_put(saved.cache_key, {"id": 123, "name": "Saved artist"})
    source._mbids["saved artist"] = "existing-identity"
    attempts = []

    def unavailable(name):
        attempts.append(name)
        raise SourceError("temporary connection failure")

    monkeypatch.setattr(source.deezer, "related", unavailable)
    for i in range(8):
        assert source.neighbors(f"Artist {i}") == {}
    assert len(attempts) == 5
    assert "deezer" in source.status()["unavailable"]

    def recovered(name):
        attempts.append(name)
        return [Neighbor("New artist", 0.8)]

    monkeypatch.setattr(source.deezer, "related", recovered)
    assert source.retry_unavailable() == ["deezer"]
    assert not source.status()["unavailable"]
    assert source.neighbors("Try again") == {"deezer": [Neighbor("New artist", 0.8)]}
    assert len(attempts) == 6
    assert source._failures["deezer"] == 0
    assert http.peek(saved) == (True, {"id": 123, "name": "Saved artist"})
    assert source._mbids["saved artist"] == "existing-identity"


def test_explicit_retry_also_resets_partial_failure_streak(tmp_path):
    source = LiveKnowledge(Store(tmp_path / "partial.db"), use_listenbrainz=False)

    def failing():
        raise SourceError("temporary")

    for _ in range(4):
        assert source._guard("deezer", failing, []) == []
    assert not source.status()["unavailable"]
    assert source.retry_unavailable() == []
    assert source._guard("deezer", failing, []) == []
    assert source._failures["deezer"] == 1
    assert not source.status()["unavailable"]
