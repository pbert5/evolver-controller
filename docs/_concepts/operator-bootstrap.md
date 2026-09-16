---
aliases:
  - Operator Bootstrap
---
# Operator Bootstrap

Operator Bootstrap is the repository-owned process that gives `metactl` one
truthful, reachable central target and the session configuration needed to use
it. It exists so operators do not need to reverse-engineer Dev Container
networking or manually copy URLs into each tool.

The bootstrap contract is:

1. explicit operator overrides win;
2. the shared `configured_transport()` remains the canonical resolver;
3. managed Meta Ball environments provision a reachable value for
   `META_WEBUI_METACTL_CENTRAL_URL` rather than teaching the TUI a separate
   network rule;
4. authentication material is passed through supported environment/credential
   mechanisms and is never printed by doctor or committed to the repository;
5. CLI, `metactl doctor`, and `metactl tui` must resolve the same target;
6. failure is explicit and actionable, never a silent switch to offline data.

The existing shared resolver already accepts `META_WEBUI_METACTL_CENTRAL_URL`,
falls back to `META_WEBUI_EVOLVER_CONTROL_URL`, and currently has a loopback
fallback. The implementation run must verify the correct reachable managed URL
from inside the Server Dev Container before choosing how the environment
provisions it.

Related: [Central vs Edge](central-vs-edge.md) `[[Central vs Edge]]` ·
[API Workbench](api-workbench.md) `[[API Workbench]]`
