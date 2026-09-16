"""Bounded typed Unix operator protocol for the controller-owned read model."""
from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import threading
from pathlib import Path
from typing import Any

from .doctor import doctor_report
from .store import EdgeStore

DEFAULT_SOCKET = "/run/evolver-controller/operator.sock"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
OPERATION_METADATA: dict[str, dict[str, str]] = {
    "binding": {"access": "read", "mode": "live"},
    "capabilities": {"access": "read", "mode": "live"},
    "doctor": {"access": "read", "mode": "live"},
    "instruments": {"access": "read", "mode": "live"},
    "runs": {"access": "read", "mode": "live"},
    "status": {"access": "read", "mode": "live"},
}
ALLOWED_OPERATIONS = frozenset(OPERATION_METADATA)


class OperatorError(RuntimeError):
    kind = "operator_error"

    def __init__(self, message: str, *, kind: str | None = None):
        super().__init__(message)
        if kind is not None:
            self.kind = kind


class OperatorUnavailable(OperatorError):
    kind = "unavailable"


class OperatorProtocolError(OperatorError):
    kind = "protocol_error"


def socket_path(value: str | os.PathLike[str] | None = None) -> Path:
    return Path(value or os.environ.get("EVOLVER_OPERATOR_SOCKET", DEFAULT_SOCKET))


def _encode(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _readline(connection: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= MAX_MESSAGE_BYTES:
        chunk = connection.recv(min(4096, MAX_MESSAGE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            line, _, _ = bytes(data).partition(b"\n")
            if len(line) > MAX_MESSAGE_BYTES:
                raise OperatorProtocolError("operator request is too large", kind="request_too_large")
            return line
    if len(data) > MAX_MESSAGE_BYTES:
        raise OperatorProtocolError("operator request is too large", kind="request_too_large")
    raise OperatorProtocolError("operator request must be one newline-delimited JSON message", kind="invalid_request")


def _request_value(request: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(request, dict) or set(request) != {"operation", "params"}:
        raise OperatorProtocolError("request must contain operation and params", kind="invalid_request")
    if not isinstance(request["operation"], str) or not request["operation"]:
        raise OperatorProtocolError("operation must be a non-empty string", kind="invalid_request")
    if not isinstance(request["params"], dict):
        raise OperatorProtocolError("params must be an object", kind="invalid_request")
    operation = request["operation"]
    if operation not in ALLOWED_OPERATIONS:
        raise OperatorProtocolError(f"unsupported operator operation: {operation}", kind="unsupported_operation")
    return operation, request["params"]


def _dispatch(store: EdgeStore, operation: str, params: dict[str, Any]) -> Any:
    if params:
        raise OperatorProtocolError("params must be empty for this operation", kind="invalid_request")
    if operation == "capabilities":
        return {"protocol_version": PROTOCOL_VERSION, "operations": OPERATION_METADATA,
                "read_only": True, "transport": "unix"}
    if operation == "status":
        return {"controller": store.identity(), "binding": store.binding(), "runs": store.list_runs()}
    if operation == "binding":
        return store.binding()
    if operation == "runs":
        return store.list_runs()
    if operation == "instruments":
        return store.list_instruments()
    if operation == "doctor":
        return doctor_report(store)
    raise OperatorProtocolError(f"unsupported operator operation: {operation}", kind="unsupported_operation")


def _error(error: OperatorError) -> dict[str, Any]:
    return {"ok": False, "error": {"kind": error.kind, "message": str(error)}}


class _OperatorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: str, store: EdgeStore):
        self.store = store
        super().__init__(address, _OperatorHandler)


class _OperatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            try:
                payload = json.loads(_readline(self.connection).decode("utf-8"))
            except json.JSONDecodeError as error:
                raise OperatorProtocolError("operator request is malformed JSON", kind="malformed_json") from error
            operation, params = _request_value(payload)
            result = _dispatch(self.server.store, operation, params)  # type: ignore[attr-defined]
            self.wfile.write(_encode({"ok": True, "result": result}))
        except OperatorError as error:
            self.wfile.write(_encode(_error(error)))
        except (UnicodeDecodeError, OSError, KeyError, ValueError):
            self.wfile.write(_encode(_error(OperatorError("operator request failed", kind="internal_error"))))


class OperatorServer:
    def __init__(self, store: EdgeStore, path: str | os.PathLike[str] = DEFAULT_SOCKET):
        self.store = store
        self.path = socket_path(path)
        self._server: _OperatorServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "OperatorServer":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.stat().st_mode):
                raise OperatorError(f"operator socket path is not a socket: {self.path}")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.2); probe.connect(str(self.path))
                raise OperatorError(f"operator socket is already in use: {self.path}")
            except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
                self.path.unlink()
        self._server = _OperatorServer(str(self.path), self.store)
        os.chmod(self.path, 0o660)
        self._thread = threading.Thread(target=self._server.serve_forever, name="evolver-operator", daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown(); server.server_close()
        if self.path.exists() and stat.S_ISSOCK(self.path.stat().st_mode):
            self.path.unlink()

    close = shutdown

    def __enter__(self) -> "OperatorServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.shutdown()


class OperatorClient:
    def __init__(self, path: str | os.PathLike[str] = DEFAULT_SOCKET, *, timeout: float = 3.0):
        self.path, self.timeout = socket_path(path), timeout

    def request(self, operation: str, params: dict[str, Any] | None = None) -> Any:
        return request(operation, self.path, self.timeout, params=params)


def request(operation: str, path: str | os.PathLike[str] = DEFAULT_SOCKET, timeout: float = 3.0,
            *, params: dict[str, Any] | None = None) -> Any:
    envelope = {"operation": operation, "params": {} if params is None else params}
    _request_value(envelope)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(socket_path(path)))
            connection.sendall(_encode(envelope))
            response = json.loads(_readline(connection).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OperatorUnavailable(f"operator service unavailable: {error}", kind="unavailable") from error
    if isinstance(response, dict) and response.get("ok") is True and "result" in response \
            and set(response) == {"ok", "result"}:
        return response["result"]
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(response, dict) and response.get("ok") is False and isinstance(error, dict) \
            and set(error) == {"kind", "message"} and all(isinstance(error[key], str) for key in error):
        raise OperatorProtocolError(error["message"], kind=error["kind"])
    raise OperatorProtocolError("invalid operator response", kind="invalid_response")
