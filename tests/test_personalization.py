"""User-facing preparation, freshness, and safe model installation."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from musicfinder.app import MusicFinder, Unavailable
from musicfinder.browser import BrowserBackend
from musicfinder.evaluation import ModelConfig
from musicfinder.graph import KnowledgeGraph
from musicfinder.models import Play
from musicfinder.store import Store
from musicfinder.taste import TasteParams


def app_with_history(tmp_path):
    app = MusicFinder(Store(tmp_path / "test.db"), knowledge=object())
    begin = datetime(2024, 1, 1, tzinfo=timezone.utc)
    app.store.add_plays([Play(begin + timedelta(days=i), "A", f"T{i}", ms_played=120_000)
                         for i in range(150)])
    return app


def install_graph(app):
    app._kg = KnowledgeGraph()
    app._kg_loaded = True
    app._set_stale(False)


def report_for(validated=True, enough_data=True):
    return {"ok": True, "enough_data": enough_data, "selection": {"validated": validated},
            "chosen": ModelConfig(TasteParams(), 0.3).describe()}


def test_prepare_builds_and_tests_once_and_uses_current_history(tmp_path, monkeypatch):
    app = app_with_history(tmp_path)
    calls = []

    def build(progress=None):
        calls.append("build")
        install_graph(app)
        if False:
            yield

    def evaluate(plays, *args):
        calls.append(("evaluate", len(plays)))
        if False:
            yield
        return report_for()

    monkeypatch.setattr(app, "build_graph_steps", build)
    monkeypatch.setattr("musicfinder.app.backtest_steps", evaluate)
    assert app.prepare()["model_current"]
    assert calls == ["build", ("evaluate", 150), "build"]
    app.prepare()
    assert len(calls) == 3  # no slow repeat of an unchanged history


def test_no_new_import_does_not_mark_ready_map_stale(tmp_path):
    app = app_with_history(tmp_path)
    install_graph(app)
    sig = app.history_signature()
    p = app.plays()[0]
    payload = json.dumps([{"ts": p.ts.isoformat(), "ms_played": p.ms_played,
                           "master_metadata_album_artist_name": p.artist,
                           "master_metadata_track_name": p.track}]).encode()
    assert app.import_files([("same.json", payload)])["new_plays_added"] == 0
    assert app.graph_ready() and app.history_signature() == sig
    assert app.import_files([("unrelated.json", b"{}")])["files_ignored"]
    assert app.graph_ready()


@pytest.mark.parametrize("validated,test_enough,installed", [(False, True, False), (True, False, True)])
def test_validation_alone_selects_settings(tmp_path, monkeypatch, validated, test_enough, installed):
    app = app_with_history(tmp_path)
    old = {"alpha": 0.2, "weights": {}, "history_signature": "old"}
    app.store.set_setting("model", old)

    def backtest(*args):
        if False:
            yield
        return report_for(validated, test_enough)

    def build(*args):
        if False:
            yield
        install_graph(app)

    monkeypatch.setattr("musicfinder.app.backtest_steps", backtest)
    monkeypatch.setattr(app, "build_graph_steps", build)
    app.evaluate()
    assert app.personalization_status()["model_current"] is installed
    if not installed:
        assert app.store.get_setting("model") == old
        assert app.personalization_status()["tested_current"]


def test_import_during_evaluation_does_not_install_old_model(tmp_path, monkeypatch):
    app = app_with_history(tmp_path)

    def backtest(*args):
        app.store.add_plays([Play(datetime(2025, 1, 1, tzinfo=timezone.utc), "B", "new", ms_played=60_000)])
        app._invalidate(graph=True)
        if False:
            yield
        return report_for()

    monkeypatch.setattr("musicfinder.app.backtest_steps", backtest)
    report = app.evaluate()
    assert report["history_signature"] != app.history_signature()
    assert app.store.get_setting("model") is None
    assert not app.personalization_status()["tested_current"]


def test_clearing_history_clears_its_model_and_evaluation(tmp_path):
    app = app_with_history(tmp_path)
    app.store.set_setting("model", {"alpha": 0.2})
    app.store.set_setting("evaluation", {"ok": True})
    app.clear("data")
    assert not app.has_data()
    assert app.store.get_setting("model") is None and app.evaluation() is None


def test_browser_can_import_and_show_profile_without_relay(tmp_path):
    be = BrowserBackend(db_path=str(tmp_path / "offline.db"), lookup_available=False)
    payload = json.dumps([{"endTime": "2024-01-01 12:00", "msPlayed": 120000,
                           "artistName": "A", "trackName": "T"}]).encode()
    task = be.request("POST", "/api/import", body=payload)
    while not task.step():
        pass
    assert json.loads(task.result_json())["status"] == 200
    assert be.app.profile_summary()["plays"] == 1
    assert not be.app.state()["lookup_available"]
    with pytest.raises(Unavailable, match="Codespaces"):
        be.app.build_graph()


def test_browser_prepare_is_one_background_job(tmp_path):
    be = BrowserBackend(db_path=str(tmp_path / "test.db"))
    task = be.request("POST", "/api/prepare", body=b"{}")
    while not task.step():
        pass
    assert json.loads(task.result_json())["payload"]["started"]
    assert be.app.job.name == "prepare"
    job = be.take_job()
    while not job.step():
        pass
    assert not be.app.job.running and be.app.job.error


@pytest.mark.parametrize("operation", ["build", "evaluate"])
def test_deletion_wins_over_a_running_job(tmp_path, monkeypatch, operation):
    app = app_with_history(tmp_path)
    graph = KnowledgeGraph()
    graph.adj = {"a": {"b": 1.0}, "b": {"a": 1.0}}

    def finish_old_job(*args, **kwargs):
        app.clear("data")
        if False:
            yield
        return graph if operation == "build" else report_for()

    monkeypatch.setattr("musicfinder.app.crawl_steps" if operation == "build"
                        else "musicfinder.app.backtest_steps", finish_old_job)
    app.build_graph() if operation == "build" else app.evaluate()
    assert not app.has_data()
    assert app._current_kg() is None and app.store.get_blob("graph") is None
    assert app.evaluation() is None and app.store.get_setting("model") is None


def test_custom_browser_relay_is_used_by_synchronous_previews(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from urllib.parse import unquote

    requests = []

    class Xhr:
        status = 200
        responseText = '{"data": []}'
        def open(self, method, url, async_):
            requests.append(url)
        def send(self):
            pass
        def getResponseHeader(self, name):
            return None

    monkeypatch.setitem(sys.modules, "js", SimpleNamespace(XMLHttpRequest=SimpleNamespace(new=Xhr)))
    be = BrowserBackend(db_path=str(tmp_path / "custom.db"), relay_url="https://lookup.example/api/proxy",
                        http_options={"sleep": lambda _: None})
    assert be.app.preview("A", "Song") is None
    assert requests and requests[0].startswith("https://lookup.example/api/proxy?url=")
    assert "https://api.deezer.com/search/track?" in unquote(requests[0])
