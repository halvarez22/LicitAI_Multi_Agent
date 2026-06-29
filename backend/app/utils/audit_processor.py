from typing import Any, Dict, List, Optional
from datetime import datetime
import json

TABULAR_ALERT_ITEM_ID = "base-tabular-alert"
TABULAR_ALERT_CATEGORY = "bases_datos_tabulares"


def resolve_line_items_count(
    line_items_count: Optional[int],
    datos_tab: Optional[Dict[str, Any]],
) -> int:
    """Cuenta efectiva de partidas: parámetro vivo o snapshot del análisis."""
    if line_items_count is not None:
        try:
            return max(0, int(line_items_count))
        except (TypeError, ValueError):
            pass
    if isinstance(datos_tab, dict):
        try:
            return max(0, int(datos_tab.get("line_items_count") or 0))
        except (TypeError, ValueError):
            pass
    return 0


def should_show_tabular_missing_alert(
    datos_tab: Optional[Dict[str, Any]],
    line_items_count: Optional[int] = None,
) -> bool:
    """
    Muestra la alerta de partidas solo si sigue faltando ingesta (0 filas).
    Con partidas en BD, se omite aunque el snapshot del análisis conserve alerta_faltante.
    """
    if not isinstance(datos_tab, dict) or not datos_tab.get("alerta_faltante"):
        return False
    return resolve_line_items_count(line_items_count, datos_tab) <= 0


def strip_stale_tabular_alert_from_dictamen(
    dictamen: Dict[str, Any],
    line_items_count: int,
) -> Dict[str, Any]:
    """Quita del dictamen persistido la alerta obsoleta si ya hay session_line_items."""
    if not isinstance(dictamen, dict) or line_items_count <= 0:
        return dictamen
    causales = dictamen.get("causales")
    if not isinstance(causales, list):
        return dictamen
    filtered = [
        h
        for h in causales
        if isinstance(h, dict)
        and h.get("id") != TABULAR_ALERT_ITEM_ID
        and h.get("category") != TABULAR_ALERT_CATEGORY
    ]
    if len(filtered) == len(causales):
        return dictamen
    out = {**dictamen, "causales": filtered}
    out["totalRequisitos"] = len(filtered)
    out["riesgos"] = sum(1 for h in filtered if h.get("isRisk"))
    return out


def _rag_in_text(s: Optional[str]) -> bool:
    t = (s or "").lower()
    return "rag" in t and ("vacío" in t or "vacio" in t or "empty" in t)


def detect_rag_infrastructure_issue(
    zones: Any, status_raw: str, error_text: Optional[str]
) -> bool:
    """True si el fallo se debe a índice RAG vacío (infra), no a hallazgo de incumplimiento."""
    if status_raw not in ("fail", "error"):
        return False
    if _rag_in_text(error_text or ""):
        return True
    if not isinstance(zones, list) or len(zones) == 0:
        return False
    for z in zones:
        if not isinstance(z, dict):
            return False
        st = str(z.get("status") or "").lower()
        if st == "pass" or not st:
            return False
        if not _rag_in_text(str(z.get("reason") or "")):
            return False
    return True


def apply_infrastructure_ux_overrides(d: Dict[str, Any]) -> Dict[str, Any]:
    """Alineado con applyInfrastructureUxOverrides del frontend (auditSummary.js)."""
    if not d:
        return d
    rag = detect_rag_infrastructure_issue(
        d.get("zones"), str(d.get("statusRaw") or ""), d.get("errorText")
    )
    if not rag:
        if "uxKind" not in d:
            d = {**d, "uxKind": "normal"}
        return d
    return {
        **d,
        "status": "⚠️ Índice de búsqueda no disponible",
        "statusColor": "#38bdf8",
        "uxKind": "rag_index_missing",
        "uxGuiaUsuario": (
            "Tus datos de expediente y el último dictamen siguen guardados en el servidor. "
            "Aquí falló la consulta al índice vectorial (Chroma): no hay fragmentos útiles para "
            "esta sesión o se vació tras un reinicio. No es un “borrón” de la base de datos. "
            "Sube o reprocesa los PDF y pulsa «Analizar bases» solo para reindexar y volver a auditar."
        ),
    }

def hallazgo_fingerprint_texto(txt_val: Any) -> str:
    """
    Paridad con hallazgoFingerprintContent (auditSummary.js): prioriza descripción/requisito sobre snippet
    para fusionar duplicados del map-reduce.
    """
    if txt_val is None:
        return ""
    if isinstance(txt_val, dict):
        raw = (
            txt_val.get("descripcion")
            or txt_val.get("requisito")
            or txt_val.get("detalle")
            or txt_val.get("nombre")
            or txt_val.get("texto_crudo")
            or txt_val.get("snippet")
            or txt_val.get("extracto")
            or txt_val.get("evidencia")
            or txt_val.get("literal")
            or ""
        )
        s = str(raw) if raw else json.dumps(txt_val, sort_keys=True)
    else:
        s = str(txt_val)
    s = " ".join(s.strip().lower().split())
    return s[:1000]


def map_compliance_hallazgo(raw: Any, tipo_label: str, list_key: str) -> Dict[str, Any]:
    """Réplica en Python de mapComplianceHallazgo de auditSummary.js."""
    if not isinstance(raw, dict):
        raw = {"texto_crudo": str(raw)}
        
    zo = raw.get("zona_origen")
    if zo and isinstance(zo, str):
        zo = zo.strip()
    else:
        zo = None
        
    fallback_zones = {
        "administrativo": "ADMINISTRATIVO/LEGAL",
        "tecnico": "TÉCNICO/OPERATIVO",
        "formatos": "FORMATOS/ANEXOS",
    }
    effective_zona = zo or fallback_zones.get(list_key, "ADMINISTRATIVO/LEGAL")
    cat_raw = raw.get("categoria") or list_key
    
    return {
        "tipo": tipo_label,
        "texto": raw,
        "category": "compliance",
        "snippet": raw.get("snippet"),
        "page": raw.get("page"),
        "id": raw.get("id"),
        "agent_id": "compliance_001",
        "zona_origen": effective_zona,
        "categoria_llm": cat_raw,
        "bucketKey": list_key, # Alineado con frontend (camelCase)
        "zona_explicita": zo is not None,
        "categoria_difiere_bucket": str(cat_raw).lower() != str(list_key).lower(),
        "audience": raw.get("audience"),
        "tipo_accion": raw.get("tipo_accion"),
    }

def build_compliance_por_zona(hallazgos: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Réplica de buildCompliancePorZona de JS."""
    tab_order = [
        'ADMINISTRATIVO/LEGAL',
        'TÉCNICO/OPERATIVO',
        'FORMATOS/ANEXOS',
        'GARANTÍAS/SEGUROS',
    ]
    out = {z: [] for z in tab_order}
    out["_OTRAS_ZONAS"] = []
    
    for h in hallazgos:
        zona = h.get("zona_origen")
        if zona in out:
            out[zona].append(h)
        else:
            out["_OTRAS_ZONAS"].append(h)
    return out

def process_audit_results_backend(
    results_data: Dict[str, Any],
    pipeline_telemetry: Optional[Dict[str, Any]] = None,
    line_items_count: Optional[int] = None,
    session_state: Optional[Dict[str, Any]] = None,
    extraction_health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Réplica en Python de processAuditResults de auditSummary.js.
    Corregido para evitar AttributeErrors y asegurar paridad 1:1 con el Frontend.

    Args:
        results_data: Payload analysis/compliance/economic (mismo contrato que el frontend).
        pipeline_telemetry: Telemetría del orquestador (`build_pipeline_telemetry`); se guarda en el dictamen.
        line_items_count: Filas actuales en session_line_items; si > 0, no se incluye alerta tabular obsoleta.
    """
    if not results_data:
        return None
        
    def safe_get_data(obj):
        if not obj: return {}
        if isinstance(obj, dict): return obj.get("data") or obj
        return getattr(obj, "data", {}) if hasattr(obj, "data") else {}

    analysis = results_data.get("analysis", {})
    compliance = results_data.get("compliance", {})
    economic = results_data.get("economic", {})
    
    comp_data = safe_get_data(compliance)
    
    compliance_hallazgos = []
    for it in comp_data.get("administrativo", []):
        compliance_hallazgos.append(map_compliance_hallazgo(it, "📁 ADMINISTRATIVO", "administrativo"))
    for it in comp_data.get("tecnico", []):
        compliance_hallazgos.append(map_compliance_hallazgo(it, "🛠️ TÉCNICO", "tecnico"))
    for it in comp_data.get("formatos", []):
        compliance_hallazgos.append(map_compliance_hallazgo(it, "📄 FORMATO / ANEXO", "formatos"))
        
    # --- LISTADO UNIFICADO ---
    raw_list = []
    
    # 1. Bases (Acceso seguro corregido)
    analysis_data = safe_get_data(analysis)
    req_part = analysis_data.get("requisitos_participacion") or []
    for i, it in enumerate(req_part):
        if isinstance(it, dict):
            inc = (it.get("inciso") or "").strip()
            txt = (it.get("texto_literal") or "").strip()
            label = f"{inc}) {txt}".strip(") ").strip() if inc else txt
        else:
            label = str(it)
        if not label:
            continue
        raw_list.append({
            "tipo": "📋 REQUISITO PARA PARTICIPAR",
            "texto": label,
            "category": "bases_participacion",
            "id": f"base-part-{i}",
            "agent_id": "analyst_001",
            "zona_origen": None,
            "categoria_llm": None,
        })
    req_filtro = analysis_data.get("requisitos_filtro", [])
    for i, r in enumerate(req_filtro):
        raw_list.append({
            "tipo": "⚖️ FILTRO / DESCALIFICACIÓN (BASES)",
            "texto": r,
            "category": "bases_filtro",
            "id": f"base-filtro-{i}",
            "agent_id": "analyst_001",
            "zona_origen": None,
            "categoria_llm": None
        })

    reglas_ec = analysis_data.get("reglas_economicas") or {}
    reglas_evidence = analysis_data.get("reglas_economicas_evidence_v1") or {}
    ev_items = (
        reglas_evidence.get("items")
        if isinstance(reglas_evidence, dict)
        else {}
    ) or {}
    if isinstance(reglas_ec, dict):
        ri = 0
        for rk, rv in reglas_ec.items():
            if not isinstance(rv, str) or not rv.strip() or rv.strip() == "No especificado":
                continue
            ev_item = ev_items.get(rk) if isinstance(ev_items, dict) else None
            ev_v1 = ev_item.get("evidence_v1") if isinstance(ev_item, dict) else None
            raw_list.append({
                "tipo": "💶 REGLA ECONÓMICA (BASES)",
                "texto": f"{rk}: {rv}",
                "category": "bases_reglas_economicas",
                "id": f"base-regla-{ri}",
                "page": ev_item.get("page") if isinstance(ev_item, dict) else None,
                "snippet": ev_item.get("snippet") if isinstance(ev_item, dict) else None,
                "source": ev_item.get("source") if isinstance(ev_item, dict) else None,
                "evidence_v1": ev_v1,
                "verification_status": (
                    (ev_v1 or {}).get("evidence_mode") if isinstance(ev_v1, dict) else "inference_only"
                ),
                "promotion_eligible": bool(ev_item.get("promotion_eligible")) if isinstance(ev_item, dict) else False,
                "agent_id": "analyst_001",
                "zona_origen": None,
                "categoria_llm": None,
            })
            ri += 1

    alcance_ops = analysis_data.get("alcance_operativo") or []
    if isinstance(alcance_ops, list):
        for ai, row in enumerate(alcance_ops):
            if not isinstance(row, dict):
                continue
            lit = (row.get("texto_literal_fila") or "").strip()
            if not lit:
                parts = [row.get(k, "") for k in (
                    "ubicacion_o_area", "puesto_funcion_o_servicio", "turno", "cantidad_o_elementos", "dias_aplicables"
                ) if row.get(k)]
                lit = " | ".join(str(p).strip() for p in parts if p)
            if not lit:
                continue
            raw_list.append({
                "tipo": "📊 ALCANCE / DOTACIÓN (BASES)",
                "texto": lit,
                "category": "bases_alcance",
                "id": f"base-alcance-{ai}",
                "agent_id": "analyst_001",
                "zona_origen": None,
                "categoria_llm": None,
            })

    datos_tab = analysis_data.get("datos_tabulares") or {}
    if should_show_tabular_missing_alert(datos_tab, line_items_count):
        raw_list.append({
            "tipo": "⚠️ ALERTA PARTIDAS / ANEXOS",
            "texto": datos_tab["alerta_faltante"],
            "category": TABULAR_ALERT_CATEGORY,
            "id": TABULAR_ALERT_ITEM_ID,
            "agent_id": "analyst_001",
            "zona_origen": None,
            "categoria_llm": None,
        })
        
    raw_list.extend(compliance_hallazgos)
    
    # 3. Risks (Acceso seguro summary)
    comp_summary = {}
    if isinstance(compliance, dict):
        comp_summary = compliance.get("summary") or {}
    elif hasattr(compliance, "summary"):
        comp_summary = compliance.summary or {}
    
    risks = comp_summary.get("causas_desechamiento", [])
    for i, d in enumerate(risks):
        raw_list.append({
            "tipo": "🚫 DESECHAMIENTO",
            "texto": d,
            "isRisk": True,
            "category": "risk",
            "snippet": d.get("snippet") if isinstance(d, dict) else None,
            "page": d.get("page") if isinstance(d, dict) else None,
            "id": d.get("id") if isinstance(d, dict) else f"risk-{i}",
            "agent_id": "compliance_001",
            "zona_origen": None,
            "categoria_llm": None,
        })
        
    econ_data = safe_get_data(economic)
    econ_alerts_raw = econ_data.get("analisis_precios", {}).get("alertas", [])
    try:
        from app.services.economic_alert_classifier import normalize_and_dedupe_economic_alerts

        forensic_econ, excluded_econ = normalize_and_dedupe_economic_alerts(
            econ_alerts_raw if isinstance(econ_alerts_raw, list) else []
        )
        for norm in forensic_econ:
            _ev = None
            try:
                from app.services.economic_risk_evidence_v1 import build_evidence_v1

                _ev = build_evidence_v1(
                    {
                        "page": norm.get("page"),
                        "snippet": norm.get("snippet"),
                        "match_confidence": "media" if norm.get("snippet") else "none",
                        "provenance": "economic_agent",
                    },
                    literal=str(norm.get("texto") or ""),
                )
            except Exception:
                pass
            raw_list.append({
                "tipo": "💰 ALERTA ECONÓMICA",
                "texto": norm.get("texto"),
                "isRisk": True,
                "category": "economic",
                "id": norm.get("id"),
                "page": norm.get("page"),
                "snippet": norm.get("snippet"),
                "alert_subtype": norm.get("alert_subtype"),
                "risk_reason_ux": norm.get("risk_reason_ux"),
                "evidence_v1": _ev,
                "agent_id": "economic_001",
                "zona_origen": None,
                "categoria_llm": None,
            })
        for norm in excluded_econ:
            raw_list.append({
                "tipo": "📋 CONTEXTO ECONÓMICO",
                "texto": norm.get("texto"),
                "isRisk": False,
                "category": "economic_context",
                "id": norm.get("id"),
                "page": norm.get("page"),
                "snippet": norm.get("snippet"),
                "alert_subtype": norm.get("alert_subtype"),
                "risk_reason_ux": norm.get("risk_reason_ux"),
                "agent_id": "economic_001",
                "zona_origen": None,
                "categoria_llm": None,
            })
    except Exception:
        for i, a in enumerate(econ_alerts_raw or []):
            raw_list.append({
                "tipo": "💰 ALERTA ECONÓMICA",
                "texto": a,
                "isRisk": True,
                "category": "economic",
                "id": f"econ-{i}",
                "agent_id": "economic_001",
                "zona_origen": None,
                "categoria_llm": None,
            })

    # Gap económico (waiting_for_data): alertas del marco de bases — no son riesgos HITL por defecto.
    gap_alerts = econ_data.get("alertas_contexto_bases") or []
    if isinstance(gap_alerts, list):
        try:
            from app.services.economic_alert_classifier import normalize_and_dedupe_economic_alerts

            forensic_gap, context_gap = normalize_and_dedupe_economic_alerts(
                [a for a in gap_alerts if a]
            )
            for norm in forensic_gap:
                raw_list.append({
                    "tipo": "📌 PAUSA ECONÓMICA / CONTEXTO DE BASES",
                    "texto": norm.get("texto"),
                    "isRisk": True,
                    "category": "economic_gap_context",
                    "id": norm.get("id"),
                    "page": norm.get("page"),
                    "snippet": norm.get("snippet"),
                    "alert_subtype": norm.get("alert_subtype"),
                    "risk_reason_ux": norm.get("risk_reason_ux"),
                    "agent_id": "economic_001",
                    "zona_origen": None,
                    "categoria_llm": None,
                })
            for norm in context_gap:
                raw_list.append({
                    "tipo": "📋 CONTEXTO ECONÓMICO",
                    "texto": norm.get("texto"),
                    "isRisk": False,
                    "category": "economic_context",
                    "id": norm.get("id"),
                    "alert_subtype": norm.get("alert_subtype"),
                    "risk_reason_ux": norm.get("risk_reason_ux"),
                    "agent_id": "economic_001",
                    "zona_origen": None,
                    "categoria_llm": None,
                })
        except Exception:
            for i, a in enumerate(gap_alerts):
                if not a:
                    continue
                raw_list.append({
                    "tipo": "📌 PAUSA ECONÓMICA / CONTEXTO DE BASES",
                    "texto": a,
                    "isRisk": True,
                    "category": "economic_gap_context",
                    "id": f"econ-gap-{i}",
                    "agent_id": "economic_001",
                    "zona_origen": None,
                    "categoria_llm": None,
                })

    # --- DEDUPLICACIÓN (Fingerprint Map) ---
    seen_map = {} # key -> item_ref
    
    for h in raw_list:
        if not h.get("texto"): continue
        
        txt_val = h.get("texto")
        fp = hallazgo_fingerprint_texto(txt_val)
        h_id = h.get("id")
        cat = h.get("category") or ""

        # Paridad con auditSummary.js: compliance se deduplica por huella de texto (evita duplicados
        # cuando el LLM/map-reduce repite el mismo párrafo con IDs distintos).
        if cat == "compliance":
            dedup_key = f"compliance:{fp}"
        else:
            dedup_key = (
                h_id
                if (h_id and "risk-" not in h_id and "base-" not in h_id and "econ-" not in h_id)
                else f"{cat}:{fp}"
            )

        if dedup_key not in seen_map:
            seen_map[dedup_key] = h
        else:
            prev = seen_map[dedup_key]
            if h.get("isRisk"):
                prev["isRisk"] = True
            if cat == "compliance" and isinstance(prev, dict):
                if not (prev.get("page") is not None and str(prev.get("page", "")).strip()):
                    if h.get("page") is not None and str(h.get("page", "")).strip():
                        prev["page"] = h.get("page")
                if not (prev.get("snippet") is not None and str(prev.get("snippet", "")).strip()):
                    if h.get("snippet") is not None and str(h.get("snippet", "")).strip():
                        prev["snippet"] = h.get("snippet")
                pt, ht = prev.get("texto"), h.get("texto")
                if isinstance(pt, dict) and isinstance(ht, dict):
                    if not pt.get("page") and ht.get("page"):
                        prev["texto"] = {**pt, "page": ht.get("page")}
                        pt = prev["texto"]
                    if not pt.get("snippet") and ht.get("snippet"):
                        prev["texto"] = {**pt, "snippet": ht.get("snippet")}

    # --- MÉTRICAS ---
    listado_hallazgos = list(seen_map.values())
    try:
        from app.services.economic_alert_classifier import sanitize_economic_causales

        listado_hallazgos = sanitize_economic_causales(listado_hallazgos)
    except Exception:
        pass
    comp_only = [h for h in listado_hallazgos if h.get("category") == "compliance"]
    compliance_por_zona = build_compliance_por_zona(comp_only)

    # --- DETERMINACIÓN DE ESTADO (Paridad 1:1 con auditSummary.js) ---
    comp_status = ""
    if isinstance(compliance, dict): comp_status = compliance.get("status") or "success"
    elif hasattr(compliance, "status"): comp_status = compliance.status or "success"
    
    display_status = "✅ COMPLETADO"
    status_color = "#2ecc71"
    
    if comp_status == "error":
        display_status = "❌ ERROR EN AUDITORÍA DE CUMPLIMIENTO"
        status_color = "#e74c3c"
    elif comp_status == "partial":
        display_status = "⚠️ COMPLETADO CON INCIDENCIAS"
        status_color = "#f39c12" # Naranja para paridad total
    elif comp_status == "fail":
        display_status = "❌ FALLO EN AUDITORÍA"
        status_color = "#e74c3c"

    # Zonas con paridad 1:1
    def get_zones():
        # Fallback exacto de auditSummary.js
        z_data = comp_data.get("audit_summary", {}).get("zones")
        if z_data: return z_data
        if isinstance(compliance, dict): return compliance.get("metrics", {}).get("zones", [])
        if hasattr(compliance, "metrics"): return getattr(compliance.metrics, "zones", []) if hasattr(compliance.metrics, "zones") else []
        return []

    base = {
        "status": display_status,
        "statusColor": status_color,
        "statusRaw": comp_status,
        # Paridad con auditSummary.js: errorText = compliance?.error || compliance?.message
        "errorText": (
            (compliance.get("error") or compliance.get("message") or "")
            if isinstance(compliance, dict)
            else (
                (getattr(compliance, "error", None) or getattr(compliance, "message", None) or "")
                if compliance is not None
                else ""
            )
        ),
        "zones": get_zones(),
        "veredicto": comp_summary.get("veredicto", "Auditoría Técnica completada."),
        "riesgos": sum(1 for h in listado_hallazgos if h.get("isRisk")),
        "totalRequisitos": len(listado_hallazgos),
        "causales": listado_hallazgos,
        "compliancePorZona": compliance_por_zona,
        "causalesPorZona": compliance_por_zona,
        "complianceHallazgosCount": len(comp_only),
        "extracted_data": analysis,  # Objeto completo para paridad total
        "fechaAuditoria": datetime.now().strftime("%d/%m/%Y, %H:%M:%S"),
        "dictamen_schema_version": 2,
    }
    if pipeline_telemetry and isinstance(pipeline_telemetry, dict):
        base["pipelineTelemetry"] = pipeline_telemetry
    orch_dec = results_data.get("orchestrator_decision")
    if isinstance(orch_dec, dict) and orch_dec.get("waiting_hints"):
        base["economicWaitingHints"] = orch_dec["waiting_hints"]
    def _filter_ccc_payload(raw: Any) -> Any:
        if not isinstance(raw, dict) or raw.get("sobre_1_tecnico") is None:
            return raw
        from app.services.document_deliverable_filter import (
            filter_consolidated_document_candidates,
        )

        return filter_consolidated_document_candidates(raw)

    ccc = results_data.get("document_candidates_consolidated")
    if ccc:
        base["documentCandidatesConsolidated"] = _filter_ccc_payload(ccc)
    ft = results_data.get("fast_track_document_candidates")
    if ft:
        if isinstance(ft, dict) and ft.get("sobre_1_tecnico") is not None:
            base["fastTrackDocumentCandidates"] = _filter_ccc_payload(ft)
        else:
            base["fastTrackDocumentCandidates"] = ft

    base = apply_infrastructure_ux_overrides(base)

    try:
        from app.config.settings import settings
        from app.services.dictamen_curation_service import (
            apply_curation_to_dictamen,
            build_forensic_audit_health,
        )

        if settings.DICTAMEN_CURATION_ENABLED:
            forensic = build_forensic_audit_health(compliance)
            base["forensicAuditHealth"] = forensic
            if extraction_health:
                base["extractionHealth"] = extraction_health
            base = apply_curation_to_dictamen(
                base,
                session_state=session_state,
                extraction_health=extraction_health,
                compliance=compliance,
                view_mode=str(settings.DICTAMEN_VIEW_MODE or "licitante"),
                curation_enabled=True,
            )
    except Exception:
        pass

    try:
        from app.services.forensic_risk_service import attach_forensic_risks_to_dictamen

        base = attach_forensic_risks_to_dictamen(base)
    except Exception:
        pass

    return base