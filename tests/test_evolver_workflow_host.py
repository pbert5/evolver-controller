from __future__ import annotations

import pytest

from evolver_procedure_runtime import ActionRef, MutationOutcome, WorkflowLibrary

from meta_webui_application_backend.evolver_edge.workflow_host import (
    Availability,
    HostContext,
    ProcedureActionInvoker,
    TargetKind,
    TargetProjection,
    WorkflowHost,
    operator_safe_stop_authority,
    resolve_target,
)
from meta_webui_application_backend.evolver_edge.cli import build_parser
from meta_webui_application_backend.evolver_edge.workflow_cli import ScenarioRegistry, production_host


class FakeOperator:
    def __init__(self):
        self.requests = []
        self.responses = {"hardware": {"request_accepted": True, "evidence": "protocol_ack"},
                          "instrument": {"id": "MEV-1", "capabilities": {}}}

    def request(self, operation, params=None):
        self.requests.append((operation, params or {}))
        return self.responses.get(operation, {})

    def safe_stop(self, *, operator, physical, command_id):
        return self.request("hardware", {"operation": "safe_stop", "operator": operator,
                                           "physical": physical, "command_id": command_id})


def target(*, kind=TargetKind.PHYSICAL, capabilities=None):
    return TargetProjection("MEV-1", kind, {"id": "controller-1", "generation": 7},
                            binding={"generation": 7}, capabilities=capabilities or {},
                            connection={"state": "operator_reachable"})


def test_temperature_is_truthfully_unsupported_and_preflight_has_no_side_effects():
    client = FakeOperator()
    invoker = ProcedureActionInvoker(client, target(), context=HostContext(target_identity="MEV-1"))

    availability = invoker.availability(ActionRef("set_temperature", 1))
    assert availability.classification is Availability.UNSUPPORTED
    assert "#58" in availability.reason
    try:
        invoker.preflight(ActionRef("set_temperature", 1), {"target_temperature_c": 30})
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("physical temperature action unexpectedly preflighted")
    assert client.requests == []


def test_simulator_temperature_is_explicitly_simulator_only():
    invoker = ProcedureActionInvoker(FakeOperator(), target(kind=TargetKind.SIMULATOR),
                                     context=HostContext(target_identity="MEV-1"))
    assert invoker.availability(ActionRef("set_temperature", 1)).classification is Availability.SIMULATOR_ONLY
    token = invoker.invoke(ActionRef("set_temperature", 1), {"target_temperature_c": 30})
    result = invoker.poll(token)
    assert result.succeeded and result.value["evidence"] == "simulated"


def test_stop_remains_dependency_blocked_without_safe_stop_authority():
    invoker = ProcedureActionInvoker(FakeOperator(), target(), context=HostContext())
    availability = invoker.availability(ActionRef("stop_actuator", 1))
    assert availability.classification is Availability.BLOCKED_DEPENDENCY
    assert availability.provenance["dependency"] == "#47"


def test_configured_safe_stop_uses_typed_lease_free_operator_authority():
    client = FakeOperator()
    invoker = ProcedureActionInvoker(
        client, target(), context=HostContext(operator="alice", physical=True,
                                              controller_generation=7, target_identity="MEV-1"),
        safe_stop_authority=operator_safe_stop_authority(client),
    )
    assert invoker.availability(ActionRef("stop_actuator", 1)).classification is Availability.AVAILABLE
    invocation = invoker.invoke(ActionRef("stop_actuator", 1), {})
    result = invoker.poll(invocation)
    assert result.succeeded
    assert result.value["evidence"] == "protocol_ack"
    assert result.value["physical_cessation"] == "not_verified"
    assert client.requests == [("hardware", {"operation": "safe_stop", "operator": "alice",
                                               "physical": True, "command_id": invocation.token})]
    assert "lease_token" not in client.requests[0][1]


@pytest.mark.parametrize("target_projection", [
    TargetProjection("MEV-1", TargetKind.PHYSICAL, {"id": "controller-1"}),
    TargetProjection("MEV-1", TargetKind.PHYSICAL, {"id": "controller-1", "generation": 0},
                     binding={"generation": 0}),
    TargetProjection("MEV-1", TargetKind.PHYSICAL, {"id": "controller-1", "generation": "7"},
                     binding={"generation": "7"}),
])
def test_safe_stop_does_not_reach_operator_without_valid_target_generation(target_projection):
    client = FakeOperator()
    invoker = ProcedureActionInvoker(
        client, target_projection, context=HostContext(operator="alice", physical=True,
                                                        controller_generation=7),
        safe_stop_authority=operator_safe_stop_authority(client),
    )

    result = invoker.poll(invoker.invoke(ActionRef("stop_actuator", 1), {}))

    assert not result.succeeded
    assert "positive controller generations" in result.error
    assert client.requests == []


def test_safe_stop_does_not_reach_operator_on_generation_mismatch():
    client = FakeOperator()
    invoker = ProcedureActionInvoker(
        client, target(), context=HostContext(operator="alice", physical=True,
                                              controller_generation=8),
        safe_stop_authority=operator_safe_stop_authority(client),
    )

    result = invoker.poll(invoker.invoke(ActionRef("stop_actuator", 1), {}))

    assert not result.succeeded
    assert "stale" in result.error
    assert client.requests == []


@pytest.mark.parametrize("context_generation", [None, 0, -1, "7", True])
def test_safe_stop_does_not_reach_operator_without_valid_context_generation(context_generation):
    client = FakeOperator()
    invoker = ProcedureActionInvoker(
        client, target(), context=HostContext(operator="alice", physical=True,
                                              controller_generation=context_generation),
        safe_stop_authority=operator_safe_stop_authority(client),
    )

    result = invoker.poll(invoker.invoke(ActionRef("stop_actuator", 1), {}))

    assert not result.succeeded
    assert "positive controller generations" in result.error
    assert client.requests == []


def test_invoker_exposes_cleanup_fence_and_authorization_projection():
    invoker = ProcedureActionInvoker(FakeOperator(), target(), context=HostContext())
    assert invoker.controller_generation == 7
    description = invoker.describe(ActionRef("stop_actuator", 1))
    assert description == {
        "id": "stop_actuator", "version": 1, "authorized": False,
        "controller_generation": 7,
    }


def test_domain_activity_is_not_falsely_session_local():
    invoker = ProcedureActionInvoker(FakeOperator(), target(), context=HostContext())
    assert invoker.availability(ActionRef("stop_activity", 1)).classification is Availability.UNSUPPORTED


def test_pump_invocation_uses_operator_path_and_preserves_command_identity():
    client = FakeOperator()
    invoker = ProcedureActionInvoker(client, target(capabilities={"pump_control": {"supported": True}}),
                                     context=HostContext(operator="alice", lease_token="lease",
                                                         lease_owner="alice", controller_generation=7,
                                                         physical=True, target_identity="MEV-1"))
    invocation = invoker.invoke(ActionRef("pulse_pump", 1), {"channel": 2, "duration_ms": 40})
    result = invoker.poll(invocation)
    assert result.succeeded
    operation, params = client.requests[0]
    assert operation == "hardware"
    assert params["operation_name"] == "pulse_pump"
    assert params["command_id"] == invocation.token
    assert params["lease_token"] == "lease"


def test_observation_is_read_only_and_retains_authority_evidence():
    client = FakeOperator()
    invoker = ProcedureActionInvoker(client, target(), context=HostContext(target_identity="MEV-1"))
    result = invoker.poll(invoker.invoke(ActionRef("capture_measurement", 1), {"metric": "od"}))
    assert result.succeeded and result.value["evidence"] == "operator_read_only"
    assert client.requests == [("instrument", {"instrument_id": "MEV-1"})]


def test_edge_sink_delegates_to_calibration_run_without_central_fallback():
    client = FakeOperator()
    host = WorkflowHost(client, target=target(), workflows=WorkflowLibrary([]), procedures={},
                        context=HostContext(operator="alice"))
    request = host.edge_observation_sink()
    from evolver_procedure_runtime import SessionBinding, SinkRegistry, SinkRequest
    sink_request = SinkRequest("edge.calibration_run.observation", {"raw_value": 1}, "obs-1",
                               session=SessionBinding("run-1", "procedure-1"), _registry=SinkRegistry())
    assert request(sink_request) == MutationOutcome("accepted")
    assert client.requests[0][0] == "calibration_run"


def test_projection_is_shared_for_renderers():
    host = WorkflowHost(FakeOperator(), target=target(capabilities={"pump_control": {"supported": True}}),
                        workflows=WorkflowLibrary([]), procedures={}, context=HostContext())
    projection = host.project_action(step={"id": "pulse"}, action=ActionRef("pulse_pump", 1),
                                    parameters={"channel": 1, "duration_ms": 20})
    assert projection.action["id"] == projection.raw["id"] == projection.api["action_id"]
    assert projection.availability.classification is Availability.AVAILABLE
    assert projection.cli == "Not applicable: evoctl has no canonical action subcommand"


def test_real_cli_parser_does_not_claim_a_nonexistent_action_command():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["workflow", "action", "pulse_pump"])


def test_target_resolution_uses_only_operator_read_models():
    client = FakeOperator()
    client.responses.update({"status": {"controller": {"id": "c1", "generation": 3}},
                              "binding": {"generation": 3},
                              "instrument": {"id": "instrument-1", "device_identity": "MEV-1",
                                              "capabilities": {"temperature_setpoint": {"supported": False}}}})
    resolved = resolve_target(client, "MEV-1")
    assert resolved.generation == 3
    assert resolved.capabilities["temperature_setpoint"]["supported"] is False
    assert [item[0] for item in client.requests] == ["status", "binding", "instrument"]


def test_repeatable_stage_projection_and_add_are_shared_and_non_actuating():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))
    session.preflight()
    session.advance()
    session.continue_stage()

    projection = host.project_stage_instances(session, "points")
    assert (projection.title, projection.cardinality, projection.can_add) == ("Calibration Points", "repeatable", True)
    assert [(item.name, item.schema["type"], item.required) for item in projection.parameters] == [
        ("reference_value", "number", True),
    ]
    created = host.add_stage_instance(session, "points", {"reference_value": 12.5})
    assert created.instances[-1]["id"] == "points-1"
    assert created.instances[-1]["parameters"] == {"reference_value": 12.5}
    assert host.operator.requests == []


def test_repeatable_stage_rejects_once_and_invalid_parameters_without_creation():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))
    session.preflight()
    with pytest.raises(ValueError, match="not accepting"):
        host.add_stage_instance(session, "setup", {})
    session.advance()
    session.continue_stage()
    with pytest.raises(ValueError, match="required instance parameters"):
        host.add_stage_instance(session, "points", {})
    with pytest.raises(ValueError, match="invalid instance parameter type"):
        host.add_stage_instance(session, "points", {"reference_value": "not-a-number"})
    assert host.project_stage_instances(session, "points").instances == ()


def test_draft_projection_exposes_trusted_templates_without_creating_instances():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))

    projection = host.project_session_for_ui(session)

    assert [stage["id"] for stage in projection["procedures"]] == ["setup", "points", "review"]
    assert all(stage["steps"] for stage in projection["procedures"])
    assert all(stage["instances"] == [] for stage in projection["procedures"])
    assert projection["selected_step"] == "complete"
    assert session.instances == {"setup": [], "points": [], "review": []}


def test_inspection_selection_changes_projection_only():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))
    before = (session.state, session.active_stage_id, session.active_instance_id, dict(session.parameters))

    projection = host.project_session_for_ui(session, {"stage_id": "review", "step_id": "complete"})

    assert {key: projection["inspection"][key] for key in ("stage_id", "step_id")} == {
        "stage_id": "review", "step_id": "complete",
    }
    assert projection["selected_step"] == "complete"
    assert (session.state, session.active_stage_id, session.active_instance_id, dict(session.parameters)) == before


def test_trusted_temperature_workflow_draft_projects_all_stages_without_operator_calls():
    from pathlib import Path

    client = FakeOperator()
    root = Path(__file__).resolve().parents[3]
    host = production_host(client, target="MEV-1", simulator=True, repository_root=root)
    session = host.new_session(host.show_workflow("calibration.temperature"))

    projection = host.project_session_for_ui(session)

    assert [stage["id"] for stage in projection["procedures"]] == ["setup", "points", "review"]
    assert all(stage["steps"] for stage in projection["procedures"])
    assert all(not stage["instances"] for stage in projection["procedures"])
    assert client.requests == []


def test_inspection_selection_honors_repeatable_instance_identity():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))
    session.preflight()
    session.advance()
    session.continue_stage()
    host.add_stage_instance(session, "points", {"reference_value": 1.0})
    host.add_stage_instance(session, "points", {"reference_value": 2.0})

    projection = host.project_session_for_ui(session, {
        "stage_id": "points", "instance_id": "points-2", "step_id": "complete",
    })

    assert projection["inspection"]["instance_id"] == "points-2"


def test_default_inspection_follows_active_instance_when_step_ids_repeat():
    host = ScenarioRegistry().host("repeatable_calibration")
    session = host.new_session(host.show_workflow("scenario.repeatable-calibration"))
    session.preflight()
    session.advance()
    session.continue_stage()
    host.add_stage_instance(session, "points", {"reference_value": 1.0})
    host.add_stage_instance(session, "points", {"reference_value": 2.0})

    projection = host.project_session_for_ui(session)

    assert projection["inspection"]["stage_id"] == session.active_stage_id == "points"
    assert projection["inspection"]["instance_id"] == session.active_instance_id == "points-2"
