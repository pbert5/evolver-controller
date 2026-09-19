# Temperature setpoint integration contract

Issue #83 integrates the reviewed temperature-setpoint component heads into
`hardware-testing`. The public action remains `set_temperature` in Celsius;
the controller derives a bounded raw ADC target from the exact immutable,
per-vial calibration reference in the run bundle. The hardware service is the
exclusive serial owner and retains only volatile refresh state.

The evidence ladder is intentionally separate:

`requested -> validated -> command sent -> correlated protocol ACK -> refresh
active -> telemetry observed -> thermal/physical evidence`

The authoritative firmware frame is the fenced nine-field
`TEMP|2|SET|correlation|channel|raw|owner|wire_lease|generation_!` grammar.
The legacy `HW_TEMP_V2` grammar is fail-closed. The controller derives the
positive uint32 `wire_lease` as the first eight hexadecimal SHA-256 digits of
the opaque lease token; correlation and generation are positive uint32 values.

A protocol ACK is only protocol evidence. It is not evidence that a vial
reached its target, that calibration is physically valid, or that a heater
changed state. Simulator behavior is `simulator_only`; hardware fakes and
fixtures never establish physical verification.

The integrated pins are:

| component | reviewed source | exact head |
| --- | --- | --- |
| firmware source | `pbert5/evolver-arduino` PR #1 | `83483cda621a2e913ad778ae62294872084a507a` |
| hardware | `pbert5/evolver-hardware` PR #2 | `78a17ebf90b64fea394a05a670ce6b58820fa377` |
| controller historical #60 source | `pbert5/evolver-controller` PR #13 | `c9b1eb24e35a52f4f328793b3b4891a314b6ba25` |

The final #103 native-TUI integration controller pin is
`7ac90e4a2abb1dcf8b5065479a20d209a8a33171`; it is required to retain the
temperature-setpoint head above and the reviewed native-TUI head
`4f3b2205315d7f9bc3783d83a7ae26dc749cebf9` as ancestry. The reviewed #151
controller composite is `a915a733372c6682676c8c806b82a61200a4cb02`; the root
integration pins that exact head after consuming accepted #108/#114 behavior.

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
