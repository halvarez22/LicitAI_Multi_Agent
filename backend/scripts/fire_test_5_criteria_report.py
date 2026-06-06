#!/usr/bin/env python3
"""
Reporte consolidado de la prueba de fuego (5 criterios) por sesión.

1. Cobertura de formatos/anexos (generar)
2. Ubicación por sobre (CompraNet)
3. Nomenclatura vs convocante (catálogo + manifiesto)
4. Contenido/formato (audit_delivery + forensic)
5. Propuesta económica (validation_result + keywords 275)

Uso:
  python scripts/fire_test_5_criteria_report.py isapeg_servicios_de_limpieza
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def build_report(session_id: str) -> Dict[str, Any]:
    from app.memory.factory import MemoryAdapterFactory
    from app.services.delivery_coverage_report import build_and_persist_coverage
    from app.services.delivery_content_audit import (
        audit_delivery_files,
        run_forensic_contamination_audit,
    )

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    try:
        state = await mem.get_session(session_id) or {}
        coverage = await build_and_persist_coverage(mem, session_id)
    finally:
        await mem.disconnect()

    content_audit = audit_delivery_files(session_id, session_state=state)
    forensic_report = run_forensic_contamination_audit(session_id, session_state=state)
    forensic = forensic_report.get("summary") or {}

    summary_cov = coverage.get("summary") or {}
    c1_ok = (
        summary_cov.get("cobertura_generacion_pct", 0) >= 100
        and summary_cov.get("faltantes_generar", 0) == 0
    )

    manifest_count = int(coverage.get("manifest_files_count") or 0)
    by_sobre: Dict[str, int] = {}
    for row in coverage.get("rows") or []:
        if row.get("estado_cobertura") != "generada":
            continue
        sobre = str(row.get("sobre_inferido") or row.get("sobre") or "?")
        by_sobre[sobre] = by_sobre.get(sobre, 0) + 1
    generadas = int(summary_cov.get("generadas") or 0)
    c2_ok = generadas > 0 and manifest_count >= generadas

    naming_issues: List[str] = []
    for row in coverage.get("rows") or []:
        if row.get("estado_cobertura") == "generada":
            ent = row.get("archivo_entregado") or ""
            src = row.get("source_filename") or ""
            if ent and src and normalize_key(ent) != normalize_key(src):
                if normalize_key(ent) not in normalize_key(src) and normalize_key(src) not in normalize_key(ent):
                    naming_issues.append(f"{src} -> {ent}")
    c3_ok = len(naming_issues) == 0

    blocking = content_audit.get("blocking_issues") or []
    forensic_blocking = int(forensic.get("blocking_findings") or 0)
    c4_ok = (
        content_audit.get("gate_passed") is True
        and forensic_report.get("gate_passed") is True
        and forensic_blocking == 0
    )

    econ_ok = False
    econ_notes: List[str] = []
    for task in reversed(state.get("tasks_completed") or []):
        if not isinstance(task, dict) or task.get("task") != "economic_proposal":
            continue
        payload = task.get("result") or task.get("data") or {}
        vr = payload.get("validation_result") if isinstance(payload, dict) else {}
        if isinstance(vr, dict):
            block_econ = vr.get("blocking_issues") or []
            econ_ok = len(block_econ) == 0 and not vr.get("passed") is False
            if block_econ:
                econ_notes.extend(str(b)[:120] for b in block_econ[:5])
            alerts = vr.get("alerts") or []
            if alerts:
                econ_notes.append(f"alerts={len(alerts)}")
        break
    keywords_275 = any(
        (f.get("keywords") or {}).get("has_275")
        for f in (content_audit.get("files") or [])
    )
    if not econ_ok and keywords_275:
        econ_notes.append("WARN: fórmula/275 en archivos pero validation_result no passed")

    criteria = [
        {"id": 1, "nombre": "Formatos y anexos requeridos", "ok": c1_ok, "detalle": summary_cov},
        {"id": 2, "nombre": "Carpeta/sobre correcto", "ok": c2_ok, "detalle": by_sobre},
        {"id": 3, "nombre": "Nomenclatura convocante", "ok": c3_ok, "detalle": naming_issues[:20]},
        {
            "id": 4,
            "nombre": "Contenido y formato",
            "ok": c4_ok,
            "detalle": {
                "gate_passed": content_audit.get("gate_passed"),
                "blocking_count": len(blocking),
                "blocking_sample": [
                    {"doc": b.get("nombre_entrega"), "type": b.get("error_type")}
                    for b in blocking[:8]
                ],
                "forensic": forensic_report.get("summary"),
                "forensic_blocking": forensic_blocking,
            },
        },
        {
            "id": 5,
            "nombre": "Propuesta económica",
            "ok": econ_ok,
            "detalle": {"notes": econ_notes, "has_275_in_files": keywords_275},
        },
    ]
    all_ok = all(c["ok"] for c in criteria)
    return {
        "session_id": session_id,
        "company_id": state.get("company_id"),
        "verdict": "PASS" if all_ok else "FAIL",
        "criteria": criteria,
        "coverage_summary": summary_cov,
    }


def normalize_key(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    report = await build_report(args.session_id)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(text, encoding="utf-8")
    print(text)
    print("\n=== VEREDICTO:", report["verdict"], "===", file=sys.stderr)
    for c in report["criteria"]:
        mark = "OK" if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['id']}. {c['nombre']}", file=sys.stderr)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
