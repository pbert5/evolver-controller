# evolver-controller

Extracted edge runtime preserving durable EdgeStore, authenticated sync,
generation fencing, orphan behavior, simulator, recovery, updater, and the
existing CLI/service entry points. Production deployment is the root-owned
Docker Compose stack in `deploy/evolver-edge`; the controller has no Docker
socket and hardware remains the exclusive privileged serial owner. Native
package, Nix, and systemd installation paths are retired.

Origin: Meta WebUI `wire-in-cli` `652cc5d`.
