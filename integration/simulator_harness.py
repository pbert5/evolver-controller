"""Reusable, hardware-free composition for the simulator acceptance lane.

The harness intentionally composes the public process boundaries in one test
process: HTTP central control, a durable edge SQLite store, edge sync, the
deterministic simulator, the read-only operator socket, and metactl's HTTP
transport.  A temporary central state root selects the repository's supported
JSON compatibility backend; production PostgreSQL is outside this lane.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import secrets
import shutil
import ssl
import subprocess
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def _add_component_paths() -> None:
    paths = [ROOT / relative for relative in (
        "metactl",
        "evolver/evolver-controller/src",
        "evolver/evolver-server/src",
    )]
    # The extracted controller package contains the local operator boundary;
    # retain it as the first owner when server and controller share a namespace.
    for path_value in reversed(paths):
        path = str(path_value)
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def _load_metactl() -> Any:
    path = ROOT / "metactl/tools/metactl.py"
    spec = importlib.util.spec_from_file_location("simulator_acceptance_metactl", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load metactl from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tls_material(root: Path) -> tuple[Path, Path]:
    """Create disposable loopback TLS material for this acceptance process."""
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("simulator acceptance requires openssl to create its ephemeral certificate")
    certificate = root / "simulator-acceptance.crt"
    private_key = root / "simulator-acceptance.key"
    try:
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
             "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("simulator acceptance could not create its ephemeral certificate") from exc
    return certificate, private_key


def _https_send(context: ssl.SSLContext, url: str, method: str, body: Any,
                headers: Any, timeout: float) -> tuple[int, bytes]:
    parts = urlsplit(url)
    connection = http.client.HTTPSConnection(
        parts.hostname, parts.port, context=context, timeout=timeout
    )
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        connection.request(method, path, body=data, headers=dict(headers))
        response = connection.getresponse()
        return int(response.status), response.read()
    finally:
        connection.close()


def _https_json_send(context: ssl.SSLContext, url: str, body: Any,
                     headers: Any, timeout: float) -> tuple[int, dict[str, Any]]:
    status, payload = _https_send(context, url, "POST", body, headers, timeout)
    return status, json.loads(payload)


@dataclass
class SimulatorAcceptanceHarness:
    """Own all temporary resources for one isolated simulator acceptance run."""

    root: Path
    central_root: Path
    edge_root: Path
    operator_socket: Path
    server: ThreadingHTTPServer
    server_thread: Thread
    edge: Any
    simulator: Any
    manual_executor: Any
    sync: Any
    operator: Any
    operator_client: Any
    metactl: Any
    transport: Any
    server_url: str
    shared_secret: str
    client_context: ssl.SSLContext

    @classmethod
    def create(cls, root: Path) -> "SimulatorAcceptanceHarness":
        _add_component_paths()
        from meta_webui_application_backend.evolver_control.service import EvolverControlHandler
        from meta_webui_application_backend.evolver_edge import EdgeStore, ManualCommandExecutor, SyncClient
        from meta_webui_application_backend import evolver_edge as edge_package
        controller_edge = str(ROOT / "evolver/evolver-controller/src/meta_webui_application_backend/evolver_edge")
        if controller_edge not in edge_package.__path__:
            edge_package.__path__.append(controller_edge)
        from meta_webui_application_backend.evolver_edge.operator import OperatorClient, OperatorServer
        from meta_webui_application_backend.evolver_edge.simulator import EvolverSimulator
        from tools.metactl_transport import HTTPTransport

        central_root = root / "central"
        edge_root = root / "edge"
        operator_socket = root / "operator.sock"
        central_root.mkdir()
        edge_root.mkdir()
        os.environ["META_WEBUI_EVOLVER_STATE_ROOT"] = str(central_root)
        shared_secret = secrets.token_urlsafe(32)
        os.environ["META_WEBUI_EVOLVER_CONTROL_SHARED_SECRET"] = shared_secret

        server = ThreadingHTTPServer(("127.0.0.1", 0), EvolverControlHandler)
        certificate, private_key = _make_tls_material(root)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(certificate, private_key)
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        server.daemon_threads = True
        server_thread = Thread(target=server.serve_forever, name="simulator-acceptance-server", daemon=True)
        server_thread.start()
        server_url = f"https://127.0.0.1:{server.server_port}"
        os.environ["META_WEBUI_EVOLVER_CONTROLLER_ENDPOINTS"] = json.dumps([{
            "id": "simulator-acceptance",
            "label": "Simulator acceptance",
            "url": server_url,
            "enabled": True,
            "controller_reachable": True,
        }])
        client_context = ssl.create_default_context(cafile=str(certificate))

        edge = EdgeStore(edge_root)
        simulator = EvolverSimulator(edge, instruments=1, vials_per_instrument=2, seed=7, tick_seconds=60)
        # Compose the same typed, durable command boundary used by the
        # production controller service.  Acceptance must exercise SyncClient
        # delivery and acknowledgement, never call the executor as a shortcut.
        manual_executor = ManualCommandExecutor(edge, simulator.device_sink)
        operator = OperatorServer(edge, operator_socket).start()
        sync = SyncClient(edge, timeout=3, manual_executor=manual_executor)
        sync.transport = lambda url, body, headers, timeout: _https_json_send(
            client_context, url, body, headers, timeout
        )
        metactl = _load_metactl()
        transport = HTTPTransport(
            base_url=server_url,
            operator="acceptance",
            shared_secret=shared_secret,
            permissions="view,manage_controller,evolver:read,operate_run",
            sender=lambda url, method, body, headers, timeout: _https_send(
                client_context, url, method, body, headers, timeout
            ),
        )
        return cls(
            root, central_root, edge_root, operator_socket, server, server_thread,
            edge, simulator, manual_executor, sync, operator,
            OperatorClient(operator_socket), metactl, transport, server_url,
            shared_secret, client_context,
        )

    def enroll(self) -> dict[str, Any]:
        issued = self.transport.action("evolver.controllers.add", {"server_url": self.server_url})
        self.sync.enroll(server=self.server_url, token=issued["enrollment_token"])
        return issued

    def restart_edge(self) -> None:
        self.operator.shutdown()
        self.edge.close()
        from meta_webui_application_backend.evolver_edge import EdgeStore, ManualCommandExecutor, SyncClient
        from meta_webui_application_backend.evolver_edge.operator import OperatorClient, OperatorServer
        from meta_webui_application_backend.evolver_edge.simulator import EvolverSimulator

        self.edge = EdgeStore(self.edge_root)
        self.simulator = EvolverSimulator(self.edge, instruments=1, vials_per_instrument=2, seed=7, tick_seconds=60)
        self.manual_executor = ManualCommandExecutor(self.edge, self.simulator.device_sink)
        self.operator = OperatorServer(self.edge, self.operator_socket).start()
        self.operator_client = OperatorClient(self.operator_socket)
        self.sync = SyncClient(self.edge, timeout=3, manual_executor=self.manual_executor)
        self.sync.transport = lambda url, body, headers, timeout: _https_json_send(
            self.client_context, url, body, headers, timeout
        )

    def metactl_json(self, *arguments: str) -> dict[str, Any]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.metactl.main(["--json", *arguments], transport=self.transport)
        if result != 0:
            raise AssertionError(f"metactl exited {result}: {output.getvalue()}")
        import json
        for line in reversed(output.getvalue().splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        raise AssertionError(f"metactl produced no JSON output: {output.getvalue()!r}")

    def close(self) -> None:
        self.operator.shutdown()
        self.edge.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)
