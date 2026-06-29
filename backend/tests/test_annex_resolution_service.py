"""Tests resolución universal de anexos (HRU)."""

from __future__ import annotations

from app.services.annex_resolution_service import (
    build_annex_doc_message,
    iter_session_annex_items,
    resolve_annex_from_query,
    resolve_economic_annex,
)
from app.services.annex_semantic_policy import infer_role_from_blob


def _panel_state(*rows: dict) -> dict:
    return {
        "document_candidates_consolidated": {
            "sobre_2_economico": list(rows),
            "sobre_1_tecnico": [],
            "requisitos_legales": [],
            "otros_requisitos_criticos": [],
        }
    }


def test_infer_role_catalog_from_dedupe():
    role = infer_role_from_blob(
        "Anexo E-2 Catálogo de conceptos",
        "El licitante presentará catálogo de conceptos",
        "obra|E2",
    )
    assert role == "concept_catalog"


def test_resolve_anexo_ae_via_panel_label():
    state = _panel_state(
        {
            "nombre_canonico": "Anexo AE — Proposición económica",
            "snippet_representativo": "Carta compromiso de la proposición económica",
            "sobre_clasificado": "sobre_2_economico",
        }
    )
    res = resolve_annex_from_query(
        state,
        "de donde sacaste el total del ANEXO AE",
    )
    assert res.matched
    assert "proposición" in res.panel_label.lower() or "ae" in res.panel_label.lower()
    assert res.semantic_role == "economic_proposal"


def test_resolve_anexo_viii_by_token():
    state = _panel_state(
        {
            "nombre_canonico": "Anexo VIII — Análisis de precios unitarios",
            "snippet_representativo": "Análisis de precios unitarios de los trabajos ejecutar",
            "dedupe_key": "pliego|ANEXO_VIII",
        }
    )
    res = resolve_annex_from_query(state, "total del Anexo VIII")
    assert res.matched
    assert "VIII" in res.panel_label.upper()
    assert res.semantic_role == "unit_price_analysis"


def test_resolve_by_economic_role_hint_without_anexo_code():
    state = _panel_state(
        {
            "nombre_canonico": "Catálogo de conceptos constructivos",
            "snippet_representativo": "Catálogo de conceptos que el licitante deberá presentar",
            "dedupe_key": "obra|E2",
        },
        {
            "nombre_canonico": "Análisis de precios unitarios",
            "snippet_representativo": "Análisis de precios unitarios de cada concepto",
            "dedupe_key": "obra|E3",
        },
    )
    res = resolve_economic_annex(state, "como viste mis precios del catalogo", mode="catalog")
    assert res.matched
    assert res.semantic_role == "concept_catalog"


def test_build_annex_doc_message_explicit_token():
    state = _panel_state(
        {
            "nombre_canonico": "Anexo AE Proposición económica",
            "snippet_representativo": "Proposición económica del licitante",
        }
    )
    res = resolve_annex_from_query(state, "total del anexo ae")
    msg = build_annex_doc_message(res, user_query="total del anexo ae")
    assert "anexo" in msg.lower()
    assert "AE" in msg.upper() or "ae" in msg.lower()


def test_fail_closed_unknown_anexo():
    state = _panel_state(
        {
            "nombre_canonico": "Anexo II Carta de integridad",
            "snippet_representativo": "Declaración de integridad del licitante",
            "dedupe_key": "pliego|ANEXO_II",
        }
    )
    res = resolve_annex_from_query(state, "que va en el Anexo IIX")
    msg = build_annex_doc_message(res, user_query="que va en el Anexo IIX")
    assert "IIX" in msg.upper()
    assert "Formatos" in msg or "no encuentro" in msg.lower()


def test_iter_deduplicates_panel():
    state = {
        "document_candidates_consolidated": {
            "sobre_2_economico": [
                {"nombre_canonico": "Catálogo de conceptos", "dedupe_key": "obra|E2"},
                {"nombre_canonico": "Catálogo de conceptos (copia)", "dedupe_key": "obra|E2"},
            ],
        }
    }
    items = iter_session_annex_items(state)
    assert len(items) == 1


def test_detect_annex_identity_not_literal():
    from app.services.annex_resolution_service import (
        build_annex_identity_message,
        detect_annex_identity_intent,
        is_annex_literal_citation_query,
    )

    assert detect_annex_identity_intent("que es el anexo AE en esta licitacion")
    assert is_annex_literal_citation_query("que dice el anexo 1 sobre garantias")
    assert not detect_annex_identity_intent("que dice el anexo 1 sobre garantias en las bases")


def test_build_annex_identity_message():
    from app.services.annex_resolution_service import build_annex_identity_message

    state = _panel_state(
        {
            "nombre_canonico": "Anexo T-2 — Relación de contratos",
            "snippet_representativo": "Relación de contratos de obras vigentes del licitante",
            "dedupe_key": "obra|T2",
            "sobre_clasificado": "sobre_1_tecnico",
        }
    )
    msg = build_annex_identity_message(state, "que es el anexo T-2")
    assert msg
    assert "T-2" in msg.upper() or "contratos" in msg.lower()
