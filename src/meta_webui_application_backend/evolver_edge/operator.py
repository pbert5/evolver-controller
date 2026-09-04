"""Bounded read-only local operator API.

The operator API is intentionally a Unix-domain, newline-delimited JSON
protocol.  It is a view of the durable edge store, not a second control
plane.  In particular, it has no command passthrough and never shares the
hardware IPC socket.
"""
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
MAX_MESSAGE_BYTES = 64 * 1024
ALLOWED_OPERATIONS = frozenset({"capabilities", "status", "runs", "instruments", "doctor"})


class OperatorError(RuntimeError):
    """Base error for the local operator transport."""


class OperatorUnavailable(OperatorError):
    """The operator service could not be reached."""


class OperatorProtocolError(OperatorError):
    """A request or response violated the bounded protocol."""


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
                raise OperatorProtocolError("operator request is too large")
            return line
    raise OperatorProtocolError("operator request must be one newline-delimited JSON message")


def _request_value(request: Any) -> str:
    if not isinstance(request, dict) or set(request) != {"operation"} or not isinstance(request["operation"], str):
        raise OperatorProtocolError("request must contain only an operation")
    operation = request["operation"]
    if operation not in ALLOWED_OPERATIONS:
        raise OperatorProtocolError(f"unsupported operator operation: {operation}")
    return operation


def _dispatch(store: EdgeStore, operation: str) -> Any:
    if operation == "capabilities":
        return {"operations": sorted(ALLOWED_OPERATIONS), "read_only": True, "transport": "unix"}
    if operation == "status":
        return {"controller": store.identity(), "binding": store.binding(), "runs": store.list_runs()}
    if operation == "runs":
        return store.list_runs()
    if operation == "instruments":
        return store.list_instruments()
    if operation == "doctor":
        return doctor_report(store)
    raise OperatorProtocolError(f"unsupported operator operation: {operation}")


class _OperatorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: str, store: EdgeStore):
        self.store = store
        super().__init__(address, _OperatorHandler)


class _OperatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = json.loads(_readline(self.connection).decode("utf-8"))
            result = _dispatch(self.server.store, _request_value(request))  # type: ignore[attr-defined]
            self.wfile.write(_encode({"ok": True, "result": result}))
        except (UnicodeDecodeError, json.JSONDecodeError, OperatorProtocolError, OSError, KeyError, ValueError) as error:
            self.wfile.write(_encode({"ok": False, "error": str(error)}))


class OperatorServer:
    """Serve the allowlisted operator read model on a private Unix socket."""

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
            # Probe before removing a stale endpoint; never displace a live service.
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.2)
                    probe.connect(str(self.path))
                raise OperatorError(f"operator socket is already in use: {self.path}")
            except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
                self.path.unlink()
        self._server = _OperatorServer(str(self.path), self.store)
        # The edge Dev Container joins the explicitly selected operator group;
        # never make the local API world-writable.
        os.chmod(self.path, 0o660)
        self._thread = threading.Thread(target=self._server.serve_forever, name="evolver-operator", daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self.path.exists() and stat.S_ISSOCK(self.path.stat().st_mode):
            self.path.unlink()

    close = shutdown

    def __enter__(self) -> "OperatorServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.shutdown()


class OperatorClient:
    """Small client facade used by local shells and easy to inject in tests."""

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_SOCKET, *, timeout: float = 3.0):
        self.path, self.timeout = socket_path(path), timeout

    def request(self, operation: str) -> Any:
        return request(operation, self.path, self.timeout)


def request(operation: str, path: str | os.PathLike[str] = DEFAULT_SOCKET, timeout: float = 3.0) -> Any:
    """Request one allowlisted read operation from the local service."""
    _request_value({"operation": operation})
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(socket_path(path)))
            connection.sendall(_encode({"operation": operation}))
            response = json.loads(_readline(connection).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, OperatorProtocolError) as error:
        raise OperatorUnavailable(f"operator service unavailable: {error}") from error
    if not isinstance(response, dict) or response.get("ok") is not True or "result" not in response:
        raise OperatorProtocolError(str(response.get("error", "invalid operator response")))
    return response["result"]
