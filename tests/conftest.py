from __future__ import annotations

import pytest

from musicfinder.ingest import parse_document
from musicfinder.synthetic import SyntheticKnowledge, make_listener, make_world, simulate_history


@pytest.fixture(scope="session")
def world():
    return make_world()


@pytest.fixture(scope="session")
def listener(world):
    return make_listener(world)


@pytest.fixture(scope="session")
def history_rows(world, listener):
    return simulate_history(world, listener)


@pytest.fixture(scope="session")
def plays(history_rows):
    return parse_document("Streaming_History_Audio_2024.json", history_rows).plays


@pytest.fixture()
def knowledge(world):
    return SyntheticKnowledge(world)


@pytest.fixture(scope="session")
def demo_app():
    from musicfinder.app import MusicFinder

    app = MusicFinder.demo_instance()
    app.build_graph()
    return app
