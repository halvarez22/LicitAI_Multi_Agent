from app.services.hitl_queue_service import (
    dedupe_pending_questions,
    is_fiscal_or_physical_intake,
    merge_pending_queues,
    normalize_pending_queue,
    semantic_question_fingerprint,
    should_exclude_from_chat_queue,
)


def test_fiscal_intake_excluded_from_chat():
    q = {
        "question_id": "INTAKE-COMP-ADM-001",
        "label": "Declaración fiscal anual SAT",
        "question": "¿proyectar?",
        "field_target": "compliance.administrativo.40",
    }
    assert is_fiscal_or_physical_intake(q["label"], q["question"], q["field_target"])
    assert should_exclude_from_chat_queue(q)


def test_dedupe_economic_price_by_field():
    qs = [
        {
            "type": "economic_price",
            "label": "Zona A | L-D",
            "field": "price_struct_service_a_lunes",
        },
        {
            "type": "economic_price",
            "label": "Zona A | L-D (dup)",
            "field": "price_struct_service_a_lunes",
        },
    ]
    assert len(dedupe_pending_questions(qs)) == 1


def test_economic_priority_first():
    qs = [
        {"type": "profile_field_blocking", "label": "RFC", "field": "rfc"},
        {"type": "economic_price", "label": "Zona A", "field": "price_a"},
        {"type": "intake", "label": "Catálogo", "question_id": "INTAKE-COMP-TEC-001"},
    ]
    ordered = normalize_pending_queue(qs)
    assert ordered[0]["type"] == "economic_price"


def test_merge_pending_queues():
    a = [{"type": "economic_price", "field": "p1", "label": "A"}]
    b = [{"type": "economic_price", "field": "p1", "label": "A dup"}]
    merged = merge_pending_queues(b, a)
    assert len(merged) == 1
    assert semantic_question_fingerprint(merged[0]).startswith("eco|")
