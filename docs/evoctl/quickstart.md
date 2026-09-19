# evoctl quickstart

Run these examples in the canonical Edge Dev Container:

```text
tools/dev-env evolver-edge up
tools/dev-env evolver-edge exec evoctl --help
tools/dev-env evolver-edge exec evoctl status
tools/dev-env evolver-edge exec evoctl capabilities
tools/dev-env evolver-edge exec evoctl instrument list
tools/dev-env evolver-edge exec evoctl action list
tools/dev-env evolver-edge exec evoctl workflow list
```

The same commands can be run as `evoctl ...` inside the container. These are
inspection commands. A live operator socket can be unavailable even when the
CLI is installed; report that as an operator transport problem rather than
falling back to a local database.

For a non-actuating rehearsal, use the simulator and an action preflight:

```text
evoctl simulator start --instruments 1
evoctl action preflight capture_measurement --target simulator-1 --simulator --parameters '{}'
evoctl workflow preflight calibration --target simulator-1 --simulator
```

`preflight` resolves authority and bounds but invokes zero actions. Do not add
`--physical` or run a bounded actuator command merely to prove the CLI works.
