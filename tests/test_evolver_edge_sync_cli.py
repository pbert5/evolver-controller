from __future__ import annotations

import json
import runpy
import sqlite3
import sys
from io import BytesIO
from urllib.error import HTTPError

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore, StaleGenerationError, SyncClient, canonical_digest
from meta_webui_application_backend.evolver_edge.cli import _compatibility_argv, main
from meta_webui_application_backend.evolver_edge import sync as sync_module
from meta_webui_application_backend.evolver_edge.bundle import calibration_artifact_digest
from meta_webui_application_backend.evolver_edge.hardware import (ProbeError, ProbeOutcome,
                                                                    ReadOnlyHardwareService)
from meta_webui_application_backend.evolver_edge.simulator import EvolverSimulator
from meta_webui_application_backend import evolver_controller


def test_service_module_entrypoint_starts_persistent_sync_loop(tmp_path, monkeypatch):
    """Executing the systemd-targeted module must invoke its service main."""
    import meta_webui_application_backend.evolver_edge.store as store_module
    import meta_webui_application_backend.evolver_edge.sync as sync_module

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
        runpy.run_module("meta_webui_application_backend.evolver_edge.service", run_name="__main__")

    assert raised.value.code == 0
    assert calls and calls[1]["interval"] == 3.0
    assert calls[0]["manual_executor"].sink.__class__.__name__ == "HardwareIPCDeviceCommandSink"
    assert calls[1]["inventory"]() == [{"id": "simulated"}]


def test_service_simulator_composes_local_non_actuating_manual_sink(tmp_path, monkeypatch):
    import meta_webui_application_backend.evolver_edge.service as service_module

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
        "__init__": lambda self, *_args: None, "start": lambda self: self, "shutdown": lambda self: None,
    }))
    service_module.main(["--state-root", str(tmp_path), "--simulator-instruments", "1"])
    assert calls[0]["manual_executor"].sink.__class__.__name__ == "SimulatorDeviceCommandSink"


def test_cli_module_entrypoint_invokes_main(tmp_path, monkeypatch, capsys):
    """Executing the Nix-targeted CLI module must invoke its main function."""
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), "status"])

    with pytest.raises(SystemExit) as raised:
        runpy.run_module("meta_webui_application_backend.evolver_edge.cli", run_name="__main__")

    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["controller"]["id"]


@pytest.mark.parametrize("command", [("status",), ("binding",), ("doctor",)])
def test_cli_inspection_redacts_nested_credentials(tmp_path, monkeypatch, capsys, command):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="sentinel-secret", generation=1)
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), *command])
    main()
    output = capsys.readouterr().out
    assert "sentinel-secret" not in output
    assert "<redacted>" in output or command == ("doctor",)


def test_cli_control_mapping_reuses_hardware_command_parser():
    assert _compatibility_argv(["control", "actuate", "pulse_pump"]) == [
        "hardware", "actuate", "pulse_pump"]


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
    monkeypatch.setattr(sys, "argv", ["evoctl", "--state-root", str(tmp_path), "calibration", "artifacts"])
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


def test_server_identity_replacement_is_not_silently_accepted(tmp_path):
    def transport(url, body, headers, timeout):
        if url.endswith("/enroll"): return 201, {"credential": "c", "binding": {"controller_generation": 1}, "webui_controller": {"id": "central-a"}}
        return 200, {"webui_controller": {"id": "central-b"}, "accepted_generation": 1, "commands": []}
    with EdgeStore(tmp_path) as edge:
        client = SyncClient(edge, transport=transport); client.enroll(server="https://same", token="t")
        with pytest.raises(StaleGenerationError): client.sync_once()
        assert edge.identity()["connection_state"] == "recovery_required"


def test_forced_adoption_increments_generation_and_fences_returning_central(tmp_path):
    """A replacement WebUI needs a purpose-bound credential and confirmation."""
    edge_root, old_root, new_root = tmp_path / "edge", tmp_path / "old", tmp_path / "new"
    _, old_token = evolver_controller.create_enrollment_token(server_url="https://old", state_root=old_root)
    _, recovery_token = evolver_controller.create_enrollment_token(server_url="https://new", purpose="forced_adoption", state_root=new_root)

    def old_transport(url, body, headers, timeout):
        if url.endswith("/enroll"):
            return evolver_controller.enroll(body, state_root=old_root)
        return evolver_controller.sync(body, credential=headers["authorization"].removeprefix("Bearer "), state_root=old_root)
    def new_transport(url, body, headers, timeout):
        assert url.startswith("https://new")
        return evolver_controller.enroll(body, state_root=new_root)

    with EdgeStore(edge_root) as edge:
        client = SyncClient(edge, transport=old_transport)
        original = client.enroll(server="https://old", token=old_token["enrollment_token"])
        assert edge.binding()["generation"] == 1
        with pytest.raises(StaleGenerationError):
            client.enroll(server="https://new", token=recovery_token["enrollment_token"])
        with pytest.raises(RuntimeError):
            SyncClient(edge, transport=new_transport).enroll(server="https://new", token=recovery_token["enrollment_token"], mode="forced_adoption")
        # Failed confirmation did not consume the one-time recovery secret.
        replacement = SyncClient(edge, transport=new_transport).enroll(server="https://new", token=recovery_token["enrollment_token"],
                                                                        mode="forced_adoption", operator_confirmed=True)
        assert replacement["binding_path"] == "forced_adoption"
        assert edge.binding()["generation"] == 2
        assert edge.binding()["webui_controller_id"] == replacement["webui_controller"]["id"]
        # The old credential/generation cannot write or deliver commands after recovery.
        evolver_controller.queue_command(edge.identity()["id"], {"command_id": "old-central-command", "controller_generation": 1,
                                                                   "command_kind": "pause_run"}, state_root=old_root)
        status, response = evolver_controller.sync({"controller_id": edge.identity()["id"], "controller_generation": 1},
                                                   credential=original["credential"], state_root=old_root)
        assert status == 200 and response["commands"][0]["controller_generation"] == 1
        with pytest.raises(StaleGenerationError):
            edge.execute_command({"command_id": "old", "controller_generation": 1}, lambda: {})


def test_same_webui_credential_repair_does_not_change_generation(tmp_path):
    central_root, edge_root = tmp_path / "central", tmp_path / "edge"
    _, first = evolver_controller.create_enrollment_token(server_url="https://central", state_root=central_root)
    _, repair = evolver_controller.create_enrollment_token(server_url="https://central", purpose="repair", state_root=central_root)
    def transport(url, body, headers, timeout):
        return evolver_controller.enroll(body, state_root=central_root)
    with EdgeStore(edge_root) as edge:
        client = SyncClient(edge, transport=transport)
        client.enroll(server="https://central", token=first["enrollment_token"])
        result = client.enroll(server="https://central", token=repair["enrollment_token"], mode="repair")
        assert result["binding_path"] == "repair"
        assert edge.binding()["generation"] == 1


def test_live_handoff_requires_old_central_release(tmp_path):
    old_root, new_root, edge_root = tmp_path / "old", tmp_path / "new", tmp_path / "edge"
    _, old_token = evolver_controller.create_enrollment_token(server_url="https://old", state_root=old_root)
    _, handoff_token = evolver_controller.create_enrollment_token(server_url="https://new", purpose="live_handoff", state_root=new_root)
    def transport(url, body, headers, timeout):
        root = old_root if url.startswith("https://old") else new_root
        if url.endswith("/enroll"):
            return evolver_controller.enroll(body, state_root=root)
        if url.endswith("/handoff/release"):
            return evolver_controller.release_handoff(body, credential=headers["authorization"].removeprefix("Bearer "), state_root=root)
        raise AssertionError(url)
    with EdgeStore(edge_root) as edge:
        client = SyncClient(edge, transport=transport)
        client.enroll(server="https://old", token=old_token["enrollment_token"])
        result = client.enroll(server="https://new", token=handoff_token["enrollment_token"], mode="live_handoff")
        assert result["binding_path"] == "live_handoff"
        assert edge.binding()["generation"] == 2
        assert evolver_controller.controllers(state_root=old_root)[1]["controllers"][0]["binding"]["status"] == "handoff_released"


def test_http_generation_conflict_is_parsed_not_misclassified_as_network_loss(tmp_path, monkeypatch):
    def response_error(*_, **__):
        raise HTTPError("https://same/api/evolver/controllers/sync", 409, "conflict", {},
                        BytesIO(b'{"kind":"GenerationConflict","error":"stale generation"}'))
    monkeypatch.setattr(sync_module, "urlopen", response_error)
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://same", credential="machine", generation=1)
        with pytest.raises(StaleGenerationError): SyncClient(edge).sync_once()
        assert edge.identity()["connection_state"] == "recovery_required"


def test_sync_loop_retries_exhausted_sqlite_lock(tmp_path, monkeypatch):
    with EdgeStore(tmp_path) as edge:
        client = SyncClient(edge)
        calls = 0
        sleeps: list[float] = []

        def sync_once(*, inventory=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("database is locked")

        client.sync_once = sync_once
        monkeypatch.setattr(sync_module.time, "sleep", sleeps.append)
        client.run_loop(interval=1, maximum_backoff=4, stop=lambda: calls >= 2)

        assert calls == 2
        assert sleeps == [2, 1]


def test_sync_loop_does_not_retry_non_lock_sqlite_errors(tmp_path, monkeypatch):
    with EdgeStore(tmp_path) as edge:
        client = SyncClient(edge)
        client.sync_once = lambda *, inventory=None: (_ for _ in ()).throw(sqlite3.OperationalError("no such table: binding"))
        monkeypatch.setattr(sync_module.time, "sleep", pytest.fail)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            client.run_loop(interval=1, stop=lambda: False)


def test_patch_command_cannot_override_its_run_target(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=1)
        edge.put_bundle(_bundle())
        edge.create_run(run_id="run-a", bundle_id="bundle", instrument_ids=["instrument"])
        edge.create_run(run_id="run-b", bundle_id="bundle", instrument_ids=["instrument"])
        acknowledgement = SyncClient(edge)._process_command({"command_id": "patch-a", "controller_generation": 1,
                                                              "command_kind": "apply_run_patch", "run_id": "run-a", "based_on_revision": 0,
                                                              "payload": {"run_id": "run-b", "change": {"parameter": 1}}})
        assert acknowledgement["disposition"] == "rejected_invalid"
        assert edge.run("run-a")["current_revision"] == edge.run("run-b")["current_revision"] == 0


def test_store_calibration_artifact_rejects_conflicting_command_digest(tmp_path):
    artifact = {"id": "artifact", "instrument_id": "instrument", "vial_position_id": "vial-1",
                "calibration_type": "temperature", "method": "linear", "method_version": "1",
                "coefficients": {"slope": 1.0}}
    artifact["artifact_digest"] = calibration_artifact_digest(artifact)
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=1)
        acknowledgement = SyncClient(edge)._process_command({
            "command_id": "store-artifact", "controller_generation": 1,
            "command_kind": "store_calibration_artifact", "artifact_id": artifact["id"],
            "artifact_digest": "sha256:conflicting", "payload": artifact,
        })
        assert acknowledgement["disposition"] == "rejected_invalid"
        assert edge.calibration_artifacts() == []


def test_hardware_rescan_uses_read_only_service_and_never_sends_actuator_frame(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=1)
        requests = []

        def hardware_request(payload, timeout):
            requests.append((payload, timeout))
            return {"source": "physical", "connection_state": "connected",
                    "device_identity": "MEV-001", "identity_state": "provisioned"}

        acknowledgement = SyncClient(edge, hardware_request=hardware_request)._process_command({
            "command_id": "rescan-1", "controller_generation": 1, "command_kind": "hardware_rescan",
        })

        assert acknowledgement["disposition"] == "completed"
        assert acknowledgement["hardware_observation"]["device_identity"] == "MEV-001"
        assert acknowledgement["physical_actuation"] is False
        assert requests == [({"operation": "discover"}, 10.0)]
        assert all(request[0].get("operation") not in {"safe_stop", "set_stir", "set_output", "pulse_pump", "pulse_heater"}
                   for request in requests)
        assert edge.command_acknowledgements()[-1]["command_id"] == "rescan-1"


def test_hardware_rescan_returns_and_records_typed_timeout(tmp_path):
    class TimeoutTransport:
        port = "/dev/ttyACM-fake"

        def open(self): pass
        def close(self): pass
        def exchange(self, payload):
            assert payload == "WHO_ARE_YOU_!"
            raise ProbeError(ProbeOutcome.TIMEOUT, "identity timeout")

    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=1)
        acknowledgement = SyncClient(
            edge, hardware_service=ReadOnlyHardwareService(edge, TimeoutTransport(), startup_attempts=1)
        )._process_command({"command_id": "rescan-timeout", "controller_generation": 1,
                            "command_kind": "hardware_rescan"})

        assert acknowledgement["disposition"] == "failed"
        assert acknowledgement["probe_outcome"] == ProbeOutcome.TIMEOUT.value
        assert acknowledgement["retryable"] is True
        assert edge.hardware_observation()["probe_outcome"] == ProbeOutcome.TIMEOUT.value
        assert edge.command_acknowledgements()[-1]["command_id"] == "rescan-timeout"


def test_hardware_rescan_ipc_timeout_is_typed_and_durable(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=1)

        def hardware_request(payload, timeout):
            assert payload == {"operation": "discover"}
            raise TimeoutError("hardware socket timed out")

        acknowledgement = SyncClient(edge, hardware_request=hardware_request)._process_command({
            "command_id": "ipc-timeout", "controller_generation": 1, "command_kind": "hardware_rescan",
        })

        assert acknowledgement["disposition"] == "failed"
        assert acknowledgement["probe_outcome"] == ProbeOutcome.TIMEOUT.value
        assert edge.hardware_observation()["probe_outcome"] == ProbeOutcome.TIMEOUT.value


def test_startup_reconciles_valid_fsynced_journal_and_spool_records(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.put_bundle(_bundle()); edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])
        event = {"id": "late-event", "run_id": "run", "sequence": 2, "event_type": "condition_reached", "occurred_at": "now", "revision": 0, "details": {}}
        telemetry = {"stream_id": "instrument/od", "sequence": 1, "payload": {"od": 0.4}, "captured_at": "now"}
        telemetry["digest"] = canonical_digest(telemetry)
        edge.event_journal_path.write_text(json.dumps(event) + "\n")
        edge.telemetry_spool_path.write_text(json.dumps(telemetry) + "\n")
    with EdgeStore(tmp_path) as restarted:
        assert restarted.events_after("run")[-1]["id"] == "late-event"
        assert restarted.telemetry_after("instrument/od")[0]["payload"] == {"od": 0.4}


def test_conflicting_append_only_record_requires_recovery(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.put_bundle(_bundle()); edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])
        conflict = {"id": "conflict", "run_id": "run", "sequence": 1, "event_type": "run_stopped",
                    "occurred_at": "now", "revision": 0, "details": {}}
        with edge.event_journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(conflict) + "\n")
    with EdgeStore(tmp_path) as restarted:
        assert restarted.identity()["connection_state"] == "recovery_required"


def test_cli_status_and_revision_safe_pause(tmp_path, capsys):
    with EdgeStore(tmp_path) as edge:
        edge.put_bundle(_bundle()); edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])
    assert main(["--state-root", str(tmp_path), "run", "pause", "run", "--based-on-revision", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "paused"
    assert main(["--state-root", str(tmp_path), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["runs"][0]["id"] == "run"


@pytest.mark.parametrize("alias, canonical", [
    (("server",), ("status",)),
    (("server", "status"), ("status",)),
    (("server", "binding"), ("binding",)),
    (("binding", "show"), ("binding",)),
    (("recovery", "show"), ("recovery",)),
    (("release", "status"), ("update", "status")),
    (("diagnostics",), ("doctor",)),
    (("read-only", "diagnostics"), ("doctor",)),
    (("local", "run", "list"), ("runs",)),
    (("local", "instrument", "list"), ("instruments",)),
    (("local", "instrument", "show"), ("instrument", "show")),
    (("local", "runs"), ("runs",)),
    (("run", "list"), ("runs",)),
])
def test_cli_hierarchy_aliases_preserve_existing_local_actions(alias, canonical):
    assert _compatibility_argv([*alias, "--state-root", "state"]) == [*canonical, "--state-root", "state"]


def test_cli_hierarchy_read_only_aliases_use_same_durable_views(tmp_path, capsys):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central",
                  credential="not-for-output", generation=3)

    for alias, canonical in ((("server",), ("status",)),
                             (("server", "binding"), ("binding",)),
                             (("binding", "show"), ("binding",)),
                             (("recovery", "show"), ("recovery",)),
                             (("release", "status"), ("update", "status")),
                             (("diagnostics",), ("doctor",)),
                             (("local", "run", "list"), ("runs",))):
        assert main(["--state-root", str(tmp_path), *alias]) == 0
        alias_output = capsys.readouterr().out
        assert main(["--state-root", str(tmp_path), *canonical]) == 0
        canonical_output = capsys.readouterr().out
        # Recovery reports carry a fresh envelope id/timestamp on every read;
        # compare the durable view rather than volatile report metadata.
        alias_value, canonical_value = json.loads(alias_output), json.loads(canonical_output)
        for value in (alias_value, canonical_value):
            if isinstance(value, dict):
                value.pop("id", None)
                value.pop("generated_at", None)
        assert alias_value == canonical_value
        assert "not-for-output" not in alias_output


def test_local_run_alias_keeps_revision_fenced_mutation_handler(tmp_path, capsys):
    with EdgeStore(tmp_path) as edge:
        edge.put_bundle(_bundle())
        edge.create_run(run_id="run", bundle_id="bundle", instrument_ids=["instrument"])

    assert main(["--state-root", str(tmp_path), "local", "run", "pause", "run",
                 "--based-on-revision", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "paused"


def test_cli_simulator_start_reports_stable_durable_inventory(tmp_path, capsys):
    assert main(["--state-root", str(tmp_path), "simulator", "start", "--instruments", "2"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert len(first["instruments"]) == 2

    assert main(["--state-root", str(tmp_path), "simulator", "start", "--instruments", "2"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["controller"]["id"] == first["controller"]["id"]
    assert [instrument["id"] for instrument in second["instruments"]] == [instrument["id"] for instrument in first["instruments"]]

    assert main(["--state-root", str(tmp_path), "instruments"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert {instrument["id"] for instrument in listed} == {instrument["id"] for instrument in first["instruments"]}
    assert main(["--state-root", str(tmp_path), "instrument", "show", first["instruments"][0]["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["capabilities"]["od_read"]["verification"] == "protocol_verified"


def test_cli_simulator_create_run_and_tick_are_durable(tmp_path, capsys):
    plan = json.dumps({"initial_state": "growth", "states": {"growth": {"terminal": True}}})
    assert main(["--state-root", str(tmp_path), "simulator", "create-run", "run-a", "--bundle-id", "bundle-a",
                 "--execution-plan", plan]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["state"] == "running"
    assert main(["--state-root", str(tmp_path), "simulator", "tick", "run-a", "--ticks", "3"]) == 0
    ticked = json.loads(capsys.readouterr().out)
    streams: dict[str, list[int]] = {}
    for record in ticked["records"]:
        streams.setdefault(record["stream_id"], []).append(record["sequence"])
    assert streams and all(sequences == [1, 2, 3] for sequences in streams.values())
    with EdgeStore(tmp_path) as store:
        assert store.run("run-a")["current_revision"] == 0
        assert all([record["sequence"] for record in store.telemetry_after(stream)] == [1, 2, 3]
                   for stream in store.telemetry_streams())


def test_same_central_restart_reconciles_an_orphaned_simulated_run(tmp_path):
    """Exercise enrollment, central loss, edge restart, and reconciliation together."""
    central_root, edge_root = tmp_path / "central", tmp_path / "edge"
    _, token = evolver_controller.create_enrollment_token(server_url="http://central", state_root=central_root)

    def central_transport(url, body, headers, timeout):
        del timeout
        if url.endswith("/enroll"):
            return evolver_controller.enroll(body, state_root=central_root)
        return evolver_controller.sync(
            body,
            credential=headers.get("authorization", "").removeprefix("Bearer "),
            state_root=central_root,
        )

    bundle = _bundle()
    bundle["execution_plan"] = {
        "content": {"initial_state": "growth", "states": {"growth": {}}},
        "media_type": "application/json",
    }
    bundle["digest"] = canonical_digest({key: value for key, value in bundle.items() if key != "digest"})

    with EdgeStore(edge_root) as edge:
        simulator = EvolverSimulator(edge, vials_per_instrument=1)
        edge.put_bundle(bundle)
        client = SyncClient(edge, transport=central_transport)
        client.enroll(server="http://central", token=token["enrollment_token"])
        simulator.start_run(run_id="run", bundle_id="bundle")
        simulator.tick_run("run")
        client.sync_once(inventory=simulator.inventory())
        central_identity = evolver_controller.controllers(state_root=central_root)[1]["webui_controller"]

        with pytest.raises(TimeoutError):
            SyncClient(edge, transport=lambda *_: (_ for _ in ()).throw(TimeoutError("offline"))).sync_once()
        assert edge.identity()["connection_state"] == "orphaned"
        assert simulator.tick_run("run")

    # Re-opening both durable stores models independent edge and WebUI process restarts.
    with EdgeStore(edge_root) as restarted:
        simulator = EvolverSimulator(restarted, vials_per_instrument=1)
        assert simulator.tick_run("run")
        SyncClient(restarted, transport=central_transport).sync_once(inventory=simulator.inventory())
        assert restarted.identity()["connection_state"] == "connected"
        assert restarted.run("run")["id"] == "run"
        status, controllers = evolver_controller.controllers(state_root=central_root)
        assert status == 200
        assert controllers["webui_controller"] == central_identity
        assert controllers["controllers"][0]["recovery_summary"]["runs"][0]["id"] == "run"


def test_wait_once_processes_command_and_persists_delivery_cursor(tmp_path):
    calls: list[tuple[str, dict, dict, float]] = []
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="central", server_url="https://central", credential="machine", generation=1)

        def transport(url, body, headers, timeout):
            calls.append((url, body, headers, timeout))
            return 200, {"command": {"command_id": "renew-1", "controller_generation": 1,
                                      "command_kind": "renew_manual_lease", "lease_token": "token",
                                      "lease_holder": "alice", "lease_expires_at": "2999-01-01T00:00:00+00:00",
                                      "delivery_cursor": 4}, "cursor": 4, "timed_out": False}

        result = SyncClient(edge, transport=transport).wait_once(wait_seconds=1)
        assert result.commands_processed == 1
        assert edge.cursor("central:command") == "4"
        assert edge.meta("control_lease")["owner"] == "alice"
        assert calls[0][0].endswith("/commands/wait") and calls[0][1]["last_cursor"] == 0
