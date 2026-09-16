---
aliases:
  - Central vs Edge
---
# Central vs Edge

Central and edge are different authorities.

`evolver-server` owns central intent, enrollment, controller fencing, sync,
telemetry projections, operator API behavior, and central persistence.
`metactl` is a client of that central control plane.

`evolver-controller` owns durable controller state, controller-initiated sync,
command execution, orphan behavior, and the local operator API. `evoctl` is the
local controller operator CLI.

`evolver-hardware` owns serial transport and hardware observation. It is the
exclusive serial owner and does not become a general central datastore.

Central state describes intent and central projection. Edge state describes
controller-local reality. Hardware evidence describes observed physical state.
Operator tools must preserve those distinctions instead of presenting one layer
as proof of another.

Related: [Operator Bootstrap](operator-bootstrap.md) `[[Operator Bootstrap]]` ·
[Command Disposition](command-disposition.md) `[[Command Disposition]]` ·
[Physical Evidence](physical-evidence.md) `[[Physical Evidence]]`
