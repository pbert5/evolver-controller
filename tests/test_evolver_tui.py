from __future__ import annotations

from pathlib import Path

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_edge.tui import (
    TUIUnavailableError,
    _offline_source,
    _operator_source,
    _load_ui_dependencies,
)


class FakeOperatorClient:
    def __init__(self, values: dict[str, object]):
        self.values = values
        self.operations: list[str] = []

    def request(self, operation: str) -> object:
        self.operations.append(operation)
        return self.values[operation]


def test_live_tui_source_reads_every_view_from_shared_operator_client() -> None:
    client = FakeOperatorClient({
        "status": {"controller": {"id": "edge-a", "connection_state": "connected"}, "binding": {"generation": 3}, "runs": [{"id": "run-a"}]},
        "runs": [{"id": "run-a"}],
        "instruments": [{"id": "instrument-a"}],
    })
    source = _operator_source(client)

    assert source({"query": "evolver.controllers"}, {}) == [{
        "id": "edge-a", "connection_state": "connected", "binding": {"generation": 3},
        "inventory": [{"id": "instrument-a"}],
    }]
    assert source({"query": "evolver.controller_snapshot"}, {}) == {
        "controller": {"id": "edge-a", "connection_state": "connected"},
        "binding": {"generation": 3}, "instruments": [{"id": "instrument-a"}],
        "central": "connected",
    }
    assert source({"query": "evolver.runs"}, {}) == [{"id": "run-a"}]
    assert source({"query": "evolver.instruments"}, {}) == [{"id": "instrument-a"}]
    assert source({"query": "evolver.maintenance"}, {})[0]["connection_state"] == "connected"
    assert client.operations == ["status", "instruments", "status", "instruments", "runs", "instruments", "status"]


def test_offline_source_is_separate_and_labels_central_offline(tmp_path: Path) -> None:
    with EdgeStore(tmp_path) as store:
        source = _offline_source(store)
        snapshot = source({"query": "evolver.controller_snapshot"}, {})

    assert snapshot["central"] == "offline"


def test_optional_tui_dependency_failure_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_import(_name: str):
        raise ModuleNotFoundError("No module named 'textual'")

    monkeypatch.setattr("importlib.import_module", missing_import)
    with pytest.raises(TUIUnavailableError, match="evoctl\[tui\]"):
        _load_ui_dependencies()
