"""
E2E mínimo Hito 4 (bloqueo FormatsAgent → perfil completo).

Ejecuta el test in-process con datos de perfil realistas (sin servidor HTTP).
Uso desde la raíz del repo o desde backend/:

    python scripts/e2e_hito4_formats_minimal.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    test_path = root / "tests" / "test_hito4_formats_e2e_minimal.py"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-v",
        "--tb=short",
    ]
    return subprocess.call(cmd, cwd=str(root))


if __name__ == "__main__":
    raise SystemExit(main())
