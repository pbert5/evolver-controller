from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_edge.operator import (
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
        assert capabilities["read_only"] is True
        assert request("status", operator_path)["controller"]["id"] == store.identity()["id"]
        assert request("runs", operator_path) == []
        assert request("instruments", operator_path) == []
        assert "checks" in request("doctor", operator_path)
        assert not hardware_path.exists()
        response = _wire(operator_path, {"operation": "hardware"})
        assert response["ok"] is False
    assert not operator_path.exists()


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
