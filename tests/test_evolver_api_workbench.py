from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evolver_controller import cli
from evolver_controller.api_workbench import (
    ApiWorkbenchSource,
    build_request,
    create_app,
    format_response,
    format_request,
    operation_descriptors,
)
from evolver_controller.operator import OPERATION_METADATA


class FakeOperatorClient:
    def __init__(self, values: dict[str, object]):
        self.values = values
        self.calls: list[tuple[str, dict[str, object]]] = []

    def request(self, operation: str, params: dict[str, object] | None = None) -> object:
        request_params = dict(params or {})
        self.calls.append((operation, request_params))
        return self.values[operation]


def test_workbench_descriptors_are_controller_capabilities_not_a_second_list() -> None:
    capabilities = {"operations": OPERATION_METADATA, "transport": "unix"}

    descriptors = operation_descriptors(capabilities)

    assert tuple(item["name"] for item in descriptors) == tuple(OPERATION_METADATA)
    assert descriptors[0]["parameters"] == OPERATION_METADATA[descriptors[0]["name"]]["parameters"]


def test_build_request_applies_defaults_required_fields_and_bounds() -> None:
    descriptor = OPERATION_METADATA["instrument"]

    request = build_request(descriptor, {"action": "telemetry_list", "instrument_id": "plate-1"})

    assert request == {"action": "telemetry_list", "instrument_id": "plate-1", "limit": 100}
    with pytest.raises(ValueError, match="instrument_id is required"):
        build_request(descriptor, {"action": "show"})
    with pytest.raises(ValueError, match="limit must be at most 1000"):
        build_request(descriptor, {"action": "telemetry_list", "instrument_id": "plate-1", "limit": 1001})


def test_workbench_source_lists_shows_and_calls_through_operator_client() -> None:
    client = FakeOperatorClient({
        "capabilities": {"operations": OPERATION_METADATA, "transport": "unix"},
        "status": {"controller": {"id": "edge-a"}},
        "instrument": {"id": "plate-1"},
    })
    source = ApiWorkbenchSource(client)

    assert source.list()[0]["name"] == "binding"
    assert source.show("instrument")["name"] == "instrument"
    assert source.call("instrument", {"action": "show", "instrument_id": "plate-1"}) == {"id": "plate-1"}
    assert client.calls == [
        ("capabilities", {}),
        ("instrument", {"action": "show", "instrument_id": "plate-1"}),
    ]


def test_format_response_preserves_structured_and_readable_evidence() -> None:
    response = {"evidence_level": "protocol_verified", "observed": {"value": 42}, "secret_token": "hidden"}

    rendered = format_response(response)

    assert rendered["structured"]["secret_token"] == "<redacted>"
    assert '"evidence_level": "protocol_verified"' in rendered["raw"]
    assert rendered["readable"] == "evidence_level: protocol_verified\nobserved: value: 42\nsecret_token: <redacted>"
    assert '"lease_token": "<redacted>"' in format_request("hardware", {"lease_token": "secret"})


def test_api_cli_list_and_call_use_the_live_operator_transport(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def operator(operation: str, _path: str, *, params: dict[str, object]) -> object:
        calls.append((operation, params))
        if operation == "capabilities":
            return {"operations": OPERATION_METADATA, "transport": "unix"}
        return {"status": "observed", "operation": operation, "params": params}

    monkeypatch.setattr(cli, "operator_request", operator)
    assert cli.main(["api", "list"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["transport"] == "unix"
    assert {item["name"] for item in listing["operations"]} == set(OPERATION_METADATA)

    assert cli.main(["api", "call", "instrument", "--params", '{"action":"show","instrument_id":"plate-1"}']) == 0
    assert calls == [
        ("capabilities", {}),
        ("capabilities", {}),
        ("instrument", {"action": "show", "instrument_id": "plate-1"}),
    ]


def test_api_cli_requires_explicit_confirmation_for_controller_mutations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def operator(operation: str, _path: str, *, params: dict[str, object]) -> object:
        calls.append(operation)
        if operation == "capabilities":
            return {"operations": OPERATION_METADATA, "transport": "unix"}
        return {"operation": operation, "params": params}

    monkeypatch.setattr(cli, "operator_request", operator)
    assert cli.main(["api", "call", "run", "--params", '{"action":"show","run_id":"run-1"}']) == 64
    assert calls == ["capabilities"]
    assert "requires --confirm" in capsys.readouterr().out


def test_api_cli_parser_has_live_workbench_surface() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["api", "show", "status"])

    assert args.command == "api"
    assert args.api_command == "show"
    assert args.operation == "status"


def test_api_workbench_has_no_direct_hardware_or_store_dependency() -> None:
    module = Path(__file__).parents[1] / "src/evolver_controller/api_workbench.py"
    source = module.read_text(encoding="utf-8")

    assert "OperatorClient" in source
    assert "EdgeStore" not in source
    assert "serial" not in source.lower()
    assert "/dev/" not in source


def test_api_workbench_renders_typed_fields_from_selected_controller_operation() -> None:
    client = FakeOperatorClient({"capabilities": {"operations": OPERATION_METADATA, "transport": "unix"}})
    app = create_app(ApiWorkbenchSource(client))

    async def exercise() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()

            app.current = client.values["capabilities"]["operations"]["instrument"] | {"name": "instrument"}
            app._render_current()
            assert app.query_one("#operation-summary").renderable
            assert app.query_one("#param-action").value == ""
            assert app.query_one("#param-limit").value == ""

    asyncio.run(exercise())


def test_editing_a_request_field_clears_mutation_confirmation() -> None:
    client = FakeOperatorClient({"capabilities": {"operations": OPERATION_METADATA, "transport": "unix"}})
    app = create_app(ApiWorkbenchSource(client))

    class Event:
        class Input:
            id = "param-run_id"
        input = Input()
        value = "changed-run"

    app._mutation_confirmed = True
    app.on_input_changed(Event())

    assert app._mutation_confirmed is False
