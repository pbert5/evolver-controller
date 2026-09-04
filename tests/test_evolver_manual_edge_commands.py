from datetime import UTC, datetime, timedelta

from meta_webui_application_backend.evolver_edge import (
    EdgeStore, HardwareIPCDeviceCommandSink, ManualCommandExecutor, SimulatorDeviceCommandSink, SyncClient,
)


class FakeClock:
    def __init__(self):
        self.value = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def _setup(tmp_path):
    store = EdgeStore(tmp_path)
    store.bind(webui_controller_id="central", server_url="https://central", credential="credential", generation=4)
    store.register_instruments([{"id": "instrument", "instrument_type": "minievolver",
                                 "vial_positions": [], "capabilities": {}, "device_identity": "device"}])
    store.set_control_lease(lease_token="lease", owner="operator", generation=4,
                            expires_at="2030-01-01T01:00:00+00:00")
    clock = FakeClock()
    sink = SimulatorDeviceCommandSink()
    return store, clock, sink, ManualCommandExecutor(store, sink, clock)


def _command(operation, **values):
    return {"command_id": values.pop("command_id", "manual-1"), "controller_generation": 4,
            "command_kind": "emergency_safe_stop" if operation == "safe_stop" else operation,
            "operation": operation, "instrument_id": "instrument",
            "expires_at": values.pop("expires_at", "2030-01-01T00:00:30+00:00"),
            "lease_token": "lease", "lease_holder": "operator", "parameters": values}


def test_manual_stir_is_typed_idempotent_and_ttl_fenced(tmp_path):
    store, clock, sink, executor = _setup(tmp_path)
    try:
        command = _command("stir_pulse", channel=0, duration_ms=100, level=25)
        assert executor.execute(command)["disposition"] == "completed"
        assert executor.execute(command)["disposition"] == "completed"
        assert len(sink.commands) == 1
        clock.advance(31)
        expired = _command("stir_pulse", command_id="manual-expired", channel=0, duration_ms=100, level=25)
        assert executor.execute(expired)["disposition"] == "expired"
        assert len(sink.commands) == 1
    finally:
        store.close()


def test_heater_is_bounded_and_safe_stop_clears_outputs(tmp_path):
    store, _clock, sink, executor = _setup(tmp_path)
    try:
        rejected = executor.execute(_command("heater_pulse", channel=0, duration_ms=251, level=64))
        assert rejected["disposition"] == "rejected_invalid"
        assert store.command_acknowledgements()[-1]["disposition"] == "rejected_invalid"
        accepted = executor.execute(_command("heater_pulse", command_id="heater", channel=0, duration_ms=250, level=64))
        assert accepted["disposition"] == "completed"
        assert sink.state("instrument")["heater"]["effective_state"] == "active"
        stopped = executor.execute({"command_id": "stop", "controller_generation": 4,
                                    "operation": "safe_stop", "instrument_id": "instrument",
                                    "expires_at": "2030-01-01T00:00:30+00:00", "parameters": {}})
        assert stopped["disposition"] == "completed"
        assert not sink.outputs
    finally:
        store.close()


def test_manual_command_rejects_stale_generation_and_run_without_ownership(tmp_path):
    store, _clock, _sink, executor = _setup(tmp_path)
    try:
        stale = _command("stir_pulse", command_id="stale", channel=0, duration_ms=1, level=1)
        stale["controller_generation"] = 3
        assert executor.execute(stale)["disposition"] == "rejected_stale_generation"
        assert store.command_acknowledgements()[-1]["disposition"] == "rejected_stale_generation"
        unowned = _command("stir_pulse", command_id="unowned", channel=0, duration_ms=1, level=1)
        unowned["run_id"] = "missing-run"
        assert executor.execute(unowned)["disposition"] == "rejected_run_ownership"
    finally:
        store.close()


def test_sync_delivers_manual_intent_once_to_the_typed_executor(tmp_path):
    store, _clock, sink, executor = _setup(tmp_path)
    try:
        command = _command("stir_pulse", command_id="sync-stir", channel=1, duration_ms=20, level=10)
        result = SyncClient(store, manual_executor=executor)._process_command(command)
        replay = SyncClient(store, manual_executor=executor)._process_command(command)
        assert result["disposition"] == replay["disposition"] == "completed"
        assert len(sink.commands) == 1
    finally:
        store.close()


def test_ipc_sink_preserves_typed_command_evidence_and_fencing(tmp_path):
    store, _clock, _sink, _executor = _setup(tmp_path)
    requests = []

    def ipc_request(socket_path, payload, timeout):
        requests.append((socket_path, payload, timeout))
        return {"command_id": payload["command_id"], "request_accepted": True,
                "protocol_response": "PULSE_STIR|ok", "verification": "protocol_verified",
                "observed_evidence": {"device": "simulated-boundary"}, "retryable": False}

    try:
        executor = ManualCommandExecutor(store, HardwareIPCDeviceCommandSink(
            store, "/run/test-hardware.sock", request=ipc_request))
        command = _command("stir_pulse", channel=0, duration_ms=20, level=10)
        first, replay = executor.execute(command), executor.execute(command)
        assert first["disposition"] == replay["disposition"] == "completed"
        assert first["result"]["verification"] == "protocol_verified"
        assert len(requests) == 1
        assert requests[0][1]["physical"] is True
        assert requests[0][1]["controller_generation"] == 4
        assert requests[0][1]["lease_token"] == "lease"
        assert store.command_acknowledgements()[-1]["command_id"] == "manual-1"
    finally:
        store.close()
