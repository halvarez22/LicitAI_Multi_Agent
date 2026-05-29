#!/usr/bin/env python3
"""
Auditoría Fase A: inventario físico de entregables en /data/outputs.

Uso (contenedor backend):
  python scripts/audit_session_deliverables.py --session isapeg
  python scripts/audit_session_deliverables.py --session isapeg --json report.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Permite ejecutar desde backend/ o desde /app en Docker
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE_OUTPUT = Path(os.environ.get("LICITAI_OUTPUTS_ROOT", "/data/outputs"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_office_text(path: Path) -> str:
    if path.suffix.lower() not in (".docx", ".xlsx"):
        return ""
    try:
        with zipfile.ZipFile(path) as z:
            parts: List[str] = []
            for name in z.namelist():
                if name.endswith(".xml") and any(
                    k in name for k in ("document", "sheet", "sharedStrings")
                ):
                    raw = z.read(name).decode("utf-8", errors="ignore")
                    parts.append(re.sub(r"<[^>]+>", " ", raw))
            return " ".join(parts)
    except Exception as exc:
        return f"__ERROR__:{exc}"


def _scan_keywords(text: str) -> Dict[str, bool]:
    low = (text or "").lower()
    return {
        "has_275": "275" in low,
        "has_9_meses": "9 meses" in low or "9 mes" in low,
        "has_proporcional": "proporcional" in low,
        "has_tarifa_mensual": "tarifa mensual" in low or "tarifa" in low,
        "has_anexo_iii": "anexo iii" in low or "anexo 3" in low,
        "has_formula_parcial": bool(
            re.search(r"\(\s*.*tarifa.*\*.*9.*\)\s*/\s*275", low, re.I)
        ),
    }


def _inventory_tree(root: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not root.is_dir():
        return items
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        text = _extract_office_text(p) if p.suffix.lower() in (".docx", ".xlsx") else ""
        items.append(
            {
                "path": rel,
                "bytes": p.stat().st_size,
                "sha256": _sha256_file(p),
                "ext": p.suffix.lower(),
                "keywords": _scan_keywords(text) if text else {},
            }
        )
    return items


def _read_manifest(root: Path) -> Optional[Dict[str, Any]]:
    for candidate in (
        root / "_compranet_validated" / "MANIFIESTO_SHA256.json",
        root / "MANIFIESTO_SHA256.json",
    ):
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"_error": str(exc), "_path": str(candidate)}
    return None


async def _session_snapshot(session_id: str) -> Dict[str, Any]:
    from app.api.v1.routes.downloads import resolve_outputs_root
    from app.memory.factory import MemoryAdapterFactory

    root_path = await resolve_outputs_root(session_id)
    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    state = await mem.get_session(session_id) or {}
    await mem.disconnect()

    tasks = [t.get("task") for t in (state.get("tasks_completed") or []) if isinstance(t, dict)]
    er = state.get("execution_results") if isinstance(state.get("execution_results"), dict) else {}
    return {
        "session_id": session_id,
        "resolved_output_root": root_path,
        "tasks_completed": tasks,
        "pipeline_flags": {
            "technical_writer": any("technical" in (t or "") for t in tasks),
            "formats": any("format" in (t or "") for t in tasks),
            "economic_writer": any("economic" in (t or "") for t in tasks),
            "document_packager": any("packager" in (t or "") for t in tasks)
            or bool(er.get("document_packager")),
            "compranet_pack": "stage_completed:compranet_pack" in tasks
            or bool(er.get("compranet_packaging")),
            "bidding_binder": bool(er.get("bidding_binder"))
            or bool(state.get("delivery_checklist")),
        },
        "compranet_packaging": er.get("compranet_packaging"),
        "delivery_checklist_present": bool(state.get("delivery_checklist")),
        "delivery_checklist_count": (
            len(state["delivery_checklist"])
            if isinstance(state.get("delivery_checklist"), list)
            else 0
        ),
    }


async def audit_session(session_id: str) -> Dict[str, Any]:
    snap = await _session_snapshot(session_id)
    root_str = snap.get("resolved_output_root")
    root = Path(root_str) if root_str else BASE_OUTPUT / session_id
    files = _inventory_tree(root) if root.is_dir() else []
    manifest = _read_manifest(root) if root.is_dir() else None

    docx = [f for f in files if f["ext"] == ".docx"]
    xlsx = [f for f in files if f["ext"] == ".xlsx"]
    pdf = [f for f in files if f["ext"] == ".pdf"]
    sha_counts: Dict[str, int] = {}
    by_top_folder: Dict[str, int] = {}
    by_sobre: Dict[str, int] = {}
    for f in files:
        sha_counts[f["sha256"]] = sha_counts.get(f["sha256"], 0) + 1
        rel = f["path"]
        top = rel.split("/")[0] if "/" in rel else rel
        by_top_folder[top] = by_top_folder.get(top, 0) + 1
        if "SOBRE_" in rel:
            parte = rel.split("/")[0]
            by_sobre[parte] = by_sobre.get(parte, 0) + 1
    duplicate_sha_groups = sum(1 for c in sha_counts.values() if c > 1)
    duplicate_extra_files = sum(c - 1 for c in sha_counts.values() if c > 1)
    any_275 = any(f.get("keywords", {}).get("has_275") for f in files)
    any_formula = any(f.get("keywords", {}).get("has_formula_parcial") for f in files)

    allowed_ext = os.environ.get(
        "COMPRANET_ALLOWED_EXT", ".doc,.docx,.pdf,.jpg,.jpeg,.png,.xlsx,.xls"
    )

    verdict_parts: List[str] = []
    if not root.is_dir():
        verdict_parts.append("FAIL: sin carpeta de salida")
    if not snap["pipeline_flags"].get("compranet_pack"):
        verdict_parts.append("FAIL: CompraNetPackager no ejecutado")
    if not manifest:
        verdict_parts.append("FAIL: MANIFIESTO_SHA256.json ausente")
    if not snap["pipeline_flags"].get("bidding_binder"):
        verdict_parts.append("FAIL: delivery_checklist / BiddingBinder ausente")
    if not any_275 and not any_formula:
        verdict_parts.append("WARN: constante 275 no detectada en docx/xlsx del volumen")

    phase_a_ok = (
        root.is_dir()
        and len(docx) > 0
        and len(xlsx) > 0
        and snap["pipeline_flags"].get("compranet_pack")
        and bool(manifest)
        and snap["pipeline_flags"].get("bidding_binder")
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session": snap,
        "output_root": str(root),
        "compranet_allowed_ext": allowed_ext,
        "inventory_summary": {
            "total_files": len(files),
            "docx_count": len(docx),
            "xlsx_count": len(xlsx),
            "pdf_count": len(pdf),
            "unique_sha256": len(sha_counts),
            "duplicate_sha256_groups": duplicate_sha_groups,
            "duplicate_extra_files": duplicate_extra_files,
            "files_by_top_folder": dict(sorted(by_top_folder.items())),
            "files_by_sobre_folder": dict(sorted(by_sobre.items())),
            "has_sobre_folders": any(
                f["path"].startswith("SOBRE_") or "/SOBRE_" in f["path"] for f in files
            ),
            "has_compranet_validated_dir": (root / "_compranet_validated").is_dir(),
            "economic_folder_present": (root / "2.propuesta_economica").is_dir(),
            "economic_folder_files": sum(
                1 for f in files if f["path"].startswith("2.propuesta_economica/")
            ),
            "keyword_275_in_office_files": any_275,
            "keyword_formula_in_office_files": any_formula,
        },
        "manifest": manifest,
        "files": files,
        "phase_a_verdict": "PASS" if phase_a_ok else "FAIL",
        "phase_a_notes": verdict_parts or ["OK"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría de entregables LicitAI")
    parser.add_argument("--session", required=True, help="ID de sesión (ej. isapeg)")
    parser.add_argument("--json", help="Ruta de salida JSON del reporte")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Elimina copias SOBRE_* y carpetas de generación; conserva _compranet_validated",
    )
    args = parser.parse_args()

    if args.prune:
        from app.services.output_delivery_view import prune_duplicate_output_copies

        root = BASE_OUTPUT / args.session
        if root.is_dir():
            pr = prune_duplicate_output_copies(str(root))
            print(json.dumps({"prune": pr}, indent=2, ensure_ascii=False), file=sys.stderr)

    report = asyncio.run(audit_session(args.session))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"\nReporte escrito en: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
