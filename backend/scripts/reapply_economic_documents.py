#!/usr/bin/env python3
"""Reaplica documentos económicos deterministas (APU, AE, carta compromiso) sin LLM."""
from __future__ import annotations

import asyncio
import os
import sys

from app.agents.formats import _save_docx
from app.agents.technical_writer import _build_carta_presentacion_text
from app.api.deps import get_connected_memory
from app.services.administrative_letter_clauses import resolve_document_ciudad, resolve_letter_session_metadata
from app.services.document_date_resolver import resolve_document_date
from app.services.economic_document_reapply import load_economic_payload, reapply_economic_documents


async def _enrich_bases_hint(session_state: dict, session_id: str) -> dict:
    state = dict(session_state)
    if str(state.get("bases_corpus_hint") or "").strip():
        return state
    try:
        from app.services.vector_service import VectorDbServiceClient

        cal_res = VectorDbServiceClient().query_texts(
            session_id,
            "recepción de propuestas calendario evento fecha presentación apertura proposiciones",
            n_results=20,
        )
        cal_docs = cal_res.get("documents") or []
        state["bases_corpus_hint"] = "\n".join(d for d in cal_docs if d)[:120000]
    except Exception:
        pass
    return state


def _resolve_technical_dir(session_id: str) -> str | None:
    base = os.path.join("/data/outputs", session_id)
    for name in ("1.propuesta tecnica", "1.propuesta_tecnica"):
        path = os.path.join(base, name)
        if os.path.isdir(path):
            return path
    return None


def _reapply_technical_carta(
    *,
    session_id: str,
    session_state: dict,
    master_profile: dict,
    tech_dir: str,
) -> str | None:
    if not os.path.isdir(tech_dir):
        return None
    carta_path = os.path.join(tech_dir, "01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx")
    if not os.path.isfile(carta_path):
        return None

    date_info = resolve_document_date(session_state)
    letter_meta = resolve_letter_session_metadata(session_state)
    dom = master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
    logo_path = master_profile.get("logo")
    if not logo_path:
        company_data = (session_state.get("initial_data") or {}).get("company_data") or {}
        logo_info = (company_data.get("docs") or {}).get("LOGOTIPO", {})
        if isinstance(logo_info, dict):
            logo_path = logo_info.get("path")

    meta = {
        "logo_path": logo_path,
        "tender_name": session_id.replace("_", " ").upper(),
        "fecha": date_info.get("fecha_es"),
        "fecha_corta": date_info.get("fecha_corta"),
        "footer_text": f"{master_profile.get('razon_social', '')} | RFC: {master_profile.get('rfc', '')} | Domicilio: {dom}",
        "domicilio": dom,
        "ciudad": resolve_document_ciudad(master_profile, str(dom)),
        "destinatario": letter_meta.get("destinatario") or "A QUIEN CORRESPONDA:",
        "formal_closing": True,
    }
    carta_text = _build_carta_presentacion_text(
        razon_social=str(master_profile.get("razon_social") or ""),
        rfc=str(master_profile.get("rfc") or ""),
        representante=str(master_profile.get("representante_legal") or ""),
        domicilio=str(dom),
        tender_name=session_id.replace("_", " ").upper(),
        fecha_es=str(date_info.get("fecha_es") or ""),
        destinatario=str(meta.get("destinatario") or ""),
    )
    _save_docx(
        "CARTA DE PRESENTACIÓN DE PROPUESTA TÉCNICA",
        carta_text,
        carta_path,
        meta,
    )
    return carta_path


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    include_technical = "--no-technical" not in sys.argv

    mem = await get_connected_memory()
    state = await _enrich_bases_hint(await mem.get_session(session_id) or {}, session_id)
    mp = state.get("master_profile") or {}
    if not mp.get("razon_social"):
        print("master_profile vacío; abortando.")
        sys.exit(1)

    economic_data, mapeo_items, resumen = load_economic_payload(
        state, session_id=session_id, memory=mem
    )
    if not mapeo_items:
        print("Sin partidas económicas en sesión; no se puede reaplicar APU/AE.")
        sys.exit(1)

    econ_dir = os.path.join("/data/outputs", session_id, "2.propuesta_economica")
    updated = reapply_economic_documents(
        session_id=session_id,
        session_state=state,
        master_profile=mp,
        output_dir=econ_dir,
        economic_data=economic_data or {},
        mapeo_items=mapeo_items,
        resumen=resumen,
    )
    for path in updated:
        print(f"updated {os.path.basename(path)} fecha={resumen.get('fecha_es')} total={resumen.get('total')}")

    if include_technical:
        tech_dir = _resolve_technical_dir(session_id)
        if tech_dir:
            tc = _reapply_technical_carta(
                session_id=session_id,
                session_state=state,
                master_profile=mp,
                tech_dir=tech_dir,
            )
            if tc:
                print(f"updated {os.path.basename(tc)} fecha={resumen.get('fecha_es')}")
        else:
            print("skip: carpeta propuesta técnica no encontrada")

    print(f"done: {len(updated)} económico(s)")


if __name__ == "__main__":
    asyncio.run(main())
