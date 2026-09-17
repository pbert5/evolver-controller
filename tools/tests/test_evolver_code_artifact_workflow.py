from pathlib import Path


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/evolver-code-artifact.yml"
SOURCE = "pbert5/evolver-arduino"
COMMIT = "952a6fd713c40caa072444a0e0e3fc4fc6ee4639"


def test_evolver_code_workflow_freezes_source_and_uploads_provenance() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert f"EVOLVER_CODE_REPOSITORY: {SOURCE}" in workflow
    assert f"EVOLVER_CODE_COMMIT: {COMMIT}" in workflow
    assert "repository: ${{ env.EVOLVER_CODE_REPOSITORY }}" in workflow
    assert "ref: ${{ env.EVOLVER_CODE_COMMIT }}" in workflow
    assert 'git -C evolver_code rev-parse HEAD)" = "$EVOLVER_CODE_COMMIT"' in workflow
    assert '"source_repository": os.environ["EVOLVER_CODE_REPOSITORY"]' in workflow
    assert '"source_commit": os.environ["EVOLVER_CODE_COMMIT"]' in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "if-no-files-found: error" in workflow


def test_evolver_code_workflow_has_no_runtime_source_fetch_or_upload() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "arduino-cli upload" not in workflow
    assert "curl " not in workflow
    assert "wget " not in workflow
