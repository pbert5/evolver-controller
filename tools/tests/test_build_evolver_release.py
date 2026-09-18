import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
BUILDER = ROOT / "tools/build_evolver_release.py"


def run_builder(output: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BUILDER), "--output", str(output), "--version", "test",
         "--git-revision", "a" * 40, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def write_artifact(path: Path, *, variant: str | None = None, bossac_version: str = "1.7.0-arduino3") -> None:
    if variant is None:
        path.write_bytes(b"native artifact")
        return
    provenance = {
        "format": 1,
        "offline": True,
        "variant": variant,
        "arduino_cli": {"version": "1.1.1"},
        "bossac": {
            "version": bossac_version,
            "source_archive_sha256": "1ae54999c1f97234c5a603eb99ad39313b11746a4ca517269a9285afa05f9100",
        },
    }
    with tarfile.open(path, "w:gz") as archive:
        data = json.dumps(provenance).encode()
        info = tarfile.TarInfo("toolchain/PROVENANCE.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def test_builder_writes_deterministic_manifest_fields_and_copies_inputs(tmp_path: Path) -> None:
    output = tmp_path / "releases"
    artifact = tmp_path / "artifact.tar.gz"
    firmware = tmp_path / "firmware.bin"
    schema = tmp_path / "schema"
    migrations = tmp_path / "migrations"
    write_artifact(artifact, variant="linux-x86_64-glibc")
    firmware.write_bytes(b"firmware")
    (schema / "actions.json").parent.mkdir()
    (schema / "actions.json").write_text("schema\n", encoding="utf-8")
    (migrations / "001.sql").parent.mkdir()
    (migrations / "001.sql").write_text("migration\n", encoding="utf-8")
    firmware_manifest = tmp_path / "firmware-manifest.json"
    firmware_manifest.write_text(
        json.dumps({
            "source_commit": "f10de7bab8aa800e0e76ec64c2851b5ed7020c1d",
            "toolchain": {"board_manager_url": "https://example.invalid", "kept": True},
        }),
        encoding="utf-8",
    )

    result = run_builder(
        output,
        "--git-revision", "a" * 40,
        "--build-timestamp", "1970-01-01T00:00:00Z",
        "--artifact", f"linux-x86_64-glibc={artifact}",
        "--firmware", str(firmware),
        "--firmware-manifest", str(firmware_manifest),
        "--schema-root", str(schema),
        "--migration-root", str(migrations),
        "--require-firmware-toolchain",
    )

    assert result.returncode == 0, result.stderr
    release = output / "test"
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_revision"] == "a" * 40
    assert manifest["build_timestamp"] == "1970-01-01T00:00:00Z"
    assert manifest["architectures"] == ["linux-x86_64-glibc"]
    assert manifest["firmware_toolchain_required"] is True
    assert manifest["artifacts"]["linux-x86_64-glibc"]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert manifest["artifacts"]["linux-x86_64-glibc"]["firmware_toolchain"]["offline"] is True
    assert manifest["firmware"]["source_commit"] == "f10de7bab8aa800e0e76ec64c2851b5ed7020c1d"
    assert "board_manager_url" not in manifest["firmware"]["toolchain"]
    assert (release / "schema/actions.json").read_text() == "schema\n"
    assert (release / "migrations/001.sql").read_text() == "migration\n"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], "at least one --artifact"),
        (["--artifact", "bad-spec"], "artifact must be PLATFORM=PATH"),
        (["--artifact", "darwin-arm64=artifact"], "unsupported or duplicate artifact platform"),
        (["--artifact", "linux-x86_64=missing"], "artifact does not exist"),
    ],
    ids=["no-artifact", "malformed-spec", "unsupported-target", "missing-input"],
)
def test_builder_rejects_invalid_artifact_matrix(tmp_path: Path, args: list[str], expected: str) -> None:
    result = run_builder(tmp_path / "releases", *args)
    assert result.returncode == 2
    assert expected in result.stderr


def test_builder_rejects_duplicate_platforms_and_existing_release(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    write_artifact(artifact)
    duplicate = run_builder(
        tmp_path / "releases",
        "--artifact", f"linux-x86_64={artifact}",
        "--artifact", f"linux-x86_64={artifact}",
    )
    assert duplicate.returncode == 2
    assert "unsupported or duplicate artifact platform" in duplicate.stderr

    release = tmp_path / "immutable" / "test"
    release.mkdir(parents=True)
    (release / "sentinel").write_text("keep", encoding="utf-8")
    immutable = run_builder(tmp_path / "immutable", "--artifact", f"linux-x86_64={artifact}")
    assert immutable.returncode == 2
    assert "already exists and is immutable" in immutable.stderr
    assert (release / "sentinel").read_text() == "keep"


@pytest.mark.parametrize(
    ("variant", "bossac_version", "expected"),
    [
        ("linux-x86_64-glibc", "1.9.1", "BOSSA"),
        ("linux-aarch64-glibc", "1.7.0-arduino3", "toolchain variant mismatch"),
    ],
    ids=["unapproved-bossa", "wrong-platform-provenance"],
)
def test_builder_rejects_invalid_toolchain_provenance_matrix(
    tmp_path: Path, variant: str, bossac_version: str, expected: str
) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    write_artifact(artifact, variant=variant, bossac_version=bossac_version)
    result = run_builder(tmp_path / "releases", "--artifact", f"linux-x86_64-glibc={artifact}")
    assert result.returncode == 2
    assert expected in result.stderr


def test_builder_rejects_non_authoritative_firmware_manifest(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    firmware = tmp_path / "firmware.bin"
    manifest = tmp_path / "firmware-manifest.json"
    write_artifact(artifact)
    firmware.write_bytes(b"firmware")
    manifest.write_text(json.dumps({"source_commit": "not-authoritative"}), encoding="utf-8")

    result = run_builder(
        tmp_path / "releases",
        "--artifact", f"linux-x86_64={artifact}",
        "--firmware", str(firmware),
        "--firmware-manifest", str(manifest),
    )
    assert result.returncode == 2
    assert "authoritative repaired revision" in result.stderr
