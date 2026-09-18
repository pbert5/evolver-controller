# Temperature setpoint integration contract

Issue #83 integrates the reviewed temperature-setpoint component heads into
`hardware-testing`. The public action remains `set_temperature` in Celsius;
the controller derives a bounded raw ADC target from the exact immutable,
per-vial calibration reference in the run bundle. The hardware service is the
exclusive serial owner and retains only volatile refresh state.

The evidence ladder is intentionally separate:

`requested -> validated -> command sent -> correlated protocol ACK -> refresh
active -> telemetry observed -> thermal/physical evidence`

A protocol ACK is only protocol evidence. It is not evidence that a vial
reached its target, that calibration is physically valid, or that a heater
changed state. Simulator behavior is `simulator_only`; hardware fakes and
fixtures never establish physical verification.

The integrated pins are:

| component | reviewed source | exact head |
| --- | --- | --- |
| firmware source | `pbert5/evolver-arduino` PR #1 | `f10de7bab8aa800e0e76ec64c2851b5ed7020c1d` |
| hardware | `pbert5/evolver-hardware` PR #2 | `018590854aff8ea886138b37d6af0dd5ab82a8ea` |
| controller | `pbert5/evolver-controller` PR #13 | `01fd57f24685acdc907ebeb54e61d6585d5f2afd` |

WorkflowHost availability must remain conservative: physical execution is
available only for hardware protocol v2 plus a matching eligible calibration
reference; v1 devices and missing, stale, ambiguous, or out-of-range
calibration are unavailable before side effects. No workflow may substitute a
heater pulse, raw ADC public input, procedure-host PID, or mutable latest
calibration.

This contract does not claim firmware upload, deployment, serial access,
heater actuation, thermal success, or physical safe-stop proof. Those remain
human-authorized follow-up work under #34/#73.

## Integration gate

The exact component heads must agree on one v2 wire grammar and raw-target
bounds before the Meta BAL PR can merge. The heater-output ceiling (64) must
not be confused with the raw ADC target bound (1..65535), and a protocol ACK
must not be promoted to thermal success. Any disagreement is a blocking
integration finding, not a documentation-only discrepancy.
