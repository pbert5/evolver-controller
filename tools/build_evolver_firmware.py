#!/usr/bin/env python3
"""Build the pinned vendored eVOLVER firmware and emit its provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SHA256_LENGTH = 64


def arduino_data_dir() -> Path:
    value = os.environ.get("ARDUINO_DIRECTORIES_DATA")
    if not value:
        raise SystemExit("ARDUINO_DIRECTORIES_DATA is required; refusing hidden developer Arduino state")
    return Path(value).resolve()


def validate_upload_closure(data_dir: Path, toolchain: dict) -> None:
    """Validate the board-selected uploader before compiling or touching USB."""
    package, version = toolchain["board_core"].split("@", 1)
    vendor, architecture = package.split(":", 1)
    core_path = data_dir / "packages" / vendor / "hardware" / architecture / version
    boards = (core_path / "boards.txt").read_text(encoding="utf-8")
    platform = (core_path / "platform.txt").read_text(encoding="utf-8")
    board_prefix = "samd21_mini."
    if f"{board_prefix}upload.tool=bossac" not in boards:
        raise SystemExit("SparkFun board definition no longer selects bossac; inspect the pinned core")
    if f"{board_prefix}upload.use_1200bps_touch=true" not in boards:
        raise SystemExit("SparkFun board definition lacks the required 1200-baud touch")
    marker = "runtime.tools.bossac-1.7.0-arduino3.path"
    if marker not in platform:
        raise SystemExit("SparkFun platform no longer resolves the expected bossac uploader")
    required = {item["version"] for item in toolchain["dependencies"]
                if item["id"] == "arduino:bossac"}
    tools_root = data_dir / "packages" / "arduino" / "tools" / "bossac"
    present = {path.name for path in tools_root.iterdir() if path.is_dir()} if tools_root.is_dir() else set()
    missing = sorted(required - present)
    if missing:
        raise SystemExit("missing pinned upload tools: " + ", ".join(missing))
    selected_version = toolchain.get("board_uploader", {}).get("version", "1.7.0-arduino3")
    selected = tools_root / selected_version / "bin" / "bossac"
    if not selected.is_file() or not os.access(selected, os.X_OK):
        raise SystemExit(f"board-selected bossac is not executable: {selected}")
    provenance_path = selected.parent.parent / "provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"board-selected bossac provenance is missing or invalid: {provenance_path}") from error
    uploader = toolchain.get("board_uploader", {})
    expected_source = uploader.get("linux_x86_64_archive_sha256")
    actual_source = provenance.get("source_archive_sha256")
    expected_executable = provenance.get("executable_sha256")
    if (not isinstance(expected_source, str) or len(expected_source) != SHA256_LENGTH or
            actual_source != expected_source):
        raise SystemExit("board-selected bossac source archive provenance mismatch")
    if not isinstance(expected_executable, str) or len(expected_executable) != SHA256_LENGTH:
        raise SystemExit("board-selected bossac executable provenance is incomplete")
    actual_executable = digest(selected)
    if actual_executable != expected_executable:
        raise SystemExit("board-selected bossac executable provenance mismatch")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def revision(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path("applications/evolver/firmware"))
    parser.add_argument("--source-commit")
    parser.add_argument("--build-revision")
    parser.add_argument("--build-timestamp", help="UTC ISO-8601 timestamp; defaults to current UTC time")
    args = parser.parse_args()
    root = args.source.resolve()
    config = json.loads((root / "build-config.json").read_text(encoding="utf-8"))
    toolchain = config["toolchain"]
    data_dir = arduino_data_dir()
    sketch = root / config["sketch"]
    libraries = [root / path for path in config["libraries"]]
    if not (sketch / "MINEVOLVER.ino").is_file() or not all(path.is_dir() for path in libraries):
        raise SystemExit("firmware source or one of its vendored libraries is missing")
    validate_upload_closure(data_dir, toolchain)

    version = subprocess.check_output(["arduino-cli", "version", "--format", "json"], text=True)
    version_payload = json.loads(version)
    actual_cli = version_payload.get("VersionString") or version_payload.get("Version", "")
    if actual_cli != toolchain["arduino_cli"]:
        raise SystemExit(f"arduino-cli {actual_cli!r} does not match pinned {toolchain['arduino_cli']!r}")
    core = subprocess.check_output(["arduino-cli", "core", "list"], text=True)
    installed = {}
    for line in core.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1][0].isdigit():
            installed[fields[0]] = fields[1]
    core_id, core_version = toolchain["board_core"].split("@", 1)
    if installed.get(core_id) != core_version:
        raise SystemExit(f"board core {toolchain['board_core']} is not installed")
    missing = []
    for dependency in toolchain.get("dependencies", []):
        dependency_id, expected = dependency["id"], dependency["version"]
        # Arduino CLI 1.1.1 exposes platform versions through `core list`,
        # while tool versions are only validated during compile. The exact
        # tool dependency set is still recorded in build-config.json and the
        # clean bootstrap installs it through the pinned core metadata.
        actual = installed.get(dependency_id) if dependency_id.endswith(":samd") else expected
        if actual != expected:
            missing.append(f"{dependency['id']}@{expected} (found {actual or 'none'})")
    if missing:
        raise SystemExit("missing pinned Arduino dependencies: " + ", ".join(missing))

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command = ["arduino-cli", "compile", "--fqbn", toolchain["fqbn"], "--build-path", str(output / "build"), "--export-binaries"]
    # Arduino CLI expects a directory containing libraries, not individual
    # library roots. The directory is checked in and contains only the
    # canonical production dependencies selected by build-config.json.
    command += ["--libraries", str(root / "source/libraries")]
    command += config.get("flags", [])
    command.append(str(sketch))
    subprocess.run(command, check=True)
    candidates = sorted((output / "build").rglob("*.bin")) + sorted((output / "build").rglob("*.hex"))
    if not candidates:
        raise SystemExit("arduino-cli did not produce a .bin or .hex firmware artifact")
    artifact = candidates[0]
    final = output / f"samd21-minievolver-{config['firmware_version']}{artifact.suffix}"
    artifact.replace(final)
    payload = {
        "variant": "samd21-minievolver",
        "version": config["firmware_version"],
        "artifact": final.name,
        "sha256": digest(final),
        "size": final.stat().st_size,
        "source_commit": args.source_commit or config["source_commit"],
        "build_revision": args.build_revision or revision(root.parent.parent.parent),
        "toolchain": {"arduino_cli": actual_cli, "board_core": toolchain["board_core"], "fqbn": toolchain["fqbn"],
                       "board_manager_url": toolchain["board_manager_url"],
                       "core_archive_url": toolchain["core_archive_url"],
                       "core_archive_sha256": toolchain["core_archive_sha256"],
                       "core_archive_size": toolchain["core_archive_size"],
                       "dependencies": toolchain.get("dependencies", [])},
        "protocol_version": config["protocol_version"],
        "hardware_protocol_version": config["hardware_protocol_version"],
        "external_libraries": config.get("external_libraries", []),
        "build_timestamp": args.build_timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    (output / "firmware-manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
