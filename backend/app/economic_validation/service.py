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
    allow_zero_total_base: bool = False,
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
        allow_zero_total_base=allow_zero_total_base,
    )


async def refresh_economic_validations_for_session(memory: Any, session_id: str) -> EconomicValidationResult:
    from app.services.economic_refresher import EconomicRefresherService
    from app.services.economic_calculator_engine import EconomicCalculatorEngine
    
    session = await memory.get_session(session_id)
    if not session:
        raise ValueError("Sesión no encontrada.")
    
    analysis, economic = get_latest_analysis_and_economic(session)
    
    # --- Hito 2: Inicializar/Recuperar MPS (Master Proposal State) ---
    # El MPS es la fuente de verdad única para la validación económica.
    mps = session.get("master_proposal_state") or {}
    if not mps and economic:
        # Inicialización por primera vez desde el archivo
        mps = {
            "items": economic.get("items") or [],
            "currency": str(economic.get("currency") or "MXN"),
            "total_base": float(economic.get("total_base") or 0.0),
            "grand_total": float(economic.get("grand_total") or 0.0),
            "source_type": "FILE_INIT"
        }
    
    if not mps:
        raise ValueError("No hay propuesta económica base (MPS) para validar.")

    # 1. Aplicar Reconciliación de Chat (Fuzzy Match) sobre el MPS
    user_inputs = session.get("economic_user_inputs") or {}
    master_list = session.get("master_compliance_list") or {}
    tech_reqs = master_list.get("tecnico") or master_list.get("técnico") or []
    
    refresher = EconomicRefresherService()
    # HITO: Pasar mps para habilitar Overrides Maestros de Totales
    updated_items = refresher.apply_overrides(mps.get("items") or [], user_inputs, tech_reqs, mps)
    
    # 2. Recalcular Totales y Cuadratura sobre el MPS
    calculator = EconomicCalculatorEngine()
    updated_items = calculator.normalize_items(updated_items)
    
    reglas = analysis.get("data", {}).get("reglas_economicas") if isinstance(analysis.get("data"), dict) else analysis.get("reglas_economicas", {})
    reglas = dict(reglas or {})
    
    # Defaults de Ley
    for k, v in {"sar": "0.02", "infonavit": "0.05", "prima_vacacional": "0.25"}.items():
        if k not in reglas: reglas[f"default_{k}"] = f"{k}: {v}"

    for k, v in user_inputs.items():
        if k != "concept_prices" and v is not None:
            reglas[f"chat_override_{k}"] = f"{k}: {v}"

    totals = calculator.compute_totals(updated_items, reglas, str(session.get("name") or session_id))
    
    # Actualizar MPS (Prioridad absoluta a inputs directos del chat)
    mps["items"] = updated_items
    
    # Búsqueda profunda de subtotal en inputs
    manual_subtotal = user_inputs.get("subtotal_propuesta")
    if not manual_subtotal:
        # Buscar en los nombres de las partidas si alguna dice "Total" o "Subtotal"
        prices = user_inputs.get("concept_prices") or {}
        for k, v in prices.items():
            if "subtotal" in k.lower() or "total" in k.lower():
                manual_subtotal = v
                break

    mps["total_base"] = manual_subtotal or mps.get("total_base") or totals["total_base"]
    mps["grand_total"] = user_inputs.get("total_propuesta") or mps.get("grand_total") or totals["grand_total"]
    mps["blocking_issues"] = totals["blocking_issues"]

    # Cuadratura
    session_line_items = await memory.get_line_items_for_session(session_id)
    if session_line_items:
        mps["quadrature_report"] = calculator.build_quadrature_report(updated_items, session_line_items)

    # 3. Validar
    allow_zero = bool(user_inputs.get("allow_zero_total_base_ack"))
    result = _run_validation_for_payload(
        analysis_result=analysis,
        economic_payload=mps,
        session_name=str(session.get("name") or session_id),
        allow_zero_total_base=allow_zero,
    )
    
    mps["validation_result"] = result.model_dump(mode="json")
    
    # Persistir MPS y sincronizar con economic_proposal para compatibilidad
    session["master_proposal_state"] = mps
    
    tasks = list(session.get("tasks_completed") or [])
    for idx in range(len(tasks) - 1, -1, -1):
        if tasks[idx].get("task") == "economic_proposal":
            tasks[idx] = {**tasks[idx], "result": mps}
            break
    
    session["tasks_completed"] = tasks
    await memory.save_session(session_id, session)
    return result
