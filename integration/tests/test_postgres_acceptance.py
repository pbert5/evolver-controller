"""Live PostgreSQL acceptance coverage for the server-owned migration runner."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest

from meta_webui_application_backend.central_store import (
    PostgresCentralControllerStore,
    configured_store,
)
from meta_webui_application_backend.database.migrations import (
    Migration,
    MigrationError,
    apply_migrations,
    configured_migrations,
)


pytestmark = pytest.mark.integration


def _database_url() -> str:
    return os.environ.get("META_WEBUI_INTERFACE_DATABASE_URL", "")


def _query(url: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()


def _test_migration(identifier: str, sql: str, path: Path) -> Migration:
    path.write_text(sql, encoding="utf-8")
    return Migration(identifier, path, hashlib.sha256(sql.encode()).hexdigest(), sql)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(base_url: str, method: str, path: str, *, body: dict | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, dict]:
    parsed = urlsplit(base_url)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    payload = None
    request_headers = {"Accept": "application/json"}
    if body is not None:
        import json
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    try:
        connection.request(method, path, payload, request_headers)
        response = connection.getresponse()
        import json
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _start_control_process(url: str, port: int) -> subprocess.Popen[bytes]:
    root = Path(__file__).parents[2]
    environment = os.environ.copy()
    environment.update({
        "META_WEBUI_INTERFACE_DATABASE_URL": url,
        "META_WEBUI_EVOLVER_CONTROL_HOST": "127.0.0.1",
        "META_WEBUI_EVOLVER_CONTROL_PORT": str(port),
        "META_WEBUI_EVOLVER_CONTROL_SHARED_SECRET": "acceptance-gateway-secret",
        "PYTHONPATH": f"{root / 'evolver/evolver-server/src'}{os.pathsep}{environment.get('PYTHONPATH', '')}",
    })
    return subprocess.Popen(
        ["uv", "run", "--project", str(root / "evolver/evolver-server"), "evolver-control"],
        cwd=root / "evolver/evolver-server",
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_control(base_url: str, process: subprocess.Popen[bytes]) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"evolver-control exited with status {process.returncode}")
        try:
            status, payload = _request(base_url, "GET", "/health")
            if status == 200:
                return payload
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("evolver-control did not become healthy")


def _stop_control(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_postgres_migrations_apply_repeat_and_rollback_failures(tmp_path: Path) -> None:
    url = _database_url()
    if not url:
        pytest.skip("run tools/test-postgres-acceptance for the live PostgreSQL lane")

    migrations = configured_migrations()
    apply_migrations(url, migrations)
    first_history = _query(
        url,
        "SELECT migration_id, checksum FROM system.schema_migrations ORDER BY migration_id",
    )
    assert [row[0] for row in first_history] == [migration.identifier for migration in migrations]
    assert _query(url, "SELECT to_regclass('evolver.central_state'), to_regclass('system.runtime_metadata')")[0] == (
        "evolver.central_state",
        "system.runtime_metadata",
    )

    # A second run must be a no-op: this exercises the applied/checksum path
    # against the real PostgreSQL history table, not a mocked executor.
    apply_migrations(url, migrations)
    assert _query(
        url,
        "SELECT migration_id, checksum FROM system.schema_migrations ORDER BY migration_id",
    ) == first_history

    failing_path = tmp_path / "failing.sql"
    failing = _test_migration(
        "acceptance_failure",
        "CREATE TABLE evolver.acceptance_rollback (id integer); SELECT 1 / 0;",
        failing_path,
    )
    with pytest.raises(MigrationError, match="PostgreSQL migration command failed"):
        apply_migrations(url, [failing])
    assert _query(url, "SELECT to_regclass('evolver.acceptance_rollback')")[0][0] is None
    assert _query(
        url,
        "SELECT 1 FROM system.schema_migrations WHERE migration_id = 'acceptance_failure'",
    ) == []

    # The failed transaction left no partial state, so the same identifier can
    # be applied successfully once its source is corrected.
    repaired_path = tmp_path / "repaired.sql"
    repaired = _test_migration(
        "acceptance_failure",
        "CREATE TABLE evolver.acceptance_rollback (id integer);",
        repaired_path,
    )
    apply_migrations(url, [repaired])
    apply_migrations(url, [repaired])
    assert _query(url, "SELECT to_regclass('evolver.acceptance_rollback')")[0][0] == "evolver.acceptance_rollback"
    assert _query(
        url,
        "SELECT count(*) FROM system.schema_migrations WHERE migration_id = 'acceptance_failure'",
    )[0][0] == 1


def test_deployed_control_process_uses_postgres_store_across_restart() -> None:
    url = _database_url()
    if not url:
        pytest.skip("run tools/test-postgres-acceptance for the live PostgreSQL lane")

    root = Path(__file__).parents[2]
    configured = configured_store(
        json_path=root / ".acceptance-unused" / "central-controller.json",
        explicit_state_root=False,
    )
    assert isinstance(configured, PostgresCentralControllerStore)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = _start_control_process(url, port)
    try:
        first_health = _wait_for_control(base_url, process)
        assert first_health["repository"] == "postgres"

        status, token = _request(
            base_url,
            "POST",
            "/api/evolver/enrollment-tokens",
            body={"server_url": "http://acceptance.invalid"},
            headers={
                "X-Meta-Webui-Evolver-Control-Secret": "acceptance-gateway-secret",
                "X-Meta-Webui-Evolver-Operator": "acceptance",
                "X-Meta-Webui-Evolver-Permissions": "manage_controller",
            },
        )
        assert status == 201
        first_identity = token["webui_controller"]["id"]
        status, persisted_health = _request(base_url, "GET", "/health")
        assert status == 200
        assert persisted_health["webui_controller"]["id"] == first_identity
    finally:
        _stop_control(process)

    restarted = _start_control_process(url, port)
    try:
        second_health = _wait_for_control(base_url, restarted)
        assert second_health["repository"] == "postgres"
        assert second_health["webui_controller"]["id"] == first_identity
        assert _query(url, "SELECT count(*) FROM evolver.enrollment_tokens")[0][0] == 1
    finally:
        _stop_control(restarted)
