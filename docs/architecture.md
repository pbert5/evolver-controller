# Architecture and ownership

`evolver-server` owns central intent, enrollment, controller fencing, sync,
telemetry, operator API, and its own database. `evolver-controller` owns the
edge durable state, central-initiated-by-client sync, command execution,
orphan behavior, `evolverctl`, and host/systemd installer/update behavior.
`evolver-hardware` exclusively owns serial transport and its bounded local IPC;
it has no PostgreSQL or catalog dependency. `metactl` is an operator API client.
`evolver-protocol` is reserved for contracts that genuinely need an independent
lifecycle. `evolver-arduino` remains the existing firmware source repository.

Central is future/operator intent; edge is physical/current reality. ACKs are
not physical observations. Controller communication is controller-initiated,
authenticated, and generation fenced. Meta WebUI and BAL catalog code remain
private and are not required by public components.
