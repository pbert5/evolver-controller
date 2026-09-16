# eVOLVER Edge Operator Overlay Design

## Goal

Make the Edge Dev Container a tooling-only client overlay. Normal `evoctl` and TUI operations use a typed local Unix operator API owned by `evolver-controller`; controller hardware actions use private hardware IPC owned by `evolver-hardware`, which alone owns serial and `/dev`.

## Boundaries and data flow

The Dev Container mounts only the operator runtime socket and Docker runtime helpers. It does not mount controller state, hardware state, hardware runtime, `/dev`, or the hardware socket. The controller mounts its durable state and both runtime channels. Hardware mounts its durable state, private hardware runtime, `/dev`, and udev. Local operation therefore follows `evoctl -> operator.sock -> controller domain/action -> hardware.sock -> hardware daemon -> serial`.

## Operator contract

Add a bounded, schema-checked request envelope `{operation, params}` and structured `{ok, result}` or `{ok:false,error:{kind,message}}` responses to the existing Unix operator service. Keep request-size limits, socket permissions, operation allowlisting, redaction, and controller safety/fencing checks. Capabilities expose protocol version and operation metadata including read/mutate and live/offline classification. Transport and domain failures map to stable typed errors.

## Client, CLI, and TUI

Create/reuse one operator client for `evoctl` and the TUI. Live commands—including status, binding, inventory, runs, doctor, calibration/update/sync requests, leases, hardware discovery/protocol tests, and bounded hardware operations—route through the controller API. `--offline` is explicit and limited to maintenance/rescue commands that intentionally open a local state root. Operator unavailability never triggers a SQLite fallback. The edge launcher adds Compose-specific guidance for stopped or unreachable services while preserving structured output and stable exit codes.

Firmware operations must not open serial from the Dev Container; if not representable through controller/hardware IPC, they remain explicit documented maintenance operations with the daemon intentionally stopped.

## Safety and concurrency

Controller-side hardware brokerage preserves operator attribution, target identity, lease, generation, physical opt-in, and bounded-parameter checks. Hardware retains a process-wide session mutex around the nonblocking cross-process `flock`, ensuring polling and IPC sessions serialize within one daemon while separate daemons still receive BUSY; exception cleanup always releases both.

## Verification

Focused executable contracts cover protocol validation/errors/capabilities, CLI routing and offline separation, unavailable UX, brokerage and safety fencing, mount topology, TUI data sourcing and optional dependencies, serial concurrency/cleanup, and central independence. Parent simulator/integration suites run on r640-0 in the canonical Dev Containers. Exactly one later worker performs read-only physical acceptance on `root-evolver`; no firmware upload or actuator movement is required.

