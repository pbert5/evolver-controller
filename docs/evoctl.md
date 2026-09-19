# evoctl

`evoctl` is the implemented controller-local operator CLI. Use it when you are
working on one controller and need local inspection, recovery, lifecycle, or
hardware-observation information. For central fleet operation, use
[metactl](metactl/README.md) instead.

In the eVOLVER Edge Dev Container run:

```text
evoctl ...
```

From the host use:

```text
tools/dev-env evolver-edge exec evoctl ...
```

Read-only inspection:

```text
evoctl status
evoctl binding
evoctl runs
evoctl instruments
evoctl doctor
```

Edge lifecycle operations use the fixed host-runtime adapter boundary:

```text
evoctl runtime status|up|stop|down|restart|logs
evoctl up|down|restart|logs
```

These commands report a bounded delegation intent for the host-owned edge
services; they do not accept Compose projects, paths, container IDs, shell
fragments, or Docker/socket options from the controller runtime.

Governed release updates remain distinct:

```text
evoctl update check RELEASE
evoctl update apply RELEASE
evoctl runtime upgrade
evoctl upgrade
```

`update apply RELEASE` applies an explicitly named governed release. `upgrade`
uses only the authoritative configured recommended release and is unavailable
with a clear diagnostic when none is selected; active runs defer it. The
developer-only `tools/evolver-edge upgrade` checkout-refresh contract is a
separate operation and is not invoked by `evoctl`.

`--offline` reads the durable controller store without contacting the local
operator socket. It does not prove central state or physical hardware was
observed. Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`.

## Native operator shell

`evoctl tui` opens one controller-native Textual application with these views:

```text
Overview | Controllers | Instruments | Runs | Recovery | Maintenance | Workflows
```

Use `evoctl tui --page <view>` to select the initial view, or
`evoctl tui --workflow` as the equivalent Workflows deep-link. `Ctrl+Left` /
`Ctrl+Right` and `Ctrl+[` / `Ctrl+]` move between views; `1` through `7`
select a view when a text field is not focused; `r` refreshes the current
read-only projection and `?` shows the key reference.

Live views use only the typed controller operator read contract. `--offline`
uses `OfflineTuiSource` and the durable edge store only when explicitly
selected. The native app factory is `create_app(source=..., workflow_host=...,
initial_view=...)`; this is the deterministic source seam for #132. No evoctl
TUI startup requires `app.yaml`, configured page YAML, a Meta WebUI compiler,
Meta WebUI Textual runtime, extension manifests, or Meta WebUI query
composition.

Workflows remain backed by the reviewed `WorkflowHost` and workspace model,
including repeatable instances, typed input, API/CLI representation mapping,
refresh coalescing, safe close, and active-instance inspection. The shell does
not add mutation controls to the other six views.

The controller owns durable edge state; the hardware daemon owns serial access
and observation state. Do not open serial devices or write the controller DB
from an operator script. Hardware observations are evidence across private IPC,
not identity or command authority. Enrollment, handoff, forced adoption,
release changes, uninstall, firmware upload, and actuation retain their
operator, confirmation, generation, lease, and physical-evidence checks.

## Runtime lifecycle QoL

A first-class host-runtime convenience surface is planned in
[Runtime Lifecycle QoL](runtime-lifecycle-qol.md) and tracked by issue #112.

The planned `upgrade` command is deliberately distinct from the existing
explicit release contract:

```text
evoctl update apply RELEASE   # explicit governed release
evoctl upgrade                # latest/recommended governed release
tools/evolver-edge upgrade    # developer checkout refresh/rebuild
```

The integrated lifecycle aliases are available on the `hardware-testing` line.
Use `tools/evolver-edge upgrade` only for the developer checkout flow; use
`evoctl update ...` and governed `evoctl upgrade` for release operations.

## Workflow CLI

The workflow commands use the same trusted library, `WorkflowHost`, and
session runtime as the workflow UI:

```text
evoctl workflow list [--search TEXT]
evoctl workflow show WORKFLOW_ID
evoctl workflow preflight WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
evoctl workflow run WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
```

`preflight` performs read-only target/capability resolution and never invokes
an action. `run --jsonl` emits versioned, deterministic records with bounded
structural redaction; lease tokens, credentials, and raw unbounded responses
are not emitted. Ctrl+C during a run calls the runtime abort path and reports
the terminal cleanup outcome.

Product tests and preview tooling can use the side-effect-free scenario seam:

```python
from meta_webui_application_backend.evolver_edge.workflow_cli import ScenarioRegistry
host = ScenarioRegistry().host("waiting_for_input")
```

Scenario hosts use the public host/session contracts and an in-memory operator;
they do not open sockets, access stores, or touch hardware.

Central catalog entries marked `planned` are not callable capabilities;
experiment enqueue/run and run-start remain planned.

## Related

- [Runtime Lifecycle QoL](runtime-lifecycle-qol.md)
- [Operator guide](operator.md) `[[Operator Guide]]`
- [Central vs Edge](_concepts/central-vs-edge.md) `[[Central vs Edge]]`
- [Command Disposition](_concepts/command-disposition.md) `[[Command Disposition]]`
- [Physical Evidence](_concepts/physical-evidence.md) `[[Physical Evidence]]`
