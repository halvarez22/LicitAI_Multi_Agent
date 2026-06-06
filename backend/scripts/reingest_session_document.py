#!/usr/bin/env python3
"""
Re-ingesta forzada de un documento PDF ya ANALYZED (borra vectores, OCR híbrido, re-indexa).

Uso:
  python scripts/reingest_session_document.py --session opm_municipio_madera --match bases
  python scripts/reingest_session_document.py --session opm_municipio_madera --doc-id UUID
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.memory.factory import MemoryAdapterFactory
from app.services.document_ingestion_router import DocumentIngestionRouter
from app.services.document_vector_index import index_pages_atomic
from app.services.vector_service import VectorDbServiceClient

_PROMPT_ECHO = "ANALIZAR Y TRANSCRIBIR"


def _pick_document(
    docs: List[Dict[str, Any]],
    *,
    doc_id: Optional[str],
    match: Optional[str],
) -> Optional[Dict[str, Any]]:
    if doc_id:
        for d in docs:
            if str(d.get("id") or "") == doc_id:
                return d
        return None
    needle = (match or "bases").lower()
    for d in docs:
        c = d.get("content") or {}
        fn = str(c.get("filename") or "").lower()
        if needle in fn and fn.endswith(".pdf"):
            return d
    return None


def _audit_pages(extracted_text: str) -> Dict[str, int]:
    parts = re.split(r"---\s*PÁGINA\s+(\d+)\s*---", extracted_text or "", flags=re.I)
    ok = bad = empty = 0
    for i in range(1, len(parts), 2):
        body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if len(body) < 80:
            empty += 1
        elif _PROMPT_ECHO in body[:150] and len(body) < 750:
            bad += 1
        else:
            ok += 1
    return {"ok": ok, "contaminadas": bad, "vacias": empty, "total": ok + bad + empty}


async def reingest_one(
    session_id: str,
    doc: Dict[str, Any],
    memory: Any,
) -> Dict[str, Any]:
    doc_id = str(doc.get("id") or "")
    content = dict(doc.get("content") or {})
    filename = str(content.get("filename") or "")
    file_path = content.get("file_path") or content.get("path")
    started = datetime.now(timezone.utc).isoformat()

    result: Dict[str, Any] = {
        "session_id": session_id,
        "doc_id": doc_id,
        "filename": filename,
        "started_at": started,
        "ok": False,
    }

    if not file_path or not os.path.isfile(file_path):
        result["error"] = "archivo_fisico_ausente"
        return result

    print(f"[{started}] Re-ingesta: {filename} ({file_path})", flush=True)

    vc = VectorDbServiceClient()
    vc.delete_by_doc_id(session_id, doc_id)
    print(f"  Vectores previos eliminados para doc {doc_id[:8]}...", flush=True)

    router = DocumentIngestionRouter()
    ocr = await router.ingest(
        file_path=str(file_path),
        filename=filename,
        session_id=session_id,
        doc_id=doc_id,
        memory=memory,
    )

    if not ocr.get("success"):
        result["error"] = ocr.get("error") or "ingest_failed"
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        return result

    pages = ocr.get("pages") or []
    chunks = index_pages_atomic(session_id, doc_id, filename, pages, vc)
    raw_text = (ocr.get("extracted_text") or "").strip()

    content["status"] = "ANALYZED"
    content["extracted_text"] = raw_text
    content["total_pages"] = ocr.get("total_pages", len(pages))
    content["pages"] = pages
    content["extraction_method"] = ocr.get("method")
    content["extraction_stats"] = ocr.get("stats")
    content["reingested_at"] = datetime.now(timezone.utc).isoformat()
    content.pop("ingest_error", None)

    await memory.save_document(
        doc_id, session_id, content, {"status": "ANALYZED", "filename": filename}
    )

    audit = _audit_pages(raw_text)
    vlm_flags = sum(
        1
        for p in pages
        if isinstance(p, dict) and (p.get("quality_flags") or [])
    )

    result.update(
        {
            "ok": True,
            "chunks": chunks,
            "text_len": len(raw_text),
            "pages_indexed": len(pages),
            "pages_with_vlm_flags": vlm_flags,
            "audit": audit,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="Re-ingesta masiva de un PDF de sesión")
    parser.add_argument("--session", required=True)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument(
        "--match",
        default="bases",
        help="Substring del filename (default: bases)",
    )
    parser.add_argument(
        "--out",
        default="/app/scratch/reingest_report.json",
        help="Ruta del informe JSON",
    )
    args = parser.parse_args()

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    docs = await mem.get_documents(args.session) or []
    target = _pick_document(docs, doc_id=args.doc_id, match=args.match)

    if not target:
        await mem.disconnect()
        print(json.dumps({"error": "documento_no_encontrado", "session": args.session}))
        sys.exit(1)

    report = await reingest_one(args.session, target, mem)
    await mem.disconnect()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report.get("ok"):
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
