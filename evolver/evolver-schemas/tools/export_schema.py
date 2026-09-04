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
    registry = root / "registry" / "trusted_actions.yaml"
    paths = [*sorted((root / "instrument").glob("*.yaml")), registry]
    for path in paths:
        content = path.read_bytes()
        relative_name = path.relative_to(root).as_posix()
        manifest_name = path.name if path.parent.name == "instrument" else relative_name
        files.append({"name": manifest_name, "sha256": hashlib.sha256(content).hexdigest()})
        digest.update(relative_name.encode("utf-8"))
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
