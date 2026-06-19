#!/usr/bin/env python3
"""
Renombra el archivo E-2 en sobre económico cuando quedó con ruido OCR (PRESUPUESTO_52…).

Universal: usa metadatos de tareas + ``deliverable_filename_service``; sin mapas por licitación.

Uso:
  PYTHONPATH=/app python scripts/rename_obra_e2_sobre.py SESSION_ID
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_OCR_NOISE_RE = re.compile(r"(?i)PRESUPUESTO_52")


def _collect_e2_doc_meta(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    for task in reversed(state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        payload = task.get("result") or {}
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for doc in (inner or {}).get("documentos") or []:
            if not isinstance(doc, dict):
                continue
            nombre = str(doc.get("nombre") or doc.get("source_filename") or "")
            key = pliego_format_dedupe_key(nombre)
            if key == "obra|E2" or "ANEXO_AE" in nombre.upper() or "E-2" in nombre.upper():
                return dict(doc)
    return None


def _target_name(doc_meta: Dict[str, Any], current_name: str) -> str:
    from app.services.deliverable_filename_service import resolve_deliverable_filename

    ext = Path(current_name).suffix or ".docx"
    resolved, _, _ = resolve_deliverable_filename(
        doc_meta,
        fallback_stem="Anexo_E-2_Propuesta_Economica",
        extension=ext,
    )
    clean = _OCR_NOISE_RE.sub("Propuesta_Economica", resolved)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean.lower().endswith(ext.lower()):
        clean = f"{clean}{ext}"
    return clean


def _rename_in_dir(directory: Path, doc_meta: Dict[str, Any]) -> List[Dict[str, str]]:
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    renamed: List[Dict[str, str]] = []
    if not directory.is_dir():
        return renamed
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        key = pliego_format_dedupe_key(name)
        if key != "obra|E2" and not _OCR_NOISE_RE.search(name):
            if "E-2" not in name.upper() and "ANEXO_AE" not in name.upper():
                continue
        dest_name = _target_name(doc_meta, name)
        if dest_name == name:
            continue
        dest = path.with_name(dest_name)
        if dest.exists() and dest.resolve() != path.resolve():
            dest.unlink()
        path.rename(dest)
        renamed.append({"from": name, "to": dest_name, "dir": str(directory)})
    return renamed


async def main(session_id: str) -> int:
    from app.api.deps import get_connected_memory

    mem = await get_connected_memory()
    try:
        state = await mem.get_session(session_id) or {}
        doc_meta = _collect_e2_doc_meta(state) or {
            "nombre": "Anexo E-2 Propuesta Económica",
            "source_filename": "01_ANEXO_AE_PROPUESTA_ECONOMICA.docx",
        }
        base = Path("/data/outputs") / session_id
        dirs = [
            base / "SOBRE_3_ECONOMICO",
            base / "propuesta_economica",
            base / "_compranet_validated" / "SobreEconomica",
        ]
        all_renamed: List[Dict[str, str]] = []
        for d in dirs:
            all_renamed.extend(_rename_in_dir(d, doc_meta))

        # Renombrar fuente de generación si aplica
        for src in base.rglob("*"):
            if not src.is_file() or src.suffix.lower() not in (".docx", ".xlsx"):
                continue
            if _OCR_NOISE_RE.search(src.name):
                dest_name = _target_name(doc_meta, src.name)
                if dest_name != src.name:
                    dest = src.with_name(dest_name)
                    if not dest.exists():
                        src.rename(dest)
                        all_renamed.append({"from": src.name, "to": dest_name, "dir": str(src.parent)})

        print({"session_id": session_id, "renamed": all_renamed, "count": len(all_renamed)})
        return 0 if all_renamed else 1
    finally:
        await mem.disconnect()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"
    raise SystemExit(asyncio.run(main(sid)))
