---
aliases:
  - Physical Evidence
---
# Physical Evidence

Physical Evidence is observation that supports a claim about real hardware
behavior. It is distinct from command acceptance, queueing, or software
completion.

Examples can include hardware-daemon observations, sensor/telemetry changes,
or other explicitly modeled evidence that crosses the hardware IPC boundary.
The controller and central server may record this evidence, but they must not
manufacture it from an ACK.

Operator UIs should therefore separate:

- request accepted;
- command queued/running/completed;
- physical actuation verified;
- physical outcome unknown or unavailable.

Tests for operator surfaces should use simulator/mock/fixture evidence by
default and must not actuate real hardware without explicit authorization.

Related: [Command Disposition](command-disposition.md) `[[Command Disposition]]` ·
[Central vs Edge](central-vs-edge.md) `[[Central vs Edge]]` ·
[Safety Mode](safety-mode.md) `[[Safety Mode]]`
