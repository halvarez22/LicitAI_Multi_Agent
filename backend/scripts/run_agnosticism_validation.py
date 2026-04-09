"""Validación de agnosticismo multi-vertical y cierre post-E2E.

Subcomandos:
  scan   — Recorre ``app/*.py`` buscando acoplamientos obvios a sesión/convocante.
  finalize — Tras un E2E real: export Oracle, run_oracle, generate_audit_report.

La corrida E2E en sí se dispara con ``e2e_monitor_job.py`` y variables ``E2E_*``
(documentadas en ese script); este módulo no sustituye a Ollama ni a la API.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _scan_line_patterns() -> List[Tuple[str, str, str]]:
    """(regex, code, severidad)."""
    return [
        (r"la-51-gyn-\d", "session_slug_la51", "CRITICAL"),
        (r"051gyn\d", "session_slug_gyn", "CRITICAL"),
    ]


def scan_app_tree(app_dir: Path) -> Tuple[List[str], List[str]]:
    """Retorna (críticos, revisión) como líneas de texto."""
    critical: List[str] = []
    review: List[str] = []
    patterns = _scan_line_patterns()
    for py in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for rx, code, sev in patterns:
                if re.search(rx, line, re.IGNORECASE):
                    rel = py.relative_to(app_dir.parent)
                    msg = f"{rel.as_posix()}:{i} [{code}] {sev}: {stripped[:160]}"
                    if sev == "CRITICAL":
                        critical.append(msg)
                    else:
                        review.append(msg)
    return critical, review


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.backend_root).resolve() if args.backend_root else _backend_root()
    app_dir = root / "app"
    if not app_dir.is_dir():
        print(f"Error: no existe {app_dir}", file=sys.stderr)
        return 2
    critical, review = scan_app_tree(app_dir)
    out_path = (root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# Agnosticism scan {now}",
        f"# backend_root: {root}",
        "",
        f"## CRITICAL ({len(critical)})",
    ]
    lines.extend(critical if critical else ["(ninguno)"])
    lines.append("")
    lines.append(f"## REVIEW ({len(review)})")
    lines.extend(review if review else ["(ninguno)"])
    lines.extend(
        [
            "",
            "## INFO",
            "- Perfil económico: `health_sector_annex_like` sustituye la detección única por "
            "'issste' en seed; `issste_2024_like` permanece como alias retrocompatible.",
            "- `template_name` interno puede conservar prefijo histórico en archivos de plantilla; "
            "no implica convocante fijo en runtime.",
            "",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Escrito {out_path} | CRITICAL={len(critical)} REVIEW={len(review)}")
    return 1 if critical else 0


def _run_step(cwd: Path, argv: List[str]) -> int:
    r = subprocess.run([sys.executable, *argv], cwd=str(cwd), check=False)
    return int(r.returncode)


def cmd_finalize(args: argparse.Namespace) -> int:
    root = Path(args.backend_root).resolve() if args.backend_root else _backend_root()
    sid = args.session_id
    db_url = args.database_url
    exp = [
        "scripts/export_oracle_inputs.py",
        "--session-id",
        sid,
        "--database-url",
        db_url,
        "--out",
        "out/oracle_real",
    ]
    rc = _run_step(root, exp)
    if rc != 0:
        print(f"export_oracle_inputs falló (código {rc})", file=sys.stderr)
        return rc
    oracle_argv = [
        "scripts/run_oracle.py",
        "--analysis",
        "out/oracle_real/analysis.json",
        "--compliance",
        "out/oracle_real/compliance.json",
        "--economic",
        "out/oracle_real/economic.json",
        "--out",
        "out",
    ]
    pkg = root / "out" / "oracle_real" / "packager.json"
    if pkg.is_file():
        oracle_argv.extend(["--packager", "out/oracle_real/packager.json"])
    rc = _run_step(root, oracle_argv)
    if rc != 0:
        print(f"run_oracle falló (código {rc})", file=sys.stderr)
        return rc
    audit_argv = [
        "scripts/generate_audit_report.py",
        "--session-id",
        sid,
        "--out",
        "out/audit",
    ]
    rc = _run_step(root, audit_argv)
    if rc != 0:
        print(f"generate_audit_report falló (código {rc})", file=sys.stderr)
        return rc
    print("finalize OK: export + oracle + audit_report")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Agnosticismo multi-vertical y cierre post-E2E.")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("scan", help="Escanear app/ en busca de acoplamientos.")
    ps.add_argument("--backend-root", default="", help="Raíz del backend (default: directorio de este script/..).")
    ps.add_argument("--out", default="out/agnosticism_findings.txt", help="Archivo de hallazgos.")
    ps.set_defaults(func=cmd_scan)

    pf = sub.add_parser(
        "finalize",
        help="Post-E2E: export Oracle, validar oracle, generar audit report (requiere DB y sesión persistida).",
    )
    pf.add_argument("--session-id", required=True)
    pf.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@localhost:5432/licitaciones",
        help="Misma URL que export_oracle_inputs.",
    )
    pf.add_argument("--backend-root", default="")
    pf.set_defaults(func=cmd_finalize)

    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
