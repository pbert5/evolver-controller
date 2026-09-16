---
aliases:
  - Command Disposition
---
# Command Disposition

Command Disposition is the recorded protocol state of a controller command. It
answers what the control system knows about command handling, not whether a
physical effect definitely occurred.

Examples include queued/accepted states while work is pending and terminal
states such as completed, failed, expired, rejected, quarantined, or safe-stop
intent recorded. The exact vocabulary remains defined by the runtime contract.

An accepted or queued disposition means the command entered the protocol. A
completed disposition means the software command lifecycle reached completion.
Neither statement alone is sufficient evidence of physical actuation.

Operator surfaces must display disposition separately from any
`physical_actuation_verified` or hardware-observation evidence.

Related: [Physical Evidence](physical-evidence.md) `[[Physical Evidence]]` ·
[Central vs Edge](central-vs-edge.md) `[[Central vs Edge]]`
