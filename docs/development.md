# Development

Clone with `git clone --recurse-submodules` and open the root in its Dev
Container. The bootstrap uses persistent uv/npm caches and prepares child
projects independently. Outside the container, use `uv sync --extra dev` and
`uv run pytest -n auto`; focused tests can be run with `uv run pytest -q
private-schema/tests` or inside a child repository with its own `uv sync`.

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
