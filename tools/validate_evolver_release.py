#!/usr/bin/env python3
"""Validate a generated eVOLVER release without network access."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

from archive_contract import validate_archive_members

SHA = re.compile(r"[0-9a-f]{64}\Z")
AUTHORITATIVE_FIRMWARE_SOURCE = "83483cda621a2e913ad778ae62294872084a507a"
BOSSA_VERSION = "1.7.0-arduino3"
BOSSA_ARCHIVE_SHA256 = "1ae54999c1f97234c5a603eb99ad39313b11746a4ca517269a9285afa05f9100"
TARGETS = {"linux-x86_64-glibc", "linux-x86_64-nixos", "linux-aarch64-glibc"}
PUBLISHABLE_TARGETS = {"linux-x86_64-glibc", "linux-x86_64-nixos"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_toolchain_bundle(path: Path, metadata: dict, platform: str) -> None:
    if metadata.get("format") != 1 or metadata.get("offline") is not True:
        raise SystemExit(f"native artifact has no offline toolchain bundle: {path.name}")
    variants = PUBLISHABLE_TARGETS
    if metadata.get("variant") not in variants:
        raise SystemExit(f"native artifact has unknown toolchain variant: {path.name}")
    if metadata["variant"] != platform:
        raise SystemExit(f"native artifact toolchain variant does not match {platform}: {path.name}")
    cli = metadata.get("arduino_cli", {})
    bossac = metadata.get("bossac", {})
    if cli.get("version") != "1.1.1" or bossac.get("version") != BOSSA_VERSION or bossac.get("source_archive_sha256") != BOSSA_ARCHIVE_SHA256:
        raise SystemExit(f"native artifact toolchain pins do not match production: {path.name}")
    try:
        with tarfile.open(path, "r:gz") as archive:
            try:
                validate_archive_members(archive)
            except ValueError as error:
                raise SystemExit(str(error)) from error
            names = set(archive.getnames())
            for required in ("toolchain/PROVENANCE.json", "toolchain/arduino-cli"):
                if required not in names:
                    raise SystemExit(f"native artifact toolchain is incomplete ({required}): {path.name}")
            if not any(name.startswith("toolchain/arduino-data/") for name in names):
                raise SystemExit(f"native artifact toolchain is incomplete (toolchain/arduino-data): {path.name}")
            if not any(name.startswith("toolchain/arduino-libraries/") for name in names):
                raise SystemExit(f"native artifact toolchain is incomplete (toolchain/arduino-libraries): {path.name}")
            cli_member = archive.getmember("toolchain/arduino-cli")
            if cli.get("sha256") and cli_member.isfile():
                raw = archive.extractfile(cli_member)
                if raw is not None:
                    import hashlib
                    if hashlib.sha256(raw.read()).hexdigest() != cli["sha256"]:
                        raise SystemExit(f"native artifact arduino-cli digest mismatch: {path.name}")
            bossac_path = bossac.get("path")
            if bossac_path:
                if platform == "linux-x86_64-nixos" and bossac_path != f"toolchain/arduino-data/packages/arduino/tools/bossac/{BOSSA_VERSION}/bossac":
                    raise SystemExit(f"native artifact NixOS BOSSA provenance must name the Arduino root wrapper: {path.name}")
                bossac_member = archive.getmember(bossac_path)
                raw = archive.extractfile(bossac_member)
                if raw is None or not SHA.fullmatch(bossac.get("sha256", "")) or hashlib.sha256(raw.read()).hexdigest() != bossac["sha256"]:
                    raise SystemExit(f"native artifact BOSSA digest mismatch: {path.name}")
                if platform == "linux-x86_64-nixos":
                    wrapper_digest = bossac.get("wrapper_sha256")
                    if not SHA.fullmatch(wrapper_digest or "") or wrapper_digest != bossac["sha256"]:
                        raise SystemExit(f"native artifact NixOS BOSSA wrapper digest does not match its declared path: {path.name}")
                    wrapper_member = archive.getmember(bossac_path)
                    wrapper_raw = archive.extractfile(wrapper_member)
                    store_executable = bossac.get("store_executable")
                    if wrapper_raw is None or not isinstance(store_executable, str):
                        raise SystemExit(f"native artifact NixOS BOSSA wrapper provenance is incomplete: {path.name}")
                    wrapper = wrapper_raw.read().decode("utf-8", errors="replace")
                    if f"exec {store_executable} \"$@\"" not in wrapper:
                        raise SystemExit(f"native artifact NixOS BOSSA wrapper is not transparent: {path.name}")
                    if "|| true" in wrapper or "exit 0" in wrapper:
                        raise SystemExit(f"native artifact NixOS BOSSA wrapper masks executable failures: {path.name}")
            if platform == "linux-x86_64-nixos":
                if bossac.get("delivery") != "nix-store-export-v1":
                    raise SystemExit(f"native artifact NixOS BOSSA lacks closure delivery: {path.name}")
                closure = bossac.get("closure_artifact")
                closure_sha = bossac.get("closure_sha256")
                root = bossac.get("store_root")
                paths = bossac.get("closure_paths")
                if not isinstance(closure, str) or not isinstance(closure_sha, str) or not isinstance(root, str) or not isinstance(paths, list) or root not in paths:
                    raise SystemExit(f"native artifact NixOS BOSSA closure provenance is incomplete: {path.name}")
                store_executable = bossac.get("store_executable")
                store_digest = bossac.get("store_executable_sha256")
                if not isinstance(store_executable, str) or not store_executable.startswith("/nix/store/") or not SHA.fullmatch(store_digest or ""):
                    raise SystemExit(f"native artifact NixOS BOSSA store executable provenance is incomplete: {path.name}")
                member = archive.getmember(closure)
                raw = archive.extractfile(member)
                if raw is None or hashlib.sha256(raw.read()).hexdigest() != closure_sha:
                    raise SystemExit(f"native artifact NixOS BOSSA closure digest mismatch: {path.name}")
    except KeyError as error:
        raise SystemExit(f"native artifact toolchain is missing a declared file: {path.name}") from error
    except tarfile.TarError as error:
        raise SystemExit(f"native artifact is not a readable tarball: {path.name}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    manifest_path = args.release / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = ("version", "git_revision", "platform", "build_timestamp", "install_type", "protocol_version", "artifacts")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise SystemExit("manifest missing: " + ", ".join(missing))
    if not re.fullmatch(r"[0-9a-f]{7,64}", payload["git_revision"]):
        raise SystemExit("manifest git_revision is not hexadecimal")
    for name, entry in payload["artifacts"].items():
        if name not in PUBLISHABLE_TARGETS and name not in {"linux-x86_64", "linux-aarch64"}:
            raise SystemExit(f"manifest has unknown artifact target: {name}")
        if name in TARGETS:
            expected = {"target": name, "platform": "linux", "architecture": name.split("-")[1], "runtime": name.split("-")[2]}
            if any(entry.get(key) != value for key, value in expected.items()):
                raise SystemExit(f"manifest target metadata disagrees with artifact key: {name}")
        path = args.release / name.split("/")[-1] if not entry["url"].startswith("/") else args.release / Path(entry["url"]).name
        if not path.is_file():
            raise SystemExit(f"missing artifact: {path.name}")
        if not SHA.fullmatch(entry.get("sha256", "")) or digest(path) != entry["sha256"] or path.stat().st_size != entry.get("size"):
            raise SystemExit(f"artifact integrity failure: {path.name}")
        try:
            with tarfile.open(path, "r:gz") as archive:
                validate_archive_members(archive)
        except ValueError as error:
            raise SystemExit(f"native artifact archive contract failure: {path.name}: {error}") from error
        except tarfile.TarError as error:
            if payload.get("firmware_toolchain_required"):
                raise SystemExit(f"native artifact archive contract failure: {path.name}: {error}") from error
        if payload.get("firmware_toolchain_required"):
            metadata = entry.get("firmware_toolchain")
            if not isinstance(metadata, dict):
                raise SystemExit(f"native artifact missing immutable firmware toolchain: {path.name}")
            validate_toolchain_bundle(path, metadata, name)
    firmware = payload.get("firmware")
    if not isinstance(firmware, dict) or not SHA.fullmatch(firmware.get("sha256", "")):
        raise SystemExit("manifest missing firmware digest")
    if "source_commit" in firmware and firmware["source_commit"] != AUTHORITATIVE_FIRMWARE_SOURCE:
        raise SystemExit("firmware source provenance does not match the authoritative repaired revision")
    firmware_path = args.release / Path(firmware["url"]).name
    if not firmware_path.is_file() or digest(firmware_path) != firmware["sha256"] or firmware_path.stat().st_size != firmware.get("size"):
        raise SystemExit("firmware integrity failure")
    print(f"validated {payload['version']} ({len(payload['artifacts'])} native artifacts + firmware)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
