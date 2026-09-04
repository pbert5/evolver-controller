from __future__ import annotations

import os
import re
from pathlib import Path

VERSIONED = re.compile(r"^bal_schema_v(?P<version>\d+\.\d+\.\d+)\.(?:ya?ml)$")


def available(directory: Path) -> list[tuple[tuple[int, int, int], str, Path]]:
    result = []
    if not directory.is_dir():
        return result
    for path in directory.iterdir():
        match = VERSIONED.match(path.name)
        if match and path.is_file():
            version = tuple(int(part) for part in match.group("version").split("."))
            result.append((version, match.group("version"), path))
    return sorted(result, key=lambda item: (item[0], item[2].name), reverse=True)


def select(directory: Path, requested: str | None = None) -> Path:
    requested = (requested or os.environ.get("BAL_SCHEMA_VERSION", "latest")).strip()
    versions = available(directory)
    if requested.lower() in {"latest", "auto", "current"}:
        if not versions:
            raise FileNotFoundError(f"no assembled BAL schemas found in {directory}")
        return versions[0][2]
    for _parsed, version, path in versions:
        if version == requested.removeprefix("v"):
            return path
    raise FileNotFoundError(f"BAL schema version {requested!r} is not available in {directory}")
