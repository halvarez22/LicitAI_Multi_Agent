"""Tests unitarios F11 — briefing y orquestador de apertura."""

from __future__ import annotations

from app.services.chat_gate5_formatter import count_visible_lines, format_gate5_briefing_opening
from app.services.chat_opening_orchestrator import resolve_chat_opening, should_skip_proactive_opening_handlers
from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.convocatoria_briefing_service import (
    briefing_content_hash,
    build_convocatoria_briefing_canonical_v1,
    merge_convocatoria_briefing_v1,
    policy_version,
)
from app.services.convocatoria_briefing_ux import humanize_plain_label, render_opening_message


def _vigilancia_state() -> dict:
    return {
        "name": "Vigilancia HRU",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "session_line_items": [
            {"concepto_raw": "Control de Pases", "extra": {"location_label": "Control de Pases"}}
        ],
        "economic_user_inputs": {},
        "pending_questions": [
            {
                "type": "economic_validation_blocking",
                "field": "economic_price_source",
                "input_mode": "price_source",
                "blocking_items": [{"concepto_label": "Integración del precio unitario"}],
            }
        ],
        "compliance_master_list": {
            "administrativo": [{"nombre": "Opinión SAT", "tipo_accion": "presentar_fisico"}],
            "tecnico": [{"nombre": "Propuesta técnica describiendo especificaciones", "tipo_accion": "generar"}],
            "economico": [{"nombre": "Resumen de cotización", "tipo_accion": "generar"}],
        },
        "technical_post_analysis_hook_pending": True,
    }


def test_policy_version():
    assert policy_version().startswith("convocatoria-briefing-v1")


def test_briefing_idempotent_hash():
    state = _vigilancia_state()
    a = build_convocatoria_briefing_canonical_v1(state)
    b = build_convocatoria_briefing_canonical_v1(state)
    assert a["content_hash"] == b["content_hash"]
    assert briefing_content_hash(a) == a["content_hash"]


def test_merge_skips_unchanged():
    state = _vigilancia_state()
    briefing = build_convocatoria_briefing_canonical_v1(state)
    state["convocatoria_briefing_v1"] = briefing
    assert merge_convocatoria_briefing_v1(state) == {}


def test_humanize_price_source_jargon():
    out = humanize_plain_label("fuente real de precios price_source")
    assert "price_source" not in out.lower()
    assert "precio" in out.lower()


def test_opening_no_technical_title_on_vigilancia(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat_opening_orchestrator.chat_opening_orchestrator_enabled",
        lambda: True,
    )
    state = _vigilancia_state()
    briefing = build_convocatoria_briefing_canonical_v1(state)
    msg = render_opening_message(session_state=state, briefing=briefing)
    assert "propuesta técnica —" not in msg.lower()
    assert "convocante" in msg.lower()
    assert_user_visible_clean(msg)
    assert count_visible_lines(msg) <= 4


def test_orchestrator_skips_without_company():
    assert resolve_chat_opening(
        session_state=_vigilancia_state(),
        pending_questions=[],
        current_idx=0,
        user_query="hola",
        company_id=None,
    ) is None


def test_should_skip_proactive_on_greeting(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat_opening_orchestrator.chat_opening_orchestrator_enabled",
        lambda: True,
    )
    assert should_skip_proactive_opening_handlers("hola") is True
    assert should_skip_proactive_opening_handlers("cotiza zona A 1000") is False


def test_gate5_briefing_four_lines():
    msg = format_gate5_briefing_opening(
        status="**Test** — esto es lo que pide la convocante",
        detail="Bloques y primer paso.",
        cta="Escribe un precio.",
    )
    assert count_visible_lines(msg) <= 4
