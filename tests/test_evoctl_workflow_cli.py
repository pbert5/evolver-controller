from __future__ import annotations

import io
import json

from meta_webui_application_backend.evolver_edge.workflow_cli import (
    SCENARIO_NAMES,
    ScenarioRegistry,
    WorkflowCLI,
    jsonl_line,
)


def test_jsonl_is_sorted_versioned_bounded_and_redacted():
    line = jsonl_line(
        "action",
        {"z": "last", "lease_token": "lease-secret", "raw": "x" * 900},
        sequence=2,
    )
    assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")) + "\n"
    record = json.loads(line)
    assert record["schema_version"] == 1
    assert record["sequence"] == 2
    assert record["payload"]["lease_token"] == "<redacted>"
    assert len(record["payload"]["raw"]) <= 512


def test_list_is_deterministic_and_show_has_only_workflow_metadata():
    cli = WorkflowCLI(ScenarioRegistry().host("library_browsing"), output=io.StringIO())
    assert cli.list_workflows() == 0
    output = cli.output.getvalue()
    assert output.index("Calibration A") < output.index("Calibration B")

    cli.output = io.StringIO()
    assert cli.show_workflow("scenario.calibration.a") == 0
    shown = cli.output.getvalue()
    assert "lease_token" not in shown
    assert "stages:" in shown


def test_preflight_does_not_invoke_fake_action():
    host = ScenarioRegistry().host("unsupported_temperature")
    cli = WorkflowCLI(host, output=io.StringIO())
    assert cli.preflight("scenario.temperature", {"value": 30}) == 2
    assert host.invocations == []
    assert "unsupported" in cli.output.getvalue()


def test_ctrl_c_aborts_once_and_emits_terminal_jsonl():
    host = ScenarioRegistry().host("waiting_for_input")
    output = io.StringIO()

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    cli = WorkflowCLI(host, output=output, jsonl=True, input_reader=interrupt)
    assert cli.run("scenario.input", {"value": 1}) == 130
    records = [json.loads(item) for item in output.getvalue().splitlines()]
    assert records[-1]["payload"]["state"] == "aborted"
    assert host.abort_count == 1


def test_run_uses_session_until_success_and_keeps_jsonl_stable():
    host = ScenarioRegistry().host("successful_completion")
    output = io.StringIO()
    cli = WorkflowCLI(host, output=output, jsonl=True)
    assert cli.run("scenario.successful_completion", {"value": 1}) == 0
    records = [json.loads(item) for item in output.getvalue().splitlines()]
    assert records[-1]["event"] == "outcome"
    assert records[-1]["payload"]["state"] == "succeeded"
    session_ids = {record["payload"]["session_id"] for record in records}
    assert len(session_ids) == 1


def test_scenario_registry_is_stable_and_has_no_io_scenarios():
    assert tuple(SCENARIO_NAMES) == tuple(sorted(SCENARIO_NAMES))
    registry = ScenarioRegistry()
    assert set(SCENARIO_NAMES) <= set(registry.names())
