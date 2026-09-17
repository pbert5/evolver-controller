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
    assert "evolver-edge-operator-runtime" in controller_volumes
    assert "evolver-edge-hardware-runtime" in controller_volumes
    assert "/dev" not in controller_volumes
    assert "/var/run/docker.sock" not in controller_volumes
    hardware_volumes = str(services["evolver-hardware"]["volumes"])
    assert "var/lib/evolver-hardware" in hardware_volumes
    assert "evolver-edge-hardware-runtime" in hardware_volumes
    assert "evolver-edge-operator-runtime" not in hardware_volumes
    assert "var/lib/evolver-controller" not in hardware_volumes
    assert "/dev" in hardware_volumes


def test_edge_compose_channels_have_exact_service_ownership():
    document = yaml.safe_load((ROOT / "deploy/evolver-edge/compose.yaml").read_text())
    services = document["services"]

    def sources(service):
        return {item["source"] for item in services[service]["volumes"] if item["type"] == "volume"}

    assert sources("evolver-controller") == {
        "evolver-edge-operator-runtime",
        "evolver-edge-hardware-runtime",
    }
    assert sources("evolver-hardware") == {"evolver-edge-hardware-runtime"}

    controller_targets = {
        item["source"]: item["target"]
        for item in services["evolver-controller"]["volumes"]
        if item["type"] == "volume"
    }
    hardware_targets = {
        item["source"]: item["target"]
        for item in services["evolver-hardware"]["volumes"]
        if item["type"] == "volume"
    }
    assert controller_targets["evolver-edge-operator-runtime"] == "/run/evolver-controller"
    assert controller_targets["evolver-edge-hardware-runtime"] == "/run/evolver-hardware"
    assert hardware_targets["evolver-edge-hardware-runtime"] == "/run/evolver-hardware"
