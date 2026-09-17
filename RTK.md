# RTK - Rust Token Killer (Codex CLI)

**Usage**: Token-optimized CLI proxy for shell commands.

## Rule

Always prefix shell commands with `rtk`.

Examples:

```bash
rtk git status
rtk cargo test
rtk npm run build
rtk pytest -q
```

## Meta Commands

```bash
rtk gain            # Token savings analytics
rtk gain --history  # Recent command savings history
rtk proxy <cmd>     # Run raw command without filtering
```

## Verification

```bash
rtk --version
rtk gain
which rtk
```

## Repository guidance

Use RTK for repository shell commands:

```bash
rtk tools/dev-env server check
rtk tools/dev-env server smoke
rtk tools/check-locks
rtk tools/test fast
```

The Dev Containers install the pinned RTK release and shared toolchain. When a
host command is unavailable, enter the Server profile before installing
anything locally. The older action-first `tools/dev-env check server` form is
accepted, but profile-first is canonical.
