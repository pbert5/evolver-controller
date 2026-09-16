@RTK.md

# Codex workspace configuration

The repository `.codex/config.toml` is the source of truth for workspace agent
spawning. Keep `agents.enabled = true`, `features.multi_agent = true`, and
`agents.max_concurrent_threads_per_session = 8`; preserve every named role in
`.codex/agents/`. Use `features.hooks` for lifecycle hooks. `features.codex_hooks`
is deprecated and must not be reintroduced.

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
