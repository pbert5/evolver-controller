# Development

Clone with `git clone --recurse-submodules` and open the root in its Dev
Container. The Common Toolchain uses a worktree-local `.venv`, a persistent
worktree-scoped uv cache, and a root uv workspace containing all four Python
components. Bootstrap runs `uv sync --all-packages --all-extras`; no Node.js or
npm installation is required. Outside the container, use `tools/dev-env`.
The three setuptools-based components are editable workspace members. `metactl`
is intentionally kept as a checkout-path component because its pinned child
metadata is not buildable by setuptools; its tests and imports remain available
from the root checkout without altering that child repository.

The root `tools/test` dispatcher owns the test topology. Use `tools/test-all`
(or `tools/test all`) for the complete root plus component suite, and
`tools/test-fast` for the xdist unit/contract lane. The fast lane excludes
tests marked `integration`, `simulator`, or `serial`. Use
`tools/test-serial`, `tools/test-integration`, and `tools/test-simulator` for
the corresponding marker-selected lanes; serial component processes run in
order with xdist disabled. `tools/test-coverage` runs the complete topology
with isolated per-component coverage data and reports.

For focused work, use `tools/test component
<controller|hardware|server|metactl|root>`. Every component is invoked in its
own pytest subprocess so its package/import environment remains isolated from
the other components. `PYTEST_WORKERS` accepts `auto` (the default) or a
non-negative integer and controls xdist workers for parallel lanes; invalid
values fail before any test starts. Root pytest registers the lane markers and
uses strict marker checking, so new lane-specific tests should use
`@pytest.mark.integration`, `@pytest.mark.simulator`, or
`@pytest.mark.serial` explicitly.

The Common container forwards port 18086 as `Meta Ball API`. Services launched
through the host Docker daemon should use `META_BAL_DEV_BIND_ADDRESS` and
`META_BAL_DEV_PORT`; the default bind is loopback. To make a service reachable
from a controller, explicitly set the bind address to a host LAN or Tailscale
IPv4, then run `tools/dev-env network`. No firewall, ACL, or public exposure is
changed by this repository.

The standalone server entry point is `uv run --project evolver-server
evolver-control`; its configuration uses `DATABASE_URL` and does not embed
PostgreSQL. `metactl` uses `EVOLVER_SERVER_URL` and the HTTP operator API.
Controller and hardware simulators are exercised by their copied pytest
suites; no physical hardware is actuated.

Release builds invoke the preserved scripts in `tools/`, especially
`build_evolver_production_release.py`, with an exact source revision recorded
in the release manifest. BAL artifacts are assembled privately and selected by
`BAL_SCHEMA_VERSION`; `latest` uses numeric semantic-version ordering. This
project does not use `.env.local`.
