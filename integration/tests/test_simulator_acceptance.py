from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from integration.simulator_harness import SimulatorAcceptanceHarness
pytestmark = [pytest.mark.integration, pytest.mark.simulator]


def _bundle() -> dict[str, object]:
    bundle: dict[str, object] = {
        "id": "acceptance-bundle", "name": "acceptance", "schema_version": "1",
        "execution_mode": "declarative_state_machine", "source": {},
        "resolved_definition": {}, "runtime_parameters": [], "source_metadata": [],
        "execution_plan": {
            "initial_state": "incubating",
            "states": {"incubating": {"transitions": [], "entry_actions": []}},
        },
    }
    bundle["digest"] = hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return bundle


@pytest.fixture()
def harness(tmp_path: Path):
    value = SimulatorAcceptanceHarness.create(tmp_path)
    try:
        yield value
    finally:
        value.close()


def test_composed_simulator_acceptance_is_restart_safe_and_evidenced(harness):
    issued = harness.enroll()
    controller_id = harness.edge.identity()["id"]
    instrument = harness.simulator.inventory()[0]
    harness.edge.put_bundle(_bundle())

    first = harness.sync.sync_once(inventory=harness.simulator.inventory())
    assert first.status == 200
    assert first.response["accepted_generation"] == 1
    assert first.response["commands"] == []
    capabilities = harness.operator_client.request("capabilities")
    assert capabilities["protocol_version"] == 1
    assert capabilities["operations"] == {
        "binding": {"access": "read", "mode": "live"},
        "capabilities": {"access": "read", "mode": "live"},
        "doctor": {"access": "read", "mode": "live"},
        "instruments": {"access": "read", "mode": "live"},
        "runs": {"access": "read", "mode": "live"},
        "status": {"access": "read", "mode": "live"},
        "hardware": {"access": "mutate", "mode": "live"},
    }
    controller_projection = harness.metactl_json("evolver.edge.controllers")["result"]["controllers"][0]
    assert controller_projection.get("controller_id", controller_projection.get("id")) == controller_id
    assert harness.metactl_json("evolver.instruments.list")["result"]["instruments"][0]["id"] == instrument["id"]

    run = harness.simulator.start_run(run_id="acceptance-run", bundle_id="acceptance-bundle")
    telemetry = harness.simulator.tick(run_ids=[run["id"]])
    assert telemetry and telemetry[0]["stream_id"].startswith(f"run:acceptance-run:instrument:{instrument['id']}:")
    before_restart = harness.edge.recovery_manifest()
    harness.sync.sync_once(inventory=harness.simulator.inventory())
    central_before_restart = json.loads((harness.central_root / "central-controller.json").read_text())
    projection_before_restart = central_before_restart["controllers"][controller_id]

    harness.restart_edge()
    assert harness.edge.identity()["id"] == controller_id
    assert harness.simulator.inventory()[0]["id"] == instrument["id"]
    assert harness.edge.run("acceptance-run")["id"] == "acceptance-run"

    after_restart = harness.sync.sync_once(inventory=harness.simulator.inventory())
    assert after_restart.response["event_cursors"]
    assert after_restart.response["telemetry_cursors"]
    assert harness.edge.recovery_manifest()["active_runs"] == before_restart["active_runs"]
    assert harness.metactl_json("evolver.runs.list")["result"]["runs"][0]["id"] == "acceptance-run"

    central = json.loads((harness.central_root / "central-controller.json").read_text())
    projection = central["controllers"][controller_id]
    assert projection["connection_state"] == "connected"
    assert projection["inventory"][0]["transport"]["kind"] == "simulated"
    assert projection["events"] and projection["telemetry"]
    assert len(projection["events"]) == len(projection_before_restart["events"])
    assert len(projection["telemetry"]) == len(projection_before_restart["telemetry"])
    assert issued["enrollment_token"] not in json.dumps(central)
