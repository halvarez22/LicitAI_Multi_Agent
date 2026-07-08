"""Tests unitarios F12.1 — evidence_anchor_service + briefing cableado."""

from __future__ import annotations

from app.agents.economic import _ensure_chat_anchor
from app.services.convocatoria_briefing_service import build_convocatoria_briefing_canonical_v1
from app.services.convocatoria_briefing_ux import render_opening_message
from app.services.evidence_anchor_service import (
    claim_quality_for_ux,
    format_claim_locus,
    is_claim_locus_visible,
    normalize_evidence_anchor,
    policy_version,
    reason_plain_with_anchor,
    verify_snippet_on_page_text,
)


def test_policy_version():
    assert policy_version().startswith("evidence-anchor-v1")


def test_synthetic_never_verified_for_claims():
    raw = {
        "source": "bases_licitacion",
        "page": 1,
        "snippet": "Cotización en chat — Control de Pases",
        "is_synthetic": True,
    }
    anchor = normalize_evidence_anchor(raw, claim_id="t")
    assert anchor["anchor_quality"] == "synthetic"
    assert is_claim_locus_visible(anchor) is False
    assert claim_quality_for_ux(anchor) == "insufficient"
    assert format_claim_locus(anchor) == ""


def test_economic_ensure_chat_anchor_marks_synthetic():
    oi = _ensure_chat_anchor({}, "Zona A")
    assert oi.get("is_synthetic") is True
    assert oi.get("anchor_quality") == "synthetic"
    anchor = normalize_evidence_anchor(oi, force_synthetic=True)
    assert anchor["anchor_quality"] == "synthetic"
    assert not is_claim_locus_visible(anchor)


def test_verified_locus_in_opening(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_anchor_service.evidence_anchor_enabled",
        lambda: True,
    )
    state = {
        "name": "Vigilancia HRU",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "session_line_items": [
            {
                "concepto_raw": "Control de Pases",
                "extra": {
                    "location_label": "Control de Pases",
                    "page": 63,
                    "snippet": "Control de Pases cuatro elementos turno matutino tabla dotación",
                    "source": "BASES.pdf",
                },
            }
        ],
        "economic_user_inputs": {},
        "compliance_master_list": {
            "economico": [
                {
                    "nombre": "Integración del precio unitario",
                    "page": 27,
                    "snippet": "Integración del precio unitario mensual y diario sin IVA por operario",
                    "archivo_fuente": "BASES.pdf",
                }
            ],
            "administrativo": [{"nombre": "Opinión SAT", "tipo_accion": "presentar_fisico"}],
            "tecnico": [{"nombre": "Organigrama", "tipo_accion": "generar"}],
        },
    }
    briefing = build_convocatoria_briefing_canonical_v1(state)
    action = briefing.get("recommended_first_action") or {}
    anchor = action.get("evidence_anchor") or {}
    assert claim_quality_for_ux(anchor) == "verified"
    assert 27 in (action.get("provenance_ui") or {}).get("page_refs", []) or anchor.get("page") == 27

    msg = render_opening_message(session_state=state, briefing=briefing)
    assert "p. 27" in msg or "p. 63" in msg
    assert "muéstrame el párrafo" in msg.lower()


def test_insufficient_degrades_reason():
    anchor = normalize_evidence_anchor({}, claim_id="x")
    reason = reason_plain_with_anchor(
        policy_reason="Las bases piden cerrar la cotización.",
        anchor=anchor,
    )
    assert "localice la página" in reason.lower() or "empezamos por la cotización" in reason.lower()
    assert "p." not in reason or "página" in reason.lower()


def test_verify_snippet_on_page():
    page = "La integración del precio unitario mensual y diario sin IVA por operario se presenta en Anexo 8."
    out = verify_snippet_on_page_text(
        "Integración del precio unitario mensual y diario sin IVA por operario",
        page,
    )
    assert out.get("passed") is True
