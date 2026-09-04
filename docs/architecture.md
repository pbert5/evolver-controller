# Architecture and ownership

`evolver-server` owns central intent, enrollment, controller fencing, sync,
telemetry, operator API, and its own database. `evolver-controller` owns the
edge durable state, central-initiated-by-client sync, command execution,
orphan behavior, `evolverctl`, and the local operator API. The preferred edge
deployment is the root-owned Docker Compose stack in `deploy/evolver-edge`:
the controller has no `/dev` or Docker socket, while `evolver-hardware` is the
exclusive privileged serial owner. Native/systemd installation remains a
legacy compatibility path.
`evolver-hardware` exclusively owns serial transport and its bounded local IPC;
it has no PostgreSQL or catalog dependency. `metactl` is an operator API client.
In the Meta BAL checkout these three component gitlinks live under `evolver/`;
the authoritative private instrument schema source is `evolver/evolver-schemas/`.
`evolver-protocol` is reserved for contracts that genuinely need an independent
lifecycle. `evolver-arduino` remains the existing firmware source repository.

The eVOLVER operator action catalog is the declarative source of truth for
externally exposed capabilities. It lives at
`metactl/applications/evolver/actions.json`; its validated `api` projection
contains the method/path contract. `metactl` projects that contract into CLI
transport, while `evolver-server` resolves it only through a trusted Python
adapter registry. Catalog registry bindings are labels, never import paths.

| Action / surface | Contract source | Runtime owner |
|---|---|---|
| controllers.list / runs.pause | action catalog | evolver-server |
| release.build | action catalog | trusted release adapter |
| controller sync | machine protocol | evolver-server/controller |
| health, action manifest | infrastructure/resource route | evolver-server |
| release artifacts | resource endpoint | release serving |
| hardware serial | local protocol | evolver-hardware |

Machine sync, health, telemetry/event exchange, artifact downloads, and local
hardware IPC remain separate protocols/resources; they are not forced into the
operator action abstraction.

`evolver-protocol` remains intentionally uncreated. Reconnaissance found no
shared public package, independent protocol release lifecycle, or existing
cross-repository dependency: the catalog is currently owned by `metactl` and
consumed by the integrated server projection. Revisit this decision when a
second independently versioned consumer requires the same public parser or
wire contract. No private BAL schema or lab data is part of the catalog.

Central is future/operator intent; edge is physical/current reality. ACKs are
not physical observations. Controller communication is controller-initiated,
authenticated, and generation fenced. Meta WebUI and BAL catalog code remain
private and are not required by public components.

The controller owns the authoritative durable state root
(`/var/lib/evolver-controller`). Hardware uses its own daemon-owned state and
observation spool (`/var/lib/evolver-hardware`) and does not open or migrate
the controller database. They share only the runtime directory
(`/run/evolver-controller`, backed by a runtime-only named volume) for distinct Unix sockets: the controller operator
socket and hardware IPC socket. Hardware observations cross that typed IPC
boundary as evidence; they are not direct writes to controller identity,
binding, command, or run state.
The controller initiates central communication; hardware uses isolated
networking and has no externally reachable port.
