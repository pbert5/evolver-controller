"""Long-running controller process entrypoint used by the systemd unit."""
from __future__ import annotations

import argparse
import os
import signal
import threading
from pathlib import Path

from .operator import DEFAULT_SOCKET as DEFAULT_OPERATOR_SOCKET, OperatorServer
from .store import EdgeStore
from .sync import SyncClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evolver-controller")
    parser.add_argument("--state-root", default=os.environ.get("EVOLVER_STATE_ROOT", "/var/lib/evolver-controller"))
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--simulator-instruments", type=int, default=0,
                        help="publish this many safe simulated instruments on every sync")
    parser.add_argument("--operator-socket", default=os.environ.get("EVOLVER_OPERATOR_SOCKET", DEFAULT_OPERATOR_SOCKET),
                        help="private Unix socket for the read-only local operator API")
    args = parser.parse_args(argv)
    # SyncClient has bounded exponential retry.  State is entirely below the
    # StateDirectory, so service restarts cannot recreate identity or bindings.
    with EdgeStore(Path(args.state_root)) as store:
        stop_event = threading.Event()
        operator = OperatorServer(store, args.operator_socket).start()
        previous_handlers: dict[int, object] = {}

        def stop(_signum: int, _frame: object) -> None:
            stop_event.set()

        # Signal handlers are installed only in this console entrypoint's main
        # thread.  This makes SIGTERM from systemd/containers stop both loops
        # cleanly while retaining the old run_loop test seam.
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, stop)
        # Inventory is shared durable edge state.  The optional simulator and
        # the exclusive read-only hardware service both populate it, so sync
        # must never hide physical observations when simulator is disabled.
        inventory = store.list_instruments
        if args.simulator_instruments:
            if args.simulator_instruments < 1:
                parser.error("--simulator-instruments must be positive")
            # The simulator only writes the durable Instrument contract and
            # never opens a serial device or performs physical actuation.
            from .simulator import EvolverSimulator
            simulator = EvolverSimulator(store, instruments=args.simulator_instruments)
            # Instantiate once to register stable simulated identities; the
            # common store inventory keeps physical and simulated instruments.
            simulator.inventory()
        try:
            SyncClient(store).run_loop(interval=args.interval, inventory=inventory, stop=stop_event.is_set)
        finally:
            operator.shutdown()
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
