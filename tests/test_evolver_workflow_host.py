from __future__ import annotations

from evolver_procedure_runtime import ActionRef, MutationOutcome, WorkflowLibrary

from meta_webui_application_backend.evolver_edge.workflow_host import (
    Availability,
    HostContext,
    ProcedureActionInvoker,
    TargetKind,
    TargetProjection,
    WorkflowHost,
    resolve_target,
)


class FakeOperator:
    def __init__(self):
        self.requests = []
        self.responses = {"hardware": {"request_accepted": True, "evidence": "protocol_ack"},
                          "instrument": {"id": "MEV-1", "capabilities": {}}}

    def request(self, operation, params=None):
        self.requests.append((operation, params or {}))
        return self.responses.get(operation, {})


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
    assert projection.cli.startswith("evoctl workflow action pulse_pump")


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
