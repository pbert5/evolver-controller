from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evolver_controller import cli
from evolver_controller.cli import CommandMode, command_spec
from evolver_controller.operator import OperatorUnavailable


@pytest.mark.parametrize(
    ("command", "mode"),
    [
        ("status", CommandMode.LIVE),
        ("runs", CommandMode.LIVE),
        ("run.show", CommandMode.LIVE),
        ("run.pause", CommandMode.LIVE),
        ("controllers", CommandMode.LIVE),
        ("instruments", CommandMode.LIVE),
        ("instrument.show", CommandMode.LIVE),
        ("instrument.status", CommandMode.LIVE),
        ("instrument.sensors.list", CommandMode.LIVE),
        ("instrument.sensors.read", CommandMode.LIVE),
        ("instrument.telemetry.latest", CommandMode.LIVE),
        ("instrument.telemetry.list", CommandMode.LIVE),
        ("capabilities", CommandMode.LIVE),
        ("action.list", CommandMode.LIVE),
        ("action.show", CommandMode.LIVE),
        ("action.availability", CommandMode.LIVE),
        ("action.preflight", CommandMode.LIVE),
        ("action.run", CommandMode.LIVE),
        ("calibration.artifacts", CommandMode.LIVE),
        ("calibration.preflight", CommandMode.LIVE),
        ("hardware.lease.acquire", CommandMode.LIVE),
        ("hardware.lease.status", CommandMode.LIVE),
        ("hardware.lease.release", CommandMode.LIVE),
        ("hardware.layout", CommandMode.LIVE),
        ("hardware.provision-identity", CommandMode.LIVE),
        ("hardware.discover", CommandMode.LIVE),
        ("hardware.protocol-test", CommandMode.LIVE),
        ("hardware.actuate", CommandMode.LIVE),
        ("update.apply", CommandMode.MAINTENANCE),
        ("validation", CommandMode.LOCAL),
        ("dispense", CommandMode.LOCAL),
    ],
)
def test_frozen_command_registry_classifies_operations(command: str, mode: CommandMode) -> None:
    assert command_spec(command).mode is mode


def test_unknown_commands_are_not_implicitly_local() -> None:
    with pytest.raises(cli.CommandRegistryError):
        command_spec("not-a-command")


def test_live_status_does_not_fallback_to_edge_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    def unavailable(operation: str, path: str, *, params: dict) -> object:
        calls.append((operation, params))
        raise OperatorUnavailable("socket down")

    class PoisonStore:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("LIVE status accessed EdgeStore")

    monkeypatch.setattr(cli, "operator_request", unavailable)
    monkeypatch.setattr(cli, "EdgeStore", PoisonStore)

    assert cli.main(["--state-root", str(tmp_path), "status"]) == 69
    assert calls == [("status", {})]


@pytest.mark.parametrize(
    "argv",
    [
        ["runs"], ["binding"], ["controllers"], ["instruments"],
        ["instrument", "show", "instrument-1"],
        ["calibration", "artifacts"], ["run", "show", "run-1"],
        ["hardware", "lease", "status"],
    ],
)
def test_every_frozen_live_cli_path_skips_edge_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]
) -> None:
    calls: list[str] = []

    def operator(operation: str, _path: str, *, params: dict) -> object:
        calls.append(operation)
        return [] if operation in {"runs", "instruments", "calibration"} else {"controller": {}, "binding": {}}

    class PoisonStore:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("LIVE command accessed EdgeStore")

    monkeypatch.setattr(cli, "operator_request", operator)
    monkeypatch.setattr(cli, "EdgeStore", PoisonStore)
    monkeypatch.setattr(cli, "_emit", lambda _value: None)

    assert cli.main(["--state-root", str(tmp_path), *argv]) == 0
    assert calls


def test_maintenance_update_does_not_fallback_to_edge_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class PoisonStore:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("MAINTENANCE update accessed EdgeStore")

    monkeypatch.setattr(cli, "EdgeStore", PoisonStore)
    monkeypatch.setattr(cli, "_emit", lambda _value: None)
    assert cli.main(["--state-root", str(tmp_path), "update", "status"]) == 0


def test_maintenance_operations_report_explicit_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "operator_request", lambda *_args, **_kwargs: pytest.fail("maintenance must not be implicit LIVE"))
    result = cli.maintenance_disposition("update.apply")
    assert result == {"mode": "MAINTENANCE", "disposition": "delegated", "delegate": "controller-service"}


def test_instrument_and_action_parser_namespaces_leave_update_and_lifecycle_space_intact() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["instrument", "list"]).instrument_command == "list"
    assert parser.parse_args(["instrument", "status", "instrument-1"]).instrument_command == "status"
    assert parser.parse_args(["instrument", "sensors", "read", "instrument-1", "temperature",
                              "--channel", "0"]).sensor == "temperature"
    assert parser.parse_args(["instrument", "telemetry", "latest", "instrument-1"]).telemetry_command == "latest"
    assert parser.parse_args(["action", "availability", "capture_measurement", "--target", "instrument-1"]).action_command == "availability"
    assert parser.parse_args(["update", "status"]).command == "update"
    assert parser.parse_args(["lifecycle-plan", "--operation", "update"]).command == "lifecycle-plan"


def test_cli_instrument_reads_use_typed_operator_contract(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, dict]] = []

    def operator(operation: str, _path: str, *, params: dict) -> object:
        calls.append((operation, params))
        return {"instrument_id": "instrument-1", "freshness": "fresh"}

    monkeypatch.setattr(cli, "operator_request", operator)
    assert cli.main(["instrument", "status", "instrument-1"]) == 0
    assert calls == [("instrument", {"action": "status", "instrument_id": "instrument-1"})]
    assert '"freshness": "fresh"' in capsys.readouterr().out


def test_cached_telemetry_is_explicitly_distinct_from_fresh_sensor_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def operator(operation: str, _path: str, *, params: dict) -> object:
        calls.append((operation, params))
        return []

    monkeypatch.setattr(cli, "operator_request", operator)
    assert cli.main(["instrument", "sensors", "read", "instrument-1", "od", "--channel", "0"]) == 0
    assert cli.main(["instrument", "telemetry", "latest", "instrument-1"]) == 0
    assert calls == [
        ("instrument", {"action": "sensor_read", "instrument_id": "instrument-1", "sensor": "od", "channel": 0}),
        ("instrument", {"action": "telemetry_latest", "instrument_id": "instrument-1"}),
    ]


def test_action_catalog_is_read_only_and_simulator_preflight_invokes_no_action(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["action", "list"]) == 0
    catalog = cli.json.loads(capsys.readouterr().out)
    assert {item["id"] for item in catalog["actions"]} == set(cli.TRUSTED_ACTIONS)

    assert cli.main(["action", "preflight", "set_temperature", "--target", "sim-1",
                     "--simulator", "--parameters", '{"target_temperature_c": 30}']) == 0
    preflight = cli.json.loads(capsys.readouterr().out)
    assert preflight["state"] == "preflighted"
    assert preflight["actions_invoked"] == 0


def test_controller_trusted_action_projection_matches_authoritative_schema() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "evolver-schemas" / "registry" / "trusted_actions.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    assert tuple(schema["actions"]) == cli.TRUSTED_ACTIONS


def test_runtime_and_upgrade_commands_are_maintenance_boundaries() -> None:
    expected = {
        "runtime.status", "runtime.up", "runtime.stop", "runtime.down",
        "runtime.restart", "runtime.logs", "runtime.upgrade", "upgrade",
    }
    assert all(cli.command_spec(command).mode is CommandMode.MAINTENANCE for command in expected)


def test_runtime_parser_and_short_aliases_remain_disjoint_from_update() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["runtime", "status"]).runtime_command == "status"
    assert parser.parse_args(["runtime", "logs"]).runtime_command == "logs"
    assert parser.parse_args(["upgrade"]).command == "upgrade"
    assert cli._compatibility_argv(["up"]) == ["runtime", "up"]
    assert cli._compatibility_argv(["down"]) == ["runtime", "down"]
    assert cli._compatibility_argv(["restart"]) == ["runtime", "restart"]
    assert cli._compatibility_argv(["logs"]) == ["runtime", "logs"]
    assert cli._compatibility_argv(["upgrade"]) == ["runtime", "upgrade"]
    assert cli._compatibility_argv(["update", "apply", "release-a"]) == ["update", "apply", "release-a"]
