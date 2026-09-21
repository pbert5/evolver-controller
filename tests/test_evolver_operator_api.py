from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from evolver_controller import EdgeStore
from evolver_controller.hardware_broker import HardwareBroker
from evolver_controller.hardware_ipc import PROVISIONING_IPC_TIMEOUT_SECONDS
from evolver_controller import OperatorIdentity
from evolver_controller.operator import (
    OPERATION_METADATA,
    PROTOCOL_VERSION,
    OperatorProtocolError,
    OperatorServer,
    OperatorUnavailable,
    request,
)


def _wire(path: Path, payload: object) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        connection.sendall((json.dumps(payload) + "\n").encode())
        return json.loads(connection.recv(65536).decode())


def test_operator_api_exposes_only_read_models_and_never_hardware_socket(tmp_path: Path) -> None:
    operator_path = tmp_path / "run" / "operator.sock"
    hardware_path = tmp_path / "run" / "hardware.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, operator_path):
        capabilities = request("capabilities", operator_path)
        assert capabilities["protocol_version"] == PROTOCOL_VERSION
        assert capabilities["operations"] == OPERATION_METADATA
        assert capabilities["read_only"] is False
        assert request("status", operator_path)["controller"]["id"] == store.identity()["id"]
        assert request("runs", operator_path) == []
        assert request("instruments", operator_path) == []
        assert "checks" in request("doctor", operator_path)
        assert not hardware_path.exists()
        response = _wire(operator_path, {"operation": "hardware", "params": {}})
        assert response["ok"] is False
    assert not operator_path.exists()


def test_operator_capabilities_expose_frozen_live_controller_operations(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store):
        operations = request("capabilities", path)["operations"]
        for name in (
            "run", "instrument", "calibration", "hardware_lease",
            "hardware_layout", "hardware_provision_identity",
        ):
            assert operations[name] == {"access": "mutate" if name.startswith("hardware_") or name == "run" else "read", "mode": "live"}
        assert operations["hardware"] == {"access": "mutate", "mode": "live"}


def test_operator_live_inventory_and_calibration_operations_are_typed(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store):
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "vial_positions": [], "capabilities": {}}])
        assert request("instrument", path, params={"instrument_id": "instrument-1"})["id"] == "instrument-1"
        assert request("calibration", path, params={"action": "artifacts", "instrument_id": "instrument-1"}) == []
        invalid = _wire(path, {"operation": "instrument", "params": {"unexpected": True}})
        assert invalid["error"]["kind"] == "invalid_request"


def test_operator_instrument_reads_preserve_fresh_vs_cached_evidence(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    calls = []

    def hardware_request(_path, payload, _timeout):
        calls.append(payload)
        if payload["operation"] == "get_status":
            return {"device_identity": "MEV-1", "temperature_state": "idle"}
        return {"device_identity": "MEV-1", "value": "77", "metric": "photodiode_raw"}

    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    with EdgeStore(tmp_path / "state") as store:
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [{"id": "vial-1"}],
                                     "capabilities": {}}])
        store.spool_telemetry(stream_id="instrument:instrument-1:read_only_sensors", sequence=1,
                              payload={"instrument_id": "instrument-1", "vial_position_ids": ["vial-1"],
                                       "photodiode_adc_0": 66,
                                       "calibration": {"temperature": "not_calibrated", "od": "not_calibrated"}},
                              captured_at="2026-01-01T00:00:00+00:00")
        broker = HardwareBroker(store, request=hardware_request)
        with OperatorServer(store, path, operator=operator, hardware_broker=broker):
            status = request("instrument", path, params={"action": "status", "instrument_id": "instrument-1"})
            fresh = request("instrument", path, params={"action": "sensor_read", "instrument_id": "instrument-1",
                                                         "sensor": "od", "channel": 0})
            cached = request("instrument", path, params={"action": "telemetry_latest", "instrument_id": "instrument-1"})
            cached_list = request("instrument", path, params={"action": "telemetry_list", "instrument_id": "instrument-1"})

    assert status["freshness"] == "fresh"
    assert fresh["freshness"] == "fresh"
    assert fresh["raw_value"] == 77
    assert fresh["derived_value"] is None
    assert cached["freshness"] == "cached"
    assert cached["source"] == "telemetry_store"
    assert cached["observations"][0]["raw_value"] == 66
    assert cached["observations"][0]["derived_value"] is None
    assert len(cached_list) == 1
    assert cached_list[0]["sequence"] == cached["sequence"]
    assert [call["operation"] for call in calls] == ["get_status", "read_sensor"]


def test_operator_instrument_read_rejects_mismatched_target_identity(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    calls = []

    with EdgeStore(tmp_path / "state") as store:
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [{"id": "vial-1"}],
                                     "capabilities": {}}])
        broker = HardwareBroker(store, request=lambda *_: calls.append(True) or {"value": 1})
        with OperatorServer(store, path, operator=operator, hardware_broker=broker):
            invalid = _wire(path, {"operation": "instrument", "params": {
                "action": "sensor_read", "instrument_id": "instrument-1", "target_identity": "MEV-2",
                "sensor": "od", "channel": 0}})

    assert invalid["error"]["kind"] == "invalid_request"
    assert calls == []


def test_operator_safe_stop_is_authenticated_physical_and_lease_free(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    calls = []

    def ipc_request(_path, payload, _timeout):
        calls.append(payload)
        return {"command_id": payload["command_id"], "request_accepted": True,
                "verification": "protocol_verified"}

    with EdgeStore(tmp_path / "state") as store:
        store.bind(webui_controller_id="central", server_url="https://central",
                   credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
        store.set_control_lease(lease_token="foreign", owner="other", generation=7,
                                expires_at="2030-01-01T01:00:00+00:00")
        broker = HardwareBroker(store, request=ipc_request)
        with OperatorServer(store, path, operator=operator, hardware_broker=broker):
            result = request("hardware", path, params={"operation": "safe_stop",
                                                         "physical": True, "operator": "alice"})
            assert result["request_accepted"] is True
            denied = _wire(path, {"operation": "hardware", "params": {
                "operation": "safe_stop", "physical": False, "operator": "alice"}})
            assert denied["error"]["kind"] == "unsafe"
            assert store.command_acknowledgements()[-1]["request_accepted"] is True

    assert calls and calls[0]["operator"] == "alice"
    assert calls[0]["controller_generation"] == 7
    assert "lease_token" not in calls[0]
    assert "target_identity" in calls[0]
def test_operator_safe_stop_requires_hardware_permission(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset())
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, path, operator=operator,
                                                                  hardware_broker=HardwareBroker(store)):
        denied = _wire(path, {"operation": "hardware", "params": {
            "operation": "safe_stop", "physical": True, "operator": "alice"}})
        assert denied["error"]["kind"] == "forbidden"


def test_operator_calibration_run_is_authenticated_typed_and_transport_neutral(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset({"manage_calibration"}))
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store, operator=operator):
        created = request("calibration_run", path, params={
            "action": "create", "run_id": "cal-run", "calibration_type": "temperature",
            "instrument_id": "instrument-1", "vial_position_id": "vial-1", "operator": "alice",
        })
        assert created["effective_state"]["kind"] == "calibration"
        observed = request("calibration_run", path, params={
            "action": "observation", "run_id": "cal-run", "operator": "alice",
            "observation": {"raw_value": 100, "reference_value": 20,
                            "action": "observation", "run_id": "transport-run", "operator": "spoof"},
        })
        evidence = observed["effective_state"]["observations"][0]
        assert evidence["run_id"] == "cal-run"
        assert "action" not in evidence

    with EdgeStore(tmp_path / "unauthenticated") as store, OperatorServer(path=tmp_path / "unauthenticated.sock", store=store):
        denied = _wire(tmp_path / "unauthenticated.sock", {"operation": "calibration_run", "params": {
            "action": "create", "run_id": "cal-run", "calibration_type": "temperature",
            "instrument_id": "instrument-1",
        }})
        assert denied["error"]["kind"] == "unauthorized"

    with EdgeStore(tmp_path / "forbidden") as store, OperatorServer(
        path=tmp_path / "forbidden.sock", store=store,
        operator=OperatorIdentity("alice", "local_operator", frozenset()),
    ):
        denied = _wire(tmp_path / "forbidden.sock", {"operation": "calibration_run", "params": {
            "action": "create", "run_id": "cal-run", "calibration_type": "temperature",
            "instrument_id": "instrument-1", "operator": "alice",
        }})
        assert denied["error"]["kind"] == "forbidden"


def test_calibration_activation_requires_calibration_run_type_and_revision_fence(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset({"manage_calibration"}))
    artifact = {"id": "temp-a", "instrument_id": "instrument-1", "calibration_type": "temperature",
                "method": "temperature_linear_v1", "method_version": "1",
                "coefficients": {"slope": 1.0, "intercept": 0.0},
                "evidence_digest": "sha256:evidence", "artifact_digest": "sha256:artifact"}
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store, operator=operator):
        created = request("calibration_run", path, params={
            "action": "create", "run_id": "cal-run", "calibration_type": "temperature",
            "instrument_id": "instrument-1", "operator": "alice",
        })
        activated = request("calibration_run", path, params={
            "action": "activate_artifact", "run_id": "cal-run", "operator": "alice",
            "based_on_revision": created["current_revision"], "artifact": artifact,
        })
        assert activated["run"]["current_revision"] == created["current_revision"] + 1
        stale = _wire(path, {"operation": "calibration_run", "params": {
            "action": "activate_artifact", "run_id": "cal-run", "operator": "alice",
            "based_on_revision": created["current_revision"], "artifact": artifact,
        }})
        assert stale["error"]["kind"] == "calibration_run_error"

def test_operator_maintenance_operation_is_explicitly_delegated(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store):
        response = _wire(path, {"operation": "hardware", "params": {"operation": "discover"}})
        assert response["ok"] is False
        assert response["error"]["kind"] == "maintenance_delegated"


def test_live_hardware_capability_keeps_typed_suboperation_safety(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    with EdgeStore(tmp_path / "state") as store, OperatorServer(path=path, store=store, operator=operator):
        assert request("capabilities", path)["operations"]["hardware"]["mode"] == "live"
        response = _wire(path, {"operation": "hardware", "params": {
            "operation": "hardware_command", "operation_name": "set_stir",
            "target_identity": "MEV-1", "parameters": {}, "controller_generation": 1,
            "lease_token": "lease", "physical": True, "unexpected": True,
        }})
        assert response["ok"] is False
        assert response["error"]["kind"] == "invalid_request"


def test_operator_protocol_rejects_extra_fields_and_oversized_requests(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, path):
        response = _wire(path, {"operation": "status", "command": "id"})
        assert response["ok"] is False
        assert response["error"]["kind"] == "invalid_request"
        assert set(response["error"]) == {"kind", "message"}
        with pytest.raises(OperatorProtocolError):
            request("not-allowlisted", path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(path))
            connection.sendall(b"x" * (64 * 1024 + 1) + b"\n")
            oversized = json.loads(connection.recv(4096).decode())
            assert oversized == {"ok": False, "error": {
                "kind": "request_too_large", "message": "operator request is too large"
            }}

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(path))
            connection.sendall(b"not-json\n")
            malformed = json.loads(connection.recv(4096).decode())
            assert malformed == {"ok": False, "error": {
                "kind": "malformed_json", "message": "operator request is malformed JSON"
            }}


def test_operator_protocol_requires_object_params_and_reports_typed_errors(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, path):
        assert _wire(path, {"operation": "status", "params": {}})["ok"] is True
        missing = _wire(path, {"operation": "status"})
        assert missing == {"ok": False, "error": {
            "kind": "invalid_request", "message": "request must contain operation and params"
        }}
        unsupported = _wire(path, {"operation": "hardware", "params": {}})
        assert unsupported["error"]["kind"] == "unsupported_operation"


def test_operator_client_rejects_malformed_typed_response(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path)); listener.listen(1)
        def serve() -> None:
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(b'{"ok":false,"error":"bad"}\n')
        thread = __import__("threading").Thread(target=serve)
        thread.start()
        with pytest.raises(OperatorProtocolError, match="invalid operator response"):
            request("status", path)
        thread.join()


def test_operator_socket_is_private_and_client_reports_explicit_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, path):
        stat_mode = os.stat(path).st_mode & 0o777
        assert stat_mode == 0o660
    with pytest.raises(OperatorUnavailable, match="operator service unavailable"):
        request("status", path, timeout=0.1)


def test_operator_hardware_diagnostics_reach_controller_broker_and_ipc_sink(tmp_path: Path) -> None:
    calls = []

    def fake_hardware_ipc(path, payload, timeout):
        calls.append((path, payload, timeout))
        return {"device_identity": "MEV-1", "verification": "protocol_verified"}

    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(
        store, path, operator=operator, hardware_broker=HardwareBroker(store, request=fake_hardware_ipc)
    ):
        assert request("hardware", path, params={"operation": "discover"})["device_identity"] == "MEV-1"
        assert request("hardware", path, params={"operation": "protocol_test"})["verification"] == "protocol_verified"

    assert [call[1] for call in calls] == [
        {"operation": "discover", "operator": "alice"},
        {"operation": "protocol_test", "operator": "alice"},
    ]


def test_operator_identity_provisioning_uses_extended_ipc_timeout(tmp_path: Path) -> None:
    calls = []

    def fake_hardware_ipc(path, payload, timeout):
        calls.append((path, payload, timeout))
        return {"verification": "protocol_verified", "observed_evidence": {
            "device_id": "MEV-002", "owner_id": "lab", "operator": "alice",
        }}

    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(
        store, path, operator=operator, hardware_broker=HardwareBroker(store, request=fake_hardware_ipc)
    ):
        result = request("hardware_provision_identity", path, params={
            "device_id": "MEV-002", "owner_id": "lab", "operator": "alice", "physical": True,
        })

    assert result["verification"] == "protocol_verified"
    assert calls[0][1] == {
        "operation": "provision_identity", "device_id": "MEV-002", "owner_id": "lab",
        "operator": "alice", "physical": True,
    }
    assert calls[0][2] == PROVISIONING_IPC_TIMEOUT_SECONDS


def test_operator_hardware_command_keeps_controller_fences(tmp_path: Path) -> None:
    calls = []

    def fake_hardware_ipc(path, payload, timeout):
        calls.append(payload)
        return {"request_accepted": True}

    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
        store.set_control_lease(lease_token="lease-7", owner="alice", generation=7,
                                expires_at="2030-01-01T01:00:00+00:00")
        with OperatorServer(store, path, operator=operator,
                            hardware_broker=HardwareBroker(store, request=fake_hardware_ipc)):
            result = request("hardware", path, params={
                "operation": "hardware_command", "operation_name": "set_stir",
                "target_identity": "MEV-1", "parameters": {"channel": 0, "duration_ms": 100, "level": 5},
                "controller_generation": 7, "lease_token": "lease-7", "lease_owner": "alice", "physical": True,
            })
            assert result["request_accepted"] is True
            denied = _wire(path, {"operation": "hardware", "params": {
                "operation": "hardware_command", "operation_name": "set_stir",
                "target_identity": "MEV-1", "parameters": {"channel": 0, "duration_ms": 100, "level": 5},
                "controller_generation": 7, "lease_token": "wrong", "lease_owner": "alice", "physical": True,
            }})
            assert denied["ok"] is True
            assert calls[-1]["lease_token"] == "wrong"
    assert len(calls) == 2
    assert calls[0]["operator"] == "alice"


@pytest.mark.parametrize("change", [
    {"physical": False},
    {"target_identity": "MEV-2"},
    {"parameters": {"channel": 0, "duration_ms": 1001, "level": 5}},
])
def test_operator_hardware_handler_rejects_unsafe_command_before_ipc(tmp_path: Path, change: dict) -> None:
    calls = []

    def fake_hardware_ipc(path, payload, timeout):
        calls.append(payload)
        return {"request_accepted": True}

    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret", generation=7)
        store.register_instruments([{"id": "instrument-1", "instrument_type": "minievolver",
                                     "device_identity": "MEV-1", "vial_positions": [], "capabilities": {}}])
        store.set_control_lease(lease_token="lease-7", owner="alice", generation=7,
                                expires_at="2030-01-01T01:00:00+00:00")
        params = {"operation": "hardware_command", "operation_name": "set_stir",
                  "target_identity": "MEV-1", "parameters": {"channel": 0, "duration_ms": 100, "level": 5},
                  "controller_generation": 7, "lease_token": "lease-7", "lease_owner": "alice", "physical": True}
        params.update(change)
        with OperatorServer(store, path, operator=operator,
                            hardware_broker=HardwareBroker(store, request=fake_hardware_ipc)):
            denied = _wire(path, {"operation": "hardware", "params": params})
            assert denied["ok"] is False
            assert denied["error"]["kind"] == "HardwareError"
    assert calls == []


def test_operator_hardware_handler_rejects_untyped_command_fields_before_ipc(tmp_path: Path) -> None:
    calls = []
    operator = OperatorIdentity("alice", "local_operator", frozenset({"hardware_maintenance"}))
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store:
        broker = HardwareBroker(store, request=lambda *args: calls.append(args) or {"request_accepted": True})
        with OperatorServer(store, path, operator=operator, hardware_broker=broker):
            response = _wire(path, {"operation": "hardware", "params": {
                "operation": "hardware_command", "operation_name": "set_stir",
                "target_identity": "MEV-1", "parameters": {}, "controller_generation": "7",
                "lease_token": "lease-7", "physical": True, "unexpected": "value",
            }})
            assert response["ok"] is False
            assert response["error"]["kind"] == "invalid_request"
    assert calls == []
