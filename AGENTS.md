@RTK.md

# Codex workspace configuration

The repository `.codex/config.toml` is the source of truth for workspace agent
spawning. Keep `agents.enabled = true`, `agents.max_depth = 2`,
`features.multi_agent = true`, and `agents.max_concurrent_threads_per_session =
16` when accepted by the live runtime; if fresh-runtime evidence proves a lower
stable ceiling, record and use that ceiling instead. Preserve every named role
in `.codex/agents/`. The normal hierarchy is one
bookkeeping-only `primary-executor`, isolated first-order `workstream-owner`
agents, and optional depth-2 specialists. A workstream owner may implement
directly and becomes a local dispatcher only when decomposition is useful.
`prompt-loader` keeps issue archaeology out of the executor context. Completion
checkers are owner-local depth-2 specialists, not mandatory root gates; the
owner's accepted terminal state is authoritative for DAG scheduling.
Use `features.hooks` for lifecycle hooks. `features.codex_hooks` is deprecated
and must not be reintroduced. The `test-architect` role is read-only and may
use shell tools for harmless repository reconnaissance; it must not edit,
commit, push, or mutate runtime state.

The primary executor must not allocate per-stream quotas, central stream locks,
or root-owned verifier/reviewer/repair lifecycles. The runtime-wide ceiling is
the constraint; owners manage and clean up their own depth-2 children.
Supervision is passive and infrequent: inspect lifecycle/output and wait with
backoff, but do not send routine status-ping messages. Send input only for a
changed constraint, owner-requested clarification, safety/resource conflict, or
explicit unblock.

Every owner exit posts a durable GitHub Session handoff and returns a compact
terminal packet containing status, issue/branch/worktree/HEAD/PR, completed
contract, claimed validation, handoff reference, blockers/follow-ups, and a
Trust audit (confidence band, least-trusted claims, untested behavior,
possible conflicts, and the next evidence that would reduce uncertainty).
The owner completes local independent verification/review, persists every
`CHANGES_REQUIRED` finding before repair, repairs or delegates bounded repair,
and re-runs verification/review before returning an accepted packet. For
scheduling, `PASS` or `PASS_WITH_FOLLOWUPS` in that packet is authoritative;
the executor does not run a second acceptance ceremony. PROMPT_READY reversible
work does not require another design approval ceremony. Runtime/tooling defects
are recorded as GitHub issues with the repository's canonical bug label when
one is needed.

# Repository agent guidance

## Development and test environment

Do not treat missing host-level `python`, `pytest`, or `uv` as a blocker in this repository. The supported development/test toolchain is provided by the Meta Ball Dev Containers.

Use the repository helper to enter the appropriate container and run tests there. For example:

```bash
rtk tools/dev-env server up
rtk tools/dev-env server exec rtk tools/test all
rtk tools/check-locks
```

The Server profile currently provides Python 3.12, `uv`, `pytest`, `pytest-xdist`, `pytest-cov`, PyYAML/component dependencies, Docker/Compose access, and RTK. Prefer repository-owned container tooling over installing Python or test dependencies onto the host.

Use `rtk` as the shell command prefix for repository commands, including
commands run inside a Dev Container. `tools/dev-env` accepts the legacy
action-first spelling (`tools/dev-env up server`) for compatibility, but
profile-first is canonical. Run `tools/check-locks --relock` only when
deliberately refreshing `uv.lock`; review the resulting diff before committing.

The root `tools/test` dispatcher is the authoritative test entry point. It uses `uv run --project ... pytest` and launches separate pytest processes for the root, controller, hardware, server, and metactl components so their import environments remain isolated.

When a task needs the physical-controller development environment, use the `evolver-edge` Dev Container/profile instead of adding host-level Python tooling or bypassing the containerized edge architecture.

Before declaring a test unavailable because a command is missing on the host, check whether the corresponding repository Dev Container/profile provides it and run the test there.
