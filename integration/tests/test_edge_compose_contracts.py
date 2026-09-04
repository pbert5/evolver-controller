from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[2]


def test_edge_compose_contract():
    document = yaml.safe_load((ROOT / "deploy/evolver-edge/compose.yaml").read_text())
    services = document["services"]
    assert set(services) == {"evolver-controller", "evolver-hardware"}
    assert "container_name" not in services["evolver-controller"]
    assert "container_name" not in services["evolver-hardware"]
    assert services["evolver-controller"]["restart"] == "unless-stopped"
    assert services["evolver-hardware"]["restart"] == "unless-stopped"
    assert services["evolver-controller"]["network_mode"] == "host"
    assert services["evolver-hardware"]["network_mode"] == "none"
    controller_volumes = str(services["evolver-controller"]["volumes"])
    assert "var/lib/evolver-controller" in controller_volumes
    assert "/dev" not in controller_volumes
    assert "/var/run/docker.sock" not in controller_volumes
    hardware_volumes = str(services["evolver-hardware"]["volumes"])
    assert "var/lib/evolver-hardware" in hardware_volumes
    assert "var/lib/evolver-controller" not in hardware_volumes
    assert "/dev" in hardware_volumes
