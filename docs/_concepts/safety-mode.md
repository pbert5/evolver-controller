---
aliases:
  - Safety Mode
---
# Safety Mode

Safety Mode is the client-side guardrail that controls whether the operator UI
may send read, mutation, destructive, or hardware-classified actions.

It is not authorization. Server permissions, revision/generation fencing,
manual-control leases, identity rules, and physical interlocks remain
authoritative even when a client mode permits a request.

The operator TUI begins in `SAFE`, which favors read operations. Mutations must
make their effect visible and follow the catalog-defined confirmation policy.
Potential hardware actions require the strongest client guardrail and must
never be represented as physically successful merely because the request was
accepted.

Safe-stop is currently a recorded intent in the controller/edge command
contract, not a settled product policy. Its capability metadata or a returned
acknowledgement does not select lease-free versus lease-bound semantics and
does not prove that hardware physically stopped. Until the decision is made,
operator surfaces must label the request as unresolved/unavailable for
physical completion and preserve the distinction between intent, protocol
completion, and physical observation.

The existing API Workbench has its own explicit `--allow-mutations` and
`--allow-hardware` controls. The operator TUI should preserve the same safety
principle without duplicating the Workbench's raw-request workflow.

Related: [Action Catalog](action-catalog.md) `[[Action Catalog]]` ·
[Command Disposition](command-disposition.md) `[[Command Disposition]]` ·
[Physical Evidence](physical-evidence.md) `[[Physical Evidence]]`
