from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_edge.operator import (
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
        assert request("capabilities", operator_path)["read_only"] is True
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
        with pytest.raises(OperatorProtocolError):
            request("not-allowlisted", path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(path))
            connection.sendall(b"x" * (64 * 1024 + 1) + b"\n")
            assert json.loads(connection.recv(4096).decode())["ok"] is False


def test_operator_socket_is_private_and_client_reports_explicit_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "operator.sock"
    with EdgeStore(tmp_path / "state") as store, OperatorServer(store, path):
        stat_mode = os.stat(path).st_mode & 0o777
        assert stat_mode == 0o660
    with pytest.raises(OperatorUnavailable, match="operator service unavailable"):
        request("status", path, timeout=0.1)
