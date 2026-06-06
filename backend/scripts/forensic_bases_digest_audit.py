#!/usr/bin/env python3
"""Auditoría forense de digestión de bases para una sesión."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _audit_pages(extracted_text: str) -> Dict[str, int]:
    import re
    parts = re.split(r"---\s*PÁGINA\s+(\d+)\s*---", extracted_text or "", flags=re.I)
    ok = bad = empty = 0
    echo = "ANALIZAR Y TRANSCRIBIR"
    for i in range(1, len(parts), 2):
        body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if len(body) < 80:
            empty += 1
        elif echo in body[:150] and len(body) < 750:
            bad += 1
        else:
            ok += 1
    total = ok + bad + empty
    return {"ok": ok, "contaminadas": bad, "vacias": empty, "total": total}


async def audit_session(session_id: str) -> Dict[str, Any]:
    from app.api.deps import get_connected_memory
    from app.services.junta_bases_corpus import build_bases_corpus

    memory = await get_connected_memory()
    state = await memory.get_session(session_id) or {}
    docs = await memory.get_documents(session_id) or []
    cat = state.get("session_template_catalog") or {}
    cat_items = cat.get("items") or []
    inv = state.get("document_inventory") or {}
    inv_items = inv.get("items") or []

    bases_docs: List[Dict[str, Any]] = []
    for d in docs:
        c = d.get("content") or {}
        fn = str(c.get("filename") or "")
        blob = fn.lower()
        if fn.lower().endswith(".pdf") and any(
            k in blob for k in ("bases", "vigilancia", "convocatoria", "051gyn", "la-51")
        ):
            text = str(c.get("extracted_text") or "")
            fp = str(c.get("file_path") or "")
            bases_docs.append({
                "doc_id": d.get("id"),
                "filename": fn,
                "status": c.get("status"),
                "file_exists": os.path.isfile(fp),
                "file_path": fp,
                "text_chars": len(text),
                "page_audit": _audit_pages(text),
            })

    orphan_catalog: List[Dict[str, Any]] = []
    for it in cat_items:
        if not isinstance(it, dict):
            continue
        doc_id = str(it.get("doc_id") or "")
        sp = str(it.get("source_path") or "")
        linked = next((d for d in docs if str(d.get("id")) == doc_id), None)
        orphan_catalog.append({
            "doc_id": doc_id,
            "source_filename": it.get("source_filename"),
            "source_path": sp,
            "file_exists": os.path.isfile(sp) if sp else False,
            "doc_in_db": linked is not None,
            "ingest_status": it.get("ingest_status"),
        })

    corpus = build_bases_corpus(session_id, docs, session_state=state)
    combined = getattr(corpus, "combined", "") or ""
    filenames = getattr(corpus, "filenames", []) or []

    verdict = "OK"
    blockers: List[str] = []
    if not docs:
        verdict = "BLOCKED"
        blockers.append("Sin documentos en Postgres para la sesión (UI vacía).")
    if not bases_docs:
        verdict = "BLOCKED"
        blockers.append("No hay PDF de bases indexado en la sesión.")
    elif not any(b.get("file_exists") for b in bases_docs):
        verdict = "BLOCKED"
        blockers.append("Registro de bases existe pero el archivo en disco fue eliminado.")
    if orphan_catalog and all(not o.get("doc_in_db") for o in orphan_catalog):
        if "Catálogo huérfano" not in " ".join(blockers):
            blockers.append("Catálogo huérfano: metadata ANALYZED sin fila en documents ni archivo en disco.")
    if len(combined) < 5000:
        if verdict == "OK":
            verdict = "WARN"
        blockers.append(f"Corpus de bases muy corto ({len(combined)} chars).")

    return {
        "session_id": session_id,
        "session_name": state.get("name"),
        "verdict": verdict,
        "blockers": blockers,
        "documents_total": len(docs),
        "bases_pdf": bases_docs,
        "orphan_catalog": orphan_catalog,
        "corpus": {
            "combined_chars": len(combined),
            "filenames": filenames,
        },
        "document_inventory_items": len(inv_items),
        "compliance_master_list": len(state.get("compliance_master_list") or []),
        "intake_plan": bool(state.get("intake_plan")),
        "analyst_result": bool(state.get("analyst_result")),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="vigilancia_issste")
    args = ap.parse_args()
    report = await audit_session(args.session)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
