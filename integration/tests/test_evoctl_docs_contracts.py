from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[2]
CONTROLLER_SRC = ROOT / "evolver" / "evolver-controller" / "src"
REFERENCE = ROOT / "docs" / "evoctl" / "reference.md"


def _cli():
    sys.path.insert(0, str(CONTROLLER_SRC))
    from meta_webui_application_backend.evolver_edge import cli

    return cli


def _leaf_paths(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                path = prefix + (name,)
                nested = any(isinstance(item, argparse._SubParsersAction) for item in child._actions)
                if nested:
                    yield from _leaf_paths(child, path)
                else:
                    yield path


def test_generated_reference_is_fresh():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_evoctl_reference.py"), "--check"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_public_parser_leaf_is_in_generated_reference():
    reference = REFERENCE.read_text(encoding="utf-8")
    for path in _leaf_paths(_cli().build_parser()):
        if path == ("record-installed-release",):
            assert "hidden compatibility helper" in reference
            continue
        assert f"`evoctl {' '.join(path)}" in reference


def test_documented_concrete_examples_parse_without_execution():
    parser = _cli().build_parser()
    docs = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "docs" / "evoctl").glob("*.md"))
    examples = re.findall(r"^\s*evoctl\s+.+$", docs, flags=re.MULTILINE)
    assert examples
    for line in examples:
        command = line.strip().split("#", 1)[0].strip()
        if (not command or "[when landed]" in command or "..." in command
                or "->" in command or not command.startswith("evoctl ")):
            continue
        argv = shlex.split(command)
        try:
            parser.parse_args(argv[1:])
        except SystemExit as error:
            assert error.code == 0, f"documented example did not parse: {command}"


def test_retired_projection_is_not_documented_as_callable():
    docs = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "docs" / "evoctl").glob("*.md"))
    assert "evoctl workflow action" in docs
    assert "old projected spelling `evoctl workflow action ...` is not a command" in docs
    assert "evoctl workflow action" not in REFERENCE.read_text(encoding="utf-8")


def test_help_surface_keeps_operator_namespaces_visible():
    parser = _cli().build_parser()
    help_text = parser.format_help()
    assert all(name in help_text for name in ("instrument", "action", "workflow", "hardware"))
    assert "--offline" in help_text


def test_pending_lifecycle_inventory_is_explicit_and_attributed():
    reference = REFERENCE.read_text(encoding="utf-8")
    for command in (
        "evoctl runtime status", "evoctl runtime up", "evoctl runtime stop",
        "evoctl runtime down", "evoctl runtime restart", "evoctl runtime logs",
        "evoctl runtime upgrade", "evoctl up", "evoctl down", "evoctl restart",
        "evoctl logs", "evoctl upgrade",
    ):
        assert f"`{command}`" in reference
    assert "pending #114 / #112" in reference
    assert "evoctl runtime status" not in {
        "evoctl " + " ".join(path) for path in _leaf_paths(_cli().build_parser())
    }


def test_documented_compatibility_aliases_are_explicit_parser_projections():
    cli = _cli()
    aliases = {
        ("local", "instrument", "list"): ("instruments",),
        ("server", "status"): ("status",),
        ("runs", "list"): ("runs",),
        ("release", "status"): ("update", "status"),
        ("diagnostics",): ("doctor",),
    }
    for source, target in aliases.items():
        assert tuple(cli._compatibility_argv(list(source))) == target
