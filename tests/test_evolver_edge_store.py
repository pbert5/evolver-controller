from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge import (
    CalibrationPreflightError,
    CommandInProgressError,
    EdgeStore,
    ImmutableBundleError,
    StaleGenerationError,
    StaleRevisionError,
    calibration_artifact_digest,
    canonical_digest,
)
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError
from meta_webui_application_backend.evolver_edge.identity import (
    canonical_samd21_usb_serial, firmware_alias_for_usb_serial,
    samd21_hardware_fingerprint, validate_usb_match,
)


def test_samd21_usb_identity_alias_and_fingerprint_are_deterministic():
    serial = "1B420A95503057334D2E3120FF13220E"
    assert canonical_samd21_usb_serial(serial.lower()) == serial
    assert firmware_alias_for_usb_serial(serial) == "MEV-8cd2e2eb0b6728080d14dd97ce0"
    fingerprint = samd21_hardware_fingerprint(vid=0x1B4F, pid=0x8D21, usb_serial=serial)
    assert fingerprint["usb_serial"] == serial
    assert fingerprint["serial_sha256"] == "8cd2e2eb0b6728080d14dd97ce07be3940c54514b7bca738dbae2b6c02a35194"
    assert validate_usb_match({"vid": 0x1B4F, "pid": 0x8D21, "serial_number": serial},
                              expected_vid=0x1B4F, expected_pid=0x8D21, expected_serial=serial) == fingerprint
    with pytest.raises(ValueError):
        validate_usb_match({"vid": 0x1B4F, "pid": 0x8D21}, expected_vid=0x1B4F,
                            expected_pid=0x8D21, expected_serial=serial)
    with pytest.raises(ValueError):
        validate_usb_match({"vid": 0x1B4F, "pid": 0x8D21, "serial_number": "0" * 32},
                            expected_vid=0x1B4F, expected_pid=0x8D21, expected_serial=serial)


def test_quarantine_command_is_db_only_and_rejects_repeat(tmp_path):
    with EdgeStore(tmp_path) as edge:
        with edge._transaction() as cursor:
            cursor.execute("INSERT INTO commands(command_id,generation,status,created_at) VALUES(?,?,?,?)",
                           ("legacy-provision", 1, "in_progress", "now"))
        result = edge.quarantine_command(
            "legacy-provision", operator="operator-a",
            reason_kind="interrupted_provisioning_identity_mismatch",
            requested_identity={"device_id": "MEV-20260824-01", "owner_id": "bench-evolver-01"},
            observed_identity={"device_id": "MEV-8cd2e2eb0b6728080d14dd97ce0", "owner_id": "controller-51731726"},
            hardware_fingerprint={"scheme": "samd21-usb-serial-sha256-v1"})
        assert result["disposition"] == "quarantined"
        assert result["protocol_ack_observed"] is False
        assert result["physical_retry_performed"] is False
        assert edge.inspect_command("legacy-provision")["status"] == "quarantined"
        with pytest.raises(EdgeStoreError, match="already terminal"):
            edge.quarantine_command("legacy-provision", operator="operator-a", reason_kind="repeat")


def bundle(bundle_id: str = "bundle-a") -> dict[str, object]:
    body: dict[str, object] = {
        "id": bundle_id, "name": "durable bundle", "purpose": "test_fixture", "schema_version": "1",
        "execution_mode": "declarative_state_machine",
        "source": {"experiment_id": "definition-a", "dataset_revision": "1", "created_at": "2026-01-01T00:00:00Z"},
        "resolved_definition": {"content": {"name": "source"}, "media_type": "application/json"},
        "execution_plan": {"content": {"states": {"growth": {}}}, "media_type": "application/json"},
        "runtime_parameters": [], "source_metadata": [],
    }
    body["digest"] = canonical_digest(body)
    return body


def calibration_artifact(artifact_id: str = "calibration-a") -> dict[str, object]:
    artifact: dict[str, object] = {
        "id": artifact_id, "instrument_id": "instrument-a", "vial_position_id": "vial-a",
        "calibration_type": "temperature", "method": "temperature_linear_v1", "method_version": "1",
        "coefficients": {"slope": 1.0, "intercept": 0.0}, "fit_diagnostics": {"rmse": 0.0},
        "performed_at": "2026-01-01T00:00:00Z", "performed_by": "operator",
    }
    artifact["artifact_digest"] = calibration_artifact_digest(artifact)
    return artifact


def calibration_reference(artifact: dict[str, object]) -> dict[str, object]:
    return {"artifact_id": artifact["id"], "artifact_digest": artifact["artifact_digest"],
            "instrument_id": artifact["instrument_id"], "vial_position_id": artifact["vial_position_id"],
            "calibration_type": artifact["calibration_type"], "method": artifact["method"],
            "method_version": artifact["method_version"]}


def test_restart_retains_identity_binding_runs_journal_dedupe_telemetry_and_cursors(tmp_path):
    with EdgeStore(tmp_path) as edge:
        identity = edge.identity()
        edge.bind(webui_controller_id="webui-a", server_url="https://server.example", credential="machine-secret")
        edge.put_bundle(bundle())
        edge.create_run(run_id="run-a", bundle_id="bundle-a", instrument_ids=["instrument-a"])
        revision = edge.apply_patch({"run_id": "run-a", "based_on_revision": 0, "patch_kind": "parameter_change", "change": {"runtime_parameters": {"temperature": 37}}})
        edge.append_event(run_id="run-a", event_type="run_started", revision=revision["revision"])
        edge.spool_telemetry(stream_id="instrument-a/od", sequence=1, payload={"od": 0.22})
        edge.set_cursor("events", 2)
        calls = []
        assert edge.execute_command({"command_id": "cmd-a", "controller_generation": 1}, lambda: calls.append(1) or {"disposition": "completed"}) == {"disposition": "completed"}
        assert edge.execute_command({"command_id": "cmd-a", "controller_generation": 1}, lambda: calls.append(2) or {}) == {"disposition": "completed"}
        assert calls == [1]

    with EdgeStore(tmp_path) as restarted:
        assert restarted.identity() == identity
        assert restarted.binding()["webui_controller_id"] == "webui-a"
        assert restarted.run("run-a")["current_revision"] == 1
        assert restarted.revision("run-a")["effective_state"]["runtime_parameters"]["temperature"] == 37
        assert len(restarted.events_after("run-a")) == 2
        assert restarted.telemetry_after("instrument-a/od")[0]["payload"] == {"od": 0.22}
        assert restarted.cursor("events") == "2"
        manifest = restarted.recovery_manifest()
        assert [run["id"] for run in manifest["runs"]] == ["run-a"]
        assert manifest["bundles"][0]["digest"] == bundle()["digest"]
        assert manifest["run_revisions"][0]["revision"] == 1
        assert manifest["run_action_executions"] == []
        assert manifest["controller"]["binding"]["generation"] == 1
        assert "credential" not in manifest["controller"]["binding"]
        assert "runtime" in manifest


def test_bundle_immutable_revision_fenced_and_multiple_runs_are_independent(tmp_path):
    with EdgeStore(tmp_path) as edge:
        first = bundle(); edge.put_bundle(first); edge.put_bundle(first)
        changed = dict(first); changed["execution_plan"] = {"content": {"states": {"different": {}}}, "media_type": "application/json"}
        with pytest.raises(ImmutableBundleError): edge.put_bundle(changed)
        edge.create_run(run_id="run-a", bundle_id="bundle-a", instrument_ids=["instrument-a"])
        edge.create_run(run_id="run-b", bundle_id="bundle-a", instrument_ids=["instrument-b"])
        edge.apply_patch({"run_id": "run-a", "based_on_revision": 0, "change": {"state": "paused"}, "patch_kind": "pause"})
        with pytest.raises(StaleRevisionError):
            edge.apply_patch({"run_id": "run-a", "based_on_revision": 0, "change": {"state": "running"}, "patch_kind": "resume"})
        assert edge.run("run-a")["current_revision"] == 1
        assert edge.run("run-b")["current_revision"] == 0


def test_binding_identity_and_command_generation_are_fenced(tmp_path):
    with EdgeStore(tmp_path) as edge:
        edge.bind(webui_controller_id="webui-a", server_url="https://a", credential="a", generation=3)
        with pytest.raises(StaleGenerationError):
            edge.bind(webui_controller_id="webui-b", server_url="https://same-url", credential="b", generation=3)
        with pytest.raises(StaleGenerationError):
            edge.execute_command({"command_id": "old", "controller_generation": 2}, lambda: {})
        edge.bind(webui_controller_id="webui-b", server_url="https://same-url", credential="b", generation=4, force_adoption=True)
        assert edge.binding()["generation"] == 4
        # Persist an interrupted command and make the unsafe replay explicit.
        with edge._transaction() as cursor:
            cursor.execute("INSERT INTO commands(command_id, generation, status, created_at) VALUES ('interrupted', 4, 'in_progress', 'now')")
        with pytest.raises(CommandInProgressError):
            edge.execute_command({"command_id": "interrupted", "controller_generation": 4}, lambda: {})


def test_store_configures_bounded_sqlite_busy_timeout(tmp_path):
    with EdgeStore(tmp_path) as edge:
        assert edge._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_command_inspection_and_identity_reconciliation_are_durable_and_read_only(tmp_path):
    identity = {"expected_device": "device-a", "actual_device": "device-a",
                "owner": "controller-a", "operator": "operator-a", "generation": 4}
    with EdgeStore(tmp_path) as edge:
        with pytest.raises(TimeoutError):
            edge.execute_command({"command_id": "timeout-a", "controller_generation": 4, **identity},
                                 lambda: (_ for _ in ()).throw(TimeoutError("ambiguous")))
        before = edge.inspect_command("timeout-a")
        assert before["status"] == "in_progress"
        assert before["acknowledgement"] is None
        assert edge.reconcile_command("timeout-a", identity) == {
            "command_id": "timeout-a", "generation": 4, **{key: identity[key] for key in identity if key != "generation"},
            "reconciled_after_timeout": True,
        }
        after = edge.inspect_command("timeout-a")
        assert after["status"] == "completed"
        assert after["acknowledgement"]["reconciled_after_timeout"] is True
        with pytest.raises(EdgeStoreError, match="already terminal"):
            edge.reconcile_command("timeout-a", identity)
        assert edge.inspect_command("timeout-a")["acknowledgement"]["command_id"] == "timeout-a"


def test_command_reconciliation_rejects_blank_invalid_and_mismatched_evidence(tmp_path):
    identity = {"expected_device": "device-a", "actual_device": "device-a",
                "owner": "controller-a", "operator": "operator-a", "generation": 4}
    with EdgeStore(tmp_path) as edge:
        with edge._transaction() as cursor:
            cursor.execute("""INSERT INTO commands
                (command_id, generation, status, created_at, expected_device,
                 actual_device, owner, operator)
                VALUES ('timeout-b', 4, 'in_progress', 'now', 'device-a',
                        'device-a', 'controller-a', 'operator-a')""")
        with pytest.raises(EdgeStoreError):
            edge.reconcile_command(" ", identity)
        with pytest.raises(EdgeStoreError, match="non-blank"):
            edge.reconcile_command("timeout-b", {**identity, "operator": " "})
        with pytest.raises(EdgeStoreError, match="does not match"):
            edge.reconcile_command("timeout-b", {**identity, "actual_device": "device-b"})
        with pytest.raises(EdgeStoreError, match="valid generation"):
            edge.reconcile_command("timeout-b", {**identity, "generation": "4"})
        assert edge.inspect_command("timeout-b")["status"] == "in_progress"


def test_calibration_storage_is_digest_verified_idempotent_and_preflight_fenced(tmp_path):
    artifact = calibration_artifact()
    reference = calibration_reference(artifact)
    with EdgeStore(tmp_path) as edge:
        assert edge.put_calibration_artifact(artifact) == artifact
        assert edge.put_calibration_artifact(artifact) == artifact

        altered = dict(artifact)
        altered["method_version"] = "2"
        altered["artifact_digest"] = calibration_artifact_digest(altered)
        with pytest.raises(ImmutableBundleError, match="already bound"):
            edge.put_calibration_artifact(altered)
        corrupt = dict(artifact); corrupt["artifact_digest"] = "sha256:" + "0" * 64
        with pytest.raises(ImmutableBundleError, match="does not match"):
            edge.put_calibration_artifact(corrupt)

        assert edge.calibration_preflight([reference])["disposition"] == "eligible"
        missing = dict(reference); missing["artifact_id"] = "not-delivered"
        assert edge.calibration_preflight([missing])["disposition"] == "blocked"
        wrong_digest = dict(reference); wrong_digest["artifact_digest"] = "sha256:" + "f" * 64
        assert edge.calibration_preflight([wrong_digest])["disposition"] == "hard_reject"
        wrong_target = dict(reference); wrong_target["vial_position_id"] = "vial-b"
        assert edge.calibration_preflight([wrong_target])["disposition"] == "hard_reject"

        gated_bundle = bundle("gated")
        gated_bundle["calibration_references"] = [missing]
        gated_bundle["digest"] = canonical_digest({key: value for key, value in gated_bundle.items() if key != "digest"})
        edge.put_bundle(gated_bundle)
        with pytest.raises(CalibrationPreflightError) as error:
            edge.create_run(run_id="blocked-run", bundle_id="gated", instrument_ids=["instrument-a"])
        assert error.value.preflight["disposition"] == "blocked"
        with pytest.raises(KeyError):
            edge.run("blocked-run")
