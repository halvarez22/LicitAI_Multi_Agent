from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.economic_validation.engine import validate_economic_proposal
from app.economic_validation.models import EconomicValidationResult


def _extract_task_result(tasks: list, task_name: str) -> Optional[Dict[str, Any]]:
    for t in reversed(tasks or []):
        if t.get("task") != task_name:
            continue
        r = t.get("result")
        return r if isinstance(r, dict) else None
    return None


def get_latest_analysis_and_economic(session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    tasks = session_state.get("tasks_completed") or []
    analysis = _extract_task_result(tasks, "stage_completed:analysis") or {}
    economic = _extract_task_result(tasks, "economic_proposal") or {}
    return analysis, economic


def _run_validation_for_payload(
    *,
    analysis_result: Dict[str, Any],
    economic_payload: Dict[str, Any],
    session_name: str = "",
) -> EconomicValidationResult:
    analysis_data = (
        analysis_result.get("data") if isinstance(analysis_result.get("data"), dict) else analysis_result
    ) or {}
    reglas = analysis_data.get("reglas_economicas") if isinstance(analysis_data, dict) else {}
    reglas = reglas if isinstance(reglas, dict) else {}

    items = economic_payload.get("items") if isinstance(economic_payload.get("items"), list) else []
    currency = str(economic_payload.get("currency") or "MXN")
    total_base = float(economic_payload.get("total_base") or 0.0)
    grand_total = float(economic_payload.get("grand_total") or 0.0)
    return validate_economic_proposal(
        proposal_items=items,
        currency=currency,
        total_base=total_base,
        grand_total=grand_total,
        reglas_economicas=reglas,
        session_name=session_name,
    )


async def refresh_economic_validations_for_session(memory: Any, session_id: str) -> EconomicValidationResult:
    session = await memory.get_session(session_id)
    if not session:
        raise ValueError("Sesión no encontrada.")
    analysis, economic = get_latest_analysis_and_economic(session)
    if not economic:
        raise ValueError("No hay economic_proposal en la sesión.")

    result = _run_validation_for_payload(
        analysis_result=analysis,
        economic_payload=economic,
        session_name=str(session.get("name") or session_id),
    )
    # Persistir dentro del economic_proposal (sin mutar stage_completed:economic)
    economic["validation_result"] = result.model_dump(mode="json")
    # Reemplazar tarea in-place (última coincidencia)
    tasks = list(session.get("tasks_completed") or [])
    for idx in range(len(tasks) - 1, -1, -1):
        if tasks[idx].get("task") == "economic_proposal":
            tasks[idx] = {**tasks[idx], "result": economic}
            break
    session["tasks_completed"] = tasks
    await memory.save_session(session_id, session)
    return result
