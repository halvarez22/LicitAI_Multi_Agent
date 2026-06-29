#!/usr/bin/env python3
"""
Paquete de evidencia para Qwen / diagnóstico presupuesto $1M forense.
Uso: PYTHONPATH=/app python scripts/forensic_presupuesto_evidence_pack.py [SESSION_ID]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"
AMOUNT_PATTERNS = [
    r"1000000",
    r"1,000,000",
    r"1\.000\.000",
    r"1'000,000",
    r"un mill[oó]n",
    r"UN MILLON",
    r"UN MILLÓN",
]


async def find_sessions_with_alert(mem) -> List[str]:
    """Sesiones con la alerta de presupuesto en dictamen o economic task."""
    hits: List[str] = []
    try:
        from sqlalchemy import text
        from app.db.database import async_session_factory

        async with async_session_factory() as db:
            res = await db.execute(
                text(
                    "SELECT id FROM sessions WHERE state_data::text ILIKE :pat ORDER BY updated_at DESC LIMIT 20"
                ),
                {"pat": "%presupuesto debe ser%"},
            )
            hits = [r[0] for r in res.fetchall()]
    except Exception as exc:
        print(f"[warn] SQL scan: {exc}")
    return hits


def _tasks_analyst_reglas(st: Dict[str, Any]) -> Dict[str, Any]:
    tc = st.get("tasks_completed") or {}
    if isinstance(tc, list):
        for t in reversed(tc):
            if isinstance(t, dict) and t.get("task") == "analyst":
                data = (t.get("result") or {}).get("data") or t.get("data") or {}
                ab = data.get("analisis_bases") or data
                return dict(ab.get("reglas_economicas") or {})
    if isinstance(tc, dict):
        analyst = tc.get("analyst") or {}
        data = analyst.get("data") or {}
        ab = data.get("analisis_bases") or data
        return dict(ab.get("reglas_economicas") or {})
    return {}


def _economic_alertas(st: Dict[str, Any]) -> List[Any]:
    tc = st.get("tasks_completed") or {}
    if isinstance(tc, list):
        for t in reversed(tc):
            if isinstance(t, dict) and t.get("task") == "economic_proposal":
                data = (t.get("result") or {}).get("data") or t.get("data") or {}
                return list((data.get("analisis_precios") or {}).get("alertas") or [])
    if isinstance(tc, dict):
        eco = tc.get("economic") or tc.get("economic_proposal") or {}
        data = eco.get("data") or {}
        return list((data.get("analisis_precios") or {}).get("alertas") or [])
    return []


def _dictamen_causales_econ(st: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = st.get("dictamen") or {}
    out = []
    for h in d.get("causales") or []:
        if not isinstance(h, dict):
            continue
        txt = h.get("texto")
        blob = txt if isinstance(txt, str) else str(txt)
        if "presupuesto" in blob.lower() or "1,000,000" in blob or "1000000" in blob:
            out.append(h)
    return out


def _search_ocr_in_docs(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Equivalente a pdf_pages: content.extracted_text + content.pages[]."""
    result: Dict[str, Any] = {
        "documents_checked": 0,
        "amount_hits": [],
        "pages_with_amount": [],
        "sample_pages_no_amount": [],
        "total_indexed_pages_ocr": 0,
        "docs_summary": [],
    }
    for doc in docs or []:
        content = doc.get("content") or {}
        if not isinstance(content, dict):
            continue
        result["documents_checked"] += 1
        fn = content.get("filename") or doc.get("filename") or "?"
        status = content.get("status") or "?"
        total_pages = int(content.get("total_pages") or 0)
        extracted = str(content.get("extracted_text") or "")
        pages = content.get("pages") if isinstance(content.get("pages"), list) else []
        result["docs_summary"].append({
            "filename": fn,
            "status": status,
            "total_pages": total_pages,
            "extracted_text_chars": len(extracted),
            "pages_array_len": len(pages),
        })
        result["total_indexed_pages_ocr"] += len(pages) or total_pages

        def _check_text(text: str, page_num: Any, source: str) -> None:
            if not text:
                return
            for pat in AMOUNT_PATTERNS:
                if re.search(pat, text, re.I):
                    result["amount_hits"].append({
                        "source": source,
                        "filename": fn,
                        "page": page_num,
                        "pattern": pat,
                        "snippet": text[max(0, text.lower().find("000") - 80):][:320],
                    })
                    return

        for pat in AMOUNT_PATTERNS:
            if re.search(pat, extracted, re.I):
                pos = 0
                for m in re.finditer(pat, extracted, re.I):
                    pos = m.start()
                    break
                result["amount_hits"].append({
                    "source": "extracted_text",
                    "filename": fn,
                    "page": None,
                    "pattern": pat,
                    "snippet": extracted[max(0, pos - 80): pos + 240],
                })
                break

        for pg in pages[:500]:
            if not isinstance(pg, dict):
                continue
            pnum = pg.get("page", pg.get("page_number"))
            ptext = str(pg.get("text") or "")
            _check_text(ptext, pnum, "pages[]")
            if pnum is not None and len(result["sample_pages_no_amount"]) < 3:
                if not any(h.get("page") == pnum and h.get("filename") == fn for h in result["amount_hits"]):
                    if len(result["sample_pages_no_amount"]) < 3:
                        result["sample_pages_no_amount"].append({
                            "filename": fn,
                            "page": pnum,
                            "preview": ptext[:200],
                        })

    return result


async def pack(session_id: str) -> Dict[str, Any]:
    from app.api.deps import get_connected_memory
    from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1
    from app.services.forensic_risk_evidence_service import _scan_index_for_literal, resolve_forensic_risk_evidence
    from app.services.economic_risk_evidence_v1 import build_evidence_v1
    from app.services.vector_service import VectorDbServiceClient

    mem = await get_connected_memory()
    st = await mem.get_session(session_id) or {}
    if not st:
        return {"error": f"session not found: {session_id}"}

    docs = await mem.get_documents(session_id)
    vdb = VectorDbServiceClient()
    chunks = vdb.scan_session_chunks(session_id)
    scan_hit = _scan_index_for_literal(vdb, session_id, LITERAL)
    evidence_raw = await resolve_forensic_risk_evidence(session_id, LITERAL, session_state=st, memory=mem)
    evidence_v1 = build_evidence_v1(evidence_raw, literal=LITERAL)
    excerpt = await fetch_bases_excerpt_v1(session_id, LITERAL, session_state=st, memory=mem)

    chunk_samples = []
    for doc, meta in chunks[:15]:
        has_amt = any(re.search(p, doc or "", re.I) for p in AMOUNT_PATTERNS)
        chunk_samples.append({
            "page": meta.get("page"),
            "source": meta.get("source"),
            "has_amount_pattern": has_amt,
            "preview": (doc or "")[:180],
        })

    amount_chunks = [
        {"page": m.get("page"), "source": m.get("source"), "preview": (d or "")[:220]}
        for d, m in chunks
        if any(re.search(p, d or "", re.I) for p in AMOUNT_PATTERNS)
    ]

    return {
        "session_id": session_id,
        "literal": LITERAL,
        "1_bases_excerpt_api_equivalent": excerpt,
        "2_analyst_reglas_economicas": _tasks_analyst_reglas(st),
        "3_economic_analisis_precios_alertas": _economic_alertas(st),
        "4_dictamen_causales_presupuesto": _dictamen_causales_econ(st),
        "5_ocr_search": _search_ocr_in_docs(docs),
        "6_chroma": {
            "indexed_chunks": vdb.count_session_chunks(session_id),
            "indexed_sources": vdb.get_sources(session_id),
            "scan_hit": scan_hit,
            "evidence_v1": evidence_v1,
            "chunks_with_amount_pattern": amount_chunks[:20],
            "chunk_samples_first_15": chunk_samples,
        },
        "7_page_coverage": {
            "ocr_pages_total": _search_ocr_in_docs(docs)["total_indexed_pages_ocr"],
            "chroma_chunks": vdb.count_session_chunks(session_id),
            "docs_summary": _search_ocr_in_docs(docs)["docs_summary"],
        },
    }


async def main() -> int:
    session_id = sys.argv[1] if len(sys.argv) > 1 else ""
    from app.api.deps import get_connected_memory

    mem = await get_connected_memory()
    if not session_id:
        candidates = await find_sessions_with_alert(mem)
        if not candidates:
            # fallback: sesión UAT habitual
            candidates = ["barda_primaria_lopez_rayon", "la-51-gyn-051gyn025-n-8-2024_vigilancia"]
        for sid in candidates:
            st = await mem.get_session(sid) or {}
            if st:
                session_id = sid
                break
        if not session_id:
            print(json.dumps({"error": "no session found"}, ensure_ascii=False, indent=2))
            return 1
        print(f"# Auto-selected session_id: {session_id}", file=sys.stderr)

    out = await pack(session_id)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
