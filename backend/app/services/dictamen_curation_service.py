"""
Curación HRU del Dictamen Forense: vista accionable del licitante vs archivo completo.

Sin hardcode por licitación: política versionada + convocante de sesión + audience/tipo_accion.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.dictamen_curation_policy import (
    actionable_non_compliance_categories,
    actionable_tipo_accion_values,
    load_dictamen_curation_policy,
    matches_any_pattern,
    policy_version,
)
from app.services.document_deliverable_filter import (
    is_procedural_noise_not_deliverable,
    should_show_deliverable_in_ui,
)

CURATION_REASON_INFORMATIVO = "informativo"
CURATION_REASON_CONVOCANTE = "convocante_narrative"
CURATION_REASON_PROCEDURAL = "procedural_noise"
CURATION_REASON_NOT_ACTIONABLE = "not_actionable_tipo"
CURATION_REASON_NEUTRAL = "neutral_context"


def _hallazgo_text_blob(h: Dict[str, Any]) -> str:
    parts: List[str] = []
    texto = h.get("texto")
    if isinstance(texto, dict):
        for key in ("descripcion", "nombre", "requisito", "snippet", "texto_crudo"):
            val = texto.get(key)
            if val:
                parts.append(str(val))
    elif texto:
        parts.append(str(texto))
    if h.get("snippet"):
        parts.append(str(h.get("snippet")))
    return " ".join(parts).strip()


def _item_tipo_accion(h: Dict[str, Any]) -> str:
    texto = h.get("texto")
    if isinstance(texto, dict):
        return str(texto.get("tipo_accion") or "").strip().lower()
    return ""


def _item_audience(h: Dict[str, Any]) -> str:
    texto = h.get("texto")
    if isinstance(texto, dict):
        return str(texto.get("audience") or "").strip().lower()
    return str(h.get("audience") or "").strip().lower()


def _convocante_session_tokens(session_convocante: Optional[Dict[str, str]]) -> List[str]:
    """Tokens del convocante resuelto en sesión (no nombres fijos de municipio)."""
    if not session_convocante:
        return []
    tokens: List[str] = []
    for key in (
        "convocante",
        "autoridad_convocante",
        "dependencia",
        "entidad",
        "comite",
        "destinatario",
    ):
        raw = str(session_convocante.get(key) or "").strip()
        if not raw:
            continue
        for chunk in re.split(r"[\n,;—\-]+", raw):
            c = chunk.strip()
            if len(c) >= 8:
                tokens.append(c.lower())
    # Deduplicar preservando orden
    seen: set[str] = set()
    out: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _matches_session_convocante(blob: str, session_convocante: Optional[Dict[str, str]]) -> bool:
    """True si el texto describe principalmente al convocante de ESTA sesión."""
    text = blob.lower()
    if not text.strip():
        return False
    tokens = _convocante_session_tokens(session_convocante)
    if tokens:
        hits = sum(1 for t in tokens if t in text)
        if hits >= 1 and not matches_any_pattern(blob, "mixed_obligation_licitante_override_patterns"):
            # Si menciona fragmento largo del convocante sin obligación licitante
            if hits >= 2 or any(len(t) > 20 and t in text for t in tokens):
                return True
    # Patrones universales de sujeto convocante (política versionada)
    if matches_any_pattern(blob, "convocante_subject_patterns"):
        if matches_any_pattern(blob, "mixed_obligation_licitante_override_patterns"):
            return False
        if matches_any_pattern(blob, "licitante_subject_patterns"):
            return False
        return True
    return False


def classify_item_audience(
    h: Dict[str, Any],
    session_convocante: Optional[Dict[str, str]] = None,
) -> str:
    """
    licitante | convocante | neutral
    Prioridad: campo audience > señales gramaticales > convocante de sesión.
    """
    aud = _item_audience(h)
    if aud in ("licitante", "convocante", "neutral"):
        return aud

    blob = _hallazgo_text_blob(h)
    if matches_any_pattern(blob, "licitante_subject_patterns"):
        return "licitante"
    if _matches_session_convocante(blob, session_convocante):
        return "convocante"
    if matches_any_pattern(blob, "convocante_subject_patterns"):
        return "convocante"
    return "neutral"


def resolve_curation_reason(
    h: Dict[str, Any],
    session_convocante: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    None → incluir en vista accionable default.
    str → código de archivo (CURATION_REASON_*).
    """
    cat = str(h.get("category") or "").lower()
    if h.get("isRisk"):
        return None

    if cat in actionable_non_compliance_categories():
        return None

    if cat != "compliance":
        return CURATION_REASON_NEUTRAL

    blob = _hallazgo_text_blob(h)
    nombre = ""
    texto = h.get("texto")
    if isinstance(texto, dict):
        nombre = str(texto.get("nombre") or texto.get("descripcion") or "")
    desc = nombre
    snippet = str(h.get("snippet") or (texto.get("snippet") if isinstance(texto, dict) else "") or "")

    tipo = _item_tipo_accion(h)
    audience = classify_item_audience(h, session_convocante)

    if tipo == "informativo":
        return CURATION_REASON_INFORMATIVO

    if audience == "convocante":
        return CURATION_REASON_CONVOCANTE

    if is_procedural_noise_not_deliverable(nombre, desc, snippet):
        if tipo in actionable_tipo_accion_values():
            return None
        return CURATION_REASON_PROCEDURAL

    if tipo in actionable_tipo_accion_values():
        return None

    # generar/presentar sin señal licitante pero entregable reconocible
    if should_show_deliverable_in_ui(nombre, desc, snippet, tipo):
        return None

    if audience == "licitante":
        return None

    return CURATION_REASON_NOT_ACTIONABLE


def build_forensic_audit_health(compliance: Any) -> Dict[str, Any]:
    """Deriva salud capa 2 desde compliance sin tocar ingesta."""
    comp_status = ""
    comp_data: Dict[str, Any] = {}
    if isinstance(compliance, dict):
        comp_status = str(compliance.get("status") or "success").lower()
        comp_data = compliance.get("data") or {}
    zones: List[Dict[str, Any]] = []
    if isinstance(comp_data, dict):
        summ = comp_data.get("audit_summary") or {}
        if isinstance(summ, dict):
            zones = list(summ.get("zones") or [])
    if not zones and isinstance(compliance, dict):
        zones = list((compliance.get("metrics") or {}).get("zones") or [])

    zones_failed = [str(z.get("zone")) for z in zones if str(z.get("status")).lower() == "fail"]
    zones_partial = [str(z.get("zone")) for z in zones if str(z.get("status")).lower() == "partial"]
    empty_blocks = 0
    for z in zones:
        metrics = z.get("metrics") if isinstance(z.get("metrics"), dict) else {}
        empty_blocks += int(metrics.get("blocks_empty_response_count") or 0)

    gmp = None
    if isinstance(comp_data, dict):
        summ = comp_data.get("audit_summary") or {}
        if isinstance(summ, dict) and summ.get("global_match_pct") is not None:
            gmp = summ.get("global_match_pct")

    if comp_status in ("fail", "failed", "error"):
        status = "failed"
    elif comp_status == "partial" or zones_failed or zones_partial:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "compliance_status_raw": comp_status,
        "zones_failed": zones_failed,
        "zones_partial": zones_partial,
        "global_match_pct": gmp,
        "empty_llm_blocks_total": empty_blocks,
    }


def session_convocante_from_state(session_state: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Extrae hints de convocante ya persistidos (sin hardcode por licitación)."""
    session_state = session_state or {}
    out: Dict[str, str] = {}
    mp = session_state.get("master_profile")
    if isinstance(mp, dict):
        for key in ("convocante", "autoridad_convocante", "dependencia", "entidad", "comite", "destinatario"):
            val = mp.get(key)
            if val and str(val).strip():
                out[key] = str(val).strip()
    for key in ("convocante", "autoridad_convocante", "dependencia", "entidad", "comite"):
        val = session_state.get(key)
        if val and str(val).strip():
            out[key] = str(val).strip()
    for block_key in ("last_analysis", "analysis_snapshot"):
        block = session_state.get(block_key)
        if not isinstance(block, dict):
            continue
        for key in ("convocante", "autoridad_convocante", "dependencia"):
            val = block.get(key)
            if val and str(val).strip() and key not in out:
                out[key] = str(val).strip()
    return out


def curate_hallazgos_list(
    hallazgos: List[Dict[str, Any]],
    session_convocante: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Particiona hallazgos en accionables y archivo + stats."""
    actionable: List[Dict[str, Any]] = []
    archival: List[Dict[str, Any]] = []
    by_reason: Dict[str, int] = {}

    for h in hallazgos:
        if not isinstance(h, dict):
            continue
        reason = resolve_curation_reason(h, session_convocante)
        enriched = {
            **h,
            "audience": classify_item_audience(h, session_convocante),
        }
        if reason is None:
            actionable.append(enriched)
        else:
            archival.append({**enriched, "curation_reason": reason})
            by_reason[reason] = by_reason.get(reason, 0) + 1

    stats = {
        "actionable_count": len(actionable),
        "archival_count": len(archival),
        "source_total": len(hallazgos),
        "by_curation_reason": by_reason,
    }
    return actionable, archival, stats


def build_dictamen_curated_v1(
    *,
    hallazgos_raw: List[Dict[str, Any]],
    session_convocante: Optional[Dict[str, str]] = None,
    extraction_health: Optional[Dict[str, Any]] = None,
    forensic_audit_health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    actionable, archival, stats = curate_hallazgos_list(hallazgos_raw, session_convocante)
    from app.services.dictamen_ux_messages import build_dictamen_ux_guia

    return {
        "schema_version": "dictamen_curated_v1",
        "filter_pipeline_version": policy_version(),
        "provenance": {
            "source_total": len(hallazgos_raw),
            "curated_at": datetime.now(timezone.utc).isoformat(),
            "policy_file": "dictamen_curation_policy.json",
        },
        "stats": stats,
        "actionable_items": actionable,
        "archival_items": archival,
        "extraction_health": extraction_health or {},
        "forensic_audit_health": forensic_audit_health or {},
        "ux_guia_usuario": build_dictamen_ux_guia(extraction_health, forensic_audit_health),
    }


def apply_curation_to_dictamen(
    dictamen: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
    extraction_health: Optional[Dict[str, Any]] = None,
    compliance: Any = None,
    view_mode: str = "licitante",
    curation_enabled: bool = True,
) -> Dict[str, Any]:
    """
    Enriquece dictamen persistido: conserva crudo, expone vista curada por defecto.
    """
    if not curation_enabled or view_mode == "forense_completo":
        return dictamen

    raw = list(dictamen.get("causales") or [])
    dictamen = {**dictamen, "causalesRaw": raw, "totalRequisitosLegacy": len(raw)}

    conv = session_convocante_from_state(session_state)
    forensic = dictamen.get("forensicAuditHealth")
    if not isinstance(forensic, dict) and compliance is not None:
        forensic = build_forensic_audit_health(compliance)
    if not isinstance(forensic, dict):
        forensic = {}

    curated = build_dictamen_curated_v1(
        hallazgos_raw=raw,
        session_convocante=conv,
        extraction_health=extraction_health,
        forensic_audit_health=forensic,
    )

    actionable = curated["actionable_items"]
    archival = curated["archival_items"]

    from app.utils.audit_processor import build_compliance_por_zona

    comp_actionable = [h for h in actionable if h.get("category") == "compliance"]
    compliance_por_zona = build_compliance_por_zona(comp_actionable)

    ext_st = str((extraction_health or {}).get("status") or "").lower()
    fore_st = str((forensic or {}).get("status") or "").lower()

    out = {
        **dictamen,
        "dictamen_curated_v1": curated,
        "causales": actionable,
        "causalesArchival": archival,
        "obligacionesDetectadas": len(actionable),
        "archivalCount": len(archival),
        "compliancePorZona": compliance_por_zona,
        "causalesPorZona": compliance_por_zona,
        "complianceHallazgosCount": len(comp_actionable),
        "totalRequisitos": len(actionable),
        "extractionHealth": extraction_health or {},
        "forensicAuditHealth": forensic or {},
        "uxGuiaUsuario": curated.get("ux_guia_usuario"),
        "dictamen_schema_version": 3,
    }

    # Salud dual: no usar semáforo único que implique fallo de lectura si extracción OK
    if ext_st in ("ok", "degraded") and fore_st in ("partial", "failed", "fail"):
        out["status"] = "⚠️ AUDITORÍA CON INCIDENCIAS"
        out["statusColor"] = "#f39c12"
        out["uxKind"] = "forensic_partial_extraction_ok"
    elif ext_st == "failed":
        out["status"] = "❌ LECTURA DE BASES INCOMPLETA"
        out["statusColor"] = "#e74c3c"
        out["uxKind"] = "extraction_failed"

    from app.services.forensic_risk_service import attach_forensic_risks_to_dictamen

    return attach_forensic_risks_to_dictamen(out)


def dictamen_needs_curation_refresh(dictamen: Dict[str, Any]) -> bool:
    """True si el dictamen guardado debe re-curarse (legacy o policy nueva)."""
    if not isinstance(dictamen, dict):
        return False
    schema = int(dictamen.get("dictamen_schema_version") or 0)
    if schema < 3 or dictamen.get("obligacionesDetectadas") is None:
        return True
    curated = dictamen.get("dictamen_curated_v1") or {}
    if str(curated.get("filter_pipeline_version") or "") != policy_version():
        return True
    if dictamen.get("causalesArchival") is None and dictamen.get("archivalCount") is None:
        return True
    return False


def refresh_dictamen_curation_if_needed(
    dictamen: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
    extraction_health: Optional[Dict[str, Any]] = None,
    compliance: Any = None,
    view_mode: str = "licitante",
    curation_enabled: bool = True,
) -> Dict[str, Any]:
    """
    Re-aplica curación HRU al dictamen persistido (GET /dictamen, sesiones legacy).
    Usa causalesRaw si existe; si no, causales actuales como fuente cruda.
    """
    if not curation_enabled or not isinstance(dictamen, dict):
        return dictamen
    if not dictamen_needs_curation_refresh(dictamen):
        return dictamen
    raw = list(dictamen.get("causalesRaw") or dictamen.get("causales") or [])
    if not raw:
        return dictamen
    base = {**dictamen, "causales": raw}
    ext = extraction_health or dictamen.get("extractionHealth")
    if isinstance(ext, dict):
        extraction_health = ext
    return apply_curation_to_dictamen(
        base,
        session_state=session_state,
        extraction_health=extraction_health,
        compliance=compliance,
        view_mode=view_mode,
        curation_enabled=True,
    )
