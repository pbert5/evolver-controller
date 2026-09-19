"""Client for the separately packaged hardware service Unix socket."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any

MAX_MESSAGE = 16 * 1024
DEFAULT_SOCKET = "/run/evolver-hardware/hardware.sock"
DEFAULT_IPC_TIMEOUT_SECONDS = 5.0
HARDWARE_EXCHANGE_TIMEOUT_SECONDS = 2.0
PROVISIONING_EXCHANGE_COUNT = 3
PROVISIONING_INNER_BUDGET_SECONDS = PROVISIONING_EXCHANGE_COUNT * HARDWARE_EXCHANGE_TIMEOUT_SECONDS
PROVISIONING_IPC_TIMEOUT_SECONDS = PROVISIONING_INNER_BUDGET_SECONDS + 1.0


def _recv(sock: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while len(data) <= MAX_MESSAGE:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
    if len(data) > MAX_MESSAGE or b"\n" not in data:
        raise ValueError("malformed or oversized hardware IPC response")
    value = json.loads(bytes(data).split(b"\n", 1)[0])
    if not isinstance(value, dict):
        raise ValueError("hardware IPC response must be an object")
    return value


def _timeout_for_request(payload: dict[str, Any], timeout: float | None) -> float:
    effective = (PROVISIONING_IPC_TIMEOUT_SECONDS if payload.get("operation") == "provision_identity"
                 else DEFAULT_IPC_TIMEOUT_SECONDS) if timeout is None else timeout
    if effective <= 0:
        raise ValueError("hardware IPC timeout must be positive")
    if payload.get("operation") == "provision_identity" and effective <= PROVISIONING_INNER_BUDGET_SECONDS:
        raise ValueError("provisioning IPC timeout must exceed its inner three-exchange budget")
    return effective


def request(path: str | Path, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + _timeout_for_request(payload, timeout)
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_MESSAGE:
        raise ValueError("hardware IPC request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(max(0.0, deadline - time.monotonic()))
        sock.connect(str(path))
        sock.settimeout(max(0.0, deadline - time.monotonic()))
        sock.sendall(data)
        response = _recv(sock)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "hardware service rejected request"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("hardware IPC result must be an object")
    return result
