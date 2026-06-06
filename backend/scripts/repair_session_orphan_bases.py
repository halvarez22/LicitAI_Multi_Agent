#!/usr/bin/env python3
"""
Repara bases huérfanas: registra en Postgres un PDF existente y lo procesa (OCR + vectores).

Cuando el catálogo de sesión referencia un PDF ANALYZED pero documents=0 y/o falta el archivo
en /data/uploads, este script re-sube desde una ruta local (host o contenedor).

Uso:
  python scripts/repair_session_orphan_bases.py --session vigilancia_issste --pdf /ruta/LA-51...VIGILANCIA.pdf
  python scripts/repair_session_orphan_bases.py --session vigilancia_issste --pdf /data/uploads/mibases.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    "/data/uploads" if os.path.exists("/.dockerenv") else str(_ROOT / "data" / "uploads"),
)


async def repair(session_id: str, pdf_path: str, *, process: bool = True) -> dict:
    from app.api.deps import get_connected_memory

    src = Path(pdf_path)
    if not src.is_file():
        raise SystemExit(f"PDF no encontrado: {pdf_path}")

    memory = await get_connected_memory()
    state = await memory.get_session(session_id) or {}
    cat = state.get("session_template_catalog") or {}
    cat_items = cat.get("items") or []
    orphan = next(
        (
            it for it in cat_items
            if isinstance(it, dict)
            and str(it.get("document_class") or "") in ("pliego_referencia", "bases", "")
            and str(it.get("source_filename") or "").lower().endswith(".pdf")
        ),
        None,
    )
    preferred_name = str((orphan or {}).get("source_filename") or src.name)
    doc_id = str((orphan or {}).get("doc_id") or uuid.uuid4())

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe = preferred_name.replace(" ", "_").lower()
    dest = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{safe}")
    shutil.copy2(src, dest)

    prev = dict(state) if isinstance(state, dict) else {}
    prev["status"] = "active"
    await memory.save_session(session_id, prev)

    content = {
        "status": "UPLOADED",
        "file_path": dest,
        "filename": preferred_name,
    }
    await memory.save_document(
        doc_id=doc_id,
        session_id=session_id,
        content=content,
        metadata={"filename": preferred_name, "status": "UPLOADED"},
    )

    result = {
        "session_id": session_id,
        "doc_id": doc_id,
        "filename": preferred_name,
        "dest_path": dest,
        "processed": False,
    }

    if process:
        from app.api.v1.routes.upload import process_document

        resp = await process_document(
            doc_id=doc_id,
            session_id=session_id,
            company_id=prev.get("company_id"),
            force=True,
        )
        result["processed"] = True
        result["process_message"] = getattr(resp, "message", str(resp))

    await memory.disconnect()
    return result


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--pdf", required=True, help="Ruta al PDF de bases en host o contenedor")
    ap.add_argument("--no-process", action="store_true")
    args = ap.parse_args()
    out = await repair(args.session, args.pdf, process=not args.no_process)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
