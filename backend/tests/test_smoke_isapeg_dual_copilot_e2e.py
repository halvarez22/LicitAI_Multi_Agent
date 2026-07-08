"""Smoke F10 E2E dual copilot (subprocess)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_smoke_isapeg_dual_copilot_e2e_runs():
    backend = Path(__file__).resolve().parents[1]
    script = backend / "scripts" / "smoke_isapeg_dual_copilot_e2e.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(backend),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
