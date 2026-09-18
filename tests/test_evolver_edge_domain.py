from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore, plan_calibrated_dispense
from meta_webui_application_backend.evolver_edge.domain import validate_bounded_operation
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError
from meta_webui_application_backend.evolver_edge.simulator import EvolverSimulator


def test_measurements_and_activities_are_durable_and_idempotent(tmp_path):
    measurement = {"id": "m-1", "captured_at": "2026-01-01T00:00:00Z",
                   "measurement_type": "temperature", "raw_value": 512,
                   "source_type": "instrument_telemetry", "stream_id": "vial-1",
                   "sequence_number": 1, "extrapolated": False, "quality_flags": []}
    with EdgeStore(tmp_path) as edge:
        assert edge.record_measurement(measurement) == measurement
        assert edge.record_measurement(measurement) == measurement
        activity = edge.record_activity(activity_type="observation", run_id="run-1", activity_id="a-1")
        assert edge.record_activity(activity_type="observation", run_id="run-1", activity_id="a-1",
                                    details=activity["details"]) == activity
        assert edge.measurements_after("vial-1") == [measurement]
        assert edge.activities(run_id="run-1") == [activity]
    with EdgeStore(tmp_path) as restarted:
        assert restarted.measurements_after("vial-1")[0]["id"] == "m-1"
        assert restarted.activities()[0]["id"] == "a-1"


def test_bounded_operation_and_calibrated_dispense_are_pure_and_fenced():
    assert validate_bounded_operation("pulse_pump", {"channel": 2, "duration_ms": 40}) == {
        "channel": 2, "direction": "forward", "duration_ms": 40}
    with pytest.raises(EdgeStoreError, match="duration"):
        validate_bounded_operation("pulse_pump", {"channel": 2, "duration_ms": 1001})
    artifact = {"id": "pump-cal", "artifact_digest": "sha256:test", "calibration_type": "pump_flow_rate",
                "coefficients": {"slope": 2.0, "intercept": 0.0}}
    assert plan_calibrated_dispense(artifact=artifact, volume_ul=80, channel=1)["parameters"]["duration_ms"] == 40
    with pytest.raises(EdgeStoreError, match="safety bound"):
        plan_calibrated_dispense(artifact=artifact, volume_ul=3000, channel=1)


def test_simulator_tick_projects_position_keyed_measurements(tmp_path):
    with EdgeStore(tmp_path) as edge:
        simulator = EvolverSimulator(edge, instruments=1, vials_per_instrument=1)
        bundle = {"id": "b", "schema_version": "1", "execution_mode": "declarative_state_machine",
                  "source": {"experiment_id": "e", "dataset_revision": "1", "created_at": "now"},
                  "resolved_definition": {"content": {}}, "execution_plan": {"content": {"states": {"run": {}}}},
                  "runtime_parameters": [], "source_metadata": []}
        from meta_webui_application_backend.evolver_edge import canonical_digest
        bundle["digest"] = canonical_digest(bundle)
        edge.put_bundle(bundle)
        run = simulator.start_run(run_id="r", bundle_id="b")
        simulator.tick(run_ids=[run["id"]])
        instrument = simulator.instruments[0]
        stream = f"run:r:instrument:{instrument.id}:vial:{instrument.vial_position_ids[0]}"
        assert edge.measurements_after(stream)[0]["vial_position_id"] == instrument.vial_position_ids[0]


def test_calibration_is_a_real_experiment_run_and_activation_is_provenanced(tmp_path):
    with EdgeStore(tmp_path) as edge:
        simulator = EvolverSimulator(edge, instruments=1, vials_per_instrument=1)
        instrument = simulator.instruments[0]
        vial = instrument.vial_position_ids[0]
        run = edge.create_calibration_run(run_id="cal-run", calibration_type="temperature",
                                          instrument_id=instrument.id, vial_position_id=vial)
        assert run["state"] == "running"
        assert run["effective_state"]["kind"] == "calibration"
        edge.record_calibration_observation(run_id="cal-run",
                                            observation={"raw_value": 100, "reference_value": 20})
        assert edge.run("cal-run")["effective_state"]["observations"][0]["run_id"] == "cal-run"
        artifact = {"id": "temp-a", "instrument_id": instrument.id, "vial_position_id": vial,
                    "calibration_type": "temperature", "method": "temperature_linear_v1",
                    "method_version": "1", "coefficients": {"slope": 1.0, "intercept": 0.0},
                    "evidence_digest": "sha256:evidence", "artifact_digest": "sha256:artifact"}
        activated = edge.activate_calibration_artifact(artifact=artifact, run_id="cal-run",
                                                       activated_by="operator")
        assert activated["activation"]["artifact_digest"] == "sha256:artifact"
        assert edge.activities(run_id="cal-run")[0]["activity_type"] == "calibration_activation"


def test_pump_calibration_without_vial_preserves_observation_and_assessment(tmp_path):
    with EdgeStore(tmp_path) as edge:
        run = edge.create_calibration_run(run_id="pump-cal-run", calibration_type="pump_flow_rate",
                                          instrument_id="instrument-a", component_id="P2")
        assert run["purpose"] == "calibration"
        edge.record_calibration_observation(
            run_id=run["id"], observation={"pulse_duration_ms": 100, "delivered_volume_ul": 250})
        assert edge.run(run["id"])["effective_state"]["observations"][0]["delivered_volume_ul"] == 250
        artifact = {"id": "pump-cal", "instrument_id": "instrument-a", "component_id": "P2",
                    "calibration_type": "pump_flow_rate", "method": "pump_flow_rate_v1",
                    "method_version": "1", "coefficients": {"ul_per_ms": 2.5},
                    "evidence_digest": "sha256:evidence", "artifact_digest": "sha256:artifact"}
        activated = edge.activate_calibration_artifact(artifact=artifact, run_id=run["id"],
                                                       activated_by="operator")
        assert activated["activation"]["assessment"] == {
            "artifact_id": "pump-cal", "status": "valid", "active": False, "reasons": []}
        assert edge.activities(run_id=run["id"])[0]["details"]["assessment"]["status"] == "valid"


def test_calibrated_dispense_executes_with_provenance_or_rejects_without_actuation(tmp_path):
    with EdgeStore(tmp_path) as edge:
        simulator = EvolverSimulator(edge, instruments=1, vials_per_instrument=1)
        instrument = simulator.instruments[0]
        bundle = {"id": "dispense-b", "schema_version": "1", "execution_mode": "declarative_state_machine",
                  "purpose": "test_fixture", "source": {"experiment_id": "e", "dataset_revision": "1", "created_at": "now"},
                  "resolved_definition": {"content": {}}, "execution_plan": {"content": {"states": {"run": {}}}},
                  "runtime_parameters": [], "source_metadata": [], "calibration_requirements": []}
        from meta_webui_application_backend.evolver_edge import canonical_digest
        bundle["digest"] = canonical_digest(bundle)
        edge.put_bundle(bundle)
        run = edge.create_run(run_id="dispense-run", bundle_id="dispense-b", instrument_ids=[instrument.id], state="running")
        artifact = {"id": "pump-a", "artifact_digest": "sha256:pump", "calibration_type": "pump_flow_rate",
                    "assessment": {"status": "valid"}, "coefficients": {"ul_per_ms": 2.0}}
        result = simulator.dispense(run_id=run["id"], artifact=artifact, volume_ul=80, instrument_id=instrument.id, channel=1)
        assert result["disposition"] == "executed"
        assert result["calibration"]["artifact_id"] == "pump-a"
        rejected = simulator.dispense(run_id=run["id"], artifact={**artifact, "assessment": {"status": "stale"}},
                                      volume_ul=80, instrument_id=instrument.id, channel=1)
        assert rejected["disposition"] == "rejected_calibration"
