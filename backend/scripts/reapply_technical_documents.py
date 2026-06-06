#!/usr/bin/env python3
"""Reaplica documentos técnicos deterministas (TE-01, carta) sin LLM."""
from __future__ import annotations

import asyncio
import os
import sys

from app.agents.formats import _save_docx
from app.agents.technical_writer import (
    TechnicalWriterAgent,
    _build_carta_presentacion_text,
)
from app.api.deps import get_connected_memory
from app.services.administrative_letter_clauses import resolve_document_ciudad, resolve_letter_session_metadata
from app.services.document_date_resolver import resolve_document_date
from app.services.technical_proposal_deterministic import (
    build_propuesta_tecnica_body,
    is_primary_technical_proposal,
)
from app.services.vector_service import VectorDbServiceClient


def _resolve_technical_dir(session_id: str) -> str | None:
    base = os.path.join("/data/outputs", session_id)
    for name in ("1.propuesta tecnica", "1.propuesta_tecnica"):
        path = os.path.join(base, name)
        if os.path.isdir(path):
            return path
    return None


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    mp = state.get("master_profile") or {}
    if not mp.get("razon_social"):
        print("master_profile vacío")
        sys.exit(1)

    tech_dir = _resolve_technical_dir(session_id)
    if not tech_dir:
        print("carpeta técnica no encontrada")
        sys.exit(1)

    if not str(state.get("bases_corpus_hint") or "").strip():
        try:
            cal_res = VectorDbServiceClient().query_texts(
                session_id,
                "recepción propuestas calendario especificaciones técnicas propuesta técnica",
                n_results=20,
            )
            state["bases_corpus_hint"] = "\n".join(d for d in (cal_res.get("documents") or []) if d)[:120000]
        except Exception:
            pass

    date_info = resolve_document_date(state)
    letter_meta = resolve_letter_session_metadata(state)
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
        "domicilio": dom,
        "ciudad": resolve_document_ciudad(mp, str(dom)),
        "footer_text": f"{mp.get('razon_social', '')} | RFC: {mp.get('rfc', '')} | Domicilio: {dom}",
        "destinatario": letter_meta.get("destinatario") or "A QUIEN CORRESPONDA:",
        "empresa": mp.get("razon_social"),
        "rfc": mp.get("rfc"),
        "representante": mp.get("representante_legal"),
        "formal_closing": True,
    }
    fecha_es = str(date_info.get("fecha_es") or "")
    tender_name = meta["tender_name"]
    updated = 0

    carta_path = os.path.join(tech_dir, "01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx")
    if os.path.isfile(carta_path):
        carta_text = _build_carta_presentacion_text(
            razon_social=str(mp.get("razon_social") or ""),
            rfc=str(mp.get("rfc") or ""),
            representante=str(mp.get("representante_legal") or ""),
            domicilio=str(dom),
            tender_name=tender_name,
            fecha_es=fecha_es,
            destinatario=str(meta.get("destinatario") or ""),
        )
        _save_docx("CARTA DE PRESENTACIÓN DE PROPUESTA TÉCNICA", carta_text, carta_path, meta)
        updated += 1
        print(f"updated carta fecha={fecha_es}")

    for fn in sorted(os.listdir(tech_dir)):
        if not fn.lower().endswith(".docx"):
            continue
        if "CARTA_PRESENTACION" in fn.upper():
            continue
        if not is_primary_technical_proposal(fn, fn.replace(".docx", ""), ""):
            continue
        path = os.path.join(tech_dir, fn)
        req_context = ""
        try:
            res = VectorDbServiceClient().query_texts(
                session_id, f"propuesta técnica {fn}", n_results=4
            )
            docs = res.get("documents") or []
            req_context = "\n".join(d for d in docs if d)[:1500]
        except Exception:
            pass
        body = build_propuesta_tecnica_body(
            razon_social=str(mp.get("razon_social") or ""),
            rfc=str(mp.get("rfc") or ""),
            representante=str(mp.get("representante_legal") or ""),
            domicilio=str(dom),
            tender_name=tender_name,
            req_nombre=fn,
            req_desc="Propuesta técnica",
            req_context=req_context,
        )
        title = fn.replace("_", " ").rsplit(".", 1)[0]
        _save_docx(title, body, path, meta)
        updated += 1
        print(f"updated {fn} fecha={fecha_es} route=deterministic_propuesta_tecnica")

    print(f"done: {updated} archivo(s)")


if __name__ == "__main__":
    asyncio.run(main())
