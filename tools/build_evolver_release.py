#!/usr/bin/env python3
"""Generate an immutable eVOLVER release directory and SHA-256 manifest.

This tool intentionally does not sign or upload artifacts.  CI/release tooling
can add a detached signature to the generated manifest after this stable,
digest-verified boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


AUTHORITATIVE_FIRMWARE_SOURCE = "952a6fd713c40caa072444a0e0e3fc4fc6ee4639"
TARGETS = {"linux-x86_64-glibc", "linux-x86_64-nixos", "linux-aarch64-glibc"}
PUBLISHABLE_TARGETS = {"linux-x86_64-glibc", "linux-x86_64-nixos"}
LEGACY_TARGETS = {"linux-x86_64", "linux-aarch64"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def artifact_toolchain(source: Path) -> dict | None:
    """Read the immutable toolchain contract without trusting archive paths."""
    try:
        with tarfile.open(source, "r:gz") as archive:
            member = archive.getmember("toolchain/PROVENANCE.json")
            if not member.isfile():
                return None
            raw = archive.extractfile(member)
            if raw is None:
                return None
            metadata = json.loads(raw.read().decode("utf-8"))
    except (KeyError, OSError, tarfile.TarError, json.JSONDecodeError):
        return None
    if metadata.get("format") != 1 or metadata.get("offline") is not True:
        raise ValueError("native artifact toolchain provenance is not an offline format-1 bundle")
    if metadata.get("variant") not in TARGETS:
        raise ValueError("native artifact toolchain has an unknown platform variant")
    bossac = metadata.get("bossac", {})
    if bossac.get("version") != "1.7.0-arduino3" or bossac.get("source_archive_sha256") != "1ae54999c1f97234c5a603eb99ad39313b11746a4ca517269a9285afa05f9100":
        raise ValueError("native artifact toolchain does not pin the production BOSSA")
    if metadata.get("arduino_cli", {}).get("version") != "1.1.1":
        raise ValueError("native artifact toolchain does not pin arduino-cli 1.1.1")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="release root (contains VERSION/)")
    parser.add_argument("--version", required=True)
    parser.add_argument("--protocol-version", default="1")
    parser.add_argument("--git-revision", default=None)
    parser.add_argument("--artifact", action="append", metavar="TARGET=PATH",
                        help="native artifact input; repeat for canonical targets")
    # Kept as a compatibility interface for existing callers. New release
    # workflows use --artifact so an x86_64-only release is explicit.
    parser.add_argument("--x86_64", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--aarch64", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--firmware", type=Path, default=None,
                        help="prebuilt SAMD21 firmware binary (optional for development releases)")
    parser.add_argument("--firmware-version", default="0.2")
    parser.add_argument("--firmware-manifest", type=Path)
    parser.add_argument("--schema-root", type=Path, help="application protocol metadata to include in the release")
    parser.add_argument("--migration-root", type=Path, help="database migration metadata to include in the release")
    parser.add_argument("--require-firmware-toolchain", action="store_true",
                        help="require every native artifact to carry the immutable offline toolchain")
    parser.add_argument("--build-timestamp")
    args = parser.parse_args()
    revision = args.git_revision or git_revision()
    destination = args.output / args.version
    if destination.exists() and any(destination.iterdir()):
        parser.error(f"release ID already exists and is immutable: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    artifact_inputs: dict[str, Path] = {}
    for item in args.artifact or []:
        try:
            platform, raw_path = item.split("=", 1)
        except ValueError:
            parser.error(f"artifact must be PLATFORM=PATH: {item}")
        if platform not in PUBLISHABLE_TARGETS | LEGACY_TARGETS or platform in artifact_inputs:
            parser.error(f"unsupported or duplicate artifact platform: {platform}")
        artifact_inputs[platform] = Path(raw_path)
    if args.x86_64:
        artifact_inputs.setdefault("linux-x86_64", args.x86_64)
    if args.aarch64:
        artifact_inputs.setdefault("linux-aarch64", args.aarch64)
    if not artifact_inputs:
        parser.error("at least one --artifact PLATFORM=PATH is required")
    artifacts = {}
    for platform, source in sorted(artifact_inputs.items()):
        if not source.is_file():
            parser.error(f"artifact does not exist: {source}")
        filename = f"{platform}-{args.version}.tar.gz"
        target = destination / filename
        shutil.copyfile(source, target)
        if platform in LEGACY_TARGETS:
            os_name, architecture, runtime = "linux", platform.removeprefix("linux-"), None
        else:
            os_name, architecture, runtime = platform.split("-")
        entry = {"url": f"/releases/evolver/{args.version}/{filename}",
                 "sha256": sha256(target), "size": target.stat().st_size,
                 "target": platform, "platform": os_name, "architecture": architecture}
        if runtime:
            entry["runtime"] = runtime
        try:
            toolchain = artifact_toolchain(target)
        except ValueError as error:
            parser.error(str(error))
        if toolchain is not None:
            if platform in TARGETS and toolchain.get("variant") != platform:
                parser.error(f"artifact {platform} toolchain variant mismatch: {toolchain.get('variant')}")
            entry["firmware_toolchain"] = toolchain
        artifacts[platform] = entry
    firmware = None
    if args.firmware is not None:
        if not args.firmware.is_file():
            parser.error(f"firmware artifact does not exist: {args.firmware}")
        filename = f"samd21-minievolver-{args.firmware_version}-{args.version}{args.firmware.suffix or '.bin'}"
        target = destination / filename
        shutil.copyfile(args.firmware, target)
        firmware = {
            "variant": "samd21-minievolver",
            "version": args.firmware_version,
            "url": f"/releases/evolver/{args.version}/{filename}",
            "sha256": sha256(target),
            "size": target.stat().st_size,
        }
        if args.firmware_manifest:
            supplied_manifest = json.loads(args.firmware_manifest.read_text(encoding="utf-8"))
            # Accept both the firmware-manifest.json emitted by the firmware
            # builder and a release manifest when reconstructing an immutable
            # release around an already-approved firmware artifact.
            if isinstance(supplied_manifest.get("firmware"), dict):
                supplied_manifest = supplied_manifest["firmware"]
            firmware.update(supplied_manifest)
            if firmware.get("source_commit") != AUTHORITATIVE_FIRMWARE_SOURCE:
                parser.error("firmware manifest source_commit is not the authoritative repaired revision")
            # Build-time acquisition URLs belong in the checked-in toolchain
            # provenance, not in the production payload. The edge must never
            # need GitHub/SparkFun/Arduino network access at install time.
            toolchain = firmware.get("toolchain")
            if isinstance(toolchain, dict):
                toolchain.pop("board_manager_url", None)
                toolchain.pop("core_archive_url", None)
            firmware["artifact"] = filename
            firmware["url"] = f"/releases/evolver/{args.version}/{filename}"
            firmware["sha256"] = sha256(target)
            firmware["size"] = target.stat().st_size
    payload = {"version": args.version, "git_revision": revision, "protocol_version": args.protocol_version,
               "platform": "linux", "architectures": sorted(artifacts),
               "build_timestamp": args.build_timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
               "install_type": "native-wheelhouse", "required_controller_schema_version": "1",
               "required_cli_capabilities": ["lifecycle-plan --current-state"],
               "schema_protocol_metadata": {"protocol_version": args.protocol_version},
               "artifacts": artifacts,
               "signature": {"status": "unsigned", "algorithm": None, "key_id": None}}
    if args.require_firmware_toolchain:
        payload["firmware_toolchain_required"] = True
    if firmware:
        payload["firmware"] = firmware
    for label, source in (("schema", args.schema_root), ("migrations", args.migration_root)):
        if source:
            if not source.exists():
                parser.error(f"{label} root does not exist: {source}")
            target = destination / label
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target / source.name)
    (destination / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
