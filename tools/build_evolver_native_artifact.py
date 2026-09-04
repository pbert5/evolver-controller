#!/usr/bin/env python3
"""Build a self-contained native eVOLVER edge wheelhouse tarball."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from archive_contract import materialize_tree, validate_archive_members


TOOLCHAIN_FORMAT = 1
TOOLCHAIN_CLI_VERSION = "1.1.1"
TOOLCHAIN_BOSSAC_VERSION = "1.7.0-arduino3"
TOOLCHAIN_BOSSAC_ARCHIVE_SHA256 = "1ae54999c1f97234c5a603eb99ad39313b11746a4ca517269a9285afa05f9100"


LOCAL_PACKAGES = (
    "packages/server-runtime-python",
    "packages/config-compiler",
    "packages/ui-runtime-textual",
    "applications/evolver/backend",
)
PYPI_REQUIREMENTS = (
    "PyYAML==6.0.3",
    "linkify-it-py==2.1.0",
    "markdown-it-py==4.2.0",
    "mdit-py-plugins==0.6.1",
    "mdurl==0.1.2",
    "platformdirs==4.11.3",
    "pyserial==3.5",
    "pygments==2.20.0",
    "rich==15.0.0",
    "textual==8.2.8",
    "typing-extensions==4.16.0",
    "uc-micro-py==2.0.0",
    "zstandard==0.25.0",
)


def _entrypoint_wrapper(module: str, callable_name: str) -> str:
    return f'''#!/bin/sh
set -eu
SELF=$(readlink -f -- "$0")
SELF=${{SELF%/*}}
ROOT=$(CDPATH= cd -- "$SELF/.." && pwd)
PYTHON="$ROOT/python/bin/python"
[ -x "$PYTHON" ] || PYTHON="$ROOT/python/bin/python3"
[ -x "$PYTHON" ] || {{ echo "release-owned Python runtime is missing" >&2; exit 69; }}
LD_LIBRARY_PATH="$ROOT/python/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
export LD_LIBRARY_PATH
PYTHONPATH="$ROOT/site-packages${{PYTHONPATH:+:$PYTHONPATH}}"
export PYTHONPATH
exec "$PYTHON" -c 'from {module} import {callable_name}; raise SystemExit({callable_name}())' "$@"
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", default="linux-x86_64-glibc",
                        choices=("linux-x86_64-glibc", "linux-x86_64-nixos", "linux-aarch64-glibc"))
    parser.add_argument("--python-version", default="3.12", help="target edge Python version (default: 3.12)")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--python-runtime", type=Path,
                        help="release-owned glibc Python tree containing bin/python or bin/python3")
    parser.add_argument("--wheelhouse", type=Path,
                        help="controlled offline wheelhouse for exact third-party dependencies")
    parser.add_argument("--arduino-data", type=Path, help="staged Arduino data directory for the offline firmware toolchain")
    parser.add_argument("--arduino-cli", type=Path, help="pinned arduino-cli executable to include in the offline toolchain")
    parser.add_argument("--arduino-libraries", type=Path, required=False,
                        help="staged Arduino user libraries for the offline firmware toolchain")
    parser.add_argument("--toolchain-variant", default=None,
                        choices=("linux-x86_64-glibc", "linux-x86_64-nixos", "linux-aarch64-glibc"),
                        help="deprecated alias; must match --platform")
    parser.add_argument("--bossac", type=Path,
                        help="variant-specific BOSSA executable; required for the NixOS variant")
    parser.add_argument("--bossac-store-root", type=Path,
                        help="exact Nix store root for the NixOS BOSSA package")
    args = parser.parse_args()
    if args.toolchain_variant and args.toolchain_variant != args.platform:
        parser.error("--platform and --toolchain-variant must identify the same target")
    toolchain_variant = args.toolchain_variant or args.platform
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="evolver-native-") as scratch_name:
        scratch = Path(scratch_name)
        wheels = scratch / "wheels"
        wheels.mkdir()
        if args.python_runtime:
            runtime = args.python_runtime.resolve()
            if not runtime.is_dir():
                parser.error(f"Python runtime does not exist: {runtime}")
            materialize_tree(runtime, scratch / "python")
            runtime_lib = scratch / "python/lib"
            runtime_lib.mkdir(parents=True, exist_ok=True)
            sqlite_library = Path("/usr/lib/x86_64-linux-gnu/libsqlite3.so.0")
            if not sqlite_library.is_file():
                parser.error("builder runtime is missing target libsqlite3.so.0")
            shutil.copy2(sqlite_library, runtime_lib / sqlite_library.name)
            runtime_python = scratch / "python/bin/python"
            if not runtime_python.is_file():
                runtime_python = scratch / "python/bin/python3"
            if not runtime_python.is_file() or not os.access(runtime_python, os.X_OK):
                parser.error("--python-runtime must contain executable bin/python or bin/python3")
        for package in LOCAL_PACKAGES:
            subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheels), "--no-build-logs", str(root / package)], check=True)
        python_digits = args.python_version.replace(".", "")
        wheel_platform = "manylinux2014_x86_64" if args.platform.startswith("linux-x86_64") else "manylinux2014_aarch64"
        if args.wheelhouse:
            wheelhouse = args.wheelhouse.resolve()
            if not wheelhouse.is_dir():
                parser.error(f"offline wheelhouse does not exist: {wheelhouse}")
            subprocess.run([sys.executable, "-m", "pip", "download", "--no-index",
                            "--find-links", str(wheelhouse), "--only-binary=:all:",
                            "--python-version", args.python_version, "--platform", wheel_platform,
                            "--implementation", "cp", "--abi", f"cp{python_digits}",
                            "--dest", str(wheels), *PYPI_REQUIREMENTS], check=True)
        else:
            subprocess.run(["uvx", "--from", "pip", "pip", "download", "--only-binary=:all:",
                            "--python-version", args.python_version, "--platform", wheel_platform,
                            "--implementation", "cp", "--abi", f"cp{python_digits}",
                            "--dest", str(wheels), *PYPI_REQUIREMENTS], check=True)
        if args.python_runtime:
            site_packages = scratch / "site-packages"
            site_packages.mkdir()
            wheel_files = sorted(str(path) for path in wheels.glob("*.whl"))
            subprocess.run([str(runtime_python), "-m", "pip", "install",
                            "--disable-pip-version-check", "--no-index", "--no-cache-dir",
                            "--target", str(site_packages), *wheel_files], check=True)
            bindir = scratch / "bin"
            bindir.mkdir()
            for name, module, callable_name in (
                ("evoctl", "meta_webui_application_backend.evolver_edge.cli", "main"),
                ("evolver-controller", "meta_webui_application_backend.evolver_edge.service", "main"),
                ("evolver-hardware", "meta_webui_application_backend.evolver_edge.hardware_service", "main"),
            ):
                wrapper = bindir / name
                wrapper.write_text(_entrypoint_wrapper(module, callable_name), encoding="utf-8")
                wrapper.chmod(0o755)
        metadata = {
            "format": 1,
            "platform": args.platform,
            "source_revision": args.source_revision,
            "python": f"=={args.python_version}",
            "packages": sorted(path.name for path in wheels.iterdir()),
            "installation": ("embedded python and pre-materialized site-packages"
                              if args.python_runtime else
                              "python3 -m venv RELEASE_ROOT; RELEASE_ROOT/bin/pip install --no-index --find-links wheels meta-webui-application-backend"),
        }
        if args.python_runtime:
            metadata["runtime"] = {"path": "python", "executable": str(runtime_python.relative_to(scratch))}
        if len({bool(args.arduino_data), bool(args.arduino_cli), bool(args.arduino_libraries)}) != 1:
            parser.error("--arduino-data, --arduino-cli, and --arduino-libraries must be supplied together")
        if args.arduino_data:
            data = args.arduino_data.resolve()
            cli = args.arduino_cli.resolve()
            libraries = args.arduino_libraries.resolve()
            if not data.is_dir() or not cli.is_file() or not os.access(cli, os.X_OK) or not libraries.is_dir():
                parser.error("offline toolchain inputs must include Arduino data, executable arduino-cli, and libraries")
            toolchain = scratch / "toolchain"
            materialize_tree(data, toolchain / "arduino-data")
            # Some pinned Nix toolchain trees carry read-only store modes.
            # The release-local tree is private staging, and must permit the
            # variant-specific BOSSA wrappers below to be materialized.
            for parent in (toolchain / "arduino-data").rglob("*"):
                if parent.is_dir():
                    parent.chmod(0o755)
            shutil.copy2(cli, toolchain / "arduino-cli")
            materialize_tree(libraries, toolchain / "arduino-libraries")
            bossac = toolchain / "arduino-data/packages/arduino/tools/bossac" / TOOLCHAIN_BOSSAC_VERSION / "bin/bossac"
            canonical_bossac = toolchain / "arduino-data/packages/arduino/tools/bossac" / TOOLCHAIN_BOSSAC_VERSION / "bossac"
            if toolchain_variant == "linux-x86_64-nixos" and not args.bossac:
                parser.error("--bossac is required for the linux-x86_64-nixos toolchain variant")
            if args.bossac:
                supplied_bossac = args.bossac.resolve()
                if not supplied_bossac.is_file() or not os.access(supplied_bossac, os.X_OK):
                    parser.error("--bossac must point to an executable")
                if toolchain_variant == "linux-x86_64-nixos":
                    store_root = (args.bossac_store_root or _nix_store_root(supplied_bossac)).resolve()
                    closure_file = toolchain / "nix-closures/bossac.closure"
                    closure_paths = _export_nix_closure(store_root, closure_file)
                    bossac.parent.mkdir(parents=True, exist_ok=True)
                    if bossac.exists():
                        bossac.chmod(0o755)
                    bossac.write_text(
                        "#!/bin/sh\nexec " + str(supplied_bossac) + ' "$@"\n', encoding="utf-8")
                    bossac.chmod(0o755)
                    canonical_bossac.write_text(
                        "#!/bin/sh\nexec " + str(supplied_bossac) + ' "$@"\n', encoding="utf-8")
                    canonical_bossac.chmod(0o755)
                    legacy_bossac = bossac.parent.parent / "bossac"
                    legacy_bossac.write_text(
                        canonical_bossac.read_text(encoding="utf-8"), encoding="utf-8")
                    legacy_bossac.chmod(0o755)
                else:
                    bossac.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(supplied_bossac, bossac)
                    store_root = None
                    closure_paths = []
            if not bossac.is_file() or not os.access(bossac, os.X_OK):
                raise SystemExit(f"offline toolchain lacks selected BOSSA: {bossac}")
            cli_digest = _sha256(toolchain / "arduino-cli")
            # The provenance path is the contract consumers resolve.  NixOS
            # ships a root-level Arduino wrapper and a legacy bin/ wrapper;
            # hashing the latter here makes the declared path unverifiable.
            bossac_digest = _sha256(canonical_bossac if toolchain_variant == "linux-x86_64-nixos" else bossac)
            toolchain_metadata = {
                "format": TOOLCHAIN_FORMAT,
                "offline": True,
                "variant": toolchain_variant,
                "arduino_cli": {"version": TOOLCHAIN_CLI_VERSION, "path": "toolchain/arduino-cli", "sha256": cli_digest},
                "arduino_data": {"path": "toolchain/arduino-data"},
                "arduino_libraries": {"path": "toolchain/arduino-libraries"},
                "board_core": "SparkFun:samd@1.8.13",
                "bossac": {
                    "version": TOOLCHAIN_BOSSAC_VERSION,
                    "path": f"toolchain/arduino-data/packages/arduino/tools/bossac/{TOOLCHAIN_BOSSAC_VERSION}/bossac" if toolchain_variant == "linux-x86_64-nixos"
                    else f"toolchain/arduino-data/packages/arduino/tools/bossac/{TOOLCHAIN_BOSSAC_VERSION}/bin/bossac",
                    "sha256": bossac_digest,
                    "source_archive_sha256": TOOLCHAIN_BOSSAC_ARCHIVE_SHA256,
                },
            }
            if toolchain_variant == "linux-x86_64-nixos":
                closure_file = toolchain / "nix-closures/bossac.closure"
                toolchain_metadata["bossac"].update({
                    "delivery": "nix-store-export-v1",
                    "store_root": str(store_root),
                    "store_executable": str(supplied_bossac),
                    "closure_artifact": "toolchain/nix-closures/bossac.closure",
                    "closure_sha256": _sha256(closure_file),
                    "closure_paths": closure_paths,
                    "store_executable_sha256": _sha256(supplied_bossac),
                    "wrapper_sha256": _sha256(canonical_bossac),
                })
            (toolchain / "PROVENANCE.json").write_text(json.dumps(toolchain_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            metadata["firmware_toolchain"] = toolchain_metadata
        (scratch / "PROVENANCE.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (scratch / "systemd").mkdir()
        (scratch / "systemd/evolver-controller.service").write_text("Generated by the signed installer from the release manifest.\n", encoding="utf-8")
        (scratch / "systemd/evolver-hardware.service").write_text("Generated by the signed installer from the release manifest.\n", encoding="utf-8")
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT, compresslevel=9) as archive:
            for path in sorted(scratch.rglob("*")):
                if path.is_file() or path.is_dir():
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(scratch)))
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    if path.is_file():
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                    else:
                        archive.addfile(info)
        with tarfile.open(output, "r:gz") as produced:
            validate_archive_members(produced)
    print(output)
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nix_store_root(executable: Path) -> Path:
    parts = executable.parts
    try:
        index = parts.index("nix")
    except ValueError as error:
        raise SystemExit("NixOS BOSSA must be inside /nix/store or provide --bossac-store-root") from error
    if index + 2 >= len(parts) or parts[index + 1] != "store":
        raise SystemExit("invalid Nix store executable path")
    return Path(*parts[:index + 3])


def _export_nix_closure(store_root: Path, destination: Path) -> list[str]:
    if not str(store_root).startswith("/nix/store/") or not store_root.is_dir():
        raise SystemExit(f"Nix BOSSA store root is missing: {store_root}")
    result = subprocess.run(["nix-store", "--query", "--requisites", str(store_root)],
                            check=True, text=True, capture_output=True)
    paths = sorted(line for line in result.stdout.splitlines() if line)
    if str(store_root) not in paths:
        raise SystemExit("Nix BOSSA closure does not contain its recorded store root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        subprocess.run(["nix-store", "--export", *paths], check=True, stdout=stream)
    return paths


if __name__ == "__main__":
    raise SystemExit(main())
