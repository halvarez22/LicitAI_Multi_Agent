"""Ítem C.4/C.7: dedup fiscal ISAPEG — una sola entrada, cero en cola chat."""

from __future__ import annotations

from app.services.hitl_queue_service import (
    dedupe_pending_questions,
    normalize_pending_queue,
    sanitize_chat_pending_questions,
    should_exclude_from_chat_queue,
)


def _fiscal_question(suffix: str, field: str) -> dict:
    return {
        "question_id": f"INTAKE-COMP-ADM-{suffix}",
        "type": "intake_planner",
        "label": f"Declaración fiscal / opinión cumplimiento variante {suffix}",
        "question": f"¿Proyectar declaración {suffix}?",
        "field_target": field,
        "priority": "CRITICO",
    }


def test_isapeg_fiscal_variants_excluded_from_chat_queue():
    variants = [
        _fiscal_question("40", "compliance.administrativo.40"),
        _fiscal_question("41", "compliance.administrativo.41"),
        _fiscal_question("42", "compliance.administrativo.42"),
    ]
    for q in variants:
        assert should_exclude_from_chat_queue(q)
    assert sanitize_chat_pending_questions(variants) == []


def test_isapeg_fiscal_semantic_dedup_at_most_one_if_misclassified():
    """Si algún fiscal se cuela, dedup semántico deja una sola huella por etiqueta."""
    dupes = [
        {
            "type": "intake_planner",
            "label": "Opinión del cumplimiento SAT positiva",
            "field_target": "compliance.administrativo.opinion_sat",
        },
        {
            "type": "intake_planner",
            "label": "Opinión del cumplimiento SAT positiva",
            "field_target": "compliance.administrativo.opinion_sat_dup",
        },
    ]
    assert len(dedupe_pending_questions(dupes)) <= 1


def test_economic_still_first_after_fiscal_filter():
    mixed = [
        _fiscal_question("40", "compliance.administrativo.40"),
        {"type": "economic_price", "label": "Zona A", "field": "price_a"},
        _fiscal_question("41", "compliance.administrativo.41"),
    ]
    ordered = normalize_pending_queue(mixed)
    assert ordered
    assert ordered[0]["type"] == "economic_price"
    assert all(not should_exclude_from_chat_queue(q) for q in ordered)
