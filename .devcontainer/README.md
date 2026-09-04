# Meta Ball Dev Container platform

The `server` profile is the canonical shared development environment. Both
profiles build from `.devcontainer/Dockerfile`; its `base` stage owns the
Python, uv, RTK, navi, and Codex versions, while `server` and `evolver-edge`
add only their profile-specific tools and launchers.

Each worktree gets an isolated uv cache volume named
`meta-ball-${META_BALL_WORKTREE_ID}-uv-cache`, mounted at
`/home/vscode/.cache/uv`. The edge profile additionally mounts the stable
`evolver-edge-runtime` volume at `/run/evolver-controller`; that volume is the
only shared runtime state between the edge stack and its Dev Container.
