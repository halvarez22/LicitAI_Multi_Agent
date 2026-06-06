"""
Reaplicación determinista de documentos económicos (APU, Anexo AE, carta compromiso).

Perspectiva concursante; montos desde motor económico / master_proposal_state.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.apu_document_builder import build_apu_markdown
from app.services.document_date_resolver import resolve_addressee_lines, resolve_document_date
from app.services.structured_economic_price_mapper import apply_structured_price_inputs


def load_economic_payload(
    session_state: Dict[str, Any],
    *,
    session_id: str = "",
    memory: Any = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Recupera datos económicos y construye mapeo_items + resumen (misma lógica que EconomicWriterAgent).

    Returns:
        (economic_data, mapeo_items, resumen) — economic_data None si no hay partidas.
    """
    economic_data: Optional[Dict[str, Any]] = None

    for task in reversed(session_state.get("tasks_completed") or []):
        if task.get("task") == "economic_proposal":
            result_data = task.get("result") or {}
            economic_data = result_data.get("data", result_data)
            break

    if not economic_data:
        mps = session_state.get("master_proposal_state")
        if isinstance(mps, dict) and mps:
            economic_data = mps

    if not economic_data:
        return None, [], {}

    items = economic_data.get("items") if isinstance(economic_data.get("items"), list) else []
    if not items:
        user_inputs = session_state.get("economic_user_inputs") or {}
        concept_prices: Dict[str, Any] = {}
        if isinstance(user_inputs, dict):
            cp = user_inputs.get("concept_prices")
            if isinstance(cp, dict):
                concept_prices = cp
        line_items: List[Dict[str, Any]] = []
        if memory and session_id and concept_prices:
            try:
                line_items = memory.get_line_items_for_session(session_id)
            except Exception:
                line_items = []
        if line_items and concept_prices:
            line_items = apply_structured_price_inputs(line_items, concept_prices)
        if line_items:
            boot: List[Dict[str, Any]] = []
            for idx, li in enumerate(line_items[:300]):
                if not isinstance(li, dict):
                    continue
                boot.append(
                    {
                        "partida": idx + 1,
                        "concepto": li.get("description")
                        or li.get("concepto")
                        or li.get("descripcion")
                        or "Partida",
                        "cantidad": float(li.get("quantity") or li.get("cantidad") or 1),
                        "precio_unitario": float(
                            li.get("unit_price") or li.get("precio_unitario") or 0
                        ),
                    }
                )
            if boot:
                economic_data = {**economic_data, "items": boot}
                items = boot

    if not items:
        return economic_data, [], {}

    mapeo_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        cantidad = float(item.get("cantidad", 1))
        precio = float(item.get("precio_unitario", 0.0))
        importe = item.get("subtotal", cantidad * precio)
        mapeo_items.append(
            {
                "partida": item.get("partida", idx + 1),
                "descripcion": item.get("concepto", item.get("descripcion", "")),
                "unidad": item.get("unidad", "Servicio"),
                "cantidad": cantidad,
                "precio_unitario": precio,
                "importe": importe,
            }
        )

    calc_subtotal = sum(float(i["importe"]) for i in mapeo_items)
    subtotal = round(float(economic_data.get("total_base") or calc_subtotal), 2)
    total = round(float(economic_data.get("grand_total") or (subtotal * 1.16)), 2)
    iva = round(total - subtotal, 2)

    validation_result = (
        economic_data.get("validation_result")
        if isinstance(economic_data.get("validation_result"), dict)
        else {}
    )
    date_info = resolve_document_date(session_state)
    resumen = {
        "subtotal": subtotal,
        "iva": iva,
        "total": total,
        "moneda": economic_data.get("currency", "MXN"),
        "fecha": date_info.get("fecha_corta") or datetime.now().strftime("%d/%m/%Y"),
        "fecha_es": date_info.get("fecha_es") or "",
        "perfil_usado": str(validation_result.get("perfil_usado") or "generic"),
    }
    return economic_data, mapeo_items, resumen


def build_economic_doc_metadata(
    *,
    session_id: str,
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
    resumen: Dict[str, Any],
    company_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Metadata compartida (logo, pie, licitación) para documentos económicos DOCX."""
    from app.services.administrative_letter_clauses import resolve_document_ciudad
    from app.services.document_date_resolver import resolve_addressee_lines

    dom = str(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
    ).strip()
    logo_path = _resolve_logo_path(session_state, master_profile)
    if not logo_path and company_data:
        logo_info = (company_data.get("docs") or {}).get("LOGOTIPO", {})
        if isinstance(logo_info, dict):
            lp = logo_info.get("path")
            if lp and os.path.exists(str(lp)):
                logo_path = str(lp)

    return {
        "logo_path": logo_path,
        "tender_name": session_id.replace("_", " ").upper(),
        "fecha": resumen.get("fecha_es") or resumen.get("fecha"),
        "fecha_corta": resumen.get("fecha_corta") or resumen.get("fecha"),
        "empresa": master_profile.get("razon_social"),
        "rfc": master_profile.get("rfc"),
        "representante": master_profile.get("representante_legal"),
        "domicilio": dom,
        "ciudad": resolve_document_ciudad(master_profile, dom),
        "footer_text": (
            f"{master_profile.get('razon_social', '')} | RFC: {master_profile.get('rfc', '')} "
            f"| Domicilio: {dom or 'S/D'}"
        ),
        "destinatario": resolve_addressee_lines(session_state),
        "formal_closing": True,
        "materialization_provenance": "deterministic_economic",
    }


def _resolve_logo_path(session_state: Dict[str, Any], master_profile: Dict[str, Any]) -> Optional[str]:
    logo_path = master_profile.get("logo")
    if logo_path and os.path.exists(str(logo_path)):
        return str(logo_path)
    company_data = (session_state.get("initial_data") or {}).get("company_data") or {}
    logo_info = (company_data.get("docs") or {}).get("LOGOTIPO", {})
    if isinstance(logo_info, dict):
        lp = logo_info.get("path")
        if lp and os.path.exists(str(lp)):
            return str(lp)
    return str(logo_path) if logo_path else None


def reapply_economic_documents(
    *,
    session_id: str,
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
    output_dir: str,
    economic_data: Dict[str, Any],
    mapeo_items: List[Dict[str, Any]],
    resumen: Dict[str, Any],
) -> List[str]:
    """
    Regenera APU, Anexo AE y carta compromiso sobre rutas existentes.

    Returns:
        Lista de rutas actualizadas.
    """
    from app.agents.economic_writer import EconomicWriterAgent
    from app.agents.formats import _save_docx

    os.makedirs(output_dir, exist_ok=True)
    dom = str(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
    ).strip()
    doc_meta = build_economic_doc_metadata(
        session_id=session_id,
        session_state=session_state,
        master_profile=master_profile,
        resumen=resumen,
    )
    agent = EconomicWriterAgent.__new__(EconomicWriterAgent)
    billing_spec = agent._resolve_proportional_billing_spec(economic_data, mapeo_items)

    updated: List[str] = []

    apu_path = os.path.join(output_dir, "ANALISIS_PRECIOS_UNITARIOS.docx")
    content = build_apu_markdown(
        razon_social=str(master_profile.get("razon_social") or ""),
        rfc=str(master_profile.get("rfc") or ""),
        representante=str(master_profile.get("representante_legal") or ""),
        domicilio=dom,
        fecha_es=str(resumen.get("fecha_es") or resumen.get("fecha") or ""),
        procedimiento=session_id.replace("_", " "),
        subtotal=float(resumen.get("subtotal") or 0),
        iva=float(resumen.get("iva") or 0),
        total=float(resumen.get("total") or 0),
        line_items=mapeo_items,
        ciudad=str(doc_meta.get("ciudad") or "").split(",")[0].strip(),
    )
    apu_meta = {**doc_meta, "materialization_provenance": "deterministic_economic_reapply"}
    _save_docx("ANÁLISIS DE PRECIOS UNITARIOS", content, apu_path, apu_meta)
    updated.append(apu_path)

    ae_path = os.path.join(output_dir, "ANEXO_AE_PROPUESTA_ECONOMICA.docx")
    agent._generate_anexo_ae(
        ae_path,
        mapeo_items,
        resumen,
        master_profile,
        billing_spec=billing_spec,
        doc_metadata=doc_meta,
    )
    updated.append(ae_path)

    carta_path = os.path.join(output_dir, "CARTA_COMPROMISO_PRECIOS.docx")
    agent._generate_carta_compromiso(carta_path, resumen, master_profile, doc_metadata=doc_meta)
    updated.append(carta_path)

    excel_path = os.path.join(output_dir, "TABLA_PRECIOS_UNITARIOS.xlsx")
    if os.path.isfile(excel_path):
        from app.utils.doc_formatting import stamp_corporate_excel_file

        agent._generate_price_excel(
            excel_path,
            mapeo_items,
            master_profile,
            resumen,
            billing_spec=billing_spec,
            doc_metadata=doc_meta,
        )
        updated.append(excel_path)
    elif doc_meta.get("logo_path"):
        from app.utils.doc_formatting import stamp_corporate_excel_file

        for fn in os.listdir(output_dir):
            if fn.lower().endswith((".xlsx", ".xlsm")):
                xp = os.path.join(output_dir, fn)
                if stamp_corporate_excel_file(xp, doc_meta):
                    updated.append(xp)

    return updated


async def regenerate_all_economic_deliverables(
    memory: Any,
    session_id: str,
) -> Dict[str, Any]:
    """
    Regenera TABLA/AE/APU/carta tras corrección HITL (Ítem B — impacto completo).
    """
    from app.agents.economic_writer import EconomicWriterAgent
    from app.agents.mcp_context import MCPContextManager
    from app.contracts.agent_contracts import AgentInput, AgentStatus

    state = await memory.get_session(session_id) or {}
    mp = state.get("master_profile") or {}
    company_id = str(state.get("company_id") or state.get("selected_company_id") or "")
    if not mp and company_id:
        co = await memory.get_company(company_id)
        if isinstance(co, dict):
            mp = co.get("master_profile") or {}

    economic_data, mapeo_items, resumen = load_economic_payload(
        state, session_id=session_id, memory=memory
    )
    if not mapeo_items:
        return {"updated": [], "error": "sin_partidas"}

    ctx = MCPContextManager(memory)
    agent_in = AgentInput(
        session_id=session_id,
        company_id=company_id or "default",
        company_data={
            "master_profile": mp,
            "economic_data": economic_data or state.get("master_proposal_state"),
        },
    )
    writer = EconomicWriterAgent(ctx)
    res = await writer.process(agent_in)
    paths = []
    if res.status == AgentStatus.SUCCESS:
        for d in (res.data or {}).get("documentos") or []:
            if isinstance(d, dict) and d.get("ruta"):
                paths.append(str(d["ruta"]))
    return {"updated": paths, "status": str(res.status), "message": res.message}
