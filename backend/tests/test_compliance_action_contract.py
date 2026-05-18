from app.agents.compliance import ComplianceAgent
from app.services.tender_router_service import TenderRouterService


def _agent_without_init() -> ComplianceAgent:
    return ComplianceAgent.__new__(ComplianceAgent)  # type: ignore[misc]


def test_normalize_item_preserva_tipo_accion_valido():
    agent = _agent_without_init()
    out = agent._normalize_item(
        {
            "nombre": "Anexo II",
            "descripcion": "Manifestación de conformidad",
            "snippet": "Anexo II, manifiesto de conformidad con las bases",
            "tipo_accion": "generar",
            "action_confidence": 0.87,
            "categoria_sugerida": "formatos",
        }
    )
    assert out["tipo_accion"] == "generar"
    assert out["action_confidence"] == 0.87
    assert out["categoria_sugerida"] == "formatos"


def test_normalize_item_normaliza_tipo_accion_invalido_a_unknown():
    agent = _agent_without_init()
    out = agent._normalize_item(
        {
            "nombre": "Evento de junta",
            "descripcion": "Junta de aclaraciones",
            "snippet": "Se llevará a cabo la junta de aclaraciones...",
            "tipo_accion": "otra_cosa",
        }
    )
    assert out["tipo_accion"] == "unknown"


def test_normalize_item_preserva_label_taxonomica_y_flags_opcionales():
    agent = _agent_without_init()
    out = agent._normalize_item(
        {
            "nombre": "Opinión SAT",
            "snippet": "opinión de cumplimiento 32-D",
            "label_taxonomica": "FIS_SAT_OPINION",
            "obligatorio_por_bases": True,
            "obligatorio_por_marco_normativo": False,
            "justificacion_clasificacion": "Literal en bases",
        }
    )
    assert out["label_taxonomica"] == "FIS_SAT_OPINION"
    assert out["obligatorio_por_bases"] is True
    assert out["obligatorio_por_marco_normativo"] is False
    assert out["justificacion_clasificacion"] == "Literal en bases"


def test_match_must_have_sat_y_estatal_y_anexo():
    t_sat = TenderRouterService.normalize_text_for_policy_match(
        "Deberá presentar opinión de cumplimiento 32-D ante el SAT"
    )
    m_sat = TenderRouterService.match_must_have_from_normalized_text(t_sat, "LAASSP", "BIENES")
    assert m_sat is not None
    assert m_sat["label"] == "FIS_SAT_OPINION"

    t_est = TenderRouterService.normalize_text_for_policy_match(
        "Opinión de cumplimiento fiscal emitida por la Secretaría de Finanzas del Estado de Querétaro"
    )
    m_est = TenderRouterService.match_must_have_from_normalized_text(t_est, "LAASSP", "BIENES")
    assert m_est is not None
    assert m_est["label"] == "FIS_ESTATAL_OPINION"

    t_id = TenderRouterService.normalize_text_for_policy_match(
        "Anexo III datos generales del licitante CURP e identificación oficial"
    )
    m_id = TenderRouterService.match_must_have_from_normalized_text(t_id, "LAASSP", "BIENES")
    assert m_id is not None
    assert m_id["label"] == "LEG_IDENTIDAD_CANDIDATO"


def test_match_must_have_estatal_excluye_garantias_y_multas():
    t_noise = TenderRouterService.normalize_text_for_policy_match(
        "Carta garantía de calidad para UNAQ en Querétaro y multa por incumplimiento"
    )
    m_noise = TenderRouterService.match_must_have_from_normalized_text(
        t_noise, "LAASSP", "BIENES"
    )
    assert m_noise is None


def test_reduce_zone_items_must_have_enforcement_cuando_tipo_accion_es_unknown():
    """El enforcement no debe quedar solo para 'informativo': unknown también se corrige."""
    agent = _agent_without_init()
    snippet = (
        "El licitante debera presentar identificacion oficial vigente del representante legal "
        "y comprobante de curp"
    )
    full_ctx = "Fragmento de bases: " + snippet + " " * 40
    law, cat = "LAASSP", "BIENES"
    triage = {
        "law": law,
        "tender_category": cat,
        "taxonomy_allowlist": TenderRouterService.get_taxonomy_allowlist(law, cat),
        "must_have_policy": TenderRouterService.get_must_have_policy(law, cat),
    }
    raw = [
        {
            "nombre": "Identificación oficial del representante",
            "descripcion": "Credencial para votar o pasaporte vigente",
            "snippet": snippet,
            "tipo_accion": "unknown",
            "categoria_orig": "administrativo",
        }
    ]
    reduced, _metrics = agent._reduce_zone_items(
        "ADMINISTRATIVO", raw, full_ctx, triage_context=triage
    )
    assert len(reduced) == 1
    it = reduced[0]
    assert "forced_by_must_have_matrix" in (it.get("quality_flags") or [])
    assert it.get("tipo_accion") == "presentar_fisico"
    assert (it.get("forced_by_must_have") or {}).get("label") == "LEG_IDENTIDAD_CANDIDATO"
    assert "taxonomy_anchor_applied" in (it.get("quality_flags") or [])
    assert it.get("label_taxonomica") == "LEG_IDENTIDAD_CANDIDATO"
