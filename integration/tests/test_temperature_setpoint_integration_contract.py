from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[2]


def gitlink(path: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT, text=True
    ).strip()


def test_reviewed_component_heads_are_pinned_exactly() -> None:
    assert gitlink("evolver/evolver-controller") == "01fd57f24685acdc907ebeb54e61d6585d5f2afd"
    assert gitlink("evolver/evolver-hardware") == "018590854aff8ea886138b37d6af0dd5ab82a8ea"


def test_firmware_provenance_and_evidence_contract_are_frozen() -> None:
    workflow = (ROOT / ".github/workflows/evolver-code-artifact.yml").read_text()
    release = (ROOT / "tools/build_evolver_release.py").read_text()
    validation = (ROOT / "tools/validate_evolver_release.py").read_text()
    contract = (ROOT / "docs/temperature-setpoint-integration.md").read_text()
    sha = "f10de7bab8aa800e0e76ec64c2851b5ed7020c1d"
    assert workflow.count(sha) >= 1
    assert f'AUTHORITATIVE_FIRMWARE_SOURCE = "{sha}"' in release
    assert f'AUTHORITATIVE_FIRMWARE_SOURCE = "{sha}"' in validation
    assert "protocol ACK" in contract
    assert "thermal success" in contract
    assert "1..65535" in contract
