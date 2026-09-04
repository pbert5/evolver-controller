# eVOLVER operator guide

The implemented local CLI is `evolverctl`; `evoctl` is not an alias. In the
edge Dev Container run `evolverctl ...`; from the host use
`tools/dev-env evolver-edge exec evolverctl ...`.

Read-only inspection:

```text
evolverctl status
evolverctl binding
evolverctl runs
evolverctl instruments
evolverctl doctor
```

`--offline` reads the durable controller store without contacting the local
operator socket. It does not prove central state or physical hardware was
observed. Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`.

The controller owns durable edge state; the hardware daemon owns serial access
and observation state. Do not open serial devices or write the controller DB
from an operator script. Hardware observations are evidence across private
IPC, not identity or command authority. Enrollment, handoff, forced adoption,
release changes, uninstall, firmware upload, and actuation retain their
operator, confirmation, generation, lease, and physical-evidence checks.

Central catalog entries marked `planned` are not callable capabilities;
experiment enqueue/run and run-start remain planned.
