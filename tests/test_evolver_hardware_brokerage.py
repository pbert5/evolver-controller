from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge.hardware_broker import (HardwareBroker,
                                                                           HardwareBrokerProtocolError,
                                                                           HardwareBrokerUnavailable)
from meta_webui_application_backend.evolver_edge.hardware_ipc import DEFAULT_SOCKET as DEFAULT_HARDWARE_SOCKET
from meta_webui_application_backend.evolver_edge.store import EdgeStore, LeaseValidationError


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

    with _store(tmp_path / "state") as store:
        broker = HardwareBroker(store, request=lambda *_: {})

    assert broker.socket_path == DEFAULT_HARDWARE_SOCKET


def test_hardware_ipc_failures_map_to_typed_errors(tmp_path):
    with _store(tmp_path) as store:
        with pytest.raises(HardwareBrokerUnavailable):
            HardwareBroker(store, request=lambda *_: (_ for _ in ()).throw(RuntimeError("hardware service unavailable"))).discover(operator="ash")
        with pytest.raises(HardwareBrokerProtocolError):
            HardwareBroker(store, request=lambda *_: (_ for _ in ()).throw(RuntimeError("invalid reply"))).protocol_test(operator="ash")


def test_mutating_broker_fences_safety_and_bounds(tmp_path):
    with _store(tmp_path) as store:
        broker = HardwareBroker(store, request=lambda *_: {"request_accepted": True})
        common = {"operator": "ash", "target_identity": "MEV-1", "lease_token": "lease-7", "controller_generation": 7, "physical": True}
        assert broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5}, **common)["request_accepted"]
        with pytest.raises(PermissionError, match="physical"):
            broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5}, **{**common, "physical": False})
        with pytest.raises(ValueError, match="duration_ms"):
            broker.command("set_stir", parameters={"channel": 0, "duration_ms": 1001, "level": 5}, **common)
        with pytest.raises(LeaseValidationError):
            broker.command("set_stir", parameters={"channel": 0, "duration_ms": 100, "level": 5}, **{**common, "lease_token": "wrong"})
