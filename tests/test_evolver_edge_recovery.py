from __future__ import annotations

from io import BytesIO
import json
import tarfile

import pytest
import zstandard

from meta_webui_application_backend.evolver_edge import EdgeStore, canonical_digest
from meta_webui_application_backend.evolver_edge.recovery import export_state, import_state
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError


def _bundle() -> dict[str, object]:
    value: dict[str, object] = {
        "id": "bundle-a",
        "name": "recovery fixture",
        "purpose": "test_fixture",
        "schema_version": "1",
        "execution_mode": "declarative_state_machine",
        "source": {"experiment_id": "definition-a", "dataset_revision": "1"},
        "resolved_definition": {"content": {"name": "source"}, "media_type": "application/json"},
        "execution_plan": {"content": {"states": {"growth": {}}}, "media_type": "application/json"},
        "runtime_parameters": [],
        "source_metadata": [],
    }
    value["digest"] = canonical_digest(value)
    return value


def _rewrite_archive(source, destination, mutate) -> None:
    raw = zstandard.ZstdDecompressor().decompress(source.read_bytes())
    with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
        payload = json.loads(archive.extractfile("recovery.json").read())
    mutate(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    tar_bytes = BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as archive:
        info = tarfile.TarInfo("recovery.json")
        info.size = len(encoded)
        archive.addfile(info, BytesIO(encoded))
    destination.write_bytes(zstandard.ZstdCompressor().compress(tar_bytes.getvalue()))


def _export_fixture(tmp_path):
    source = tmp_path / "source"
    archive = tmp_path / "recovery.tar.zst"
    with EdgeStore(source) as edge:
        edge.put_bundle(_bundle())
        edge.create_run(run_id="run-a", bundle_id="bundle-a", instrument_ids=["instrument-a"])
        edge.spool_telemetry(stream_id="instrument-a/od", sequence=1, payload={"od": 0.22})
        export_state(edge, archive)
    return archive


@pytest.mark.parametrize("tamper", [
    pytest.param(lambda snapshot: snapshot["bundles"][0]["execution_plan"]["content"]["states"].update({"tampered": {}}), id="execution-plan"),
    pytest.param(lambda snapshot: snapshot["run_revisions"][0]["effective_state"].update({"tampered": True}), id="revision"),
    pytest.param(lambda snapshot: snapshot["telemetry"][0]["payload"].update({"od": 999}), id="telemetry"),
])
def test_tampered_immutable_recovery_records_are_rejected_atomically(tmp_path, tamper):
    archive = _export_fixture(tmp_path)
    tampered = tmp_path / "tampered.tar.zst"
    _rewrite_archive(archive, tampered, tamper)
    destination = tmp_path / "destination"

    with EdgeStore(destination) as edge:
        with pytest.raises(EdgeStoreError, match="digest"):
            import_state(edge, tampered)
        assert edge._connection.execute("SELECT COUNT(*) FROM bundles").fetchone()[0] == 0
        assert edge._connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert edge._connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 0
        assert edge._connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 0
