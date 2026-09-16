# eVOLVER operator guide

The implemented local CLI is `evoctl`. In the edge Dev Container run
`evoctl ...`; from the host use `tools/dev-env evolver-edge exec evoctl ...`.

Read-only inspection:

```text
evoctl status
evoctl binding
evoctl runs
evoctl instruments
evoctl doctor
```

Normal commands are live commands. They use the local operator service and
never silently fall back to a direct SQLite read:

`evoctl -> operator.sock -> controller -> hardware.sock -> hardware -> serial`

If the operator service is stopped or unreachable, the CLI reports that state
and points to `tools/evolver-edge up`, `tools/evolver-edge status`, and
`tools/evolver-edge logs controller`. The edge launcher returns an unavailable
exit status instead of presenting stale local data as live state.

Offline mode is an intentional rescue/maintenance mode. It reads the durable
controller store without contacting the operator socket and does not prove
central state or physical hardware was observed. Use the explicit route when
the controller service is stopped:

```text
tools/evolver-edge rescue recovery
tools/evolver-edge rescue export-state recovery.tar.zst
```

Equivalent direct use inside the edge container is `evoctl --offline ...`.
Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`; offline output must be labelled as
offline by the operator.

The controller owns durable edge state; the hardware daemon owns serial access
and observation state. Do not open serial devices or write the controller DB
from an operator script. Hardware observations are evidence across private
IPC, not identity or command authority. Enrollment, handoff, forced adoption,
release changes, uninstall, firmware upload, and actuation retain their
operator, confirmation, generation, lease, and physical-evidence checks.

Central catalog entries marked `planned` are not callable capabilities;
experiment enqueue/run and run-start remain planned.
