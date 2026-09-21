from __future__ import annotations

import pytest

from evolver_controller.hardware_broker import (HardwareBroker,
                                                                           HardwareBrokerProtocolError,
                                                                           HardwareBrokerUnavailable)
from evolver_controller.store import EdgeStore


def _store(tmp_path):
    store = EdgeStore(tmp_path); store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
    store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver", "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
    store.set_control_lease(lease_token="lease-7", owner="ash", generation=7, expires_at="2030-01-01T01:00:00+00:00")
    return store


def test_discover_and_protocol_test_are_controller_mediated(tmp_path):
    calls = []
    def request(path, payload, timeout):
        calls.append((path, payload, timeout)); return {"device_identity": "MEV-1", "verification": "protocol_verified"}
    with _store(tmp_path) as store:
        broker = HardwareBroker(store, "/run/hardware.sock", request=request)
        assert broker.discover(operator="ash")["device_identity"] == "MEV-1"
        assert broker.protocol_test(operator="ash", target_identity="MEV-1")["verification"] == "protocol_verified"
    assert calls[0][1] == {"operation": "discover", "operator": "ash"}
    assert calls[0][0] == "/run/hardware.sock"
    assert calls[1][1]["target_identity"] == "MEV-1"


def test_discover_registers_provisioned_hardware_in_controller_inventory(tmp_path):
    discovered = {
        "id": "instrument-1", "controller_id": "hardware-daemon-controller",
        "instrument_type": "minievolver", "device_identity": "MEV-1",
        "identity_state": "provisioned", "vial_positions": [], "capabilities": {},
    }
    with EdgeStore(tmp_path / "state") as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        broker = HardwareBroker(store, request=lambda *_: discovered)
        first = broker.discover(operator="ash")
        second = broker.discover(operator="ash")
        assert first["id"] == "instrument-1"
        assert second["id"] == "instrument-1"
        inventory = store.list_instruments()
        assert len(inventory) == 1
        assert inventory[0]["id"] == "instrument-1"
        assert inventory[0]["device_identity"] == "MEV-1"
        assert inventory[0]["controller_id"] == store.identity()["id"]


def test_hardware_socket_uses_environment_override_and_reaches_that_socket(tmp_path, monkeypatch):
    configured_socket = str(tmp_path / "configured-hardware.sock")
    calls = []
    monkeypatch.setenv("EVOLVER_HARDWARE_SOCKET", configured_socket)

    with _store(tmp_path / "state") as store:
        broker = HardwareBroker(store, request=lambda path, payload, timeout: calls.append(path) or {})
        broker.discover(operator="ash")

    assert calls == [configured_socket]
    assert "/run/evolver-controller/hardware.sock" not in calls


def test_explicit_hardware_socket_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLVER_HARDWARE_SOCKET", "/env/hardware.sock")

    with _store(tmp_path / "state") as store:
        broker = HardwareBroker(store, "/explicit/hardware.sock", request=lambda *_: {})

    assert broker.socket_path == "/explicit/hardware.sock"


def test_hardware_socket_defaults_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("EVOLVER_HARDWARE_SOCKET", raising=False)
    calls = []

    with _store(tmp_path / "state") as store:
        broker = HardwareBroker(store, request=lambda path, payload, timeout: calls.append(path) or {})
        broker.discover(operator="ash")

    assert calls == ["/run/evolver-hardware/hardware.sock"]
    assert "/run/evolver-controller/hardware.sock" not in calls


def test_hardware_ipc_failures_map_to_typed_errors(tmp_path):
    with _store(tmp_path) as store:
        with pytest.raises(HardwareBrokerUnavailable):
            HardwareBroker(store, request=lambda *_: (_ for _ in ()).throw(RuntimeError("hardware service unavailable"))).discover(operator="ash")
        with pytest.raises(HardwareBrokerProtocolError):
            HardwareBroker(store, request=lambda *_: (_ for _ in ()).throw(RuntimeError("invalid reply"))).protocol_test(operator="ash")


def test_read_only_broker_exposes_fresh_status_and_sensor_evidence(tmp_path):
    calls = []

    def request(_path, payload, _timeout):
        calls.append(payload)
        if payload["operation"] == "get_status":
            return {"device_identity": "MEV-1", "sleeves": "1", "temperature_state": "idle"}
        return {"device_identity": "MEV-1", "value": "123", "metric": "thermistor_raw"}

    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [{"id": "vial-1"}],
                                     "capabilities": {}}])
        broker = HardwareBroker(store, request=request)
        status = broker.status(operator="ash", target_identity="MEV-1")
        sensor = broker.read_sensor(operator="ash", target_identity="MEV-1", sensor="temperature", channel=0)

    assert status["freshness"] == "fresh"
    assert status["source"] == "hardware_ipc"
    assert status["device_identity"] == "MEV-1"
    assert status["status"]["sleeves"] == "1"
    assert sensor["sensor"] == "temperature"
    assert sensor["channel"] == 0
    assert sensor["raw_value"] == 123
    assert sensor["derived_value"] is None
    assert sensor["calibration"]["state"] == "not_calibrated"
    assert sensor["evidence_level"] == "protocol_verified"
    assert [call["operation"] for call in calls] == ["get_status", "read_sensor"]
    assert all("physical" not in call for call in calls)


def test_read_sensor_rejects_unregistered_channel_before_hardware_io(tmp_path):
    calls = []
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [{"id": "vial-1"}],
                                     "capabilities": {}}])
        broker = HardwareBroker(store, request=lambda *_: calls.append(True) or {})
        with pytest.raises(ValueError, match="channel"):
            broker.read_sensor(operator="ash", target_identity="MEV-1", sensor="od", channel=1)
    assert calls == []


def test_read_sensor_rejects_malformed_or_mismatched_hardware_reply(tmp_path):
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [{"id": "vial-1"}],
                                     "capabilities": {}}])
        missing_value = HardwareBroker(store, request=lambda *_: {"device_identity": "MEV-1"})
        with pytest.raises(HardwareBrokerProtocolError, match="value"):
            missing_value.read_sensor(operator="ash", target_identity="MEV-1", sensor="od", channel=0)
        mismatched = HardwareBroker(store, request=lambda *_: {"device_identity": "MEV-2", "value": 1})
        with pytest.raises(HardwareBrokerProtocolError, match="identity"):
            mismatched.read_sensor(operator="ash", target_identity="MEV-1", sensor="od", channel=0)


def test_mutating_broker_fences_safety_and_bounds(tmp_path):
    with _store(tmp_path) as store:
        broker = HardwareBroker(store, request=lambda *_: {"request_accepted": True})
        common = {"operator": "ash", "target_identity": "MEV-1", "lease_token": "lease-7", "controller_generation": 7, "physical": True}
        assert broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5}, **common)["request_accepted"]
        with pytest.raises(PermissionError, match="physical"):
            broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5}, **{**common, "physical": False})
        with pytest.raises(ValueError, match="duration_ms"):
            broker.command("set_stir", parameters={"channel": 0, "duration_ms": 1001, "level": 5}, **common)
        forwarded = broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5},
                                   **{**common, "lease_token": "wrong"})
        assert forwarded["request_accepted"]


def test_safe_stop_is_lease_free_all_inventory_and_preserves_operator(tmp_path):
    calls = []
    with _store(tmp_path) as store:
        store.register_instruments([{"id": "instrument-2", "instrument_type": "minievolver",
                                     "device_identity": "MEV-2", "vial_positions": [], "capabilities": {}}])
        broker = HardwareBroker(store, request=lambda _path, payload, _timeout: calls.append(payload) or {
            "command_id": payload["command_id"], "request_accepted": True,
            "verification": "protocol_verified"})
        result = broker.safe_stop(operator="operator", physical=True)
        repeated = broker.safe_stop(operator="operator", physical=True)

    assert {call["target_identity"] for call in calls} == {"MEV-1", "MEV-2"}
    assert all(call["operator"] == "operator" for call in calls)
    assert all(call["controller_generation"] == 7 for call in calls)
    assert all("lease_token" not in call and "lease_owner" not in call for call in calls)
    assert result["request_accepted"] is True
    assert repeated["command_id"] != result["command_id"]


def test_unbound_local_commissioning_authorizes_bounded_command_and_safe_stop(tmp_path):
    calls = []
    with EdgeStore(tmp_path) as store:
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
        lease = store.acquire_local_commissioning_lease("operator")
        broker = HardwareBroker(store, request=lambda _path, payload, _timeout:
                                calls.append(payload) or {"request_accepted": True})
        result = broker.command("set_stir", operator="operator", target_identity="MEV-1",
                                parameters={"channel": 0, "duration_ms": 100, "level": 5},
                                lease_token=lease["token"], controller_generation=lease["generation"],
                                physical=True)
        assert result["request_accepted"] is True
        store.release_local_commissioning_lease("operator")
        stopped = broker.safe_stop(operator="operator", physical=True)

    assert stopped["request_accepted"] is True
    assert calls[0]["controller_generation"] == 1
    assert calls[1]["controller_generation"] == 1


def test_stale_local_lease_is_rejected_after_reacquire(tmp_path):
    calls = []
    with EdgeStore(tmp_path) as store:
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
        first = store.acquire_local_commissioning_lease("operator")
        store.release_local_commissioning_lease("operator")
        second = store.acquire_local_commissioning_lease("operator")
        broker = HardwareBroker(store, request=lambda *_: calls.append(True) or {"request_accepted": True})
        broker.command("set_stir", operator="operator", target_identity="MEV-1",
                       parameters={"channel": 0, "duration_ms": 100, "level": 5},
                       lease_token=first["token"], controller_generation=first["generation"],
                       physical=True)
        assert second["generation"] == 2
    assert calls == [True]
