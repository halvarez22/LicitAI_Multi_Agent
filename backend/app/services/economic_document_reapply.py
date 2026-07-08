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
    calc = economic_data.get("calculator_result") or {}
    directos = float(
        economic_data.get("costos_directos")
        or calc.get("costos_directos")
        or calc_subtotal
        or 0.0
    )
    indirectos = economic_data.get("costos_indirectos")
    if indirectos is None:
        indirectos = calc.get("costos_indirectos")
    utilidad = economic_data.get("utilidad")
    if utilidad is None:
        utilidad = calc.get("utilidad")
    subtotal_antes_iva = economic_data.get("subtotal_antes_iva")
    if subtotal_antes_iva is None:
        subtotal_antes_iva = calc.get("subtotal_antes_iva")
    iva_amount = economic_data.get("iva_amount")
    if iva_amount is None:
        iva_amount = calc.get("iva_amount")
    ind_rate = economic_data.get("indirectos_rate")
    if ind_rate is None:
        ind_rate = calc.get("indirectos_rate")
    util_rate = economic_data.get("utilidad_rate")
    if util_rate is None:
        util_rate = calc.get("utilidad_rate")

    validation_result = (
        economic_data.get("validation_result")
        if isinstance(economic_data.get("validation_result"), dict)
        else {}
    )
    date_info = resolve_document_date(session_state)
    perfil = str(validation_result.get("perfil_usado") or calc.get("profile_name") or "generic")

    if indirectos is not None and utilidad is not None:
        subtotal = round(float(subtotal_antes_iva or economic_data.get("total_base") or 0.0), 2)
        total = round(float(economic_data.get("grand_total") or 0.0), 2)
        iva = round(
            float(iva_amount if iva_amount is not None else total - subtotal),
            2,
        )
        resumen = {
            "costos_directos": round(directos, 2),
            "costos_indirectos": round(float(indirectos), 2),
            "utilidad": round(float(utilidad), 2),
            "indirectos_rate": float(ind_rate or 0.10),
            "utilidad_rate": float(util_rate or 0.05),
            "subtotal": subtotal,
            "iva": iva,
            "total": total,
            "obra_breakdown": True,
            "moneda": economic_data.get("currency", "MXN"),
            "fecha": date_info.get("fecha_corta") or datetime.now().strftime("%d/%m/%Y"),
            "fecha_es": date_info.get("fecha_es") or "",
            "perfil_usado": perfil,
        }
    else:
        subtotal = round(float(economic_data.get("total_base") or calc_subtotal), 2)
        total = round(float(economic_data.get("grand_total") or (subtotal * 1.16)), 2)
        iva = round(total - subtotal, 2)
        resumen = {
            "subtotal": subtotal,
            "iva": iva,
            "total": total,
            "obra_breakdown": False,
            "moneda": economic_data.get("currency", "MXN"),
            "fecha": date_info.get("fecha_corta") or datetime.now().strftime("%d/%m/%Y"),
            "fecha_es": date_info.get("fecha_es") or "",
            "perfil_usado": perfil,
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
    from app.services.administrative_letter_clauses import (
        resolve_document_ciudad,
        resolve_letter_session_metadata,
    )

    dom = str(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
    ).strip()
    letter_meta = resolve_letter_session_metadata(session_state)
    logo_path = _resolve_logo_path(session_state, master_profile)
    if not logo_path and company_data:
        logo_info = (company_data.get("docs") or {}).get("LOGOTIPO", {})
        if isinstance(logo_info, dict):
            lp = logo_info.get("path")
            if lp and os.path.exists(str(lp)):
                logo_path = str(lp)

    from app.services.document_date_resolver import (
        resolve_document_date,
        resolve_generation_header_date,
    )

    date_info = resolve_document_date(session_state)
    gen_info = resolve_generation_header_date()
    fecha_doc = (
        resumen.get("fecha_es")
        or date_info.get("fecha_es")
        or resumen.get("fecha")
        or ""
    )

    return {
        "logo_path": logo_path,
        "tender_name": session_id.replace("_", " ").upper(),
        "fecha": fecha_doc,
        "fecha_documental": fecha_doc,
        "fecha_encabezado": gen_info.get("fecha_es") or "",
        "fecha_generacion": gen_info.get("fecha_es") or "",
        "fecha_corta": resumen.get("fecha_corta") or date_info.get("fecha_corta") or "",
        "fecha_documental_source": date_info.get("source", ""),
        "fecha_encabezado_source": gen_info.get("source", "generation_timestamp"),
        "generated_at_iso": gen_info.get("generated_at_iso", ""),
        "empresa": master_profile.get("razon_social"),
        "rfc": master_profile.get("rfc"),
        "representante": master_profile.get("representante_legal"),
        "domicilio": dom,
        "ciudad": resolve_document_ciudad(
            master_profile, dom, letter_meta=letter_meta
        ),
        "concurso_label": letter_meta.get("concurso_label", ""),
        "convocante": letter_meta.get("convocante", ""),
        "footer_text": (
            f"{master_profile.get('razon_social', '')} | RFC: {master_profile.get('rfc', '')} "
            f"| Domicilio: {dom or 'S/D'}"
        ),
        "destinatario": letter_meta.get("destinatario")
        or resolve_addressee_lines(session_state),
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
    if resumen.get("obra_breakdown"):
        from app.services.obra_economic_annex_clauses import build_obra_e3_annex_markdown

        snippet = str(
            session_state.get("_obra_e3_snippet")
            or session_state.get("bases_corpus_hint")
            or ""
        )[:120000]
        tabla_name = ""
        for fn in os.listdir(output_dir):
            if fn.lower().endswith((".xlsx", ".xlsm")):
                tabla_name = fn
                break
        content = build_obra_e3_annex_markdown(
            concurso=str(
                doc_meta.get("concurso_label")
                or session_id.replace("_", " ").upper()
            ),
            mapeo_items=mapeo_items,
            req_snippet=snippet,
            tabla_precios_basename=tabla_name,
        )
        apu_meta = {
            **doc_meta,
            "obra_pliego_contract": True,
            "document_title": "Análisis de Precios Unitarios",
            "materialization_provenance": "deterministic_obra_e3_reapply",
        }
    else:
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
        apu_meta = {
            **doc_meta,
            "materialization_provenance": "deterministic_economic_reapply",
        }
    _save_docx("ANÁLISIS DE PRECIOS UNITARIOS", content, apu_path, apu_meta)
    updated.append(apu_path)

    ae_path = os.path.join(output_dir, "ANEXO_AE_PROPUESTA_ECONOMICA.docx")
    if resumen.get("obra_breakdown"):
        from app.services.obra_economic_annex_clauses import build_obra_e2_catalog_markdown

        ae_body = build_obra_e2_catalog_markdown(
            concurso=str(
                doc_meta.get("concurso_label")
                or session_id.replace("_", " ").upper()
            ),
            mapeo_items=mapeo_items,
            resumen=resumen,
            req_snippet=str(
                session_state.get("_obra_e2_snippet")
                or session_state.get("bases_corpus_hint")
                or ""
            ),
        )
        ae_meta = {
            **doc_meta,
            "obra_pliego_contract": True,
            "document_title": "Catálogo de conceptos y precios unitarios",
            "materialization_provenance": "deterministic_obra_e2_reapply",
        }
        _save_docx(
            "ANEXO E-2 — CATÁLOGO DE CONCEPTOS",
            ae_body,
            ae_path,
            ae_meta,
        )
    else:
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


def _find_sobre_economic_path(session_id: str, dedupe_key: str) -> Optional[str]:
    """Ruta en SOBRE_3_ECONOMICO que corresponde a una clave obra|E."""
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    sobre = os.path.join("/data/outputs", session_id, "SOBRE_3_ECONOMICO")
    if not os.path.isdir(sobre):
        return None
    for fn in sorted(os.listdir(sobre)):
        if fn.startswith("00_CARATULA"):
            continue
        if pliego_format_dedupe_key(fn) == dedupe_key:
            return os.path.join(sobre, fn)
    return None


def reapply_obra_economic_annexes(
    *,
    session_id: str,
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
    memory: Any = None,
    gap_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Reaplica E-1/E-2/E-3/E-4/E-5 de obra con cláusulas HRU y sincroniza al sobre económico.

    Returns:
        Resumen con rutas actualizadas en propuesta económica y sobre.
    """
    import shutil

    economic_data, mapeo_items, resumen = load_economic_payload(
        session_state, session_id=session_id, memory=memory
    )
    if not mapeo_items:
        return {"updated": [], "error": "sin_partidas"}

    session_state = dict(session_state)
    if session_id:
        from app.services.official_format_resolver import enrich_obra_official_corpus

        enrich_obra_official_corpus(session_id, session_state)
    for row in (gap_report or {}).get("rows") or []:
        key = str(row.get("dedupe_key") or "")
        snip = str(row.get("snippet") or "")
        if key == "obra|E1" and snip:
            session_state["_obra_e1_snippet"] = snip
        if key == "obra|E2" and snip:
            session_state["_obra_e2_snippet"] = snip
        if key == "obra|E3" and snip:
            session_state["_obra_e3_snippet"] = snip
        if key == "obra|E3E" and snip:
            session_state["_obra_e3e_snippet"] = snip
        if key == "obra|E4" and snip:
            session_state["_obra_e4_snippet"] = snip
        if key == "obra|E5" and snip:
            session_state["_obra_e5_snippet"] = snip

    snippet_by_key: Dict[str, str] = {}
    for row in (gap_report or {}).get("rows") or []:
        key = str(row.get("dedupe_key") or "")
        if key:
            snippet_by_key[key] = str(row.get("snippet") or "")

    econ_dir = os.path.join("/data/outputs", session_id, "2.propuesta_economica")
    os.makedirs(econ_dir, exist_ok=True)

    if resumen.get("obra_breakdown"):
        from app.services.official_format_resolver import materialize_obra_economic_envelope

        tabla_name = ""
        xp = os.path.join(econ_dir, "TABLA_PRECIOS_UNITARIOS.xlsx")
        if os.path.isfile(xp):
            tabla_name = os.path.basename(xp)
        obra_docs = materialize_obra_economic_envelope(
            session_id=session_id,
            session_state=session_state,
            master_profile=master_profile,
            output_dir=econ_dir,
            economic_data=economic_data,
            mapeo_items=mapeo_items,
            resumen=resumen,
            snippets_by_key=snippet_by_key,
            tabla_precios_basename=tabla_name,
        )
        updated = [str(d.get("ruta")) for d in obra_docs if d.get("ruta")]
    else:
        updated = reapply_economic_documents(
            session_id=session_id,
            session_state=session_state,
            master_profile=master_profile,
            output_dir=econ_dir,
            economic_data=economic_data or {},
            mapeo_items=mapeo_items,
            resumen=resumen,
        )

    doc_meta = build_economic_doc_metadata(
        session_id=session_id,
        session_state=session_state,
        master_profile=master_profile,
        resumen=resumen,
    )

    # Sincronizar propuesta económica → sobre (por huella de nombre; evita colisión obra|E2)
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    _SRC_TO_SOBRE_TOKENS = (
        ("ANEXO_AE_PROPUESTA_ECONOMICA", ("ANEXO_AE", "PROPUESTA_ECONOMICA")),
        ("ANALISIS_PRECIOS_UNITARIOS", ("ANALISIS_PRECIOS",)),
        ("CARTA_COMPROMISO_PROPOSICION", ("COMPROMISO", "PROPOSIC")),
        ("CARTA_COMPROMISO_PRECIOS", ("CARTA_COMPROMISO", "PRECIOS")),
        ("Anexo_E-5_Cotizaciones_Materiales", ("E-5", "MATERIAL")),
        ("Anexo_E-3E_Utilidad_Propuesta", ("E-3E", "UTILIDAD")),
        ("TABLA_PRECIOS_UNITARIOS", ("TABLA_PRECIOS",)),
    )

    def _match_sobre_dest(src_base: str) -> Optional[str]:
        sobre_dir = os.path.join("/data/outputs", session_id, "SOBRE_3_ECONOMICO")
        if not os.path.isdir(sobre_dir):
            return None
        src_up = src_base.upper().replace(".DOCX", "").replace(".XLSX", "")
        for src_key, tokens in _SRC_TO_SOBRE_TOKENS:
            if src_key in src_up:
                for fn in sorted(os.listdir(sobre_dir)):
                    if fn.startswith("00_CARATULA"):
                        continue
                    fn_up = fn.upper()
                    if all(tok in fn_up for tok in tokens):
                        return os.path.join(sobre_dir, fn)
        key = pliego_format_dedupe_key(src_base)
        if key:
            return _find_sobre_economic_path(session_id, key)
        return None

    sobre_synced: List[str] = []

    def _sync_to_sobre(src: str, dedupe_key: str) -> None:
        dest = _find_sobre_economic_path(session_id, dedupe_key)
        if not dest or not os.path.isfile(src):
            return
        if os.path.abspath(src) == os.path.abspath(dest):
            return
        shutil.copy2(src, dest)
        if dest not in sobre_synced:
            sobre_synced.append(dest)

    for path in updated:
        src_base = os.path.basename(path)
        src_up = src_base.upper()
        if "ANEXO_AE_PROPUESTA_ECONOMICA" in src_up:
            _sync_to_sobre(path, "obra|E2")
        if "CARTA_COMPROMISO_PROPOSICION" in src_up:
            _sync_to_sobre(path, "obra|E1")
        if "ANALISIS_PRECIOS_UNITARIOS" in src_up:
            _sync_to_sobre(path, "obra|E3")
        if "Anexo_E-3E" in src_base or "UTILIDAD_PROPUESTA" in src_up:
            _sync_to_sobre(path, "obra|E3E")
        if "Anexo_E-5" in src_base or "COTIZACIONES_MATERIALES" in src_up:
            _sync_to_sobre(path, "obra|E5")
        if "Anexo_E-4" in src_base or "PROGRAMAS_OBRA" in src_up:
            _sync_to_sobre(path, "obra|E4")

    for path in updated:
        src_base = os.path.basename(path)
        src_up = src_base.upper()
        if "CARTA_COMPROMISO_PRECIOS" in src_up:
            continue
        dest = _match_sobre_dest(src_base)
        if not dest or os.path.abspath(path) == os.path.abspath(dest):
            continue
        shutil.copy2(path, dest)
        sobre_synced.append(dest)

    return {
        "updated": updated,
        "sobre_synced": sobre_synced,
        "resumen_total": resumen.get("total"),
        "obra_breakdown": bool(resumen.get("obra_breakdown")),
    }


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
