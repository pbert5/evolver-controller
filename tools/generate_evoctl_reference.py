#!/usr/bin/env python3
"""Generate the checked-in evoctl reference from the controller parser."""

from __future__ import annotations

import argparse
import argparse as _argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_SRC = ROOT / "evolver" / "evolver-controller" / "src"
OUTPUT = ROOT / "docs" / "evoctl" / "reference.md"
HEADER = """# evoctl generated command reference

<!-- GENERATED FILE. DO NOT EDIT. Run tools/generate_evoctl_reference.py. -->

This inventory is derived from `evolver/evolver-controller`'s `build_parser()`.
Descriptions, safety classifications, and examples live in the linked operator
guide; this file answers which parser spellings exist at the reviewed head.

| Command | Classification | Parser status |
| --- | --- | --- |
"""
LIFECYCLE_PENDING = """
## Pending lifecycle integration inventory

The following spellings are the #112/#114 coordination contract. They are
intentionally marked pending because the reviewed #106 parser head does not
implement them. The #108 integration owner must regenerate this section from
the integrated lifecycle parser and preserve the existing `update` commands.

| Command | Classification | Parser status |
| --- | --- | --- |
| `evoctl runtime status` | `live` | pending #114 / #112 |
| `evoctl runtime up` | `maintenance` | pending #114 / #112 |
| `evoctl runtime stop` | `maintenance` | pending #114 / #112 |
| `evoctl runtime down` | `maintenance` | pending #114 / #112 |
| `evoctl runtime restart` | `maintenance` | pending #114 / #112 |
| `evoctl runtime logs` | `maintenance` | pending #114 / #112 |
| `evoctl runtime upgrade` | `maintenance` | pending #114 / #112 |
| `evoctl up` | `maintenance` | pending #114 / #112 |
| `evoctl down` | `maintenance` | pending #114 / #112 |
| `evoctl restart` | `maintenance` | pending #114 / #112 |
| `evoctl logs` | `maintenance` | pending #114 / #112 |
| `evoctl upgrade` | `maintenance` | pending #114 / #112 |
"""


def _load_cli():
    sys.path.insert(0, str(CONTROLLER_SRC))
    from meta_webui_application_backend.evolver_edge import cli

    return cli


def _children(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, _argparse._SubParsersAction):
            yield action


def _leaves(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()):
    for action in _children(parser):
        for name, child in sorted(action.choices.items()):
            path = prefix + (name,)
            nested = tuple(_children(child))
            if nested:
                yield from _leaves(child, path)
            else:
                yield path, child


def _registry_key(path: tuple[str, ...]) -> str:
    if path[0] in {"run", "calibration", "update"} and len(path) > 1:
        return ".".join(path[:2])
    if path[:2] == ("instrument", "sensors") and len(path) > 2:
        return ".".join(path[:3])
    if path[:2] == ("instrument", "telemetry") and len(path) > 2:
        return ".".join(path[:3])
    if path[:2] == ("hardware", "lease") and len(path) > 2:
        return ".".join(path[:3])
    return ".".join(path)


def _classification(cli, path: tuple[str, ...]) -> tuple[str, str]:
    key = _registry_key(path)
    if key == "record-installed-release":
        return "internal", "hidden compatibility helper"
    spec = cli._COMMAND_REGISTRY.get(key)
    if spec is None and key.startswith("workflow."):
        return "live", "implemented parser path"
    if path[0] == "simulator":
        return "local", "execute"
    if spec is None:
        return "review", "parser path lacks registry metadata"
    return spec.mode.value.lower(), spec.disposition


def render() -> str:
    cli = _load_cli()
    rows: list[str] = []
    for path, parser in _leaves(cli.build_parser()):
        classification, status = _classification(cli, path)
        usage = " ".join(parser.format_usage().split())
        usage = usage.removeprefix("usage: ")
        rows.append(f"| `{usage}` | `{classification}` | {status} |")
    return HEADER + "\n".join(rows) + LIFECYCLE_PENDING + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        actual = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if actual != expected:
            print(f"stale evoctl reference: {OUTPUT}")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
