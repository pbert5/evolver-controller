# Trusted actions and physical boundaries

Trusted action IDs are the workflow action registry, not a CLI-only catalog:

```text
evoctl action list
evoctl action show capture_measurement
evoctl action availability capture_measurement --target INSTRUMENT_ID
evoctl action preflight capture_measurement --target INSTRUMENT_ID --parameters '{}'
evoctl action run capture_measurement --target INSTRUMENT_ID --parameters '{}'
```

`availability` reports the classification and reason for a target. `preflight`
must be used before any run and invokes no action. `run` uses the same
`ProcedureActionInvoker` authority as workflows and returns bounded evidence;
it is not a shortcut around controller policy.

Physical or mutating actions require all applicable controls: operator
attribution, an active lease, controller-generation fencing, bounded
parameters, idempotency/correlation, explicit `--physical` opt-in, and
safe-stop authority. A protocol ACK is not physical success. A rejected,
unavailable, stale-generation, or lease-expired result is an operator outcome,
not an invitation to retry through another path.

`set_temperature` remains a truthful registry action but its physical
capability is owned by #60. This workstream does not claim or implement that
setpoint path. TUI reliability (#99), firmware, and arbitrary host/Docker
commands are likewise outside this CLI documentation contract.
