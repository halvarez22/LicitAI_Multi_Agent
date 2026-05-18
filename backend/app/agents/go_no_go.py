"""
go_no_go.py — GoNoGoAgent: Semáforo de decisión Go/No-Go.

Inserta una capa de decisión explícita entre ComplianceAgent y EconomicAgent.
Evalúa brechas críticas y calcula el score de cumplimiento técnico de forma
determinista, sin LLM, usando exclusivamente MCPContextManager para estado.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent
from app.agents.go_no_go_scorer import (
    calculate_score_tecnico,
    calculate_semaforo,
    detect_brechas,
)
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class GoNoGoAgent(BaseAgent):
    """Agente de decisión Go/No-Go.

    Evalúa si la empresa puede continuar con la licitación comparando el perfil
    maestro contra los requisitos detectados por ComplianceAgent y AnalystAgent.
    Opera de forma determinista sin llamadas al LLM.
    """

    def __init__(self, context_manager: MCPContextManager) -> None:
        super().__init__(
            agent_id="go_no_go_001",
            name="Semáforo Go/No-Go",
            description="Evalúa brechas críticas y score de cumplimiento técnico.",
            context_manager=context_manager,
        )

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """Ejecuta la evaluación Go/No-Go para la sesión.

        Args:
            agent_input: Contrato estándar de entrada con session_id y company_data.

        Returns:
            AgentOutput con data conteniendo GoNoGoResult serializado.
            En caso de error interno retorna status=ERROR sin propagar la excepción.
        """
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or ""

        try:
            context = await self.context_manager.get_global_context(session_id)
            session_state = context.get("session_state") or {}
            tasks_completed = session_state.get("tasks_completed") or []

            # Verificar prerequisito: compliance debe estar completado
            compliance_done = any(
                t.get("task") == "stage_completed:compliance"
                for t in tasks_completed
            )
            if not compliance_done:
                logger.warning(
                    "go_no_go_compliance_not_ready",
                    session_id=session_id,
                    correlation_id=correlation_id,
                )
                return AgentOutput(
                    status=AgentStatus.PARTIAL,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message="ComplianceAgent no ha completado su ejecución.",
                    correlation_id=correlation_id,
                )

            compliance_data = _extract_stage_result(tasks_completed, "stage_completed:compliance")
            analyst_data = _extract_stage_result(tasks_completed, "stage_completed:analysis")
            master_profile = agent_input.company_data.get("master_profile") or {}
            baseline_for_atenuadas = agent_input.company_data.get(
                "go_no_go_baseline_master_profile"
            )

            # Detectar brechas
            try:
                brechas = detect_brechas(compliance_data, master_profile)
            except Exception as exc:
                logger.error(
                    "go_no_go_detect_brechas_failed",
                    session_id=session_id,
                    error=str(exc),
                )
                return AgentOutput(
                    status=AgentStatus.ERROR,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    error=f"Error detectando brechas: {exc}",
                    correlation_id=correlation_id,
                )

            semaforo = calculate_semaforo(brechas)

            # Calcular score técnico (fallo no bloquea el agente)
            score_result = None
            try:
                criterios = (analyst_data.get("criterios_evaluacion") or
                             analyst_data.get("reglas_economicas") or [])
                score_result = calculate_score_tecnico(criterios, master_profile, brechas=brechas)
            except Exception as exc:
                logger.warning(
                    "go_no_go_score_failed",
                    session_id=session_id,
                    error=str(exc),
                )

            atenuadas = _count_brechas_atenuadas_por_evidencia_sesion(
                compliance_data=compliance_data,
                brechas_efectivo=brechas,
                baseline_profile=baseline_for_atenuadas
                if isinstance(baseline_for_atenuadas, dict)
                else None,
            )
            result_data = _build_result(brechas, semaforo, score_result, atenuadas)

            await self.context_manager.record_task_completion(
                session_id=session_id,
                task_name="go_no_go_result",
                result=result_data,
            )

            logger.info(
                "go_no_go_completed",
                session_id=session_id,
                semaforo=semaforo,
                total_brechas=result_data["total_brechas"],
                total_knockouts=result_data["total_knockouts"],
                score=result_data.get("score_cumplimiento_tecnico"),
                correlation_id=correlation_id,
            )

            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id=self.agent_id,
                session_id=session_id,
                data=result_data,
                correlation_id=correlation_id,
            )

        except Exception as exc:
            logger.error(
                "go_no_go_unexpected_error",
                session_id=session_id,
                error=str(exc),
            )
            return AgentOutput(
                status=AgentStatus.ERROR,
                agent_id=self.agent_id,
                session_id=session_id,
                error=str(exc),
                correlation_id=correlation_id,
            )


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _extract_stage_result(
    tasks_completed: list,
    task_name: str,
) -> Dict[str, Any]:
    """Extrae el resultado de una etapa completada desde tasks_completed.

    Args:
        tasks_completed: Lista de tareas completadas del session_state.
        task_name: Nombre de la tarea a buscar.

    Returns:
        Dict con el resultado de la etapa, o dict vacío si no se encuentra.
    """
    for task in reversed(tasks_completed):
        if task.get("task") == task_name:
            result = task.get("result") or {}
            if isinstance(result, dict):
                return result.get("data") or result
    return {}


def _count_brechas_atenuadas_por_evidencia_sesion(
    *,
    compliance_data: Dict[str, Any],
    brechas_efectivo: List[Brecha],
    baseline_profile: Optional[Dict[str, Any]],
) -> int:
    """Cuenta brechas que dejarían de reportarse al usar solo el maestro vs. el perfil ya evaluado.

    El perfil evaluado suele ser el efectivo (maestro + evidencia de sesión). La línea base
    es el ``master_profile`` de empresa antes de fusionar evidencia.

    Args:
        compliance_data: Salida de compliance para ``detect_brechas``.
        brechas_efectivo: Brechas ya calculadas con el perfil efectivo.
        baseline_profile: Perfil maestro sin fusión de sesión, o None si no aplica.

    Returns:
        Entero >= 0; 0 si no hay baseline o ante error interno.
    """
    if baseline_profile is None:
        return 0
    try:
        brechas_base = detect_brechas(compliance_data, baseline_profile)
        return max(0, len(brechas_base) - len(brechas_efectivo))
    except Exception:
        return 0


def _build_result(
    brechas: list,
    semaforo: str,
    score_result: Optional[Any],
    brechas_atenuadas_por_evidencia_sesion: int = 0,
) -> Dict[str, Any]:
    """Construye el dict GoNoGoResult serializable.

    Args:
        brechas: Lista de objetos Brecha.
        semaforo: Estado del semáforo (RED/YELLOW/GREEN).
        score_result: Resultado del scorer técnico o None.

    Returns:
        Dict con todos los campos del contrato GoNoGoResult.
    """
    brechas_list = [
        {
            "id": b.id,
            "categoria": b.categoria,
            "descripcion": b.descripcion,
            "requisito_bases": b.requisito_bases,
            "valor_empresa": b.valor_empresa,
            "is_knockout": b.is_knockout,
            "zona_origen": b.zona_origen,
        }
        for b in brechas
    ]

    score = None
    score_detalle: list = []
    if score_result is not None:
        score = score_result.score
        score_detalle = [
            {
                "criterio": d.criterio,
                "cumple": d.cumple,
                "evidencia": d.evidencia,
                "peso": d.peso,
            }
            for d in score_result.detalle
        ]

    return {
        "semaforo": semaforo,
        "brechas": brechas_list,
        "total_knockouts": sum(1 for b in brechas if b.is_knockout),
        "total_brechas": len(brechas),
        "brechas_atenuadas_por_evidencia_sesion": max(0, int(brechas_atenuadas_por_evidencia_sesion)),
        "score_cumplimiento_tecnico": score,
        "score_detalle": score_detalle,
        "requires_user_decision": semaforo in ("RED", "YELLOW"),
        "schema_version": 1,
    }
