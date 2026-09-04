"""Export a deterministic neutral schema manifest for runtime consumers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PACKAGE_VERSION = "0.1.0"


def export_manifest(root: Path) -> dict:
    files = []
    digest = hashlib.sha256()
    for path in sorted((root / "instrument").glob("*.yaml")):
        content = path.read_bytes()
        file_digest = hashlib.sha256(content).hexdigest()
        files.append({"name": path.name, "sha256": file_digest})
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
    return {"schema_package_version": PACKAGE_VERSION, "source_digest": digest.hexdigest(), "modules": files}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.dumps(export_manifest(args.root), sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
