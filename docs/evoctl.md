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

`--offline` reads the durable controller store without contacting the local
operator socket. It does not prove central state or physical hardware was
observed. Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`.

The controller owns durable edge state; the hardware daemon owns serial access
and observation state. Do not open serial devices or write the controller DB
from an operator script. Hardware observations are evidence across private IPC,
not identity or command authority. Enrollment, handoff, forced adoption,
release changes, uninstall, firmware upload, and actuation retain their
operator, confirmation, generation, lease, and physical-evidence checks.

Central catalog entries marked `planned` are not callable capabilities;
experiment enqueue/run and run-start remain planned.

## Related

- [Operator guide](operator.md) `[[Operator Guide]]`
- [Central vs Edge](_concepts/central-vs-edge.md) `[[Central vs Edge]]`
- [Command Disposition](_concepts/command-disposition.md) `[[Command Disposition]]`
- [Physical Evidence](_concepts/physical-evidence.md) `[[Physical Evidence]]`
