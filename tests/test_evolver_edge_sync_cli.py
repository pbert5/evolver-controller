from __future__ import annotations

import json
import runpy
import sqlite3
import sys
from io import BytesIO
from urllib.error import HTTPError

import pytest

from evolver_controller import EdgeStore, StaleGenerationError, SyncClient, canonical_digest
from evolver_controller.cli import _compatibility_argv, main
from evolver_controller import sync as sync_module
from evolver_controller.bundle import calibration_artifact_digest
from evolver_controller.hardware_protocol import ProbeError, ProbeOutcome
from evolver_controller.simulator import EvolverSimulator


def test_service_module_entrypoint_starts_persistent_sync_loop(tmp_path, monkeypatch):
    """The Compose service entrypoint invokes the persistent sync loop."""
    import evolver_controller.store as store_module
    import evolver_controller.sync as sync_module

    calls: list[dict[str, object]] = []

    class FakeStore:
        def __init__(self, root):
            self.root = root
            self.list_instruments = lambda: [{"id": "simulated"}]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class FakeSyncClient:
        def __init__(self, store, **kwargs):
            self.store = store
            self.init_kwargs = kwargs
            calls.append(kwargs)

        def run_loop(self, **kwargs):
            calls.append({**self.init_kwargs, **kwargs})

    monkeypatch.setattr(store_module, "EdgeStore", FakeStore)
    monkeypatch.setattr(sync_module, "SyncClient", FakeSyncClient)
    monkeypatch.setenv("EVOLVER_OPERATOR_SOCKET", str(tmp_path / "operator.sock"))
    monkeypatch.setattr(sys, "argv", ["evolver-edge-service", "--state-root", str(tmp_path), "--interval", "3"])

    with pytest.raises(SystemExit) as raised:
        runpy.run_module("evolver_controller.service", run_name="__main__")

    assert raised.value.code == 0
    assert calls and calls[1]["interval"] == 3.0
    assert calls[0]["manual_executor"].sink.__class__.__name__ == "HardwareIPCDeviceCommandSink"
    assert calls[1]["inventory"]() == [{"id": "simulated"}]


def test_service_simulator_composes_local_non_actuating_manual_sink(tmp_path, monkeypatch):
    import evolver_controller.service as service_module

    calls = []

    class FakeStore:
        def __init__(self, root): self.list_instruments = lambda: [{"id": "simulated"}]
        def identity(self): return {"id": "controller"}
        def register_instruments(self, _instruments): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False

    class FakeSyncClient:
        def __init__(self, store, **kwargs): calls.append(kwargs)
        def run_loop(self, **kwargs): pass

    monkeypatch.setattr(service_module, "EdgeStore", FakeStore)
    monkeypatch.setattr(service_module, "SyncClient", FakeSyncClient)
    monkeypatch.setattr(service_module, "OperatorServer", type("Operator", (), {
        "__init__": lambda self, *_args, **_kwargs: None, "start": lambda self: self, "shutdown": lambda self: None,
    }))
    service_module.main(["--state-root", str(tmp_path), "--simulator-instruments", "1"])
    assert calls[0]["manual_executor"].sink.__class__.__name__ == "SimulatorDeviceCommandSink"


def test_cli_module_entrypoint_invokes_main(tmp_path, monkeypatch, capsys):
    """Executing the CLI module invokes its main function."""
    with EdgeStore(tmp_path):
        pass
    monkeypatch.setattr(sys, "argv", ["evoctl", "--offline", "--state-root", str(tmp_path), "status"])

    with pytest.raises(SystemExit) as raised:
        runpy.run_module("evolver_controller.cli", run_name="__main__")

    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["controller"]["id"]


@pytest.mark.parametrize("command", [("status",), ("binding",), ("doctor",)])
def test_cli_inspection_redacts_nested_credentials(tmp_path, monkeypatch, capsys, command):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="sentinel-secret", generation=1)
    monkeypatch.setattr(sys, "argv", ["evoctl", "--offline", "--state-root", str(tmp_path), *command])
    main()
    output = capsys.readouterr().out
    assert "sentinel-secret" not in output
    assert "<redacted>" in output or command == ("doctor",)


@pytest.mark.parametrize("command, operation", [("status", "status"), ("binding", "binding"),
                                                  ("instruments", "instruments"), ("runs", "runs")])
def test_cli_live_read_models_route_through_operator_without_opening_store(
    tmp_path, monkeypatch, capsys, command, operation
):
    import evolver_controller.cli as cli_module

    calls = []
    monkeypatch.setattr(cli_module, "operator_request", lambda name, path, params=None: calls.append(
        (name, path, params)) or {"operation": operation})
    monkeypatch.setattr(cli_module, "EdgeStore", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live CLI opened EdgeStore")))
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), command])

    assert cli_module.main() == 0
    assert calls == [(operation, cli_module.DEFAULT_OPERATOR_SOCKET if False else calls[0][1], {})]
    assert json.loads(capsys.readouterr().out)["operation"] == operation


def test_cli_live_hardware_dispatches_to_operator_client(tmp_path, monkeypatch, capsys):
    import evolver_controller.cli as cli_module
    calls = []
    monkeypatch.setattr(cli_module, "operator_request", lambda name, path, params=None: calls.append(
        (name, params)) or {"hardware": "ok"})
    monkeypatch.setattr(cli_module, "EdgeStore", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live CLI opened EdgeStore")))
    monkeypatch.setattr(sys, "argv", ["evoctl", "hardware", "discover"])
    assert cli_module.main() == 0
    assert calls[0][0] == "hardware"
    assert calls[0][1] == {"operation": "discover"}


def test_cli_live_hardware_actuation_sends_typed_fenced_request(tmp_path, monkeypatch, capsys):
    import evolver_controller.cli as cli_module
    calls = []
    monkeypatch.setattr(cli_module, "operator_request", lambda name, path, params=None: calls.append(
        (name, params)) or {"request_accepted": True})
    monkeypatch.setattr(cli_module, "EdgeStore", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("live CLI opened EdgeStore")))
    monkeypatch.setattr(sys, "argv", ["evoctl", "hardware", "actuate", "set_stir",
                                        "--target", "MEV-1", "--channel", "0", "--duration-ms", "100",
                                        "--level", "5", "--physical", "--operator", "alice",
                                        "--lease-token", "lease-7", "--controller-generation", "7"])

    assert cli_module.main() == 0
    assert calls == [("hardware", {
        "operation": "hardware_command", "operation_name": "set_stir", "target_identity": "MEV-1",
        "parameters": {"channel": 0, "duration_ms": 100, "level": 5},
        "physical": True, "operator": "alice", "lease_token": "lease-7",
        "lease_owner": "alice", "controller_generation": 7,
    })]
    assert json.loads(capsys.readouterr().out)["request_accepted"] is True


def test_cli_raw_temperature_hold_reads_current_local_generation_and_forwards_lease(
    monkeypatch, capsys
):
    import evolver_controller.cli as cli_module
    calls = []

    def operator(name, _path, params=None):
        calls.append((name, params))
        if name == "hardware_lease":
            return {"status": "active", "owner": "alice", "generation": 12}
        return {"request_accepted": True}

    monkeypatch.setattr(cli_module, "operator_request", operator)
    monkeypatch.setattr(sys, "argv", ["evoctl", "hardware", "temperature-calibration-hold-raw", "start",
                                        "--target", "MEV-1", "--vial-position-id", "vial-1", "--channel", "0", "--raw-target-adc", "34416",
                                        "--session-id", "hold-1", "--lease-token", "lease-12",
                                        "--physical", "--operator", "alice"])

    assert cli_module.main() == 0
    assert calls == [
        ("hardware_lease", {"action": "status", "operator": "alice"}),
        ("hardware", {"operation": "temperature_calibration_hold_raw", "action": "start",
                       "target_identity": "MEV-1", "vial_position_id": "vial-1", "channel": 0, "session_id": "hold-1",
                       "physical": True, "operator": "alice", "lease_owner": "alice",
                       "lease_token": "lease-12", "controller_generation": 12,
                       "raw_target_adc": 34416}),
    ]
    assert json.loads(capsys.readouterr().out)["request_accepted"] is True


def test_cli_raw_temperature_hold_fails_closed_without_current_owned_lease(monkeypatch, capsys):
    import evolver_controller.cli as cli_module
    calls = []
    monkeypatch.setattr(cli_module, "operator_request", lambda name, _path, params=None:
                        calls.append((name, params)) or {"status": "released", "owner": "alice", "generation": 12})
    monkeypatch.setattr(sys, "argv", ["evoctl", "hardware", "temperature-calibration-hold-raw", "disable",
                                        "--target", "MEV-1", "--vial-position-id", "vial-1", "--channel", "0", "--session-id", "hold-1",
                                        "--lease-token", "lease-12", "--physical", "--operator", "alice"])
    assert cli_module.main() == 64
    assert calls and calls[0][0] == "hardware_lease"
    assert len(calls) == 1
    assert "current local commissioning lease" in capsys.readouterr().err


def test_cli_safe_stop_returns_nonzero_for_partial_unverified_result(monkeypatch, capsys):
    import evolver_controller.cli as cli_module
    monkeypatch.setattr(cli_module, "operator_request", lambda *_args, **_kwargs: {
        "request_accepted": False, "verification": "unverified", "results": [{"error": "offline"}]})
    monkeypatch.setattr(sys, "argv", ["evoctl", "hardware", "safe-stop",
                                        "--physical", "--operator", "alice"])

    assert cli_module.main() == 2
    assert json.loads(capsys.readouterr().out)["verification"] == "unverified"


def test_cli_live_unavailable_is_explicit_and_offline_missing_state_is_actionable(tmp_path, monkeypatch, capsys):
    import evolver_controller.cli as cli_module
    monkeypatch.setattr(cli_module, "operator_request", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        cli_module.OperatorUnavailable("operator service unavailable: refused")))
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), "status"])
    assert cli_module.main() == 69
    assert "operator service unavailable" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["evoctl", "--offline", "--state-root", str(tmp_path / "missing"), "status"])
    assert cli_module.main() == 66
    assert "--offline" in capsys.readouterr().err


def test_cli_control_mapping_reuses_hardware_command_parser():
    assert _compatibility_argv(["control", "actuate", "pulse_pump"]) == [
        "hardware", "actuate", "pulse_pump"]


def test_runtime_lifecycle_is_a_fixed_host_adapter_delegation(monkeypatch, capsys):
    import evolver_controller.cli as cli_module

    monkeypatch.setattr(cli_module, "operator_request", lambda *_args, **_kwargs: pytest.fail(
        "runtime lifecycle must not use the controller operator socket"))
    monkeypatch.setattr(cli_module, "EdgeStore", lambda *_args, **_kwargs: pytest.fail(
        "runtime lifecycle must not open the controller store"))

    assert cli_module.main(["up"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "operation": "runtime.up", "target": "edge",
        "services": ["evolver-controller", "evolver-hardware"],
        "disposition": "delegated", "delegate": "host-runtime-adapter", "executed": False,
    }


def test_upgrade_requires_authoritative_recommended_release(monkeypatch, capsys, tmp_path):
    import evolver_controller.cli as cli_module

    monkeypatch.setattr(cli_module, "_recommended_release", lambda _root: None)
    assert cli_module.main(["--state-root", str(tmp_path), "upgrade"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "upgrade"
    assert result["final_state"] == "unavailable"
    assert "recommended release" in result["error"]


def test_upgrade_defers_for_active_runs_and_reports_old_release(monkeypatch, capsys, tmp_path):
    import evolver_controller.cli as cli_module

    monkeypatch.setattr(cli_module, "_recommended_release", lambda _root: "release-b")
    with cli_module.EdgeStore(tmp_path) as store:
        store.set_meta("controller_software_release", "release-a")
        bundle = {"id": "bundle", "purpose": "research", "execution_mode": "declarative_state_machine"}
        bundle["digest"] = cli_module.canonical_digest(bundle)
        store.put_bundle(bundle)
        store.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"], state="running")

    assert cli_module.main(["--state-root", str(tmp_path), "upgrade"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["requested_release"] == "release-b"
    assert result["old_release"] == "release-a"
    assert result["final_state"] == "deferred"
    assert result["reason"] == "active runs present"


def test_upgrade_failure_cannot_report_success(monkeypatch, capsys, tmp_path):
    import evolver_controller.cli as cli_module

    monkeypatch.setattr(cli_module, "_recommended_release", lambda _root: "release-b")
    monkeypatch.setattr(cli_module, "_update_backend", lambda: type(
        "Backend", (), {"name": "compose", "install": lambda _self, _release: (_ for _ in ()).throw(
            RuntimeError("activation health check failed"))})())

    assert cli_module.main(["--state-root", str(tmp_path), "upgrade"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["final_state"] == "failed"
    assert "activation health check failed" in result["error"]


def test_cli_safe_stop_is_first_class_and_has_no_lease_or_target():
    from evolver_controller.cli import _live_request, build_parser

    args = build_parser().parse_args(["hardware", "safe-stop", "--physical", "--operator", "alice"])
    assert _live_request(args) == ("hardware", {"operation": "safe_stop", "physical": True,
                                                  "operator": "alice"})


def test_cli_validation_delegates_to_bounded_domain(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), "validation",
                                        "pulse_pump", "--parameters", '{"channel": 2, "duration_ms": 40}'])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["parameters"] == {
        "channel": 2, "direction": "forward", "duration_ms": 40}


def test_cli_dispense_is_a_calibrated_plan_only(tmp_path, monkeypatch, capsys):
    artifact = tmp_path / "pump.json"
    artifact.write_text(json.dumps({"id": "pump", "calibration_type": "pump_flow_rate",
                                    "assessment": {"status": "valid"},
                                    "coefficients": {"slope": 2, "intercept": 0}}))
    monkeypatch.setattr(sys, "argv", ["evoctl", "dispense", "--artifact", str(artifact),
                                        "--volume-ul", "80", "--channel", "1"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "pulse_pump"
    assert result["parameters"]["duration_ms"] == 40


def test_cli_calibration_artifacts_reads_edge_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evoctl", "--offline", "--state-root", str(tmp_path), "calibration", "artifacts"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out) == []


def _bundle() -> dict[str, object]:
    value: dict[str, object] = {"id": "bundle", "name": "bundle", "schema_version": "1", "execution_mode": "declarative_state_machine",
                                "source": {}, "resolved_definition": {}, "execution_plan": {}, "runtime_parameters": [], "source_metadata": []}
    value["digest"] = canonical_digest(value)
    return value


def test_enroll_sync_command_and_orphan_transition_are_transport_independent(tmp_path):
    calls: list[tuple[str, dict, dict]] = []
    def transport(url, body, headers, timeout):
        calls.append((url, body, headers))
        if url.endswith("/enroll"):
            return 201, {"credential": "machine", "binding": {"controller_generation": 1}, "webui_controller": {"id": "central-a"}}
        return 200, {"webui_controller": {"id": "central-a"}, "accepted_generation": 1, "commands": [{"command_id": "pause", "controller_generation": 1, "command_kind": "pause_run", "run_id": "run", "based_on_revision": 0}], "event_cursors": {"run": 1}}
    with EdgeStore(tmp_path) as edge:
        client = SyncClient(edge, transport=transport)
        client.enroll(server="https://webui", token="one-use")
        edge.put_bundle(_bundle()); edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])
        result = client.sync_once(inventory=[{"id": "instrument"}])
        assert result.commands_processed == 1
        assert edge.identity()["connection_state"] == "connected"
        assert edge.run("run")["state"] == "paused"
        assert edge.cursor("central:event:run") == "1"
        assert calls[-1][2]["authorization"] == "Bearer machine"

    def offline(*_): raise TimeoutError("offline")
    with EdgeStore(tmp_path) as edge:
        with pytest.raises(TimeoutError): SyncClient(edge, transport=offline).sync_once()
        assert edge.identity()["connection_state"] == "orphaned"


def test_sync_batch_projects_edge_facts_into_stable_history_batches(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.put_bundle(_bundle())
        edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])
        edge.append_event(run_id="run", event_type="run_started", revision=0)
        events = edge.events_after("run")
        telemetry = edge.spool_telemetry(stream_id="instrument/od", sequence=1,
                                         payload={"od": 0.2}, captured_at="2026-09-01T00:00:00Z")
        edge.bind(webui_controller_id="central", server_url="https://central",
                  credential="credential", generation=3)
        history = SyncClient(edge)._batch()["history_batches"]

    assert history[0] == {"fact_type": "event", "stream_id": "run", "records": [
        {"fact_id": event["id"], "run_id": "run", "sequence": event["sequence"],
         "occurred_at": event["occurred_at"], "payload": event} for event in events
    ]}
    assert history[1] == {"fact_type": "telemetry", "stream_id": "instrument/od", "records": [{
        "fact_id": "telemetry:instrument/od:1", "stream_id": "instrument/od", "sequence": 1,
        "captured_at": telemetry["captured_at"], "payload": {"od": 0.2},
    }]}


def test_server_identity_replacement_is_not_silently_accepted(tmp_path):
    def transport(url, body, headers, timeout):
        if url.endswith("/enroll"): return 201, {"credential": "c", "binding": {"controller_generation": 1}, "webui_controller": {"id": "central-a"}}
        return 200, {"webui_controller": {"id": "central-b"}, "accepted_generation": 1, "commands": []}
    with EdgeStore(tmp_path) as edge:
        client = SyncClient(edge, transport=transport); client.enroll(server="https://same", token="t")
        with pytest.raises(StaleGenerationError): client.sync_once()
        assert edge.identity()["connection_state"] == "recovery_required"
