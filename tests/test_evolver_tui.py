from __future__ import annotations

from pathlib import Path

from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_edge.tui import (
    LiveTuiSource,
    OfflineTuiSource,
    VIEW_NAMES,
    create_app,
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
    source = LiveTuiSource(client)

    assert source.read("controllers") == {
        "controller": {"id": "edge-a", "connection_state": "connected"},
        "binding": {"generation": 3},
    }
    assert source.read("runs") == {"runs": [{"id": "run-a"}]}
    assert source.read("instruments") == {"instruments": [{"id": "instrument-a"}]}
    assert client.operations == ["status", "status", "runs", "status", "instruments"]


def test_offline_source_is_separate_and_labels_central_offline(tmp_path: Path) -> None:
    with EdgeStore(tmp_path) as store:
        source = OfflineTuiSource(store)
        snapshot = source.read("recovery")

    assert snapshot["controller"]["id"]


def test_native_source_contract_uses_typed_view_names_without_query_composition() -> None:
    client = FakeOperatorClient({"status": {"controller": {"id": "edge-a"}, "binding": {}},
                                 "instruments": [], "runs": [], "doctor": {"checks": []},
                                 "capabilities": {"operations": {}}})
    source = LiveTuiSource(client)

    assert source.read("overview")["controller"]["id"] == "edge-a"
    assert source.read("controllers")["binding"] == {}
    assert set(source.read("recovery")) == {"controller", "binding"}
    assert all("query" not in operation for operation in client.operations)


def test_native_app_exposes_one_seven_view_factory_and_workflow_deep_link() -> None:
    class Source:
        def read(self, view: str):
            return {"view": view}

    assert VIEW_NAMES == ("overview", "controllers", "instruments", "runs",
                          "recovery", "maintenance", "workflows")
    app = create_app(source=Source(), initial_view="workflows")
    assert app.initial_view == "workflows"
    assert app.view_names == VIEW_NAMES


def test_offline_source_is_explicit_and_has_no_operator_client() -> None:
    class Store:
        def identity(self): return {"id": "edge-offline"}
        def binding(self): return {"generation": 2}
        def list_instruments(self): return []
        def list_runs(self): return []
        def meta(self, key): return key
        def recovery_manifest(self): return {"state": "offline"}

    source = OfflineTuiSource(Store())
    assert source.read("overview")["controller"]["id"] == "edge-offline"
    assert source.read("recovery")["manifest"] == {"state": "offline"}
