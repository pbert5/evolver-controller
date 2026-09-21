from __future__ import annotations

import pytest

from evolver_controller.actuator import (
    HardwareDeviceCommandSink,
    SimulatorDeviceCommandSink,
    compile_trusted_action,
)
from evolver_controller.bundle import calibration_artifact_digest
from evolver_controller.domain import plan_calibrated_temperature
from evolver_controller.store import EdgeStoreError
from evolver_controller.store import EdgeStore
from evolver_controller.hardware_protocol import HardwareUnavailableError
from evolver_controller.actuator import HardwareIPCDeviceCommandSink


INSTRUMENT = {"id": "instrument-1", "vial_positions": [
    {"id": "vial-1", "position_index": 0},
    {"id": "vial-2", "position_index": 1},
]}


def artifact(**overrides):
    value = {
        "id": "temp-cal", "artifact_digest": "sha256:fixture",
        "instrument_id": "instrument-1", "vial_position_id": "vial-2",
        "hardware_fingerprint": {"scheme": "samd21-usb-serial-sha256-v1", "serial_sha256": "abc"},
        "calibration_type": "temperature", "method": "temperature_linear_v1",
        "method_version": "1", "assessment": {"status": "valid"},
        "coefficients": {"slope": 2.0, "intercept": -10.0},
        "calibration_range": {"reference_min": 10.0, "reference_max": 50.0,
                               "raw_min": 10, "raw_max": 100},
    }
    value.update(overrides)
    value["artifact_digest"] = calibration_artifact_digest(value)
    return value


def test_calibrated_temperature_inverts_and_maps_stable_vial_identity():
    plan = plan_calibrated_temperature(artifact=artifact(), target_temperature_c=30,
                                       instrument=INSTRUMENT)
    assert plan["operation"] == "set_temperature"
    assert plan["parameters"] == {"channel": 1, "raw_target_adc": 20}
    assert plan["calibration"]["requested_temperature_c"] == 30.0
    assert plan["calibration"]["predicted_temperature_c"] == 30.0
    assert plan["calibration"]["quantization_error_c"] == 0.0
    assert plan["calibration"]["reference_min"] == 10.0
    assert plan["calibration"]["reference_max"] == 50.0
    assert plan["calibration"]["raw_min"] == 10
    assert plan["calibration"]["raw_max"] == 100
    assert plan["calibration"]["hardware_fingerprint"] == artifact()["hardware_fingerprint"]
    assert plan["calibration"]["status"] == "valid"


def test_calibrated_temperature_accepts_integral_float_raw_bounds_from_fitted_artifacts():
    plan = plan_calibrated_temperature(
        artifact=artifact(calibration_range={"reference_min": 10.0, "reference_max": 50.0,
                                              "raw_min": 10.0, "raw_max": 100.0}),
        target_temperature_c=30, instrument=INSTRUMENT)
    assert plan["parameters"]["raw_target_adc"] == 20


@pytest.mark.parametrize("bad", [
    artifact(assessment={"status": "stale"}),
    artifact(calibration_type="pump_flow_rate"),
    artifact(coefficients={"slope": 0.0, "intercept": 0.0}),
    artifact(calibration_range={"reference_min": 10, "reference_max": 50,
                                "raw_min": 10, "raw_max": 19}),
])
def test_calibrated_temperature_rejects_invalid_artifacts_before_planning(bad):
    with pytest.raises(EdgeStoreError):
        plan_calibrated_temperature(artifact=bad, target_temperature_c=30, instrument=INSTRUMENT)


def test_calibrated_temperature_rejects_digest_and_target_mismatch():
    with pytest.raises(EdgeStoreError, match="digest"):
        plan_calibrated_temperature(artifact={**artifact(), "artifact_digest": "sha256:wrong"},
                                    target_temperature_c=30, instrument=INSTRUMENT)
    with pytest.raises(EdgeStoreError, match="instrument"):
        plan_calibrated_temperature(artifact=artifact(instrument_id="other"), target_temperature_c=30,
                                    instrument=INSTRUMENT)


@pytest.mark.parametrize("target", [0, 100, -0.1, 100.1, 9.9, 50.1])
def test_calibrated_temperature_rejects_out_of_range_targets(target):
    with pytest.raises(EdgeStoreError):
        plan_calibrated_temperature(artifact=artifact(), target_temperature_c=target,
                                    instrument=INSTRUMENT)


def test_calibrated_temperature_rejects_unknown_vial_and_user_channel():
    with pytest.raises(EdgeStoreError, match="vial"):
        plan_calibrated_temperature(artifact=artifact(), target_temperature_c=30,
                                    instrument=INSTRUMENT, vial_position_id="missing")
    with pytest.raises(EdgeStoreError, match="channel"):
        plan_calibrated_temperature(artifact=artifact(), target_temperature_c=30,
                                    instrument=INSTRUMENT, channel=1)


def test_trusted_temperature_requires_artifact_and_preserves_typed_provenance():
    common = dict(command_id="temp-1", run_id="run-a", run_revision=0,
                  bundle_id="bundle-a", state="running", instrument_id="instrument-1",
                  controller_generation=7)
    with pytest.raises(EdgeStoreError, match="calibration"):
        compile_trusted_action({"action_id": "set_temperature", "parameters": {"target": 30}}, **common)

    command = compile_trusted_action({
        "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
        "parameters": {"target": 30}, "calibration_artifact": artifact(),
        "instrument": INSTRUMENT, "lease_token": "lease", "lease_owner": "operator",
    }, **common)
    assert command["operation"] == "set_temperature"
    assert command["parameters"] == {"channel": 1, "raw_target_adc": 20}
    assert command["context"]["calibration"]["artifact_id"] == "temp-cal"
    assert command["context"]["calibration"]["reference_min"] == 10.0
    assert command["context"]["calibration"]["reference_max"] == 50.0
    assert command["context"]["calibration"]["raw_min"] == 10
    assert command["context"]["calibration"]["raw_max"] == 100


def test_simulator_projects_calibrated_target_and_safe_stop_clears_it():
    command = compile_trusted_action({
        "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
        "parameters": {"target": 30}, "calibration_artifact": artifact(),
        "instrument": INSTRUMENT,
    }, command_id="temp-sim", run_id="run-a", run_revision=0, bundle_id="bundle-a",
       state="running", instrument_id="instrument-1", controller_generation=7,
       lease_token="lease", lease_owner="operator")
    sink = SimulatorDeviceCommandSink()
    sink.send(command)
    assert sink.state("instrument-1")["temperature"]["target_c"] == 30.0
    sink.send({"schema_version": "evolver.device.v2", "command_id": "stop",
               "operation": "safe_stop", "target": {"instrument_id": "instrument-1"},
               "parameters": {}, "context": {"controller_generation": 7}})
    assert "target_c" not in sink.state("instrument-1")["temperature"]


def test_controller_local_physical_temperature_sink_fails_closed():
    class Store:
        def binding(self):
            return {"generation": 7}

        def instrument(self, _instrument_id):
            return {"device_identity": "device-a"}

    class Service:
        def __init__(self):
            self.calls = []

        def command(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return type("Result", (), {"as_json": lambda self: {"request_accepted": True}})()

    command = compile_trusted_action({
        "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
        "parameters": {"target": 30}, "calibration_artifact": artifact(),
        "instrument": INSTRUMENT, "lease_token": "lease", "lease_owner": "operator",
    }, command_id="temp-physical", run_id="run-a", run_revision=0, bundle_id="bundle-a",
       state="running", instrument_id="instrument-1", controller_generation=7,
       lease_token="lease", lease_owner="operator")
    service = Service()
    with pytest.raises(EdgeStoreError, match="hardware-daemon IPC"):
        HardwareDeviceCommandSink(Store(), service).send(command)
    assert service.calls == []


def test_temperature_ipc_payload_contains_one_vial_and_no_raw_artifact(tmp_path):
    from evolver_controller.actuator import HardwareIPCDeviceCommandSink
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.put_calibration_artifact(artifact())
        store.register_instruments([{"id": "instrument-1", "device_identity": "MEV-1",
                                     "instrument_type": "minievolver", "vial_positions": INSTRUMENT["vial_positions"]}])
        captured = []
        command = compile_trusted_action({
            "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
            "parameters": {"target": 30}, "calibration_artifact": artifact(),
            "instrument": INSTRUMENT,
        }, command_id="ipc-1", run_id="run-a", run_revision=0, bundle_id="bundle-a", state="running",
           instrument_id="instrument-1", controller_generation=7, lease_token="lease", lease_owner="operator")
        def request(_path, payload, _timeout):
            captured.append(payload)
            return {"request_accepted": True}
        result = HardwareIPCDeviceCommandSink(store, request=request).send(command)
        assert result["request_accepted"] is True
        assert captured == [{"operation": "set_temperature", "physical": True, "target_identity": "MEV-1",
                             "operator": "operator", "controller_generation": 7, "command_id": "ipc-1",
                             "lease_token": "lease", "lease_owner": "operator",
                             "parameters": {"channel": 1, "raw_target_adc": 20, "temperature_c": 30.0,
                                             "calibration": {**command["context"]["calibration"]}}}]
        assert "calibration_artifact" not in captured[0]["parameters"]


def test_temperature_ipc_requires_immutable_hardware_fingerprint(tmp_path):
    from evolver_controller.actuator import HardwareIPCDeviceCommandSink
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "device_identity": "MEV-1",
                                     "instrument_type": "minievolver", "vial_positions": INSTRUMENT["vial_positions"]}])
        command = compile_trusted_action({
            "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
            "parameters": {"target": 30}, "calibration_artifact": artifact(hardware_fingerprint=None),
            "instrument": INSTRUMENT,
        }, command_id="ipc-2", run_id="run-a", run_revision=0, bundle_id="bundle-a", state="running",
           instrument_id="instrument-1", controller_generation=7, lease_token="lease", lease_owner="operator")
        with pytest.raises(EdgeStoreError, match="hardware fingerprint"):
            HardwareIPCDeviceCommandSink(store, request=lambda *_: {"request_accepted": True}).send(command)


