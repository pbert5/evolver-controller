# evoctl workflow host contract

`meta_webui_application_backend.evolver_edge.workflow_host` is the single
controller-local bridge from the frozen `evolver_procedure_runtime` contracts
to operator authority.

`WorkflowHost` owns workflow list/show/search, session construction, target
projection, preflight, sink adapters, and one `ActionProjection` used by Step,
Action, API, CLI, and Raw renderers. `ProcedureActionInvoker` is the only
runtime action adapter. Physical commands use `OperatorClient`'s typed
`hardware` operation and retain operator, lease, physical opt-in, generation,
and command identity. The host never opens serial/USB or accesses EdgeStore.

The initial realization matrix is intentionally conservative:

- physical `set_temperature` is `unsupported` under #58; simulator targets
  report `simulator_only`;
- trusted `set_stirring` is `unsupported` because a target is not equivalent to
  the bounded `set_stir` pulse;
- bounded pump actions are available only when the target reports
  `pump_control.supported`;
- `stop_actuator` is `blocked_dependency` until the dedicated #47 safe-stop
  authority is injected; it is never replaced by another actuator command;
- observations are `read_only_available` and retain operator read-model
  evidence; session-local actions remain local.

Preflight resolves these classifications before invocation. Unavailable
actions fail closed with reason and capability provenance. ACK/accepted
responses remain bounded operator/protocol evidence and are not promoted to
physical or scientific success.

Edge observation, central observation, and checkpoint export are separate
adapters. There is no central-to-edge fallback, and checkpoint destinations
are supplied by host configuration as opaque runtime identities rather than
descriptor paths.
