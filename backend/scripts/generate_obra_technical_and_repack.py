#!/usr/bin/env python3
"""Genera propuesta técnica determinista para obra y re-empaqueta CompraNet."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from app.agents.formats import _save_docx
from app.agents.mcp_context import MCPContextManager
from app.agents.technical_writer import _build_carta_presentacion_text
from app.api.deps import get_connected_memory
from app.services.document_traceability import attach_traceability, safe_file_sha256
from app.services.administrative_letter_clauses import (
    resolve_document_ciudad,
    resolve_letter_session_metadata,
)
from app.services.document_date_resolver import resolve_document_date
from app.services.technical_proposal_deterministic import build_propuesta_tecnica_body
from app.services.vector_service import VectorDbServiceClient

async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"
    mem = await get_connected_memory()
    st = await mem.get_session(session_id) or {}
    company_id = str(st.get("company_id") or st.get("selected_company_id") or "")
    co = await mem.get_company(company_id) if company_id else None
    mp = (co or {}).get("master_profile") or st.get("master_profile") or {}
    dom = str(mp.get("domicilio_fiscal") or mp.get("domicilio") or "")
    tech_dir = Path("/data/outputs") / session_id / "1.propuesta tecnica"
    tech_dir.mkdir(parents=True, exist_ok=True)

    if not str(st.get("bases_corpus_hint") or "").strip():
        try:
            vc = VectorDbServiceClient()
            cal = vc.query_texts(
                session_id,
                "barda perimetral propuesta tecnica programa de obra especificaciones",
                n_results=12,
            )
            st["bases_corpus_hint"] = "\n".join(
                d for d in (cal.get("documents") or []) if d
            )[:120000]
        except Exception:
            pass

    date_info = resolve_document_date(st)
    letter_meta = resolve_letter_session_metadata(st)
    fecha_es = str(date_info.get("fecha_es") or "")
    tender_name = "LICITACION D/080/2025 - BARDA PRIMARIA LOPEZ RAYON"
    destinatario = letter_meta.get("destinatario") or "A QUIEN CORRESPONDA:"
    meta = {
        "logo_path": mp.get("logo"),
        "tender_name": tender_name,
        "fecha": fecha_es,
        "fecha_corta": date_info.get("fecha_corta") or "",
        "domicilio": dom,
        "ciudad": resolve_document_ciudad(mp, dom),
        "footer_text": (
            f"{mp.get('razon_social', '')} | RFC: {mp.get('rfc', '')} | Domicilio: {dom}"
        ),
        "destinatario": destinatario,
        "empresa": mp.get("razon_social"),
        "rfc": mp.get("rfc"),
        "representante": mp.get("representante_legal"),
        "formal_closing": True,
    }
    rs = str(mp.get("razon_social") or "")
    rfc = str(mp.get("rfc") or "")
    rep = str(mp.get("representante_legal") or "")

    carta_path = tech_dir / "01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx"
    carta_text = _build_carta_presentacion_text(
        razon_social=rs,
        rfc=rfc,
        representante=rep,
        domicilio=dom,
        tender_name=tender_name,
        fecha_es=fecha_es,
        destinatario=str(destinatario),
    )
    _save_docx(
        "CARTA DE PRESENTACION DE PROPUESTA TECNICA",
        carta_text,
        str(carta_path),
        meta,
    )

    req_context = ""
    try:
        vc = VectorDbServiceClient()
        res = vc.query_texts(
            session_id,
            "propuesta tecnica barda perimetral construccion obra programa metodologia",
            n_results=6,
        )
        req_context = "\n".join(d for d in (res.get("documents") or []) if d)[:2000]
    except Exception:
        pass
    prop_path = tech_dir / "02_PROPUESTA_TECNICA_BARDA_PERIMETRAL.docx"
    body = build_propuesta_tecnica_body(
        razon_social=rs,
        rfc=rfc,
        representante=rep,
        domicilio=dom,
        tender_name=tender_name,
        req_nombre="Propuesta Tecnica - Construccion de barda perimetral",
        req_desc=(
            "Construccion de barda perimetral en Primaria Lopez Rayon "
            "conforme bases D/080/2025"
        ),
        req_context=req_context,
    )
    _save_docx("PROPUESTA TECNICA", body, str(prop_path), meta)

    docs = []
    for p, nombre, tipo in (
        (carta_path, "Carta de Presentacion", "tecnico_carta"),
        (prop_path, "Propuesta Tecnica Barda Perimetral", "tecnico_propuesta"),
    ):
        docs.append(
            attach_traceability(
                {
                    "nombre": nombre,
                    "source_filename": p.name,
                    "ruta": str(p),
                    "status": "OK",
                    "tipo": tipo,
                },
                materialization_route="deterministic_obra",
                output_hash=safe_file_sha256(str(p)),
            )
        )

    ctx = MCPContextManager(mem)
    await ctx.record_task_completion(
        session_id,
        "technical_writing_COMPLETED",
        {"documentos": docs, "count": len(docs), "obra_forced": True},
    )

    base = Path("/data/outputs") / session_id
    sobre2 = base / "SOBRE_2_TECNICO"
    sobre2.mkdir(parents=True, exist_ok=True)
    import shutil

    for src in tech_dir.glob("*.docx"):
        dest = sobre2 / src.name
        shutil.copy2(src, dest)

    print("generated:", [p.name for p in tech_dir.glob("*.docx")])
    print("SOBRE_2:", [p.name for p in sorted(sobre2.glob("*"))])

    import subprocess

    repack = subprocess.run(
        [sys.executable, "scripts/repack_session_compranet.py", "--session", session_id],
        cwd="/app",
        env={**dict(os.environ), "PYTHONPATH": "/app"},
        capture_output=True,
        text=True,
    )
    print(repack.stdout)
    if repack.stderr:
        print(repack.stderr[-2000:])
    print("repack exit:", repack.returncode)

    stec = base / "_compranet_validated" / "SobreTecnica"
    val = sorted(stec.glob("*")) if stec.is_dir() else []
    print("CompraNet SobreTecnica:", [p.name for p in val])
    await mem.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
