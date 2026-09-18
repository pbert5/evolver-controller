# Repository Codex agent workflow

This repository uses native Codex multi-agent primitives for approved GitHub
workstreams. The configured ceiling is eight concurrent threads and depth two.

```text
depth 0  primary-executor (bookkeeping only)
depth 1  workstream-owner (one issue, branch, and worktree)
depth 2  scout / adviser / implementation specialist / verifier / reviewer / repair worker
```

The primary executor first asks `prompt-loader` for a compact launch capsule,
then launches isolated workstream owners as the approved DAG makes them ready.
An owner may implement directly. It uses a depth-2 specialist only when that
decomposition is useful; it is not required to route every action.

## Capacity and supervision

Count an active owner together with reserved capacity for its possible
depth-2 specialist. Keep a checker/auditor reserve when a terminal claim needs
independent review. The executor must never fill all eight slots with owners
that are waiting for children. Reclaim capacity only after terminal state or a
durable blocked handoff.

Observation is passive. Inspect lifecycle state and emitted output, wait with a
long/infrequent backoff, and continue unrelated READY work. Do not send
routine `status?` or `progress?` messages. Send input only for a changed
constraint, owner-requested clarification, safety/resource conflict, or an
explicit unblock.

## Terminal packet and acceptance

An owner terminal packet is a claim, not proof. It must contain:

```text
status
issue / branch / worktree / HEAD / PR
completed contract
claimed validation
durable GitHub Session handoff
blockers / follow-ups
Trust audit:
  subjective confidence percentage or band
  claims trusted least
  untested or hard-to-observe behavior
  possible conflicts or misunderstandings
  next evidence that would most reduce uncertainty
```

The confidence value is subjective and never an acceptance criterion. The
independent `completion-checker`, together with the relevant existing
`test-verifier`, `integration-reviewer`, `test-architect`, `repo-scout`, or
`recovery-advisor`, supplies authoritative evidence. Checker states are
`PASS`, `PASS_WITH_FOLLOWUPS`, `CHANGES_REQUIRED`, `BLOCKED_AMBIGUOUS`, and
`BLOCKED_DEPENDENCY`. Only PASS or PASS_WITH_FOLLOWUPS unlocks a dependent
node. A repair contract must be bounded and evidence-backed.

Every exit posts a durable GitHub Session handoff with branch/base/HEAD/PR,
changes, validation, nested-spawn evidence, review result, limitations, Trust
audit, and the exact next action. Tooling defects that persist beyond the
session are recorded as GitHub issues using the repository's canonical bug
label. No workflow in this document changes product semantics, deploys,
actuates hardware, changes credentials, force-pushes, or merges protected
branches.

## Harmless runtime smoke

Run this from a fresh Codex session using the repository roles, without product
or hardware access:

1. Launch one `primary-executor` and give it a tiny synthetic two-node DAG.
2. Have it launch one `workstream-owner`; the owner launches a read-only
   depth-2 `repo-scout` that reports a known file/HEAD.
3. Use a passive wait. Confirm the owner consumes the scout result and returns
   only the compact terminal packet to the executor.
4. Launch `completion-checker` with that packet; on PASS, record the dependent
   node as READY and launch it.
5. Record the runtime evidence: depth-1 to depth-2 spawn, returned results,
   no routine `send_input` status ping, and slot accounting showing an owner,
   nested reserve, and checker reserve can coexist.

This smoke is an orchestration check only. It must not edit repository files,
create product artifacts, call hardware, or merge anything.
