"""Live PostgreSQL acceptance coverage for the server-owned migration runner."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg
import pytest

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
