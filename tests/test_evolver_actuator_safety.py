from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge.actuator import (
    HardwareDeviceCommandSink,
    RunActuatorExecutor,
    SimulatorDeviceCommandSink,
    compile_device_command,
    compile_trusted_action,
)
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError


ACTION = {"kind": "device_command", "action_id": "dose", "operation": "pump_pulse",
          "target": {"channel": 1}, "parameters": {"duration_ms": 25}}
RUN = {"id": "run-a", "bundle_id": "bundle-a", "instrument_ids": ["instrument-a"]}


class MemoryStore:
    def __init__(self, generation=7):
        self.generation = generation
        self.actions = {}

    def binding(self):
        return {"generation": self.generation} if self.generation is not None else None

    def run_action(self, command_id):
        return self.actions.get(command_id)

    def record_run_action(self, **values):
        record = dict(values)
        record.update({"status": values.get("status", "pending"), "result": values.get("result")})
        self.actions[values["command_id"]] = record
        return record

    def complete_run_action(self, command_id, *, status, result=None):
        self.actions[command_id].update(status=status, result=result)
        return self.actions[command_id]

    def append_event(self, **_values):
        return {}


class CountingSink:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"request_accepted": True}

    def send(self, command):
        self.calls.append(command)
        return dict(self.result)


def test_executor_uses_authoritative_binding_generation_and_simulator_changes_state():
    store = MemoryStore(generation=9)
    sink = SimulatorDeviceCommandSink()
    RunActuatorExecutor(store, sink).execute_actions(run=RUN, state="running", revision=0, actions=[ACTION])

    assert sink.commands[0]["context"]["controller_generation"] == 9
    assert sink.state("instrument-a")["pump"]["effective_state"] == "active"


def test_hardware_pump_stop_is_rejected_without_service_dispatch():
    class Service:
        def __init__(self):
            self.calls = []

        def command(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("must not dispatch")

    store = MemoryStore()
    store.instrument = lambda _instrument_id: {"device_identity": "device-a"}
    service = Service()
    command = compile_device_command(
        {"operation": "pump_stop", "target": {"channel": 1}, "parameters": {}},
        command_id="stop-1", run_id="run-a", run_revision=0, bundle_id="bundle-a",
        state="running", instrument_id="instrument-a", controller_generation=7,
    )

    with pytest.raises(EdgeStoreError, match="pump_stop"):
        HardwareDeviceCommandSink(store, service).send(command)
    assert service.calls == []


def test_replay_acknowledged_deduplicates_but_failed_is_operator_visible():
    store = MemoryStore()
    sink = CountingSink({"request_accepted": True, "answer": "ok"})
    executor = RunActuatorExecutor(store, sink)

    first = executor.execute_actions(run=RUN, state="running", revision=0, actions=[ACTION])
    second = executor.execute_actions(run=RUN, state="running", revision=0, actions=[ACTION])
    assert first == second == [{"request_accepted": True, "answer": "ok"}]
    assert len(sink.calls) == 1

    command_id = executor.command_id("run-a", 1, "running", 0, ACTION)
    store.actions[command_id] = {"request": compile_device_command(
        ACTION, command_id=command_id, run_id="run-a", run_revision=1, bundle_id="bundle-a",
        state="running", instrument_id="instrument-a", controller_generation=7),
        "status": "failed", "result": {"error": "timeout"}}
    with pytest.raises(EdgeStoreError, match="operator review"):
        executor.execute_actions(run=RUN, state="running", revision=1, actions=[ACTION])


def test_trusted_run_pump_and_pulse_pump_adapt_to_fenced_pump_pulses():
    common = dict(command_id="trusted-1", run_id="run-a", run_revision=3,
                  bundle_id="bundle-a", state="running", instrument_id="instrument-a",
                  controller_generation=7)
    command = compile_trusted_action(
        {"action_id": "run_pump", "action_version": "1.0", "target": {"channel": 2},
         "parameters": {"duration_ms": 40}}, **common)
    assert command["operation"] == "pump_pulse"
    assert command["parameters"] == {"channel": 2, "direction": "forward", "duration_ms": 40}

    pulse = compile_trusted_action(
        {"action_id": "pulse_pump", "action_version": "1", "target": {"channel": 1},
         "parameters": {"duration_ms": 25}}, **{**common, "command_id": "trusted-2"})
    assert pulse["operation"] == "pump_pulse"

    calibrated = compile_trusted_action(
        {"action_id": "dispense", "target": {"channel": 1},
         "parameters": {"volume_ul": 80},
         "calibration_artifact": {"id": "pump-cal", "artifact_digest": "sha256:pump",
                                   "calibration_type": "pump_flow_rate", "assessment": {"status": "valid"},
                                   "coefficients": {"ul_per_ms": 2.0}}},
        **{**common, "command_id": "trusted-3"})
    assert calibrated["operation"] == "pump_pulse"
    assert calibrated["parameters"]["duration_ms"] == 40
    assert calibrated["context"]["calibration"]["artifact_id"] == "pump-cal"


def test_set_temperature_is_logical_and_physical_sink_rejects_without_dispatch():
    command = compile_trusted_action(
        {"action_id": "set_temperature", "parameters": {"target": 30}},
        command_id="temp-1", run_id="run-a", run_revision=0, bundle_id="bundle-a",
        state="running", instrument_id="instrument-a", controller_generation=7)
    assert command["operation"] == "set_temperature"
    assert command["parameters"] == {"temperature_c": 30.0}

    class Service:
        def command(self, *args, **kwargs):
            raise AssertionError("temperature target must not reach physical service")

    store = MemoryStore()
    store.instrument = lambda _instrument_id: {"device_identity": "device-a"}
    with pytest.raises(EdgeStoreError, match="temperature setpoint"):
        HardwareDeviceCommandSink(store, Service()).send(command)
