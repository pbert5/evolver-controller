from pathlib import Path
import subprocess

import pytest


ROOT = Path.cwd()


def test_reviewed_component_heads_are_pinned_exactly() -> None:
    contract = (ROOT / "docs/temperature-setpoint-integration.md").read_text()
    assert "83483cda621a2e913ad778ae62294872084a507a" in contract
    assert "5a7f0c188978851ae1324b5de1cc05a1278d84f4" in contract
    assert "a65844bb1624da5c0fbf8aa0845f6e61d9278fc1" in contract
    try:
        controller = subprocess.check_output(
            ["git", "rev-parse", "HEAD:evolver/evolver-controller"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        hardware = subprocess.check_output(
            ["git", "rev-parse", "HEAD:evolver/evolver-hardware"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        pytest.skip("container mount does not expose the worktree git metadata")
    assert controller == "a65844bb1624da5c0fbf8aa0845f6e61d9278fc1"
    assert hardware == "5a7f0c188978851ae1324b5de1cc05a1278d84f4"


def test_firmware_provenance_and_evidence_contract_are_frozen() -> None:
    workflow = (ROOT / ".github/workflows/evolver-code-artifact.yml").read_text()
    release = (ROOT / "tools/build_evolver_release.py").read_text()
    validation = (ROOT / "tools/validate_evolver_release.py").read_text()
    contract = (ROOT / "docs/temperature-setpoint-integration.md").read_text()
    sha = "83483cda621a2e913ad778ae62294872084a507a"
    assert workflow.count(sha) >= 1
    assert f'AUTHORITATIVE_FIRMWARE_SOURCE = "{sha}"' in release
    assert f'AUTHORITATIVE_FIRMWARE_SOURCE = "{sha}"' in validation
    assert "protocol ACK" in contract
    assert "thermal success" in contract
    assert "1..65535" in contract
