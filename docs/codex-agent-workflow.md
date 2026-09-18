# Repository Codex agent workflow

This repository uses native Codex multi-agent primitives for approved GitHub
workstreams. The repository target is sixteen concurrent threads with depth two:
the live runtime smoke must confirm sixteen, or record the highest stable value
it actually accepts without claiming the target.

```text
depth 0  primary-executor (bookkeeping-only scheduler)
depth 1  workstream-owner (one issue, branch, and worktree; complete lifecycle)
depth 2  scout / adviser / implementation specialist / verifier / reviewer / repair worker
```

The primary executor asks a short-lived `prompt-loader` for a compact launch
capsule, launches isolated first-order owners as the approved DAG makes them
ready, passively observes emitted terminal state, and reclaims finished agents.
An owner may implement directly. It uses depth-2 specialists only when useful;
it is not required to route every action through a child.

## Owner-local lifecycle

The first-order owner owns its issue, branch/worktree/PR, local DAG, nested
children, implementation, verification, independent review, review-history
checkpointing, repair, re-verification, durable handoff, and terminal
classification.

Before spawning a child, the owner closes finished or stale children it owns.
After consuming and durably recording a child result, it closes that child
immediately. If a reviewer returns `CHANGES_REQUIRED`, the owner persists the
finding before repair, performs or delegates the bounded repair, and re-runs
verification/review locally. It continues until accepted or genuinely blocked.
The primary executor never pulls this loop into the root.

## Scheduler and cleanup

The runtime-wide thread ceiling is the only capacity constraint. The executor
does not create a per-stream slot broker, quota allocator, or ordinary stream
lock. Real external exclusivity (a physical device, serial bus, mutable
database, deployment lane, or similar resource) remains in the workstream
contract or a dedicated shared-resource workstream.

Observation is passive: inspect lifecycle state and emitted output, then wait
with long/infrequent backoff while continuing unrelated READY work. Never send
routine `status?` or `progress?` messages. Send input only for a changed
constraint, owner-requested clarification, safety/resource conflict, or an
explicit unblock.

Close the prompt-loader immediately after its capsule is consumed. Close a
first-order owner immediately after the executor consumes its terminal packet
and durable handoff. If an owner is blocked, it persists the blocker, returns a
blocked packet, and is closed; the DAG can relaunch it later from GitHub state.
If `agent thread limit reached` appears, reclaim terminal/stale agents first;
never move review or repair into the executor to work around pressure.

## Terminal packet and acceptance

An owner terminal packet is a claim for auditability, but an accepted owner
state is authoritative for scheduling; the executor does not run a second
acceptance ceremony. It must contain:

```text
status (PASS, PASS_WITH_FOLLOWUPS, or a blocked classification)
issue / branch / worktree / HEAD / PR
completed contract
claimed validation and local review/re-review evidence
durable GitHub Session handoff
blockers / follow-ups
Trust audit:
  subjective confidence percentage or band
  claims trusted least
  untested or hard-to-observe behavior
  possible conflicts or misunderstandings
  next evidence that would most reduce uncertainty
```

`PASS` or `PASS_WITH_FOLLOWUPS` unlocks a dependent DAG node directly. A
depth-2 `completion-checker` or relevant domain reviewer may independently
review the work for the owner, but it is not a mandatory root-owned
post-handoff gate. Checker states are `PASS`, `PASS_WITH_FOLLOWUPS`,
`CHANGES_REQUIRED`, `BLOCKED_AMBIGUOUS`, and `BLOCKED_DEPENDENCY`; the owner
consumes the result and owns the next local transition.

Every exit posts a durable GitHub Session handoff with branch/base/HEAD/PR,
changes, validation, nested-spawn and cleanup evidence, review state,
limitations, Trust audit, and the exact next action. Tooling defects that
persist beyond the session are recorded as GitHub issues using the repository's
canonical `bug` label. No workflow here changes product semantics, deploys,
actuates hardware, changes credentials, force-pushes, or merges protected
branches.

## Harmless runtime smoke

Run this from a fresh Codex configuration context using the repository roles,
without product or hardware access:

1. Launch one `primary-executor` with a synthetic DAG containing three
   independent first-order owners and one dependent node.
2. Confirm all three owners run concurrently and each owner launches at least
   one read-only depth-2 specialist without root assistance.
3. Have one owner exercise implementation → independent local review →
   `CHANGES_REQUIRED` → persisted finding → bounded local repair → re-review →
   `PASS`/`PASS_WITH_FOLLOWUPS` → accepted terminal packet.
4. Confirm the primary executor does not launch that stream's verifier,
   reviewer, or repair worker; it only consumes the terminal packet, closes the
   owner, and launches the dependent node directly.
5. Confirm prompt-loader and all finished depth-2 children close promptly,
   finished owners are reclaimed promptly, no routine `send_input` status ping
   occurs, and no stale-agent accumulation causes an avoidable thread-limit
   failure.
6. Record the exact Codex version, effective configured/proven thread ceiling,
   nested-spawn evidence, local repair/re-review evidence, cleanup evidence,
   and any runtime limitation in the GitHub Session handoff.

This smoke is an orchestration check only. It must not edit repository files,
create product artifacts, call hardware, or merge anything.
