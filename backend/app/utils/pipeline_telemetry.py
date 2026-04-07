"""
Telemetría unificada del pipeline multi-agente para UI y persistencia.

Contrato alineado con el frontend: objeto serializable con claves en camelCase
(`stagesCompleted`, `pausedStage`, `orchestratorStatus`, `stopReason`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Orden canónico de etapas conocidas en el orquestador (subconjunto habitual).
_CANONICAL_STAGES: Tuple[str, ...] = (
    "analysis",
    "compliance",
    "economic",
    "datagap",
    "technical",
    "formats",
    "economic_writer",
    "packager",
    "delivery",
)


def _paused_stage_from_stop_reason(stop_reason: Optional[str], orchestrator_status: str) -> Optional[str]:
    """
    Deriva la etapa donde el flujo quedó bloqueado esperando datos o acción del usuario.

    Returns:
        Identificador de etapa alineado con `_CANONICAL_STAGES`, o None si no aplica pausa conocida.
    """
    if not stop_reason or not isinstance(stop_reason, str):
        return None
    sr = stop_reason.strip().upper()
    if sr == "ECONOMIC_GAP":
        return "economic"
    if sr == "INCOMPLETE_DATA":
        return "datagap"
    if sr.startswith("INCOMPLETE_") and sr.endswith("_DATA"):
        inner = sr[len("INCOMPLETE_") : -len("_DATA")].lower()
        mapping = {
            "technical": "technical",
            "formats": "formats",
            "economic_writer": "economic_writer",
            "packager": "packager",
            "delivery": "delivery",
        }
        return mapping.get(inner, inner if inner in _CANONICAL_STAGES else None)
    return None


def _results_has_stage(results: Dict[str, Any], stage: str) -> bool:
    if stage not in results:
        return False
    v = results.get(stage)
    if v is None:
        return False
    if isinstance(v, dict) and len(v) == 0:
        return False
    return True


def _derive_stages_completed(
    results: Dict[str, Any],
    orchestrator_status: str,
    stop_reason: Optional[str],
) -> List[str]:
    """
    Lista etapas completadas cuando no hay `metadata.pipeline_config` (p. ej. waiting_for_data).

    Una etapa listada en `results` pero bloqueada por `waiting_for_data` en esa misma etapa
    no cuenta como completada (p. ej. economic con GAP de precios).
    """
    out: List[str] = []
    for k in _CANONICAL_STAGES:
        if _results_has_stage(results, k):
            out.append(k)

    paused = _paused_stage_from_stop_reason(stop_reason, orchestrator_status)
    if orchestrator_status == "waiting_for_data" and paused and paused in out:
        out = [s for s in out if s != paused]

    return out


def build_pipeline_telemetry(resultado: Dict[str, Any]) -> Dict[str, Any]:
    """
    Construye el objeto `pipelineTelemetry` a partir del dict retornado por `OrchestratorAgent.process`.

    Args:
        resultado: Debe incluir al menos `status`, opcionalmente `results`, `metadata`,
            `orchestrator_decision`.

    Returns:
        Dict con stagesCompleted, pausedStage, orchestratorStatus, stopReason (listo para JSON).
    """
    orch_status = str(resultado.get("status") or "error")
    decision = resultado.get("orchestrator_decision") or {}
    stop_reason = decision.get("stop_reason") if isinstance(decision, dict) else None
    if stop_reason is not None and not isinstance(stop_reason, str):
        stop_reason = str(stop_reason)

    results = resultado.get("results") if isinstance(resultado.get("results"), dict) else {}
    metadata = resultado.get("metadata") if isinstance(resultado.get("metadata"), dict) else {}
    pc = metadata.get("pipeline_config") if isinstance(metadata.get("pipeline_config"), dict) else {}
    stages_from_meta = pc.get("stages_executed")

    if isinstance(stages_from_meta, list) and stages_from_meta:
        stages_completed = [str(s) for s in stages_from_meta if s is not None]
    else:
        stages_completed = _derive_stages_completed(results, orch_status, stop_reason)

    paused_stage = _paused_stage_from_stop_reason(stop_reason, orch_status)

    return {
        "stagesCompleted": stages_completed,
        "pausedStage": paused_stage,
        "orchestratorStatus": orch_status,
        "stopReason": stop_reason,
    }
