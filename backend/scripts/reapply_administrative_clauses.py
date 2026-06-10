#!/usr/bin/env python3
"""Reaplica cláusulas administrativas determinísticas sobre DOCX ya generados (sin LLM)."""
from __future__ import annotations

import asyncio
import os
import sys

from app.agents.formats import _save_docx
from app.api.deps import get_connected_memory
from app.services.administrative_letter_clauses import (
    build_administrative_letter_markdown,
    extract_letter_body_from_docx,
    is_obra_pliego_contract_annex,
    is_obra_tabular_annex,
    resolve_document_ciudad,
    resolve_letter_asunto,
    resolve_letter_session_metadata,
    try_build_clause_markdown,
)
from app.services.document_date_resolver import resolve_document_date
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

CLAUSE_TARGETS = {
    "obra|T1",
    "obra|T2",
    "obra|T3",
    "obra|T4",
    "obra|T5",
    "obra|E4",
    "obra|T-B-2",
    "obra|T8_PRIVACIDAD",
    "obra|T8",
    "pliego|ANEXO_II",
    "pliego|ANEXO_III",
    "pliego|ANEXO_IV",
    "pliego|ANEXO_V",
    "pliego|ANEXO_VI",
    "pliego|ANEXO_VII",
    "pliego|ANEXO_VIII",
    "pliego|ANEXO_IX",
    "pliego|ANEXO_X",
    "pliego|ANEXO_XI",
    "pliego|ANEXO_XII",
}


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    clauses_only = "--clauses-only" in sys.argv[1:]
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    mp = state.get("master_profile") or {}
    admin_dir = os.path.join("/data/outputs", session_id, "3.documentos administrativos")
    if not os.path.isdir(admin_dir):
        print(f"Missing {admin_dir}")
        sys.exit(1)

    session_state = dict(state)
    try:
        from app.services.junta_bases_corpus import build_bases_corpus
        from app.services.convocante_resolver import merge_convocante_into_session_patch
        from app.services.vector_service import VectorDbServiceClient

        vdb = VectorDbServiceClient()
        if not str(session_state.get("bases_corpus_hint") or "").strip():
            cal_res = vdb.query_texts(
                session_id,
                "recepción de propuestas calendario evento fecha presentación apertura proposiciones",
                n_results=20,
            )
            cal_docs = cal_res.get("documents") or []
            session_state["bases_corpus_hint"] = "\n".join(d for d in cal_docs if d)[:120000]

        docs = await mem.get_documents(session_id)
        corpus = build_bases_corpus(session_id, docs, session_state=session_state)
        combined = str(corpus.combined or "")
        if len(combined) > len(str(session_state.get("bases_corpus_hint") or "")):
            session_state["bases_corpus_hint"] = combined[:180000]
        patch = merge_convocante_into_session_patch(session_state, corpus.combined)
        if patch.get("convocante"):
            la = dict(session_state.get("last_analysis") or {})
            for k, v in patch.items():
                if v and not str(la.get(k) or "").strip():
                    la[k] = v
            session_state["last_analysis"] = la
            if patch.get("destinatario"):
                session_state["destinatario"] = patch["destinatario"]
            session_state["convocante"] = patch.get("convocante")
    except Exception:
        pass

    date_info = resolve_document_date(session_state)
    letter_meta = resolve_letter_session_metadata(session_state)
    dom = mp.get("domicilio_fiscal") or mp.get("domicilio") or ""
    logo_path = mp.get("logo")
    if not logo_path:
        company_data = (state.get("initial_data") or {}).get("company_data") or {}
        logo_info = (company_data.get("docs") or {}).get("LOGOTIPO", {})
        if isinstance(logo_info, dict):
            logo_path = logo_info.get("path")
    meta = {
        "logo_path": logo_path,
        "tender_name": session_id.replace("_", " ").upper(),
        "fecha": date_info.get("fecha_es"),
        "fecha_corta": date_info.get("fecha_corta"),
        "deadline_dt_iso": date_info.get("deadline_dt"),
        "footer_text": f"{mp.get('razon_social', '')} | RFC: {mp.get('rfc', '')} | Domicilio: {dom}",
        "domicilio": dom,
        "destinatario": letter_meta.get("destinatario") or "A QUIEN CORRESPONDA:",
        "concurso_label": letter_meta.get("concurso_label", ""),
        "convocante": letter_meta.get("convocante", ""),
        "ciudad": resolve_document_ciudad(mp, str(dom), letter_meta=letter_meta),
        "empresa": mp.get("razon_social", ""),
        "rfc": mp.get("rfc", ""),
        "representante": mp.get("representante_legal") or mp.get("representante", ""),
        "formal_closing": True,
        "bases_corpus_hint": session_state.get("bases_corpus_hint", ""),
        "session_state": session_state,
    }

    updated = 0
    for fn in sorted(os.listdir(admin_dir)):
        if not fn.lower().endswith(".docx"):
            continue
        path = os.path.join(admin_dir, fn)
        key = pliego_format_dedupe_key(fn)
        title = fn.replace("_", " ").rsplit(".", 1)[0]

        if key in CLAUSE_TARGETS:
            body = try_build_clause_markdown(
                req_label=fn,
                master_profile=mp,
                doc_metadata=meta,
            ) or build_administrative_letter_markdown(
                req_nombre=fn,
                master_profile=mp,
                doc_metadata=meta,
                session_state=session_state,
            )
        elif clauses_only:
            continue
        else:
            body = extract_letter_body_from_docx(path)
            if not body.strip():
                continue

        doc_meta = {**meta, "obra_tabular": is_obra_tabular_annex(fn, key)}
        if is_obra_pliego_contract_annex(fn, key):
            doc_meta["obra_pliego_contract"] = True
            doc_meta["document_title"] = resolve_letter_asunto(fn, "", key)
        _save_docx(title, body, path, doc_meta)
        updated += 1
        print(
            f"updated {fn} key={key} lugar={meta.get('ciudad')} fecha={meta.get('fecha')}"
        )

    try:
        from app.services.obra_delivery_gap_service import sync_admin_to_sobre_administrativo

        n_sync, _ = sync_admin_to_sobre_administrativo(session_id)
        print(f"sync_sobre_admin count={n_sync}")
    except Exception as exc:
        print(f"sync_sobre_admin_skipped error={exc}")

    print(f"reapply_done count={updated}")
    sys.exit(0 if updated else 2)


if __name__ == "__main__":
    asyncio.run(main())
