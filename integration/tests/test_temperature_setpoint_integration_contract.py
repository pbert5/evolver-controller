from pathlib import Path


ROOT = Path.cwd()


def test_reviewed_component_heads_are_pinned_exactly() -> None:
    contract = (ROOT / "docs/temperature-setpoint-integration.md").read_text()
    assert "83483cda621a2e913ad778ae62294872084a507a" in contract
    assert "36da3d8b63b7cef65d35b5b86ec4d72f83690547" in contract
    assert "01fd57f24685acdc907ebeb54e61d6585d5f2afd" in contract


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
