#!/usr/bin/env python3
"""
Monitoreo de ingesta: Postgres (estado por doc) + ChromaDB (chunks por archivo).

Uso:
  python scripts/monitor_session_ingestion.py --session isapeg
  python scripts/monitor_session_ingestion.py --session isapeg --watch 15
  python scripts/monitor_session_ingestion.py --session isapeg --json report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.memory.factory import MemoryAdapterFactory
from app.services.vector_service import VectorDbServiceClient


def _sanitize_session(session_id: str) -> str:
    return session_id.strip().lower().replace("-", "_")


async def _collect(session_id: str) -> Dict[str, Any]:
    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    docs_raw = await mem.get_documents(session_id)
    await mem.disconnect()

    docs: List[Dict[str, Any]] = []
    for d in docs_raw or []:
        c = d.get("content") or {}
        docs.append(
            {
                "id": d.get("id"),
                "name": c.get("filename", "?"),
                "status": c.get("status", "UNKNOWN"),
                "total_pages": c.get("total_pages"),
                "text_len": len((c.get("extracted_text") or "")),
            }
        )

    vdb = VectorDbServiceClient()
    clean = _sanitize_session(session_id)
    col = vdb.get_or_create_collection(session_id)
    chunk_total = 0
    by_source: Dict[str, int] = defaultdict(int)
    by_doc: Dict[str, int] = defaultdict(int)
    chunk_types: Dict[str, int] = defaultdict(int)
    pages_by_source: Dict[str, set] = defaultdict(set)
    empty_chunks = 0
    sample_headers: List[str] = []

    if col:
        try:
            chunk_total = int(col.count())
        except Exception as exc:
            chunk_total = -1
            err_count = str(exc)
        else:
            err_count = None

        # Paginar metadatas (Chroma limit por get)
        offset = 0
        page_size = 500
        while True:
            try:
                res = col.get(
                    include=["metadatas", "documents"],
                    limit=page_size,
                    offset=offset,
                )
            except TypeError:
                res = col.get(include=["metadatas", "documents"], limit=page_size)
            metas = res.get("metadatas") or []
            texts = res.get("documents") or []
            if not metas:
                break
            for meta, text in zip(metas, texts):
                src = (meta or {}).get("source") or "(sin source)"
                did = (meta or {}).get("doc_id") or "(sin doc_id)"
                by_source[src] += 1
                by_doc[did] += 1
                ct = (meta or {}).get("chunk_type") or "legacy"
                chunk_types[ct] += 1
                pg = (meta or {}).get("page")
                if pg is not None:
                    pages_by_source[src].add(pg)
                body = (text or "").strip()
                if len(body) < 50:
                    empty_chunks += 1
                elif len(sample_headers) < 3 and body.startswith("[FUENTE:"):
                    sample_headers.append(body[:100].replace("\n", " "))
            if len(metas) < page_size:
                break
            offset += page_size
    else:
        err_count = "no_collection"

    analyzed = sum(1 for d in docs if d["status"] == "ANALYZED")
    uploaded = sum(1 for d in docs if d["status"] == "UPLOADED")
    errors = sum(1 for d in docs if d["status"] == "ERROR")

    issues: List[str] = []
    if not docs:
        issues.append("FAIL: no hay documentos en la sesión")
    if uploaded:
        issues.append(f"WARN: {uploaded} doc(s) aún UPLOADED (falta /process o Analizar Bases)")
    if errors:
        issues.append(f"FAIL: {errors} doc(s) en ERROR")
    if chunk_total == 0:
        issues.append("FAIL: colección Chroma vacía (RAG inutilizable)")
    elif chunk_total > 0 and analyzed < len(docs):
        issues.append("WARN: hay docs no ANALYZED pero ya hay chunks (revisar coherencia)")
    for d in docs:
        if d["status"] == "ANALYZED" and d["text_len"] < 100:
            issues.append(f"WARN: {d['name']} ANALYZED pero texto <100 chars")
    chroma_sources = set(by_source.keys()) - {"(sin source)"}
    db_names = {d["name"] for d in docs if d["status"] == "ANALYZED"}
    missing_in_chroma = sorted(db_names - chroma_sources)
    if missing_in_chroma:
        issues.append(
            f"FAIL: ANALYZED sin chunks en Chroma: {', '.join(missing_in_chroma[:5])}"
            + ("…" if len(missing_in_chroma) > 5 else "")
        )

    verdict = "PASS"
    if any(i.startswith("FAIL") for i in issues):
        verdict = "FAIL"
    elif issues:
        verdict = "WARN"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "chroma_collection": clean,
        "documents": {
            "total": len(docs),
            "analyzed": analyzed,
            "uploaded": uploaded,
            "error": errors,
            "items": docs,
        },
        "chromadb": {
            "chunk_total": chunk_total,
            "count_error": err_count,
            "unique_sources": len(by_source),
            "chunks_by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
            "chunks_by_doc_id": dict(sorted(by_doc.items(), key=lambda x: -x[1])),
            "chunk_types": dict(chunk_types),
            "pages_indexed_by_source": {
                k: len(v) for k, v in sorted(pages_by_source.items())
            },
            "empty_or_tiny_chunks": empty_chunks,
            "sample_chunk_headers": sample_headers,
        },
        "issues": issues,
        "verdict": verdict,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor ingesta Postgres + ChromaDB")
    parser.add_argument("--session", required=True)
    parser.add_argument("--watch", type=int, default=0, help="Repetir cada N segundos (0=una vez)")
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()

    import time

    while True:
        report = await _collect(args.session)
        line = (
            f"[{report['verdict']}] docs={report['documents']['total']} "
            f"ANALYZED={report['documents']['analyzed']} UPLOADED={report['documents']['uploaded']} "
            f"ERROR={report['documents']['error']} | chunks={report['chromadb']['chunk_total']} "
            f"fuentes={report['chromadb']['unique_sources']}"
        )
        print(line, flush=True)
        if report["issues"]:
            for iss in report["issues"]:
                print(f"  → {iss}", flush=True)
        if report["chromadb"]["chunks_by_source"]:
            for src, n in list(report["chromadb"]["chunks_by_source"].items())[:12]:
                pages = report["chromadb"]["pages_indexed_by_source"].get(src, "?")
                print(f"    · {src}: {n} chunks, ~{pages} páginas", flush=True)
            rest = len(report["chromadb"]["chunks_by_source"]) - 12
            if rest > 0:
                print(f"    … y {rest} archivo(s) más", flush=True)

        if args.json_path:
            Path(args.json_path).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        if args.watch <= 0:
            break
        await asyncio.sleep(args.watch)


if __name__ == "__main__":
    asyncio.run(main())
