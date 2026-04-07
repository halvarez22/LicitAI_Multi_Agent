"""Runner cross-platform para oracle_validator (sin dependencias shell)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta validacion oracle en un solo comando.")
    parser.add_argument("--oracle", default="tests/oracle_v1.0.1-runtime-final.json", help="Path oracle JSON.")
    parser.add_argument("--analysis", help="Path analysis JSON.")
    parser.add_argument("--compliance", help="Path compliance JSON.")
    parser.add_argument("--economic", help="Path economic JSON.")
    parser.add_argument("--session-id", help="ID de sesion para resolver paths por convencion.")
    parser.add_argument("--out", default="out", help="Directorio de salida para reportes.")
    parser.add_argument("--max-fixes", type=int, default=5, help="Maximo de issues a reportar.")
    return parser.parse_args()


def _default_payload_paths(out_dir: Path, session_id: str) -> List[Path]:
    session_dir = out_dir / session_id
    if session_dir.exists():
        return [session_dir / "analysis.json", session_dir / "compliance.json", session_dir / "economic.json"]
    return [
        out_dir / f"{session_id}_analysis.json",
        out_dir / f"{session_id}_compliance.json",
        out_dir / f"{session_id}_economic.json",
    ]


def main() -> int:
    args = parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    out_dir = (backend_root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)

    analysis = args.analysis
    compliance = args.compliance
    economic = args.economic

    if not (analysis and compliance and economic):
        if not args.session_id:
            raise SystemExit(
                "Debes pasar --analysis --compliance --economic o usar --session-id para resolver rutas automaticamente."
            )
        defaults = _default_payload_paths(out_dir, args.session_id)
        analysis = str(defaults[0])
        compliance = str(defaults[1])
        economic = str(defaults[2])

    input_paths = [Path(str(analysis)), Path(str(compliance)), Path(str(economic))]
    missing_paths = [str(path) for path in input_paths if not path.exists()]
    if missing_paths:
        print("Error: faltan archivos de entrada para validacion oracle:", file=sys.stderr)
        for missing in missing_paths:
            print(f"- {missing}", file=sys.stderr)
        return 2

    validator_path = backend_root / "scripts" / "oracle_validator.py"
    command = [
        sys.executable,
        str(validator_path),
        "--oracle",
        args.oracle,
        "--analysis",
        analysis,
        "--compliance",
        compliance,
        "--economic",
        economic,
        "--max-fixes",
        str(args.max_fixes),
        "--save-report",
        "--report-dir",
        str(out_dir),
    ]

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
