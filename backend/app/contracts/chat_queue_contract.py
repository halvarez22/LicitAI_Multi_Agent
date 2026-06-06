"""
Contrato universal de cola conversacional (chat HITL).

Una sola fuente de verdad: qué ítems NO deben entrar en ``pending_questions``
del chat. Las reglas son por semántica (prefijos, provenance, taxonomía),
nunca por ``session_id`` ni convocante.

Ver también: ``docs/CONTRATO_COLA_CHAT_UNIVERSAL.md``
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

# Prefijos de question_id que solo viven en paneles (Go/No-Go, contractual, gaps).
PANEL_ONLY_QUESTION_ID_PREFIXES: Tuple[str, ...] = (
    "INTAKE-B-GNG-",
    "INTAKE-B-CON-",
    "INTAKE-GAP-",
)

# Razones de provenance_ui que marcan ítem de panel, no captura en chat.
PANEL_ONLY_PROVENANCE_REASONS: frozenset[str] = frozenset(
    {
        "brecha_detectada",
        "condicion_contractual",
        "gap_analysis",
    }
)

# Tipos permitidos en cola conversacional (whitelist laxa; lo demás pasa por exclusiones).
CHAT_ALLOWED_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        "intake_planner",
        "intake",
        "economic_price",
        "economic_validation_blocking",
        "profile_field_blocking",
        "quality_validation_blocking",
        "evidence_profile_conflict",
        "data_gap",
        "clarification",
    }
)


def is_panel_only_intake_item(question: Dict[str, Any]) -> bool:
    """
    True si el ítem debe mostrarse en paneles (semáforo, análisis, checklist),
    no en la cola secuencial del chat.
    """
    if not isinstance(question, dict):
        return True
    qid = str(question.get("question_id") or "")
    if any(qid.startswith(p) for p in PANEL_ONLY_QUESTION_ID_PREFIXES):
        return True
    prov = question.get("provenance_ui") if isinstance(question.get("provenance_ui"), dict) else {}
    if str(prov.get("reason") or "") in PANEL_ONLY_PROVENANCE_REASONS:
        return True
    return False


def filter_questions_for_chat(questions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtra preguntas de intake_plan (u otra fuente) dejando solo las aptas para chat."""
    from app.services.hitl_queue_service import should_exclude_from_chat_queue

    out: List[Dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if is_panel_only_intake_item(q):
            continue
        if should_exclude_from_chat_queue(q):
            continue
        out.append(q)
    return out


def find_chat_queue_violations(queue: Sequence[Dict[str, Any]]) -> List[str]:
    """
    Devuelve descripciones de violaciones del contrato (vacío = conforme).

    Usado en tests y smoke CI; no lanza excepción para permitir reportes agregados.
    """
    from app.services.hitl_queue_service import should_exclude_from_chat_queue

    violations: List[str] = []
    for i, q in enumerate(queue):
        if not isinstance(q, dict):
            violations.append(f"[{i}] entrada no es dict")
            continue
        qid = str(q.get("question_id") or q.get("field") or i)
        if is_panel_only_intake_item(q):
            violations.append(f"[{qid}] ítem de panel en cola chat")
        elif should_exclude_from_chat_queue(q):
            violations.append(f"[{qid}] excluido por política HITL pero presente en cola")
    return violations


def assert_chat_queue_compliant(queue: Sequence[Dict[str, Any]]) -> None:
    """Fallo explícito en tests/CI si la cola incumple el contrato universal."""
    bad = find_chat_queue_violations(queue)
    if bad:
        raise AssertionError(
            "Cola de chat incumple CONTRATO_COLA_CHAT_UNIVERSAL:\n- " + "\n- ".join(bad)
        )
