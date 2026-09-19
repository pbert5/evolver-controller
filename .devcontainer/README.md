# Meta Ball Dev Container platform

The `server` profile is the canonical shared development environment. Both
profiles build from `.devcontainer/Dockerfile`; its `base` stage owns the
Python, uv, RTK, navi, and Codex versions, while `server` and `evolver-edge`
add only their profile-specific tools and launchers.

Each worktree gets an isolated uv cache volume named
`meta-ball-${META_BALL_WORKTREE_ID}-uv-cache`, mounted at
`/home/vscode/.cache/uv`. The edge profile mounts only the operator runtime
volume at `/run/evolver-controller`; it has no controller state, hardware
state, hardware runtime, `/dev`, or hardware socket. The controller owns
durable state and the operator socket, while the hardware daemon owns its
state, private hardware socket, `/dev`, and serial.

The final live path is
`evoctl -> operator.sock -> controller -> hardware.sock -> hardware -> serial`.
Normal `evoctl` commands require that live operator path and do not silently
fall back to a local database. If the controller is stopped or unreachable,
run `tools/evolver-edge up`, `status`, or `logs controller`. Offline access is
outside the fixed lifecycle adapter; direct `evoctl --offline ...` is rejected
by the edge launcher.

Zsh is the canonical interactive shell in both profiles. Use
`tools/dev-env server shell` to enter it explicitly, or use the configured VS
Code terminal profile. `tools/dev-env server exec <command...>` remains the
non-interactive command path, including for Bash scripts.
