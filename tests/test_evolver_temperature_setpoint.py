from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge.actuator import (
    HardwareDeviceCommandSink,
    SimulatorDeviceCommandSink,
    compile_trusted_action,
)
from meta_webui_application_backend.evolver_edge.bundle import calibration_artifact_digest
from meta_webui_application_backend.evolver_edge.domain import plan_calibrated_temperature
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError
from meta_webui_application_backend.evolver_edge.store import EdgeStore
from meta_webui_application_backend.evolver_edge.hardware import HardwareService


INSTRUMENT = {"id": "instrument-1", "vial_positions": [
    {"id": "vial-1", "position_index": 0},
    {"id": "vial-2", "position_index": 2},
]}


def artifact(**overrides):
    value = {
        "id": "temp-cal", "artifact_digest": "sha256:fixture",
        "instrument_id": "instrument-1", "vial_position_id": "vial-2",
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
    assert plan["parameters"] == {"channel": 2, "raw_target_adc": 20}
    assert plan["calibration"]["requested_temperature_c"] == 30.0
    assert plan["calibration"]["predicted_temperature_c"] == 30.0
    assert plan["calibration"]["quantization_error_c"] == 0.0
    assert plan["calibration"]["reference_min"] == 10.0
    assert plan["calibration"]["reference_max"] == 50.0
    assert plan["calibration"]["raw_min"] == 10
    assert plan["calibration"]["raw_max"] == 100


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
    assert command["parameters"] == {"channel": 2, "raw_target_adc": 20}
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


def test_physical_sink_forwards_only_typed_calibrated_operation():
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
    result = HardwareDeviceCommandSink(Store(), service).send(command)
    assert result["request_accepted"] is True
    assert service.calls[0][0][:2] == ("set_temperature", "device-a")
    assert service.calls[0][0][2] == {"channel": 2, "raw_target_adc": 20,
                                      "temperature_c": 30.0,
                                      "calibration": command["context"]["calibration"]}


class FakeTemperatureTransport:
    port = "fake-temperature"

    def __init__(self):
        self.opened = False
        self.commands = []

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def exchange(self, payload):
        assert self.opened
        self.commands.append(payload)
        if payload == "WHO_ARE_YOU_!":
            return "MEV|2|MEV-1|1|HELLO|type=minievolver,proto=2,fw=0.2,hw_proto=2,id=MEV-1"
        if payload.startswith("TEMP|2|SET|"):
            return "HW|2|OK|TEMP|applied=1"
        raise AssertionError(payload)


def test_physical_sink_fake_integration_emits_exact_temp_v2_payload_without_real_io(tmp_path):
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "device_identity": "MEV-1",
                                     "instrument_type": "minievolver", "vial_positions": INSTRUMENT["vial_positions"]}])
        transport = FakeTemperatureTransport()
        service = HardwareService(store, transport, allow_physical=True)
        command = compile_trusted_action({
            "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
            "parameters": {"target": 30}, "calibration_artifact": artifact(),
            "instrument": INSTRUMENT,
        }, command_id="123", run_id="run-a", run_revision=0, bundle_id="bundle-a",
           state="running", instrument_id="instrument-1", controller_generation=7,
           lease_token="17", lease_owner="operator")
        # The fake store only needs the same durable lease contract as the real edge.
        store.set_control_lease(lease_token="17", owner="operator", generation=7,
                                expires_at="2099-01-01T00:00:00+00:00")
        result = HardwareDeviceCommandSink(store, service).send(command)
        assert result["request_accepted"] is True
        assert "TEMP|2|SET|123|2|20|operator|17|7_!" in transport.commands
        replay = HardwareDeviceCommandSink(store, service).send(command)
        assert replay["request_accepted"] is True
        assert transport.commands.count("TEMP|2|SET|123|2|20|operator|17|7_!") == 1


def test_physical_sink_rejects_stale_generation_before_fake_io(tmp_path):
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "device_identity": "MEV-1",
                                     "instrument_type": "minievolver", "vial_positions": INSTRUMENT["vial_positions"]}])
        transport = FakeTemperatureTransport()
        service = HardwareService(store, transport, allow_physical=True)
        command = compile_trusted_action({
            "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
            "parameters": {"target": 30}, "calibration_artifact": artifact(),
            "instrument": INSTRUMENT,
        }, command_id="124", run_id="run-a", run_revision=0, bundle_id="bundle-a",
           state="running", instrument_id="instrument-1", controller_generation=6,
           lease_token="17", lease_owner="operator")
        with pytest.raises(EdgeStoreError, match="active positive controller generation"):
            HardwareDeviceCommandSink(store, service).send(command)
        assert transport.commands == []


@pytest.mark.parametrize("field, value", [
    ("command_id", "temp-wire"),
    ("lease_token", "lease"),
    ("lease_owner", "different-owner"),
])
def test_physical_sink_rejects_non_firmware_authority_fields_before_fake_io(tmp_path, field, value):
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "device_identity": "MEV-1",
                                     "instrument_type": "minievolver", "vial_positions": INSTRUMENT["vial_positions"]}])
        transport = FakeTemperatureTransport()
        service = HardwareService(store, transport, allow_physical=True)
        command = compile_trusted_action({
            "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
            "parameters": {"target": 30}, "calibration_artifact": artifact(),
            "instrument": INSTRUMENT,
        }, command_id="123", run_id="run-a", run_revision=0, bundle_id="bundle-a",
           state="running", instrument_id="instrument-1", controller_generation=7,
           lease_token="17", lease_owner="operator")
        if field == "command_id":
            command["command_id"] = value
        else:
            command["context"][field] = value
        store.set_control_lease(lease_token="17", owner="operator", generation=7,
                                expires_at="2099-01-01T00:00:00+00:00")
        result = HardwareDeviceCommandSink(store, service).send(command)
        assert result["request_accepted"] is False
        assert transport.commands == []


def test_physical_sink_rejects_tampered_provenance_before_fake_io():
    class Service:
        def __init__(self): self.calls = []
        def command(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("hardware service must not be called")

    class Store:
        def binding(self): return {"generation": 7}
        def instrument(self, _instrument_id): return {"device_identity": "device-a"}
        def list_instruments(self): return [{"device_identity": "device-a"}]

    command = compile_trusted_action({
        "action_id": "set_temperature", "target": {"vial_position_id": "vial-2"},
        "parameters": {"target": 30}, "calibration_artifact": artifact(),
        "instrument": INSTRUMENT,
    }, command_id="temp-tampered", run_id="run-a", run_revision=0, bundle_id="bundle-a",
       state="running", instrument_id="instrument-1", controller_generation=7,
       lease_token="lease", lease_owner="operator")
    command["context"]["calibration"]["raw_max"] = 19
    with pytest.raises(EdgeStoreError, match="mismatch"):
        HardwareDeviceCommandSink(Store(), Service()).send(command)


def test_trusted_temperature_serializes_artifact_vial_and_requires_lease():
    common = dict(command_id="temp-lease", run_id="run-a", run_revision=0,
                  bundle_id="bundle-a", state="running", instrument_id="instrument-1",
                  controller_generation=7)
    action = {"action_id": "set_temperature", "parameters": {"target": 30},
              "calibration_artifact": artifact(), "instrument": INSTRUMENT}
    with pytest.raises(EdgeStoreError, match="lease"):
        compile_trusted_action(action, **common)
    command = compile_trusted_action(action, lease_token="lease", lease_owner="operator", **common)
    assert command["target"]["vial_position_id"] == "vial-2"
    assert command["context"]["lease_token"] == "lease"
