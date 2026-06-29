"""Tests HRU para curación del Dictamen Forense (sin hardcode por licitación)."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.dictamen_curation_service import (
    CURATION_REASON_CONVOCANTE,
    CURATION_REASON_INFORMATIVO,
    apply_curation_to_dictamen,
    classify_item_audience,
    curate_hallazgos_list,
    resolve_curation_reason,
)


def _compliance_item(
    descripcion: str,
    *,
    tipo_accion: str = "",
    audience: str = "",
) -> dict:
    texto: dict = {"descripcion": descripcion, "nombre": descripcion}
    if tipo_accion:
        texto["tipo_accion"] = tipo_accion
    if audience:
        texto["audience"] = audience
    return {
        "tipo": "📁 ADMINISTRATIVO",
        "texto": texto,
        "category": "compliance",
        "agent_id": "compliance_001",
        "zona_origen": "ADMINISTRATIVO/LEGAL",
    }


def test_convocante_narrative_archived_via_session_tokens_not_fixed_names():
    """Archiva narrativa del convocante usando tokens de ESTA sesión (HRU-H)."""
    session_conv = {
        "convocante": "Autoridad Responsable del Procedimiento Licitatorio ARC-2024-001",
        "dependencia": "Unidad Administrativa de Contrataciones",
    }
    item = _compliance_item(
        "La Autoridad Responsable del Procedimiento Licitatorio ARC-2024-001 "
        "comparece con personalidad para suscribir el contrato."
    )
    reason = resolve_curation_reason(item, session_conv)
    assert reason == CURATION_REASON_CONVOCANTE
    assert classify_item_audience(item, session_conv) == "convocante"


def test_convocante_narrative_via_universal_pattern_without_session():
    """Patrones universales de sujeto convocante (política JSON), sin nombre de entidad fijo."""
    item = _compliance_item("El comité convocante establece el calendario del procedimiento.")
    assert classify_item_audience(item, {}) == "convocante"
    assert resolve_curation_reason(item, {}) == CURATION_REASON_CONVOCANTE


def test_licitante_obligation_stays_actionable():
    item = _compliance_item(
        "El licitante deberá presentar constancia de situación fiscal vigente.",
        tipo_accion="presentar_fisico",
    )
    assert resolve_curation_reason(item, {}) is None
    assert classify_item_audience(item, {}) == "licitante"


def test_informativo_archived():
    item = _compliance_item(
        "Las bases se publicaron en el portal de compras.",
        tipo_accion="informativo",
    )
    assert resolve_curation_reason(item, {}) == CURATION_REASON_INFORMATIVO


def test_risk_and_bases_participacion_always_actionable():
    risk = {
        "tipo": "🚫 DESECHAMIENTO",
        "texto": "Falta de documentación",
        "category": "risk",
        "isRisk": True,
    }
    bases = {
        "tipo": "📋 REQUISITO PARA PARTICIPAR",
        "texto": "RFC vigente",
        "category": "bases_participacion",
    }
    assert resolve_curation_reason(risk, {}) is None
    assert resolve_curation_reason(bases, {}) is None


def test_apply_curation_reduces_default_view():
    session_conv_name = "Autoridad Responsable del Procedimiento Licitatorio ARC-2024-001"
    raw = [
        _compliance_item(
            f"{session_conv_name} comparece con personalidad para suscribir el contrato.",
        ),
        _compliance_item(
            "El licitante deberá entregar propuesta técnica.",
            tipo_accion="generar",
        ),
        {
            "tipo": "📋 REQUISITO PARA PARTICIPAR",
            "texto": "Acta constitutiva",
            "category": "bases_participacion",
        },
    ]
    session_state = {"convocante": session_conv_name}
    dictamen = {
        "causales": raw,
        "status": "⚠️ COMPLETADO CON INCIDENCIAS",
        "statusColor": "#f39c12",
        "statusRaw": "partial",
        "totalRequisitos": len(raw),
    }
    out = apply_curation_to_dictamen(
        dictamen,
        session_state=session_state,
        extraction_health={"status": "ok"},
        compliance={"status": "partial", "data": {"audit_summary": {"zones": []}}},
    )
    assert out["dictamen_schema_version"] == 3
    assert out["obligacionesDetectadas"] == 2
    assert out["archivalCount"] == 1
    assert len(out["causales"]) == 2
    assert out["totalRequisitosLegacy"] == 3
    assert out["uxKind"] == "forensic_partial_extraction_ok"


def test_curate_hallazgos_stats_by_reason():
    items = [
        _compliance_item("Texto informativo de convocatoria.", tipo_accion="informativo"),
        _compliance_item("El comité convocante establece el calendario."),
    ]
    actionable, archival, stats = curate_hallazgos_list(items, {})
    assert stats["actionable_count"] == 0
    assert stats["archival_count"] == 2
    assert stats["by_curation_reason"][CURATION_REASON_INFORMATIVO] == 1
    assert stats["by_curation_reason"][CURATION_REASON_CONVOCANTE] == 1
    assert not actionable
    assert len(archival) == 2


def test_convocante_contract_preamble_archived():
    """Preámbulo contractual del convocante (patrones universales, sin municipio fijo)."""
    samples = [
        "Que es una persona moral legalmente constituida conforme a las leyes mexicanas, según lo acredita con el testimonio de la Escritura Pública No. 19687",
        "F) Que Señala como su domicilio el ubicado en Palacio Municipal S/N, Col. Centro C.P. 37000",
        "Tiene capacidad jurídica para suscribir el presente contrato y está facultado para representarla legalmente en este acto",
    ]
    for text in samples:
        item = _compliance_item(text)
        assert resolve_curation_reason(item, {}) == CURATION_REASON_CONVOCANTE, text[:60]


def test_frontend_policy_mirror_matches_backend():
    """El contenedor frontend no monta /backend; el JSON debe estar espejado."""
    repo_root = Path(__file__).resolve().parents[2]
    backend_path = repo_root / "backend" / "app" / "contracts" / "dictamen_curation_policy.json"
    frontend_path = repo_root / "frontend" / "src" / "contracts" / "dictamen_curation_policy.json"
    assert frontend_path.is_file(), "Falta espejo frontend/src/contracts/dictamen_curation_policy.json"
    backend = json.loads(backend_path.read_text(encoding="utf-8"))
    frontend = json.loads(frontend_path.read_text(encoding="utf-8"))
    for key in (
        "policy_version",
        "actionable_tipo_accion",
        "actionable_non_compliance_categories",
        "licitante_subject_patterns",
        "convocante_subject_patterns",
        "mixed_obligation_licitante_override_patterns",
    ):
        assert backend[key] == frontend[key], f"Policy drift en {key}"


def test_refresh_dictamen_curation_legacy_schema():
    session_conv_name = "Autoridad Responsable del Procedimiento Licitatorio ARC-2024-001"
    raw = [
        _compliance_item(
            f"{session_conv_name} comparece con personalidad para suscribir el contrato.",
        ),
        _compliance_item(
            "El licitante deberá entregar propuesta técnica.",
            tipo_accion="generar",
        ),
    ]
    legacy_dictamen = {
        "causales": raw,
        "status": "⚠️ COMPLETADO CON INCIDENCIAS",
        "totalRequisitos": len(raw),
        "dictamen_schema_version": 2,
    }
    from app.services.dictamen_curation_service import refresh_dictamen_curation_if_needed

    out = refresh_dictamen_curation_if_needed(
        legacy_dictamen,
        session_state={"convocante": session_conv_name},
        extraction_health={"status": "ok"},
        compliance={"status": "partial", "data": {"audit_summary": {"zones": []}}},
    )
    assert out["dictamen_schema_version"] == 3
    assert out["obligacionesDetectadas"] == 1
    assert out["archivalCount"] == 1
