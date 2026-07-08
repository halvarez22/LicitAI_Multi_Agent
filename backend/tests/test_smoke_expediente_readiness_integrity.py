"""Smoke R5 integrado (subprocess)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_smoke_expediente_readiness_integrity_runs():
    backend = Path(__file__).resolve().parents[1]
    script = backend / "scripts" / "smoke_expediente_readiness_integrity.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(backend),
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SMOKE OK" in (proc.stdout or "")
