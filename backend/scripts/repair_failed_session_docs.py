#!/usr/bin/env python3
"""
Limpia vectores de documentos ERROR/UPLOADED .doc y re-ingesta con el pipeline actual.

Uso (contenedor backend, tras rebuild con antiword + LibreOffice):
  python scripts/repair_failed_session_docs.py --session isapeg
  python scripts/repair_failed_session_docs.py --session isapeg --reanalyze
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.api.schemas.requests import ProcessBasesRequest
from app.memory.factory import MemoryAdapterFactory
from app.services.document_ingestion_router import DocumentIngestionRouter
from app.services.document_vector_index import index_pages_atomic
from app.services.vector_service import VectorDbServiceClient


def _needs_repair(doc: Dict[str, Any]) -> bool:
    content = doc.get("content") or {}
    status = str(content.get("status") or "").upper()
    filename = str(content.get("filename") or "")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if status == "ERROR":
        return True
    if status == "UPLOADED" and ext in ("doc", "docx"):
        return True
    return False


async def _clean_doc_vectors(
    session_id: str, doc_id: str, vector_client: VectorDbServiceClient
) -> None:
    vector_client.delete_by_doc_id(session_id, doc_id)


async def _reingest_one(
    session_id: str,
    doc: Dict[str, Any],
    memory: Any,
    router: DocumentIngestionRouter,
    vector_client: VectorDbServiceClient,
) -> Dict[str, Any]:
    doc_id = str(doc.get("id") or "")
    content = dict(doc.get("content") or {})
    filename = str(content.get("filename") or "")
    file_path = content.get("file_path")
    result: Dict[str, Any] = {
        "doc_id": doc_id,
        "filename": filename,
        "ok": False,
        "error": None,
        "chunks": 0,
    }
    if not file_path or not os.path.isfile(file_path):
        result["error"] = "archivo_fisico_ausente"
        content["status"] = "ERROR"
        await memory.save_document(
            doc_id, session_id, content, {"status": "ERROR", "filename": filename}
        )
        return result

    await _clean_doc_vectors(session_id, doc_id, vector_client)

    ocr_result = await router.ingest(
        file_path=file_path,
        filename=filename,
        session_id=session_id,
        doc_id=doc_id,
        memory=memory,
    )
    if not ocr_result.get("success"):
        content["status"] = "ERROR"
        content["ingest_error"] = ocr_result.get("error", "ingest_failed")
        await memory.save_document(
            doc_id, session_id, content, {"status": "ERROR", "filename": filename}
        )
        result["error"] = content["ingest_error"]
        return result

    raw_text = (ocr_result.get("extracted_text") or "").strip()
    pages = ocr_result.get("pages") or []
    chunks = index_pages_atomic(
        session_id, doc_id, filename, pages, vector_client
    )
    content["status"] = "ANALYZED"
    content["extracted_text"] = raw_text
    content["total_pages"] = ocr_result.get("total_pages", len(pages))
    content.pop("ingest_error", None)
    await memory.save_document(
        doc_id, session_id, content, {"status": "ANALYZED", "filename": filename}
    )
    result["ok"] = True
    result["chunks"] = chunks
    result["text_len"] = len(raw_text)
    return result


async def _reanalyze(session_id: str, company_id: str | None) -> Dict[str, Any]:
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    mcp = MCPContextManager(memory_repository=memory)
    orchestrator = OrchestratorAgent(context_manager=mcp)
    out = await orchestrator.process(
        session_id=session_id,
        input_data={
            "company_id": company_id,
            "company_data": {"mode": "analysis_only"},
        },
    )
    await memory.disconnect()
    if isinstance(out, dict):
        return {
            "status": out.get("status"),
            "chatbot_message": (out.get("chatbot_message") or "")[:500],
        }
    return {"status": "unknown"}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Reparar ingesta de docs fallidos")
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="Tras re-ingestar, ejecutar orquestador analysis_only",
    )
    args = parser.parse_args()

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    session_state = await mem.get_session(args.session) or {}
    docs = await mem.get_documents(args.session)
    targets = [d for d in docs if _needs_repair(d)]
    company_id = session_state.get("company_id")

    report: Dict[str, Any] = {
        "session_id": args.session,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "targets": [t.get("content", {}).get("filename") for t in targets],
        "results": [],
    }

    if not targets:
        print(json.dumps({**report, "message": "no_hay_documentos_a_reparar"}, indent=2))
        await mem.disconnect()
        return

    router = DocumentIngestionRouter()
    vector_client = VectorDbServiceClient()

    for doc in targets:
        print(f"Reparando: {doc.get('content', {}).get('filename')}", flush=True)
        row = await _reingest_one(args.session, doc, mem, router, vector_client)
        report["results"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    await mem.disconnect()

    if args.reanalyze:
        print("Iniciando re-análisis (analysis_only)...", flush=True)
        report["reanalyze"] = await _reanalyze(args.session, company_id)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    ok = sum(1 for r in report["results"] if r.get("ok"))
    report["summary"] = {
        "repaired_ok": ok,
        "failed": len(report["results"]) - ok,
        "total": len(report["results"]),
    }
    out_path = f"/data/outputs/{args.session}/_REPAIR_INGESTION.json"
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
