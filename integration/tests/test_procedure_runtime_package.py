from __future__ import annotations

import subprocess
import sys


def test_runtime_import_uses_installed_public_distribution(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib.metadata import version; "
                "from evolver_procedure_runtime import ProcedureEngine; "
                "print(version('evolver-procedure-runtime')); "
                "print(ProcedureEngine.__module__)"
            ),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["0.1.0", "evolver_procedure_runtime.engine"]
