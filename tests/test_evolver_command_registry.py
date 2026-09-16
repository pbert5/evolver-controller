from __future__ import annotations

from pathlib import Path

import pytest

from meta_webui_application_backend.evolver_edge import cli
from meta_webui_application_backend.evolver_edge.cli import CommandMode, command_spec
from meta_webui_application_backend.evolver_edge.operator import OperatorUnavailable


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
        ("calibration.artifacts", CommandMode.LIVE),
        ("calibration.preflight", CommandMode.LIVE),
        ("hardware.lease.acquire", CommandMode.LIVE),
        ("hardware.lease.status", CommandMode.LIVE),
        ("hardware.lease.release", CommandMode.LIVE),
        ("hardware.layout", CommandMode.LIVE),
        ("hardware.provision-identity", CommandMode.LIVE),
        ("hardware.discover", CommandMode.MAINTENANCE),
        ("hardware.actuate", CommandMode.MAINTENANCE),
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
    result = cli.maintenance_disposition("hardware.discover")
    assert result == {"mode": "MAINTENANCE", "disposition": "delegated", "delegate": "hardware-service"}
