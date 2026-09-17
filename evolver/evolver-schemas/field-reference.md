# eVOLVER schema field reference

This index points to the authoritative LinkML definitions; it is not a second
schema.

| Concern | Module |
|---|---|
| identifiers and provenance | [`instrument/base.yaml`](instrument/base.yaml) |
| hardware and serial evidence | [`instrument/hardware.yaml`](instrument/hardware.yaml) |
| calibration | [`instrument/calibration.yaml`](instrument/calibration.yaml) |
| experiment and BAL samples | [`instrument/experiment.yaml`](instrument/experiment.yaml) |
| programs and state machines | [`instrument/experiment_program.yaml`](instrument/experiment_program.yaml) |
| requirements | [`instrument/requirements.yaml`](instrument/requirements.yaml) |
| measurements | [`instrument/measurement.yaml`](instrument/measurement.yaml) |
| validation | [`instrument/validation.yaml`](instrument/validation.yaml) |
| fixtures | [`instrument/fixture.yaml`](instrument/fixture.yaml) |
| transport payloads | [`instrument/protocol.yaml`](instrument/protocol.yaml) |

`instrument/schema.yaml` composes these LinkML modules. Composition does not
authorize actuation; identity, fencing, attribution, and hardware evidence are
runtime concerns.
