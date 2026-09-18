from pathlib import Path
import subprocess

import pytest


ROOT = Path.cwd()


def test_reviewed_component_heads_and_final_lineage_are_pinned() -> None:
    contract = (ROOT / "docs/temperature-setpoint-integration.md").read_text()
    assert "83483cda621a2e913ad778ae62294872084a507a" in contract
    assert "78a17ebf90b64fea394a05a670ce6b58820fa377" in contract
    assert "c9b1eb24e35a52f4f328793b3b4891a314b6ba25" in contract
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
    assert controller == "7ac90e4a2abb1dcf8b5065479a20d209a8a33171"
    assert hardware == "78a17ebf90b64fea394a05a670ce6b58820fa377"
    for ancestor in (
        "c9b1eb24e35a52f4f328793b3b4891a314b6ba25",
        "4f3b2205315d7f9bc3783d83a7ae26dc749cebf9",
    ):
        assert subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, controller],
            cwd=ROOT / "evolver/evolver-controller", check=False,
        ).returncode == 0


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


def test_workflow_host_prose_matches_reviewed_controller_consumer() -> None:
    workflow_host = (ROOT / "docs/workflow-host-contract.md").read_text()
    assert "integrated reviewed" in workflow_host
    assert "consumer accepts the physical sink" in workflow_host
    assert "still rejects the physical sink" not in workflow_host
