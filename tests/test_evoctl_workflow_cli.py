from __future__ import annotations

import io
import json

from evolver_controller.workflow_cli import (
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


def test_interactive_repeatable_calibration_reaches_three_points_then_review():
    host = ScenarioRegistry().host("repeatable_calibration")
    output = io.StringIO()
    answers = iter(["a", "10", "a", "20", "a", "30", "c"])
    cli = WorkflowCLI(host, output=output, input_reader=lambda _prompt: next(answers))

    assert cli.run("scenario.repeatable-calibration") == 0
    rendered = output.getvalue()
    assert "Calibration Points" in rendered
    assert "points-1" in rendered and "points-2" in rendered and "points-3" in rendered
    assert "Review" in rendered
    assert host.operator.requests == []


def test_repeatable_instance_jsonl_is_stable_and_reports_zero_actions():
    host = ScenarioRegistry().host("repeatable_calibration")
    output = io.StringIO()
    answers = iter(["a", "12.5", "c"])
    cli = WorkflowCLI(host, output=output, jsonl=True, input_reader=lambda _prompt: next(answers))

    assert cli.run("scenario.repeatable-calibration") == 0
    records = [json.loads(item) for item in output.getvalue().splitlines()]
    created = [item for item in records if item["event"] == "stage_instance_created"]
    assert created == [{
        "event": "stage_instance_created", "payload": {
            "actions_invoked": 0, "instance_count": 1, "instance_id": "points-1", "stage_id": "points",
        }, "schema_version": 1, "sequence": created[0]["sequence"],
    }]
    assert records[-1]["event"] == "outcome"
    assert records[-1]["payload"]["state"] == "succeeded"


def test_repeatable_stage_abort_uses_normal_cleanup_path():
    host = ScenarioRegistry().host("repeatable_calibration")
    output = io.StringIO()
    cli = WorkflowCLI(host, output=output, jsonl=True, input_reader=lambda _prompt: "q")

    assert cli.run("scenario.repeatable-calibration") == 130
    record = json.loads(output.getvalue().splitlines()[-1])
    assert record["event"] == "outcome"
    assert record["payload"]["state"] == "aborted"
    assert host.abort_count == 1


def test_repeatable_prompt_retries_invalid_choice_and_eof_aborts():
    host = ScenarioRegistry().host("repeatable_calibration")
    answers = iter(["invalid", "a"])

    def read(_prompt):
        try:
            return next(answers)
        except StopIteration as error:
            raise EOFError from error

    cli = WorkflowCLI(host, output=io.StringIO(), input_reader=read)
    assert cli.run("scenario.repeatable-calibration") == 130
    assert host.abort_count == 1
