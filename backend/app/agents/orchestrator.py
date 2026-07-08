import logging
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.core.observability import get_logger, agent_span, generate_correlation_id
from app.contracts.session_contracts import SessionStateMigrator
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.contracts.orchestrator_contracts import OrchestratorState
from app.config.settings import settings
from app.services.document_candidate_list_service import build_candidate_document_list
from app.services.tender_router_service import TenderRouterService
from app.orchestration.pipeline_configurator import PipelineConfigurator, PipelineConfig, ActionType, ConditionType
from app.core.formats_pilot_slots import is_usable_profile_field_value

# Logger estructurado
logger = get_logger(__name__)


def _result_status_value(res: Any) -> Optional[str]:
    """Obtiene el status como string desde AgentOutput o dict legacy."""
    if res is None:
        return None
    if isinstance(res, dict):
        s = res.get("status")
    else:
        s = getattr(res, "status", None)
    if s is None:
        return None
    return s.value if hasattr(s, "value") else str(s)


def _result_message(res: Any) -> Optional[str]:
    """Obtiene message desde AgentOutput o dict legacy."""
    if isinstance(res, dict):
        return res.get("message")
    return getattr(res, "message", None)


def _tasks_completed_list(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in (session_state.get("tasks_completed") or []) if isinstance(t, dict)]


def _collect_completed_stages_from_session(session_state: Dict[str, Any]) -> Set[str]:
    """Hitos ``stage_completed:*`` persistidos en la sesión."""
    stages: Set[str] = set()
    for task in _tasks_completed_list(session_state):
        name = str(task.get("task") or "")
        if name.startswith("stage_completed:"):
            stages.add(name.split(":", 1)[1])
    return stages


async def _persist_compliance_recovery_if_needed(
    memory: Any,
    session_id: str,
    session_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Rehidrata ``compliance_master_list`` desde mini-dictamen u otros artefactos
    si el índice forense se perdió por un guardado parcial de sesión.
    """
    if _compliance_list_from_session(session_state):
        return session_state
    from app.services.compliance_session_recovery import try_recover_compliance_master_list

    recovered, source = try_recover_compliance_master_list(session_state)
    if not recovered:
        return session_state
    session_state["compliance_master_list"] = recovered
    session_state["compliance_recovery_source"] = source
    await _safe_save_session(
        memory,
        session_id,
        {
            "compliance_master_list": recovered,
            "compliance_recovery_source": source,
        },
    )
    logger.info(
        "compliance_master_list_recovered",
        session_id=session_id,
        source=source,
        counts={
            k: len(recovered.get(k) or [])
            for k in ("administrativo", "tecnico", "formatos")
        },
    )
    return session_state


def _compliance_list_from_session(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Lista maestra de compliance con al menos un rubro (administrativo/técnico/formatos)."""
    cm = session_state.get("compliance_master_list")
    if isinstance(cm, dict) and any(
        isinstance(cm.get(k), list) and cm.get(k)
        for k in ("administrativo", "tecnico", "formatos")
    ):
        return cm
    for task in reversed(_tasks_completed_list(session_state)):
        tname = str(task.get("task") or "")
        if tname not in ("stage_completed:compliance", "master_compliance_list"):
            continue
        res = task.get("result") or {}
        data = res.get("data") if isinstance(res.get("data"), dict) else res
        if isinstance(data, dict) and any(
            isinstance(data.get(k), list) and data.get(k)
            for k in ("administrativo", "tecnico", "formatos")
        ):
            return data
    return {}


def _session_has_compliance_evidence(session_state: Dict[str, Any]) -> bool:
    """
    True si hay lista de requisitos utilizable para generación (no basta Go/No-Go aislado).

    Cubre sesiones donde el dictamen existe pero falta el hito ``stage_completed:compliance``.
    """
    from app.services.compliance_session_recovery import try_recover_compliance_master_list

    recovered, _ = try_recover_compliance_master_list(session_state)
    if recovered and not _compliance_list_from_session(session_state):
        session_state["compliance_master_list"] = recovered
    if _compliance_list_from_session(session_state):
        return True
    if session_state.get("mini_dictamen_anexos"):
        return True
    intake = session_state.get("intake_plan")
    if isinstance(intake, dict) and (intake.get("questions") or intake.get("checklist_corporativo")):
        return True
    for task in _tasks_completed_list(session_state):
        tname = str(task.get("task") or "").lower()
        if tname == "stage_completed:compliance" and task.get("result"):
            return True
        if "compliance" in tname and task.get("result"):
            return True
    return False


def _coerce_economic_data(result: Any) -> Dict[str, Any]:
    """Obtiene data económica desde AgentOutput o dict legacy."""
    if result is None:
        return {}
    if isinstance(result, dict):
        data = result.get("data")
    else:
        data = getattr(result, "data", None)
    return data if isinstance(data, dict) else {}


def _normalize_gate_stage(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict) and "data" in raw:
        return raw
    if hasattr(raw, "data"):
        return {"status": "success", "data": getattr(raw, "data") or {}}
    return {"status": "success", "data": raw if isinstance(raw, dict) else {}}


def _build_compliance_gate_payload(
    session_id: str,
    execution_results: Dict[str, Any],
    session_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Arma el payload del ComplianceGate hidratando compliance/economic desde la sesión
    cuando en ``generation_only`` se reutilizan hitos sin re-ejecutar agentes.
    """
    analysis = _normalize_gate_stage(execution_results.get("analysis") or {})
    compliance = _normalize_gate_stage(execution_results.get("compliance") or {})
    economic = _normalize_gate_stage(execution_results.get("economic") or {})

    comp_data = _coerce_compliance_data(compliance)
    if not any(
        isinstance(comp_data.get(k), list) and comp_data.get(k)
        for k in ("administrativo", "tecnico", "formatos")
    ):
        hydrated = _compliance_list_from_session(session_state)
        if not hydrated:
            from app.services.compliance_session_recovery import try_recover_compliance_master_list

            recovered, _ = try_recover_compliance_master_list(session_state)
            if recovered:
                hydrated = recovered
        if hydrated:
            compliance = {"status": "success", "data": hydrated}

    econ_data = _coerce_economic_data(economic)
    if not econ_data.get("validation_result"):
        for task in reversed(_tasks_completed_list(session_state)):
            if str(task.get("task") or "") not in (
                "stage_completed:economic",
                "economic_proposal",
            ):
                continue
            res = task.get("result") or {}
            candidate = _coerce_economic_data(res)
            if candidate.get("validation_result") or candidate.get("items"):
                economic = {"status": "success", "data": candidate}
                break

    return {
        "session_id": session_id,
        "analysis": analysis,
        "compliance": compliance,
        "economic": economic,
    }


def _format_compliance_gate_blocking_message(gate_result: Any) -> str:
    """Mensaje UX con reglas 12.1 concretas (no solo el numeral genérico)."""
    from app.agents.compliance_gate import ComplianceGateResult
    from app.core.disqualification_rules import get_disqualification_rules

    if not isinstance(gate_result, ComplianceGateResult):
        return "Pipeline detenido por causas deterministas de descalificación (12.1)."

    rules_by_code = {r.code: r.description for r in get_disqualification_rules()}
    lines = ["Pipeline detenido por causas deterministas de descalificación (12.1):"]
    for code in gate_result.failed_rules:
        ev = next(
            (x for x in (gate_result.evidence or {}).get("rules", []) if x.get("code") == code),
            {},
        )
        reason = str(ev.get("reason") or "").strip() or rules_by_code.get(code, code)
        lines.append(f"- **{code}**: {reason}")

    if any(c in gate_result.failed_rules for c in ("12.1.A", "12.1.P")):
        lines.append(
            "\nSi importaste precios en el chat y la sesión quedó incompleta, ejecuta de nuevo "
            "**Analizar Bases** para restaurar el índice de requisitos antes de **Generar**."
        )
    return "\n".join(lines)


def _economic_waiting_hints_from_output(res: Any) -> Optional[Dict[str, Any]]:
    """
    Extrae del EconomicAgent (AgentOutput o dict) el bloque útil para UI y dictamen
    cuando hay ECONOMIC_GAP (waiting_for_data).
    """
    if res is None:
        return None
    if isinstance(res, dict):
        data = res.get("data")
    else:
        data = getattr(res, "data", None)
    if not isinstance(data, dict):
        return None
    missing = data.get("missing") or []
    return {
        "alertas_contexto_bases": list(data.get("alertas_contexto_bases") or []),
        "contexto_bases_analista": data.get("contexto_bases_analista"),
        "missing_price_count": len(missing) if isinstance(missing, list) else 0,
    }


def _document_quality_waiting_hints_from_output(res: Any) -> Optional[Dict[str, Any]]:
    """
    Extrae hints de gate documental cuando TechnicalWriter/Formats bloquean por calidad.
    """
    if res is None:
        return None
    data = res.get("data") if isinstance(res, dict) else getattr(res, "data", None)
    if not isinstance(data, dict):
        return None
    gate = data.get("document_quality_gate")
    if not isinstance(gate, dict):
        return None
    return {
        "reason": str(gate.get("reason") or ""),
        "metrics": gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {},
    }


def _document_fill_quality_waiting_hints_from_output(
    res: Any, stage: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Extrae hints del gate de llenado documental cuando writers bloquean por calidad final.
    """
    if res is None:
        return None
    data = res.get("data") if isinstance(res, dict) else getattr(res, "data", None)
    if not isinstance(data, dict):
        return None
    gate = data.get("document_fill_quality_gate")
    if not isinstance(gate, dict):
        return None
    issues_raw = gate.get("issues") if isinstance(gate.get("issues"), list) else []
    issues = [i for i in issues_raw if isinstance(i, dict)][:12]
    return {
        "validation_passed": bool(gate.get("validation_passed", True)),
        "blocking_count": int(gate.get("blocking_count", 0) or 0),
        "warning_count": int(gate.get("warning_count", 0) or 0),
        "metrics": gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {},
        "stage": stage or "",
        "issues": issues,
        "experience_summary": data.get("experience_sources_ux") or "",
    }


def _economic_company_data_for_run(
    agent_input: AgentInput,
    *,
    extra: Optional[Dict[str, Any]] = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Datos de empresa para EconomicAgent; en generación no aplica silencio por inventario legal."""
    cd = dict(agent_input.company_data or {})
    if extra:
        cd.update(extra)
    if not cd.get("compliance_master_list") and session_state:
        cm = session_state.get("compliance_master_list") or session_state.get(
            "master_compliance_list"
        )
        if cm:
            cd["compliance_master_list"] = cm
    if (agent_input.mode or "") in ("generation_only", "generation"):
        cd["skip_economic_silence"] = True
    return cd


async def _ensure_economic_snapshot_ready(
    context_manager: MCPContextManager,
    session_id: str,
    agent_input: AgentInput,
    session_state: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Tarea 4: Verifica que el snapshot económico esté listo para generación de documentos.

    Flujo:
    1. Si no existe snapshot → ejecuta EconomicAgent (p. ej. tras limpiar expediente en disco).
    2. Si snapshot tiene total_base >= 0.01 o allow_zero_total_base_ack → listo.
    3. Si snapshot está desactualizado (total_base ~0) → re-sincroniza o re-ejecuta EconomicAgent.
    4. Si EconomicAgent retorna SUCCESS → listo.
    5. Si EconomicAgent retorna WAITING_FOR_DATA → retorna error con lista de precios pendientes.

    Retorna (ready: bool, error_payload: Optional[Dict])
    """
    tasks = list(session_state.get("tasks_completed") or [])
    snapshot: Optional[Dict[str, Any]] = None
    for task in reversed(tasks):
        if task.get("task") == "economic_proposal":
            snapshot = task.get("result") if isinstance(task.get("result"), dict) else None
            break

    user_inputs = (session_state.get("economic_user_inputs") or {})
    allow_zero = bool(user_inputs.get("allow_zero_total_base_ack"))

    if snapshot:
        total_base = float(snapshot.get("total_base") or 0.0)
        snap_status = str(snapshot.get("status") or "")
        has_items = _economic_snapshot_has_line_items(snapshot)
        if snap_status == "complete" and (total_base >= 0.01 or allow_zero):
            if has_items or allow_zero:
                return True, None  # Snapshot listo para EconomicWriter
            logger.warning(
                "orchestrator_economic_snapshot_complete_without_items",
                session_id=session_id,
                total_base=total_base,
            )
    else:
        total_base = 0.0
        snap_status = ""
        logger.warning(
            "orchestrator_economic_snapshot_missing_will_run_agent",
            session_id=session_id,
        )

    # Snapshot ausente o desactualizado: intentar re-sincronizar primero con el refresher
    # (más rápido que re-ejecutar el LLM completo)
    if snapshot:
        try:
            from app.economic_validation.service import refresh_economic_validations_for_session
            await refresh_economic_validations_for_session(context_manager.memory, session_id)
            # Releer snapshot tras el refresh
            fresh_session = await context_manager.memory.get_session(session_id) or {}
            fresh_tasks = list(fresh_session.get("tasks_completed") or [])
            for task in reversed(fresh_tasks):
                if task.get("task") == "economic_proposal":
                    refreshed = task.get("result") if isinstance(task.get("result"), dict) else {}
                    new_total = float(refreshed.get("total_base") or 0.0)
                    new_status = str(refreshed.get("status") or "")
                    if new_status == "complete" and (new_total >= 0.01 or allow_zero):
                        if _economic_snapshot_has_line_items(refreshed) or allow_zero:
                            logger.info(
                                "orchestrator_economic_snapshot_refreshed_ok",
                                session_id=session_id,
                                total_base=new_total,
                            )
                            return True, None
                    break
        except Exception as _refresh_err:
            logger.warning(
                "orchestrator_economic_snapshot_refresh_failed",
                session_id=session_id,
                error=str(_refresh_err),
            )

    # Sin snapshot o refresh insuficiente: ejecutar EconomicAgent
    logger.info(
        "orchestrator_economic_agent_run_for_generation",
        session_id=session_id,
        had_snapshot=bool(snapshot),
        total_base=total_base,
        snap_status=snap_status,
    )
    try:
        from app.agents.economic import EconomicAgent
        econ_input = AgentInput(
            session_id=session_id,
            company_id=agent_input.company_id,
            company_data=_economic_company_data_for_run(
                agent_input,
                extra={
                    "compliance_master_list": (agent_input.company_data or {}).get(
                        "compliance_master_list"
                    )
                    or {},
                },
                session_state=session_state,
            ),
            correlation_id=agent_input.correlation_id,
            job_id=agent_input.job_id,
            mode=agent_input.mode,
        )
        econ_result = await EconomicAgent(context_manager).process(econ_input)

        if econ_result.status == AgentStatus.SUCCESS:
            fresh_session = await context_manager.memory.get_session(session_id) or {}
            snap = _economic_proposal_snapshot(fresh_session)
            fresh_allow_zero = bool(
                (fresh_session.get("economic_user_inputs") or {}).get(
                    "allow_zero_total_base_ack"
                )
            )
            snap_ready = bool(
                snap
                and str(snap.get("status") or "") == "complete"
                and (_economic_snapshot_has_line_items(snap) or fresh_allow_zero)
                and (
                    float(snap.get("total_base") or 0) >= 0.01
                    or fresh_allow_zero
                )
            )
            if snap_ready:
                logger.info(
                    "orchestrator_economic_agent_rerun_success",
                    session_id=session_id,
                )
                return True, None
            logger.info(
                "orchestrator_economic_agent_success_without_snapshot",
                session_id=session_id,
                message=str(econ_result.message or "")[:120],
            )
            return False, {
                "status": "waiting_for_data",
                "stop_reason": "MISSING_ECONOMIC_PROPOSAL",
                "message": (
                    "Antes de generar documentos debes armar la cotización económica. "
                    "Escribe **`generar propuesta económica`** en el chat y captura los precios "
                    "del catálogo de conceptos o sube tu Excel de cotización."
                ),
                "data": econ_result.data if isinstance(econ_result.data, dict) else {},
            }

        # EconomicAgent retornó WAITING_FOR_DATA: hay precios pendientes
        missing = []
        if isinstance(econ_result.data, dict):
            missing = list(econ_result.data.get("missing") or [])
        pending_count = len(missing)
        logger.info(
            "orchestrator_economic_agent_rerun_waiting",
            session_id=session_id,
            pending_count=pending_count,
        )
        return False, {
            "status": "waiting_for_data",
            "stop_reason": "ECONOMIC_PRICES_INCOMPLETE",
            "message": (
                econ_result.message
                or f"Faltan {pending_count} precio(s) por capturar antes de generar documentos. "
                   "Regresa al chat y proporciona los precios solicitados."
            ),
            "data": econ_result.data,
        }

    except Exception as _econ_err:
        logger.error(
            "orchestrator_economic_agent_rerun_error",
            session_id=session_id,
            error=str(_econ_err),
        )
        return False, {
            "status": "error",
            "stop_reason": "ECONOMIC_AGENT_ERROR",
            "message": (
                "Ocurrió un error al recalcular la propuesta económica. "
                "Intenta de nuevo o contacta soporte."
            ),
        }


def _extract_output_data(res: Any) -> Dict[str, Any]:
    if isinstance(res, dict):
        data = res.get("data")
        return data if isinstance(data, dict) else res
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else {}


def _aggregate_health_from_results(results: Dict[str, Any]) -> str:
    """
    Si compliance devolvió partial/fail pero el pipeline siguió, el dictamen global refleja degradación.
    """
    comp = results.get("compliance")
    st = (_result_status_value(comp) or "").lower()
    if st == "partial":
        return "partial"
    if st in ("fail", "failed"):
        return "failed"
    return "ok"


def _notify_job_progress(job_id: Optional[str], stage: str, pct: int, message: str) -> None:
    """
    Actualiza Redis con porcentaje y mensaje para la UI de progreso.
    `pct` se acota a [0, 99] mientras el job sigue en RUNNING (100 lo reserva agents.py al COMPLETED).
    """
    if not job_id:
        return
    from app.services.job_service import update_job_status

    pct_i = max(0, min(99, int(pct)))
    update_job_status(job_id, "RUNNING", {"stage": stage, "pct": pct_i, "message": message})


def _now_utc_iso() -> str:
    """Retorna timestamp UTC en ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def _finalize_stage_telemetry(telemetry: Dict[str, Any], stage_name: str, start_iso: str) -> None:
    """Completa telemetría de etapa con fin y duración en segundos."""
    end_iso = _now_utc_iso()
    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)
    telemetry.setdefault("stages", {})[stage_name] = {
        "start": start_iso,
        "end": end_iso,
        "duration_seconds": round((end_dt - start_dt).total_seconds(), 3),
    }


def _default_generation_jobs() -> List[Dict[str, Any]]:
    """Cola MVP de generación (Hito 3 / ROADMAP)."""
    return [
        {"id": "datagap", "type": "checkpoint", "status": "pending"},
        {"id": "technical", "type": "agent", "status": "pending"},
        {"id": "formats", "type": "agent", "status": "pending"},
        {"id": "economic_writer", "type": "agent", "status": "pending"},
        {"id": "packager", "type": "agent", "status": "pending"},
        {"id": "delivery", "type": "agent", "status": "pending"},
    ]


def _generation_progress_for_step(step: str) -> Tuple[int, int, str, str]:
    """Mapa estable de progreso por etapa para UI durante generación."""
    mapping: Dict[str, Tuple[int, int, str, str]] = {
        "datagap": (91, 92, "Validando datos mínimos para generar propuesta…", "Validación de datos completada."),
        "technical": (93, 94, "Generando propuesta técnica…", "Propuesta técnica completada."),
        "formats": (95, 96, "Generando formatos administrativos…", "Formatos administrativos completados."),
        "economic_writer": (97, 98, "Generando propuesta económica…", "Propuesta económica completada."),
        "packager": (98, 99, "Empaquetando expediente en sobres oficiales…", "Expediente empaquetado correctamente."),
        "delivery": (99, 99, "Preparando guía logística y entregables finales…", "Guía de entrega completada."),
    }
    return mapping.get(step, (92, 99, f"Ejecutando etapa {step}…", f"Etapa {step} completada."))


def _prepare_generation_queue(
    session_state: Dict[str, Any],
    resume_generation: bool,
    mode: str,
    generation_mode: str = "full",
    generation_stream: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Estado de cola de generación. Solo aplica a ``generation`` / ``generation_only``.
    Sin ``resume_generation``: reinicia siempre. Con resume: conserva cola activa.
    F6: soporta ``generation_stream`` y ``job_id`` para colas por stream.
    """
    from app.services.generation_queue_controller import prepare_generation_queue_with_mode

    return prepare_generation_queue_with_mode(
        session_state,
        resume_generation=resume_generation,
        orchestrator_mode=mode,
        generation_mode=generation_mode,
        generation_stream=generation_stream,
        job_id=job_id,
    )


def _gen_job_status(gen_state: Optional[Dict[str, Any]], job_id: str) -> Optional[str]:
    if not gen_state:
        return None
    for j in gen_state.get("jobs") or []:
        if j.get("id") == job_id:
            return str(j.get("status", "pending"))
    return None


def _set_gen_job_status(gen_state: Optional[Dict[str, Any]], job_id: str, status: str) -> None:
    if not gen_state:
        return
    for j in gen_state.get("jobs") or []:
        if j.get("id") == job_id:
            j["status"] = status
            return


def _unblock_generation_jobs_for_economic_retry(gen_state: Optional[Dict[str, Any]]) -> None:
    """Tras snapshot económico listo, reintentar etapas que quedaron ``blocked`` en corridas previas."""
    if not gen_state:
        return
    for job_id in ("economic_writer", "packager", "delivery"):
        if _gen_job_status(gen_state, job_id) in ("blocked", "error"):
            _set_gen_job_status(gen_state, job_id, "pending")


def _economic_snapshot_has_line_items(snapshot: Dict[str, Any]) -> bool:
    items = snapshot.get("items")
    return isinstance(items, list) and len(items) > 0


def _economic_proposal_snapshot(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for task in reversed(list(session_state.get("tasks_completed") or [])):
        if isinstance(task, dict) and task.get("task") == "economic_proposal":
            result = task.get("result")
            return result if isinstance(result, dict) else None
    return None


def _can_continue_generation_past_economic_failure(
    step: str, gen_state: Optional[Dict[str, Any]]
) -> bool:
    """Si técnico y formatos ya están en disco, no abortar todo el pipeline por fallo económico."""
    if step != "economic_writer" or not gen_state:
        return False
    return (
        _gen_job_status(gen_state, "technical") == "done"
        and _gen_job_status(gen_state, "formats") == "done"
    )


async def _enforce_readiness_generation_gate(
    *,
    step: str,
    session_id: str,
    session_state: Dict[str, Any],
    memory: Any,
    company_id: Optional[str],
    correlation_id: str,
    gen_state: Optional[Dict[str, Any]],
    execution_results: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Bloquea writers cuando readiness indica que no procede."""
    from app.services.expediente_readiness_service import (
        generation_step_allowed,
        primary_blocker_for_step,
        readiness_gates_enabled,
        resolve_expediente_readiness,
        stop_reason_for_blocker,
    )

    if not readiness_gates_enabled():
        return None
    if step not in ("technical", "formats", "economic_writer", "packager", "delivery"):
        return None

    company_profile = None
    company_exists = None
    if company_id:
        row = await memory.get_company(str(company_id))
        if row:
            company_exists = True
            company_profile = row.get("master_profile") if isinstance(row.get("master_profile"), dict) else row
        else:
            company_exists = False

    output_root = os.path.join("/data/outputs", session_id)
    readiness = resolve_expediente_readiness(
        {**session_state, "session_id": session_id},
        company_profile=company_profile,
        company_exists=company_exists,
        session_output_path=output_root if os.path.isdir(output_root) else None,
    )
    if generation_step_allowed(readiness, step):
        return None

    blocker = primary_blocker_for_step(readiness, step)
    stop_reason = stop_reason_for_blocker(blocker)
    message = str(
        (blocker or {}).get("message")
        or "La generación no puede continuar hasta resolver los pendientes."
    )
    if gen_state:
        _set_gen_job_status(gen_state, step, "blocked")
    decision = OrchestratorState(
        stop_reason=stop_reason,
        aggregate_health="partial",
        next_steps=[],
        correlation_id=correlation_id,
    ).model_dump()
    updates: Dict[str, Any] = {"last_orchestrator_decision": decision}
    if gen_state:
        updates["generation_state"] = gen_state
    await _safe_save_session(memory, session_id, updates)
    return {
        "status": "waiting_for_data",
        "session_id": session_id,
        "chatbot_message": message,
        "results": {
            k: (v if isinstance(v, dict) else v.model_dump())
            for k, v in execution_results.items()
        },
        "orchestrator_decision": decision,
        "data": {"readiness_blocker": blocker, "readiness": readiness},
    }


def _agent_output_user_message(res: Any) -> str:
    msg = getattr(res, "message", None) or getattr(res, "error", None)
    data = getattr(res, "data", None) if not isinstance(res, dict) else res.get("data")
    if isinstance(data, dict):
        gate = data.get("document_fill_quality_gate")
        if isinstance(gate, dict) and not bool(gate.get("validation_passed", True)):
            from app.services.document_fill_ux_messages import build_fill_quality_user_brief

            issues = gate.get("issues") if isinstance(gate.get("issues"), list) else []
            brief = build_fill_quality_user_brief(
                str(data.get("stage") or "technical"),
                issues,
            )
            return brief["full_message"]
    return str(msg).strip() if msg else "Error desconocido"


def _response_with_generation_state(
    base: Dict[str, Any], session_state: Dict[str, Any], mode: str
) -> Dict[str, Any]:
    out = dict(base)
    if mode in ("generation_only", "generation") and session_state.get("generation_state") is not None:
        out["generation_state"] = session_state["generation_state"]
    
    # Asegurar que los candidatos fluyan hacia el dictamen incluso en estados parciales
    candidates = base.get("fast_track_document_candidates") or session_state.get("document_candidates_v1")
    if candidates:
        out["fast_track_document_candidates"] = candidates
    consolidated = base.get("document_candidates_consolidated") or session_state.get(
        "document_candidates_consolidated"
    )
    if consolidated and isinstance(consolidated, dict) and consolidated.get("sobre_1_tecnico") is not None:
        from app.services.document_deliverable_filter import (
            filter_consolidated_document_candidates,
        )

        out["document_candidates_consolidated"] = filter_consolidated_document_candidates(
            consolidated
        )

    return out


def _apply_filtered_compliance_master_list(
    input_data: Dict[str, Any],
    agent_input: AgentInput,
) -> tuple[Dict[str, Any], AgentInput]:
    """
    Propaga la lista de compliance ya filtrada (sin causales/informativos) hacia
    TechnicalWriter, Formats y EconomicWriter en generación documental.
    """
    cm = input_data.get("compliance_master_list") or {}
    if not any(cm.get(k) for k in ("administrativo", "tecnico", "formatos")):
        return input_data, agent_input
    from app.config.settings import settings
    from app.services.document_deliverable_filter import (
        filter_compliance_for_generation,
        filter_compliance_master_list,
    )

    if getattr(settings, "GENERATION_FILTER_ENABLED", True):
        filtered = filter_compliance_for_generation(cm)
        gen_meta = dict(filtered.pop("_generation_filter_meta", None) or {})
        if gen_meta:
            input_data["generation_filter_meta"] = gen_meta
            logger.info(
                "compliance_generation_filter_applied",
                output_generable=gen_meta.get("output_generable"),
                deduped=gen_meta.get("deduped"),
                skipped_causal=gen_meta.get("skipped_causal"),
            )
    else:
        filtered = filter_compliance_master_list(cm)
    input_data["compliance_master_list"] = filtered
    return input_data, agent_input.model_copy(
        update={
            "company_data": {
                **(agent_input.company_data or {}),
                "compliance_master_list": filtered,
            }
        }
    )


async def _inject_document_inventory_for_generation(
    *,
    memory: Any,
    session_id: str,
    session_state: Dict[str, Any],
    input_data: Dict[str, Any],
    agent_input: AgentInput,
    correlation_id: str,
) -> Tuple[Dict[str, Any], AgentInput, Dict[str, Any]]:
    """
    Inyecta ``document_inventory`` en ``company_data`` antes de los writers.

    Cascada HRU: ``input_data`` → ``session_state`` → servicio canónico.
    Sin mapas por licitación; aplica a cualquier modalidad (servicios, obra, bienes).
    """
    dump: Optional[Dict[str, Any]] = None
    for src in (
        input_data.get("document_inventory"),
        session_state.get("document_inventory"),
    ):
        if isinstance(src, dict) and isinstance(src.get("items"), list) and src.get("items"):
            dump = src
            break

    if dump is None and settings.DOCUMENT_INVENTORY_SERVICE_ENABLED:
        try:
            from app.services.document_inventory_service import DocumentInventoryService

            inv = await DocumentInventoryService.build_for_session(
                session_id,
                use_llm=bool(settings.DOCUMENT_INVENTORY_SERVICE_USE_LLM),
                correlation_id=correlation_id,
            )
            dump = inv.model_dump(mode="json")
            input_data["document_inventory"] = dump
            session_state["document_inventory"] = dump
        except Exception as exc:
            logger.warning(
                "document_inventory_pre_generation_build_failed",
                session_id=session_id,
                error=str(exc)[:200],
            )

    if isinstance(dump, dict) and dump.get("items"):
        agent_input = agent_input.model_copy(
            update={
                "company_data": {
                    **(agent_input.company_data or {}),
                    "document_inventory": dump,
                }
            }
        )
        logger.info(
            "document_inventory_injected_for_generation",
            session_id=session_id,
            items=len(dump.get("items") or []),
        )
    return input_data, agent_input, session_state


async def _safe_save_session(
    memory: Any,
    session_id: str,
    updates: Dict[str, Any],
) -> None:
    """Guarda campos específicos en session_state sin sobreescribir tasks_completed.

    Lee el estado fresco desde la BD, aplica solo los campos indicados en `updates`,
    y guarda. Esto evita la race condition donde el orquestador sobreescribe
    tasks_completed que los agentes guardaron vía record_task_completion.

    Args:
        memory: Adaptador de memoria (PostgresMemoryAdapter).
        session_id: ID de la sesión.
        updates: Dict con los campos a actualizar (nunca incluir tasks_completed aquí).
    """
    fresh = await memory.get_session(session_id) or {}
    for key, value in updates.items():
        if key == "tasks_completed":
            continue
        
        # DEBUG LOG: Monitorear cambios en la cola de preguntas
        if key == "pending_questions":
            from app.services.hitl_queue_service import normalize_pending_queue, sanitize_chat_pending_questions

            q_list = sanitize_chat_pending_questions(value or [], fresh)
            q_list = normalize_pending_queue(q_list)
            value = q_list
            logger.info("safe_save_pending_questions", 
                        session_id=session_id, 
                        count=len(q_list),
                        first_id=q_list[0].get("question_id") if q_list else "empty")
            
        fresh[key] = value
    await memory.save_session(session_id, fresh)


def _extract_documentos(agent_result: Any) -> List[Dict[str, Any]]:
    """Extrae la lista de documentos generados desde el output de un agente escritor.

    Soporta tanto AgentOutput (con .data) como dict legacy.
    Retorna lista vacía si el agente no completó o no generó documentos.

    Args:
        agent_result: Output del agente (AgentOutput o dict).

    Returns:
        Lista de dicts con campos nombre, ruta, status.
    """
    if agent_result is None:
        return []
    data: Dict[str, Any] = {}
    if hasattr(agent_result, "data") and isinstance(agent_result.data, dict):
        data = agent_result.data
    elif isinstance(agent_result, dict):
        data = agent_result.get("data", agent_result)
    return data.get("documentos", []) if isinstance(data, dict) else []


def _coerce_compliance_data(result: Any) -> Dict[str, Any]:
    """Obtiene data de compliance desde AgentOutput o dict legacy."""
    if result is None:
        return {}
    if isinstance(result, dict):
        data = result.get("data")
    else:
        data = getattr(result, "data", None)
    return data if isinstance(data, dict) else {}


class OrchestratorAgent(BaseAgent):
    """
    Agente 0: Orquestador Supervisor.
    Coordina y asigna tareas a los agentes especializados evaluando los resultados.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="orchestrator_001",
            name="Orquestador Supervisor",
            description="Controlador central que supervisa y encadena el flujo de la licitación.",
            context_manager=context_manager
        )
        self.available_agents = {}
        self.context_manager = context_manager

    async def _proactive_injection_checkpoint(self, session_id: str) -> None:
        """Asegura que las preguntas del Planner (si existen) estén al inicio de la cola."""
        try:
            fresh = await self.context_manager.memory.get_session(session_id)
            if not fresh: return
            
            plan_raw = fresh.get("intake_plan")
            plan = plan_raw if isinstance(plan_raw, dict) else {}
            planner_questions = [q for q in list(plan.get("questions") or []) if isinstance(q, dict)]
            if not planner_questions or bool(settings.INTAKE_PLANNER_SHADOW_MODE):
                return
                
            existing_pending = [q for q in list(fresh.get("pending_questions") or []) if isinstance(q, dict)]
            
            def _get_q_key(q):
                if not isinstance(q, dict):
                    return ""
                return str(q.get("question_id") or q.get("field") or q.get("field_target") or "")

            # HITO: Purgar de la cola actual cualquier pregunta que el Planner haya movido al checklist corporativo
            corp_checklist = [c for c in list(plan.get("checklist_corporativo") or []) if isinstance(c, dict)]
            corp_keys = {_get_q_key(c) for c in corp_checklist if _get_q_key(c)}
            
            from app.services.hitl_queue_service import merge_pending_queues, should_exclude_from_chat_queue

            existing_pending = [q for q in existing_pending if _get_q_key(q) not in corp_keys]
            existing_pending = [q for q in existing_pending if not should_exclude_from_chat_queue(q)]

            existing_keys = {_get_q_key(q) for q in existing_pending if _get_q_key(q)}
            new_to_add = [
                q for q in planner_questions
                if _get_q_key(q) not in existing_keys and not should_exclude_from_chat_queue(q)
            ]

            merged = merge_pending_queues(existing_pending, new_to_add)

            # Guardamos siempre porque pudo haber purgas de checklist_corporativo
            await _safe_save_session(self.context_manager.memory, session_id, {"pending_questions": merged})
            logger.info("proactive_injection_success", session_id=session_id, added=len(new_to_add), purged_corp=len(corp_keys))
        except Exception as e:
            logger.warning("proactive_injection_failed", session_id=session_id, error=str(e))

    def _profile_document(self, input_data: Dict, session_state: Dict) -> Dict[str, Any]:
        """Perfilado ligero de complejidad y foco del documento."""
        all_reqs_count = 0
        results = session_state.get("execution_results", {})
        if "compliance" in results:
            res = results["compliance"]
            data = res.data if hasattr(res, 'data') else (res.get("data") if isinstance(res, dict) else {})
            all_reqs_count = sum(len(v) for v in data.values() if isinstance(v, list))
        
        complexity = "medium"
        if all_reqs_count > 30: complexity = "high"
        elif all_reqs_count > 0 and all_reqs_count < 10: complexity = "low"
        
        is_cost_focus = False
        company_data = input_data.get("company_data", {})
        if "cost" in str(company_data).lower() or "price" in str(company_data).lower():
            is_cost_focus = True
            
        return {
            "complexity": complexity,
            "is_cost_focus": is_cost_focus,
            "estimated_reqs": all_reqs_count
        }

    def _apply_short_circuit(self, config: PipelineConfig, results: Dict, confidence_summary: Optional[Dict]) -> Optional[Dict]:
        """Evalúa reglas de short-circuit sobre resultados actuales."""
        if not config.short_circuit_rules: return None
        triggered = []
        for rule in config.short_circuit_rules:
            if rule.condition_type == ConditionType.LOW_CONFIDENCE_AVG and confidence_summary:
                if confidence_summary.get("avg_confidence", 1.0) < rule.threshold:
                    triggered.append(rule)
            elif rule.condition_type == ConditionType.MISSING_CRITICAL_DATA:
                if any(r.status == AgentStatus.WAITING_FOR_DATA for r in results.values() if hasattr(r, 'status')):
                    triggered.append(rule)
        
        if not triggered: return None
        severity = {"stop": 3, "escalate": 2, "skip_stage": 1, "continue": 0}
        top_rule = max(triggered, key=lambda r: severity.get(r.action.value, 0))
        return {
            "rule_name": top_rule.name,
            "action": top_rule.action.value,
            "target": top_rule.target_stage
        }

    def _should_execute_stage(self, stage_name: str, config: PipelineConfig, stages_skipped: List[str]) -> bool:
        """Determina si un stage debe ejecutarse según el plan adaptativo."""
        if not settings.ADAPTIVE_ORCHESTRATOR_ENABLED:
            return True
        should = stage_name in config.stages
        if not should:
            if settings.ADAPTIVE_PIPELINE_SAFE_MODE:
                logger.info("adaptive_stage_skip_suggested", stage=stage_name)
                return True
            else:
                if len(stages_skipped) < settings.ADAPTIVE_MAX_SKIPS:
                    logger.info("adaptive_stage_skipped", stage=stage_name)
                    stages_skipped.append(stage_name)
                    return False
                return True
        return True

    async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        correlation_id = input_data.get("correlation_id") or generate_correlation_id()
        try:
            raw_company = dict(input_data.get("company_data") or {})
            _cm = input_data.get("compliance_master_list")
            if _cm is not None:
                raw_company["compliance_master_list"] = _cm
            _mode = str(raw_company.get("mode") or "full")
            _allowed_modes = ("full", "analysis_only", "generation", "generation_only")
            if _mode not in _allowed_modes:
                return {
                    "status": "error",
                    "session_id": session_id,
                    "message": f"Modo inválido o no soportado: {_mode}",
                    "orchestrator_decision": {
                        "stop_reason": "INVALID_MODE",
                        "aggregate_health": "failed",
                    },
                    "results": {},
                }
            agent_input = AgentInput(
                session_id=session_id,
                company_id=str(input_data.get("company_id")) if input_data.get("company_id") else None,
                company_data=raw_company,
                mode=_mode,
                resume_generation=input_data.get("resume_generation", False),
                correlation_id=correlation_id,
                job_id=input_data.get("job_id"),
            )
        except Exception as e:
            logger.error("orchestrator_failed", session_id=session_id, error=str(e))
            
            # Reportar a Redis para el Traceback Forense (Bajo protección)
            try:
                from app.services.job_service import update_job_status
                last_st = stages_executed[-1] if 'stages_executed' in locals() and stages_executed else "init"
                
                j_id = None
                if 'agent_input' in locals(): j_id = agent_input.job_id
                elif 'input_data' in locals(): j_id = input_data.get("job_id")
                
                update_job_status(
                    job_id=j_id,
                    status="FAILED",
                    error=str(e),
                    forensic_traceback={
                        "last_stage": last_st,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
            except Exception as inner_e:
                logger.error(f"Error registrando fallo en Redis: {inner_e}")
            
            err_txt = str(e)
            stop = "INVALID_MODE" if "Modo inválido" in err_txt else "ERROR"
            return {
                "status": "error",
                "session_id": session_id,
                "message": err_txt,
                "orchestrator_decision": {"stop_reason": stop, "aggregate_health": "failed"},
            }

        async with agent_span(logger, self.agent_id, session_id, correlation_id):
            mode = agent_input.mode
            session_state: Dict[str, Any] = {}
            raw_session_state = await self.context_manager.memory.get_session(session_id)
            if not raw_session_state:
                await self.context_manager.initialize_session(session_id, input_data)
                session_state = await self.context_manager.memory.get_session(session_id)
            else:
                session_state, _ = SessionStateMigrator.migrate(session_id, raw_session_state)

            if not agent_input.company_id:
                _session_company_id = (
                    session_state.get("company_id")
                    or (session_state.get("initial_data") or {}).get("company_id")
                    or (session_state.get("global_inputs") or {}).get("company_id")
                )
                if _session_company_id:
                    agent_input = agent_input.model_copy(
                        update={"company_id": str(_session_company_id)}
                    )
                    logger.info(
                        "orchestrator_company_id_hydrated_from_session",
                        session_id=session_id,
                        company_id=str(_session_company_id),
                        resume_generation=bool(agent_input.resume_generation),
                    )

            _session_docs = await self.context_manager.memory.get_documents(session_id) or []
            from app.services.session_bases_analysis_invalidation import (
                bases_analysis_committed,
                bases_fingerprint_matches_stored,
                sync_bases_analysis_state,
            )

            session_state, _bases_sync = await sync_bases_analysis_state(
                self.context_manager.memory,
                session_id,
                session_state,
                _session_docs,
                persist=True,
            )
            if _bases_sync.get("invalidated"):
                logger.info(
                    "bases_analysis_invalidated",
                    session_id=session_id,
                    reason=_bases_sync.get("reason"),
                    fingerprint=_bases_sync.get("fingerprint"),
                )
            session_state = await self.context_manager.memory.get_session(session_id) or session_state

            # --- HARD RESET (Hito A1): solo si bases cambiaron; preserva capturas HITL económicas ---
            from app.services.session_bases_analysis_invalidation import should_hard_reset_session_artifacts

            if should_hard_reset_session_artifacts(
                mode=mode,
                resume_generation=bool(agent_input.resume_generation),
                session_state=session_state,
                documents=_session_docs,
            ):
                logger.info("orchestrator_hard_reset_session_artifacts", session_id=session_id)
                reset_fields = {
                    "pending_questions": [],
                    "document_inventory": {"items": []},
                    "document_candidates_v1": [],
                    "intake_plan": {},
                    "economic_user_inputs": {},
                }
                session_state.update(reset_fields)
                await _safe_save_session(self.context_manager.memory, session_id, reset_fields)
                session_state = await self.context_manager.memory.get_session(session_id) or session_state
            elif mode == "full" and not agent_input.resume_generation:
                logger.info(
                    "orchestrator_hard_reset_skipped_bases_unchanged",
                    session_id=session_id,
                )
            
            context = await self.context_manager.get_global_context(session_id)
            tasks_completed = context.get("session_state", {}).get("tasks_completed", [])
            execution_results = {}
            next_steps = []
            telemetry: Dict[str, Any] = {"stages": {}, "llm_calls_estimate": 0}
            fast_track_candidates: Optional[Dict[str, Any]] = None
            # Cola de generación: se reasigna en modo generation*; en analysis_only puede quedar None.
            _raw_gen = session_state.get("generation_state")
            gen_state: Optional[Dict[str, Any]] = _raw_gen if isinstance(_raw_gen, dict) else None

            doc_profile = self._profile_document(input_data, session_state)
            pipeline_config = PipelineConfigurator.configure(doc_profile, mode=mode)
            # --- LÓGICA DE REANUDACIÓN (RESUME) ---
            # generation_only/generation: reutilizar hitos ya persistidos (analysis/compliance/economic)
            # para no volver a ejecutar ~15 min de Map-Reduce antes de generar documentos.
            stages_executed, stages_skipped, rules_triggered = [], [], []
            completed_stages = set()
            reuse_prior_stages = agent_input.resume_generation or mode in (
                "generation_only",
                "generation",
            )
            # Si no es resume_generation, forzamos la ejecución de análisis incluso en modo full
            if not agent_input.resume_generation and mode in ("full", "analysis_only"):
                reuse_prior_stages = False
            if reuse_prior_stages:
                completed_stages = _collect_completed_stages_from_session(session_state)
                if not bases_fingerprint_matches_stored(session_state, _session_docs):
                    completed_stages -= {"analysis", "compliance"}
                    logger.info(
                        "resume_stages_trimmed_stale_bases",
                        session_id=session_id,
                        mode=mode,
                    )
                elif not bases_analysis_committed(session_state):
                    completed_stages -= {"analysis", "compliance"}
                    logger.info(
                        "resume_stages_trimmed_pending_reanalysis",
                        session_id=session_id,
                        mode=mode,
                    )
                for completed_stage in sorted(completed_stages):
                    logger.info(
                        "resume_skip_stage",
                        stage=completed_stage,
                        session_id=session_id,
                        mode=mode,
                    )
                if (
                    mode in ("generation_only", "generation")
                    and "compliance" not in completed_stages
                    and _session_has_compliance_evidence(session_state)
                ):
                    completed_stages.add("compliance")
                    logger.info(
                        "compliance_inferred_from_session_artifacts",
                        session_id=session_id,
                    )
                if (
                    mode in ("generation_only", "generation")
                    and "analysis" not in completed_stages
                    and _session_has_compliance_evidence(session_state)
                ):
                    completed_stages.add("analysis")

            # --- VALIDACIÓN PREREQUISITO 1: generation_only/generation requiere company_id ---
            # Sin empresa no hay master_profile → los agentes de generación no pueden
            # producir documentos con datos corporativos correctos (RFC, razón social, etc.)
            if mode in ("generation_only", "generation") and not agent_input.company_id:
                logger.error(
                    "generation_missing_company_id",
                    session_id=session_id,
                    mode=mode,
                )
                decision = OrchestratorState(
                    stop_reason="MISSING_COMPANY_ID",
                    aggregate_health="failed",
                    next_steps=[],
                    correlation_id=correlation_id,
                ).model_dump()
                await _safe_save_session(
                    self.context_manager.memory, session_id,
                    {"last_orchestrator_decision": decision}
                )
                return {
                    "status": "error",
                    "session_id": session_id,
                    "message": (
                        "No se puede generar documentos sin seleccionar una empresa. "
                        "Por favor selecciona tu empresa en el menú superior antes de generar la propuesta."
                    ),
                    "orchestrator_decision": decision,
                }

            session_state = await _persist_compliance_recovery_if_needed(
                self.context_manager.memory, session_id, session_state
            )
            if not bases_analysis_committed(session_state):
                session_state.pop("compliance_master_list", None)
                session_state.pop("compliance_recovery_source", None)
            if _compliance_list_from_session(session_state) and "compliance" not in completed_stages:
                if bases_analysis_committed(session_state) and bases_fingerprint_matches_stored(
                    session_state, _session_docs
                ):
                    completed_stages.add("compliance")
                    logger.info(
                        "compliance_stage_inferred_from_recovery",
                        session_id=session_id,
                        source=session_state.get("compliance_recovery_source"),
                    )
                else:
                    logger.info(
                        "compliance_recovery_skipped_stale_bases",
                        session_id=session_id,
                    )

            # --- VALIDACIÓN PREREQUISITO 2: generation_only requiere compliance previo ---
            # Sin datos de compliance no hay lista maestra → los agentes de generación
            # no pueden producir documentos correctos. Req 1.3, 1.5
            if mode in ("generation_only", "generation") and "compliance" not in completed_stages:
                if _session_has_compliance_evidence(session_state):
                    completed_stages.add("compliance")
                    logger.warning(
                        "generation_compliance_inferred_late",
                        session_id=session_id,
                    )
                else:
                    logger.error(
                        "generation_missing_prior_compliance",
                        session_id=session_id,
                        mode=mode,
                        completed_stages=list(completed_stages),
                    )
                    decision = OrchestratorState(
                        stop_reason="MISSING_PRIOR_ANALYSIS",
                        aggregate_health="failed",
                        next_steps=[],
                        correlation_id=correlation_id,
                    ).model_dump()
                    await _safe_save_session(
                        self.context_manager.memory, session_id,
                        {"last_orchestrator_decision": decision}
                    )
                    return {
                        "status": "error",
                        "session_id": session_id,
                        "message": (
                            "No se puede generar documentos sin un análisis de compliance previo. "
                            "Ejecuta primero 'Analizar Bases' para indexar los requisitos de la licitación."
                        ),
                        "orchestrator_decision": decision,
                    }

            # ── FIX LOGO: Enriquecer company_data con perfil fresco de la DB ──────────
            # El frontend envía company_data con docs como entero (conteo) y master_profile
            # potencialmente desactualizado. Los agentes de generación necesitan:
            #   - master_profile.logo  → ruta en disco del logotipo
            #   - docs["LOGOTIPO"]["path"] → fallback si logo no está en master_profile
            # Solución: leer company fresco de la DB y fusionar con el company_data del request.
            if agent_input.company_id and mode in ("generation_only", "generation", "full"):
                try:
                    _fresh_company = await self.context_manager.memory.get_company(
                        agent_input.company_id
                    )
                    if _fresh_company and isinstance(_fresh_company, dict):
                        _fresh_profile = _fresh_company.get("master_profile") or {}
                        _fresh_docs = _fresh_company.get("docs") or {}

                        # Inyectar logo en master_profile si no viene del frontend
                        _current_profile = dict(agent_input.company_data.get("master_profile") or {})
                        if not _current_profile.get("logo"):
                            # Prioridad 1: master_profile.logo de la DB
                            if _fresh_profile.get("logo"):
                                _current_profile["logo"] = _fresh_profile["logo"]
                            # Prioridad 2: docs["LOGOTIPO"]["path"] de la DB
                            elif isinstance(_fresh_docs.get("LOGOTIPO"), dict):
                                _logo_path = _fresh_docs["LOGOTIPO"].get("path")
                                if _logo_path:
                                    _current_profile["logo"] = _logo_path

                        # Fusionar: la DB gana sobre placeholders del frontend (N/A, vacío, etc.)
                        for _field in (
                            "razon_social", "rfc", "representante_legal",
                            "domicilio_fiscal", "tipo", "logo",
                        ):
                            _cur = _current_profile.get(_field)
                            _fresh = _fresh_profile.get(_field)
                            if _fresh and (
                                not is_usable_profile_field_value(_cur)
                                or not str(_cur or "").strip()
                            ):
                                _current_profile[_field] = _fresh

                        # Actualizar agent_input con el perfil enriquecido y docs reales
                        agent_input = agent_input.model_copy(
                            update={
                                "company_data": {
                                    **agent_input.company_data,
                                    "master_profile": _current_profile,
                                    "docs": _fresh_docs,  # docs real (dict), no el conteo del frontend
                                }
                            }
                        )
                        logger.info(
                            "orchestrator_company_enriched",
                            session_id=session_id,
                            company_id=agent_input.company_id,
                            has_logo=bool(_current_profile.get("logo")),
                            logo_path=str(_current_profile.get("logo") or "")[:80],
                        )
                        if agent_input.company_id and not session_state.get("company_id"):
                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                {"company_id": str(agent_input.company_id)},
                            )
                            session_state["company_id"] = str(agent_input.company_id)
                except Exception as _enrich_err:
                    # No bloquear el pipeline si el enriquecimiento falla
                    logger.warning(
                        "orchestrator_company_enrich_failed",
                        session_id=session_id,
                        company_id=agent_input.company_id,
                        error=str(_enrich_err),
                    )

            if mode in ("generation_only", "generation") and agent_input.company_id:
                try:
                    from app.services.company_binding_service import ensure_company_bound_for_generation

                    _bind_res = await ensure_company_bound_for_generation(
                        self.context_manager.memory,
                        session_id,
                        str(agent_input.company_id),
                        session_state,
                    )
                    if _bind_res:
                        session_state = await self.context_manager.memory.get_session(session_id) or session_state
                        logger.info(
                            "orchestrator_company_binding_applied",
                            session_id=session_id,
                            company_id=str(agent_input.company_id),
                            company_changed=bool(_bind_res.get("company_changed")),
                        )
                except ValueError as _bind_err:
                    if "COMPANY_NOT_FOUND" in str(_bind_err):
                        decision = OrchestratorState(
                            stop_reason="COMPANY_ORPHAN_ID",
                            aggregate_health="failed",
                            next_steps=[],
                            correlation_id=correlation_id,
                        ).model_dump()
                        await _safe_save_session(
                            self.context_manager.memory,
                            session_id,
                            {"last_orchestrator_decision": decision},
                        )
                        return {
                            "status": "error",
                            "session_id": session_id,
                            "message": (
                                "La empresa seleccionada no existe en el catálogo. "
                                "Selecciona una empresa válida antes de generar."
                            ),
                            "orchestrator_decision": decision,
                        }
                    raise

            # --- TRIAGE NORMATIVO (PIPELINE PASO 1) ---
            triage_context = session_state.get("triage_context")
            if triage_context:
                agent_input.triage_context = triage_context

            # Triage guardado antes de taxonomy_allowlist / must_have_policy: completar y persistir
            # para que Compliance reciba matriz y allowlist (evita legfis/anchor en cero silencioso).
            if triage_context and mode in ("full", "analysis_only"):
                law = triage_context.get("law", "LAASSP")
                cat = triage_context.get("tender_category", "BIENES")
                triage_dirty = False
                if not triage_context.get("taxonomy_allowlist"):
                    triage_context["taxonomy_allowlist"] = await TenderRouterService.get_taxonomy_allowlist(
                        law, cat
                    )
                    triage_dirty = True
                if not triage_context.get("must_have_policy"):
                    triage_context["must_have_policy"] = await TenderRouterService.get_must_have_policy(law, cat)
                    triage_dirty = True
                if not triage_context.get("must_have"):
                    triage_context["must_have"] = await TenderRouterService.get_must_have_list(law, cat)
                    triage_dirty = True
                if not triage_context.get("critical_rules"):
                    triage_context["critical_rules"] = await TenderRouterService.get_critical_rules(law)
                    triage_dirty = True
                if triage_dirty:
                    await _safe_save_session(
                        self.context_manager.memory, session_id, {"triage_context": triage_context}
                    )
                    agent_input.triage_context = triage_context
                    logger.info(
                        "orchestrator_triage_enriched_legacy",
                        session_id=session_id,
                        law=law,
                        category=cat,
                    )

            if not triage_context and mode in ("full", "analysis_only"):
                from app.services.vector_service import VectorDbServiceClient
                _notify_job_progress(agent_input.job_id, "triage", 25, "Ejecutando triage normativo...")
                vdb = VectorDbServiceClient()
                triage_context = await TenderRouterService.get_triage(session_id, vdb)
                
                # Inyectar matriz de obligatorios y reglas
                triage_context["must_have"] = await TenderRouterService.get_must_have_list(
                    triage_context.get("law", "LAASSP"), 
                    triage_context.get("tender_category", "BIENES")
                )
                triage_context["must_have_policy"] = await TenderRouterService.get_must_have_policy(
                    triage_context.get("law", "LAASSP"),
                    triage_context.get("tender_category", "BIENES")
                )
                triage_context["critical_rules"] = await TenderRouterService.get_critical_rules(
                    triage_context.get("law", "LAASSP")
                )
                triage_context["taxonomy_allowlist"] = await TenderRouterService.get_taxonomy_allowlist(
                    triage_context.get("law", "LAASSP"),
                    triage_context.get("tender_category", "BIENES"),
                )

                await _safe_save_session(self.context_manager.memory, session_id, {"triage_context": triage_context})
                logger.info("orchestrator_triage_stored", session_id=session_id, triage=triage_context)
                
                # Actualizar agent_input para los siguientes agentes
                agent_input.triage_context = triage_context

            # --- ANALISIS CON BACKTRACKING ---
            bt_iterations = 0
            max_bt = settings.BACKTRACK_MAX_ITERATIONS if settings.BACKTRACKING_ENABLED else 0
            bt_history = []
            refinement_data = None
            while bt_iterations <= max_bt:
                # Analyst
                if self._should_execute_stage("analysis", pipeline_config, stages_skipped) and "analysis" not in completed_stages:
                    from app.agents.analyst import AnalystAgent
                    if bt_iterations > 0:
                        agent_input.refinement = refinement_data
                    _t0_iso = _now_utc_iso()
                    _notify_job_progress(
                        agent_input.job_id,
                        "analysis",
                        32,
                        "Agente analista: extrayendo requisitos de las bases…",
                    )
                    res = await AnalystAgent(self.context_manager).process(agent_input)
                    _finalize_stage_telemetry(telemetry, "analysis", _t0_iso)
                    execution_results["analysis"] = res
                    stages_executed.append("analysis")
                    next_steps.append(f"analysis_it_{bt_iterations}")
                    
                    # CHECKPOINT: Analyst (Hito forense enriquecido)
                    await self.context_manager.record_task_completion(
                        session_id=session_id,
                        task_name="stage_completed:analysis",
                        result=res if isinstance(res, dict) else res.model_dump()
                    )
                    try:
                        from app.services.economic_post_analysis_hook import run_economic_post_analysis_hook

                        _sess_eco = await self.context_manager.memory.get_session(session_id) or {}
                        _eco_hook = await run_economic_post_analysis_hook(
                            self.context_manager.memory,
                            session_id,
                            _sess_eco,
                        )
                        if _eco_hook:
                            execution_results["economic_post_analysis_hook"] = _eco_hook
                    except Exception as _eco_hook_exc:
                        logger.warning(
                            "economic_post_analysis_hook_failed",
                            session_id=session_id,
                            error=str(_eco_hook_exc)[:200],
                        )
                    try:
                        from app.services.technical_post_analysis_hook import (
                            run_technical_post_analysis_hook,
                        )

                        _sess_tech = await self.context_manager.memory.get_session(session_id) or {}
                        _tech_hook = await run_technical_post_analysis_hook(
                            self.context_manager.memory,
                            session_id,
                            _sess_tech,
                        )
                        if _tech_hook:
                            execution_results["technical_post_analysis_hook"] = _tech_hook
                    except Exception as _tech_hook_exc:
                        logger.warning(
                            "technical_post_analysis_hook_failed",
                            session_id=session_id,
                            error=str(_tech_hook_exc)[:200],
                        )
                    try:
                        from app.services.convocatoria_briefing_service import (
                            run_convocatoria_briefing_post_analysis_hook,
                        )

                        _sess_brief = await self.context_manager.memory.get_session(session_id) or {}
                        _brief_hook = await run_convocatoria_briefing_post_analysis_hook(
                            self.context_manager.memory,
                            session_id,
                            _sess_brief,
                        )
                        if _brief_hook:
                            execution_results["convocatoria_briefing_hook"] = _brief_hook
                    except Exception as _brief_hook_exc:
                        logger.warning(
                            "convocatoria_briefing_hook_failed",
                            session_id=session_id,
                            error=str(_brief_hook_exc)[:200],
                        )
                    try:
                        from app.checklist.submission_checklist_service import (
                            upsert_checklist_from_cronograma,
                        )

                        analyst_data = (
                            res.data
                            if hasattr(res, "data")
                            else (res.get("data") if isinstance(res, dict) else None)
                        )
                        cron = (
                            analyst_data.get("cronograma")
                            if isinstance(analyst_data, dict)
                            else None
                        )
                        if isinstance(cron, dict):
                            sess_snap = await self.context_manager.memory.get_session(session_id) or {}
                            await upsert_checklist_from_cronograma(
                                self.context_manager.memory,
                                session_id,
                                cron,
                                licitation_id=sess_snap.get("name"),
                                merge=bool(sess_snap.get("submission_checklist")),
                            )
                    except Exception as e:
                        logger.warning(
                            "submission_checklist_init_failed",
                            session_id=session_id,
                            error=str(e),
                        )
                    _notify_job_progress(
                        agent_input.job_id,
                        "analysis",
                        40,
                        "Análisis de bases listo; iniciando auditoría forense…",
                    )

                    sc = self._apply_short_circuit(pipeline_config, execution_results, None)
                    if sc and sc["action"] == "stop":
                        rules_triggered.append(sc["rule_name"])
                        break
                elif "analysis" in completed_stages:
                    # Último hito válido (append puede dejar intentos viejos delante)
                    execution_results["analysis"] = next(
                        (t["result"] for t in reversed(tasks_completed) if t.get("task") == "stage_completed:analysis"),
                        {"status": "resumed"},
                    )

                # Compliance
                if self._should_execute_stage("compliance", pipeline_config, stages_skipped) and "compliance" not in completed_stages:
                    from app.agents.compliance import ComplianceAgent
                    if bt_iterations > 0:
                        agent_input.refinement = refinement_data
                    _t0_iso = _now_utc_iso()
                    _notify_job_progress(
                        agent_input.job_id,
                        "compliance",
                        41,
                        "Auditoría forense en curso (map-reduce por zonas)…",
                    )
                    try:
                        res = await ComplianceAgent(self.context_manager).process(agent_input)
                        _finalize_stage_telemetry(telemetry, "compliance", _t0_iso)
                        execution_results["compliance"] = res
                        stages_executed.append("compliance")
                        input_data["compliance_master_list"] = (
                            res.data if hasattr(res, "data") else (res.get("data", {}) if isinstance(res, dict) else {})
                        )
                        next_steps.append(f"compliance_it_{bt_iterations}")

                        await self.context_manager.record_task_completion(
                            session_id=session_id,
                            task_name="stage_completed:compliance",
                            result=res if isinstance(res, dict) else res.model_dump(),
                        )
                        try:
                            from app.services.analysis_artifacts_rehydrate_service import (
                                rehydrate_after_analysis_pipeline,
                            )

                            _rehydrate_cid = (
                                getattr(agent_input, "company_id", None)
                                or session_state.get("company_id")
                                or (session_state.get("initial_data") or {}).get("company_id")
                                or (session_state.get("global_inputs") or {}).get("company_id")
                            )
                            _rehydrate = await rehydrate_after_analysis_pipeline(
                                self.context_manager.memory,
                                session_id,
                                company_id=str(_rehydrate_cid) if _rehydrate_cid else None,
                                commit_snapshot=True,
                            )
                            if not _rehydrate.success:
                                logger.warning(
                                    "analysis_rehydrate_incomplete",
                                    session_id=session_id,
                                    error=_rehydrate.error,
                                    failed_steps=[
                                        s.step for s in _rehydrate.steps if not s.ok
                                    ],
                                )
                            else:
                                logger.info(
                                    "analysis_rehydrate_ok",
                                    session_id=session_id,
                                    hitos=_rehydrate.counts.get("hitos"),
                                    junta=_rehydrate.counts.get("junta_items"),
                                    snapshot_committed=_rehydrate.snapshot_committed,
                                )
                        except Exception as _reh_exc:
                            logger.warning(
                                "analysis_rehydrate_failed",
                                session_id=session_id,
                                error=str(_reh_exc)[:200],
                            )
                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                {
                                    "last_orchestrator_decision": {
                                        "stop_reason": "ANALYSIS_REHYDRATE_INCOMPLETE",
                                        "aggregate_health": "failed",
                                        "error": str(_reh_exc)[:200],
                                    },
                                },
                            )
                    except Exception as e:
                        logger.error("compliance_stage_failed", session_id=session_id, error=str(e))
                        execution_results["compliance"] = {
                            "status": "error",
                            "message": str(e),
                            "data": {},
                        }
                        input_data["compliance_master_list"] = {}
                        next_steps.append(f"compliance_it_{bt_iterations}_failed")
                elif "compliance" in completed_stages:
                    # Recuperar data para EconomicAgent y posteriores (último compliance completado)
                    comp_task = next(
                        (t for t in reversed(tasks_completed) if t.get("task") == "stage_completed:compliance"),
                        {},
                    )
                    res_data = comp_task.get("result", {})
                    execution_results["compliance"] = res_data
                    # RECONSTRUCCIÓN CRÍTICA: Inyectar la master_list para el flujo downstream
                    input_data["compliance_master_list"] = res_data.get("data", {})
                    logger.info("resume_data_reconstructed", stage="compliance", session_id=session_id)

                if settings.FAST_TRACK_DOC_CANDIDATES_ENABLED:
                    try:
                        # Extraer datos de cumplimiento de forma robusta
                        comp_res = execution_results.get("compliance", {})
                        comp_data = comp_res.get("data", {}) if isinstance(comp_res, dict) else (getattr(comp_res, "data", {}) if comp_res else {})
                        
                        if comp_data and (comp_data.get("administrativo") or comp_data.get("tecnico") or comp_data.get("formatos")):
                            from app.services.document_deliverable_filter import (
                                filter_compliance_master_list,
                            )

                            comp_data = filter_compliance_master_list(comp_data)
                            try:
                                from app.services.compliance_source_enrichment import (
                                    enrich_compliance_archivo_fuente,
                                )
                                from app.services.session_template_catalog import (
                                    build_session_template_catalog,
                                )

                                _docs_for_catalog = (
                                    await self.context_manager.memory.get_documents(
                                        session_id
                                    )
                                )
                                comp_data = enrich_compliance_archivo_fuente(
                                    comp_data, _docs_for_catalog
                                )
                                _catalog = build_session_template_catalog(
                                    session_id, _docs_for_catalog
                                )
                                await _safe_save_session(
                                    self.context_manager.memory,
                                    session_id,
                                    {
                                        "compliance_master_list": comp_data,
                                        "session_template_catalog": _catalog,
                                    },
                                )
                            except Exception as _enrich_exc:
                                logger.warning(
                                    "compliance_catalog_enrich_failed",
                                    session_id=session_id,
                                    error=str(_enrich_exc),
                                )
                            input_data["compliance_master_list"] = comp_data
                            agent_input = agent_input.model_copy(
                                update={
                                    "company_data": {
                                        **(agent_input.company_data or {}),
                                        "compliance_master_list": comp_data,
                                    }
                                }
                            )
                            logger.info("building_fast_track_candidates", session_id=session_id)
                            fast_track_candidates = build_candidate_document_list(
                                compliance_master_list=comp_data,
                                require_human_confirmation=bool(settings.FAST_TRACK_REQUIRE_HUMAN_CONFIRM),
                                low_conf_threshold=float(settings.FAST_TRACK_LOW_CONF_THRESHOLD),
                            )
                            input_data["fast_track_document_candidates"] = fast_track_candidates

                            # --- CCC: Capa de Consolidación de Compliance (Universal) ---
                            # Agrupa los ítems granulares en entregables accionables (~25)
                            # sin asumir nombres de Anexo específicos de ninguna licitación.
                            consolidated: dict = {}
                            try:
                                from app.services.compliance_consolidation_service import ComplianceConsolidator
                                consolidated = await ComplianceConsolidator().consolidate(
                                    raw_items=comp_data,
                                    session_id=session_id,
                                )
                                meta = consolidated.get("_meta", {})
                                logger.info(
                                    "compliance_consolidated",
                                    session_id=session_id,
                                    raw=meta.get("total_raw_items", 0),
                                    consolidados=meta.get("total_consolidados", 0),
                                    latencia_ms=meta.get("latencia_ms", 0),
                                )
                            except Exception as _ccc_exc:
                                logger.warning("compliance_consolidation_failed", session_id=session_id, error=str(_ccc_exc))

                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                {
                                    "document_candidates_v1": fast_track_candidates,       # Backward compat
                                    "document_candidates_final": fast_track_candidates,
                                    "document_candidates_consolidated": consolidated,        # CCC: lista limpia
                                },
                            )
                            try:
                                from app.services.delivery_coverage_report import (
                                    build_and_persist_coverage,
                                )

                                await build_and_persist_coverage(
                                    self.context_manager.memory, session_id
                                )
                            except Exception as _cov_exc:
                                logger.warning(
                                    "coverage_report_after_compliance_failed",
                                    session_id=session_id,
                                    error=str(_cov_exc),
                                )
                    except Exception as _ft_exc:
                        logger.warning("fast_track_document_candidates_failed", session_id=session_id, error=str(_ft_exc))

                # Error check (Legacy Support)
                comp_res = execution_results.get("compliance")
                comp_st = _result_status_value(comp_res)
                if comp_res is not None and comp_st == AgentStatus.ERROR.value:
                    decision = OrchestratorState(stop_reason="COMPLIANCE_ERROR", aggregate_health="failed", next_steps=next_steps, correlation_id=correlation_id).model_dump()
                    await _safe_save_session(
                        self.context_manager.memory, session_id,
                        {"last_orchestrator_decision": decision}
                    )
                    return {
                        "status": "success",
                        "session_id": session_id,
                        "fast_track_document_candidates": fast_track_candidates,
                        "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()},
                        "orchestrator_decision": decision,
                        "metadata": {"telemetry": telemetry}
                    }

                # Validation & Reflection
                if settings.BACKTRACKING_ENABLED and mode in ["full", "analysis_only"]:
                    from app.agents.validator import ValidatorAgent
                    from app.agents.critic import CriticAgent
                    from app.agents.communication.redis_bus import RedisAgentBus, AgentMessage, AgentMessageType
                    validator, critic, redis_bus = ValidatorAgent(), CriticAgent(), RedisAgentBus()
                    report = validator.validate(execution_results.get("analysis"), execution_results.get("compliance"))
                    verdict = critic.decide(report, bt_iterations, settings.BACKTRACK_MAX_ITERATIONS)
                    redis_bus.publish(session_id, AgentMessage(message_id=f"msg_{session_id}_{bt_iterations}", session_id=session_id, correlation_id=correlation_id, from_agent="orchestrator", message_type=AgentMessageType.VALIDATION_NOTE, payload=report.model_dump()))
                    bt_history.append({"iteration": bt_iterations, "verdict": verdict.verdict})
                    if verdict.verdict in ["rerun_analyst", "rerun_compliance"]:
                        bt_iterations += 1
                        refinement_data = {
                            "iteration": bt_iterations,
                            "source": "backtracking",
                            "hints": report.suggested_corrections,
                            "focus_req_ids": list(report.suggested_corrections.keys())
                        }
                        continue
                    break
                else: break

            # --- GoNoGoAgent: Semáforo de decisión antes del EconomicAgent ---
            intake_plan_data: Optional[Dict[str, Any]] = None
            go_no_go_override = session_state.get("go_no_go_override") or {}
            from app.services.go_no_go_session_bridges import (
                build_silent_go_no_go_override,
                is_go_no_go_acknowledged,
            )

            _already_authorized = is_go_no_go_acknowledged(go_no_go_override)
            # Saltar re-ejecución en generación si ya hubo acknowledgment (user o system_auto).
            _skip_go_no_go = mode in ("generation_only", "generation") and _already_authorized

            if not _skip_go_no_go:
                try:
                    from app.agents.go_no_go import GoNoGoAgent
                    effective_profile = agent_input.company_data.get("master_profile") or {}
                    go_no_go_baseline_master_profile: Dict[str, Any] = {}
                    if settings.ENABLE_EVIDENCE_PROFILE_BRIDGE:
                        go_no_go_baseline_master_profile = dict(effective_profile)

                    if settings.ENABLE_EVIDENCE_PROFILE_BRIDGE:
                        try:
                            from app.services.evidence_profile_service import (
                                build_conflict_pending_questions,
                                build_evidence_profile_from_documents,
                                build_effective_profile,
                                detect_profile_conflicts,
                            )

                            session_docs = await self.context_manager.memory.get_documents(session_id)
                            evidence_profile = build_evidence_profile_from_documents(session_docs or [])
                            user_overrides = session_state.get("evidence_profile_overrides") or {}
                            conflicts = detect_profile_conflicts(
                                master_profile=effective_profile,
                                evidence_profile=evidence_profile,
                                evidence_profile_overrides=user_overrides,
                            )
                            effective_profile, profile_provenance = build_effective_profile(
                                master_profile=effective_profile,
                                evidence_profile=evidence_profile,
                                user_overrides=user_overrides,
                            )
                            updates: Dict[str, Any] = {
                                "evidence_profile": evidence_profile,
                                "effective_profile_provenance": profile_provenance,
                                "evidence_profile_conflicts": conflicts,
                            }
                            fresh_session = await self.context_manager.memory.get_session(session_id) or {}
                            old_pending = list(fresh_session.get("pending_questions") or [])
                            existing_pending = [
                                q for q in old_pending
                                if str(q.get("type") or "") != "evidence_profile_conflict"
                            ]
                            had_conflict_pending = any(
                                str(q.get("type") or "") == "evidence_profile_conflict" for q in old_pending
                            )
                            if conflicts:
                                existing_pending.extend(build_conflict_pending_questions(conflicts))
                            if conflicts or had_conflict_pending:
                                updates["pending_questions"] = existing_pending
                                if conflicts and existing_pending:
                                    updates["current_question_index"] = 0
                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                updates,
                            )
                        except Exception as _ev_exc:
                            logger.warning(
                                "evidence_profile_bridge_failed",
                                session_id=session_id,
                                error=str(_ev_exc),
                            )

                    _t0_gng = _now_utc_iso()
                    _notify_job_progress(
                        agent_input.job_id, "go_no_go", 85,
                        "Evaluando viabilidad de participación (Semáforo Go/No-Go)…",
                    )
                    _gng_company_data: Dict[str, Any] = {
                        **agent_input.company_data,
                        "master_profile": effective_profile,
                    }
                    if settings.ENABLE_EVIDENCE_PROFILE_BRIDGE:
                        _gng_company_data["go_no_go_baseline_master_profile"] = (
                            go_no_go_baseline_master_profile
                        )
                    gng_input = agent_input.model_copy(
                        update={"company_data": _gng_company_data}
                    )
                    gng_res = await GoNoGoAgent(self.context_manager).process(gng_input)
                    _finalize_stage_telemetry(telemetry, "go_no_go", _t0_gng)
                    execution_results["go_no_go"] = gng_res

                    gng_data = gng_res.data if hasattr(gng_res, "data") else (gng_res.get("data") if isinstance(gng_res, dict) else {})
                    semaforo = (gng_data or {}).get("semaforo", "GREEN")

                    # --- NUEVO: Generar Inventario Documental antes del Planner (Proactividad) ---
                    if settings.DOCUMENT_INVENTORY_SERVICE_ENABLED:
                        try:
                            from app.services.document_inventory_service import DocumentInventoryService
                            _notify_job_progress(
                                agent_input.job_id, "orchestration", 86,
                                "Sincronizando inventario documental de las bases…",
                            )
                            _doc_inv = await DocumentInventoryService.build_for_session(
                                session_id,
                                use_llm=bool(settings.DOCUMENT_INVENTORY_SERVICE_USE_LLM),
                                correlation_id=correlation_id,
                            )
                            _doc_inv_dump = _doc_inv.model_dump(mode="json")
                            input_data["document_inventory"] = _doc_inv_dump
                            # Actualizar session_state local para que el planner lo vea
                            session_state["document_inventory"] = _doc_inv_dump
                            
                            # Persistencia inmediata en sesión
                            await _safe_save_session(
                                self.context_manager.memory, session_id,
                                {"document_inventory": _doc_inv_dump}
                            )
                        except Exception as _svc_exc:
                            logger.warning("document_inventory_early_service_failed", session_id=session_id, error=str(_svc_exc))

                    # Intake Planner (shadow): consolida preguntas priorizadas sin reemplazar pending_questions legacy
                    if settings.INTAKE_PLANNER_ENABLED:
                        try:
                            from app.agents.intake_planner import IntakePlannerAgent

                            # Hidratación forzada: consultar el master_profile real desde la BD
                            # para garantizar que el planner vea los datos actuales de la empresa.
                            _company_id = agent_input.company_id or session_state.get("company_id")
                            _db_master_profile: Dict[str, Any] = {}
                            if _company_id:
                                try:
                                    _company_db = await self.context_manager.memory.get_company(_company_id)
                                    _db_master_profile = (_company_db.get("master_profile") or {}) if _company_db else {}
                                except Exception as _mp_exc:
                                    logger.warning("intake_planner_master_profile_fetch_failed", session_id=session_id, error=str(_mp_exc))

                            # Fusionar: DB tiene prioridad sobre el input del agente
                            _input_master_profile = (agent_input.company_data or {}).get("master_profile") or {}
                            _master_profile_final = {**_input_master_profile, **_db_master_profile}

                            planner_input = agent_input.model_copy(
                                update={
                                    "company_data": {
                                        "master_profile": _master_profile_final,
                                        "results": {
                                            "analysis": execution_results.get("analysis", {}),
                                            "compliance": execution_results.get("compliance", {}),
                                            "go_no_go": execution_results.get("go_no_go", {}),
                                        },
                                        "session_state": session_state,
                                    }
                                }
                            )
                            planner_res = await IntakePlannerAgent(self.context_manager).process(planner_input)
                            execution_results["intake_planner"] = planner_res
                            intake_plan_data = _extract_output_data(planner_res)

                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                {
                                    "intake_plan": intake_plan_data,
                                    "intake_plan_version": str(intake_plan_data.get("plan_version") or "1.0.0"),
                                    "intake_last_updated_at": _now_utc_iso(),
                                    "intake_shadow_mode": bool(settings.INTAKE_PLANNER_SHADOW_MODE),
                                },
                            )
                        except Exception as _planner_exc:
                            logger.warning(
                                "intake_planner_failed",
                                session_id=session_id,
                                error=str(_planner_exc),
                            )

                    if semaforo in ("RED", "YELLOW"):
                        _silent_analysis_ack = bool(
                            settings.GO_NO_GO_SILENT_IN_ANALYSIS
                            and mode in ("analysis_only", "full")
                        )
                        if _silent_analysis_ack:
                            override_record = build_silent_go_no_go_override(
                                gng_data or {},
                                mode=mode,
                            )
                            await _safe_save_session(
                                self.context_manager.memory,
                                session_id,
                                {
                                    "go_no_go_result": gng_data,
                                    "go_no_go_override": override_record,
                                    "intake_plan": intake_plan_data,
                                },
                            )
                            fresh_state = await self.context_manager.memory.get_session(session_id) or {}
                            session_state = fresh_state
                            go_no_go_override = override_record
                            logger.info(
                                "go_no_go_silent_ack",
                                session_id=session_id,
                                semaforo=semaforo,
                                mode=mode,
                                brechas_registradas=override_record.get("brechas_registradas"),
                            )
                            _notify_job_progress(
                                agent_input.job_id,
                                "go_no_go",
                                87,
                                "Viabilidad registrada (control interno). Continuando análisis…",
                            )
                        else:
                            decision = OrchestratorState(
                                stop_reason="GO_NO_GO_PENDING",
                                aggregate_health="partial",
                                next_steps=next_steps,
                                correlation_id=correlation_id,
                            ).model_dump()
                            await _safe_save_session(
                                self.context_manager.memory, session_id,
                                {
                                    "last_orchestrator_decision": decision,
                                    "go_no_go_result": gng_data,
                                    "intake_plan": intake_plan_data
                                }
                            )
                            fresh_state = await self.context_manager.memory.get_session(session_id) or {}
                            session_state = fresh_state
                            _notify_job_progress(
                                agent_input.job_id, "go_no_go", 87,
                                f"Semáforo {semaforo}: se detectaron brechas críticas. Esperando decisión del usuario.",
                            )
                            try:
                                return {
                                    "status": "go_no_go_pending",
                                    "session_id": session_id,
                                    "go_no_go_result": gng_data,
                                    "intake_plan": intake_plan_data,
                                    "fast_track_document_candidates": fast_track_candidates,
                                    "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()},
                                    "orchestrator_decision": decision,
                                    "metadata": {"telemetry": telemetry},
                                }
                            finally:
                                if fast_track_candidates and session_id:
                                    try:
                                        await _safe_save_session(
                                            self.context_manager.memory, session_id,
                                            {"document_candidates_v1": fast_track_candidates}
                                        )
                                    except Exception as _save_exc:
                                        logger.warning("orchestrator_persist_candidates_failed", error=str(_save_exc))
                                await self._proactive_injection_checkpoint(session_id)
                except Exception as _gng_exc:
                    logger.error(
                        "go_no_go_agent_failed",
                        session_id=session_id,
                        error=str(_gng_exc),
                    )
                    # Fallback: continuar pipeline como GREEN para no bloquear por fallo de la nueva capa

            # Si se omitió Go/No-Go por autorización previa, aún generar intake plan en shadow
            if _skip_go_no_go and settings.INTAKE_PLANNER_ENABLED:
                try:
                    from app.agents.intake_planner import IntakePlannerAgent

                    # Hidratación forzada (mismo patrón que el bloque principal)
                    _company_id2 = agent_input.company_id or session_state.get("company_id")
                    _db_master_profile2: Dict[str, Any] = {}
                    if _company_id2:
                        try:
                            _company_db2 = await self.context_manager.memory.get_company(_company_id2)
                            _db_master_profile2 = (_company_db2.get("master_profile") or {}) if _company_db2 else {}
                        except Exception:
                            pass
                    _input_mp2 = (agent_input.company_data or {}).get("master_profile") or {}
                    _master_profile_final2 = {**_input_mp2, **_db_master_profile2}

                    planner_input = agent_input.model_copy(
                        update={
                            "company_data": {
                                "master_profile": _master_profile_final2,
                                "results": {
                                    "analysis": execution_results.get("analysis", {}),
                                    "compliance": execution_results.get("compliance", {}),
                                    "go_no_go": execution_results.get("go_no_go", {}),
                                },
                                "session_state": session_state,
                            }
                        }
                    )
                    planner_res = await IntakePlannerAgent(self.context_manager).process(planner_input)
                    execution_results["intake_planner"] = planner_res
                    intake_plan_data = _extract_output_data(planner_res)
                    await _safe_save_session(
                        self.context_manager.memory,
                        session_id,
                        {
                            "intake_plan": intake_plan_data,
                            "intake_plan_version": str(intake_plan_data.get("plan_version") or "1.0.0"),
                            "intake_last_updated_at": _now_utc_iso(),
                            "intake_shadow_mode": bool(settings.INTAKE_PLANNER_SHADOW_MODE),
                        },
                    )
                    # HITO: Inyectar proactivamente las preguntas a la cola aunque se haya saltado el Go/No-Go
                    await self._proactive_injection_checkpoint(session_id)
                except Exception as _planner_exc2:
                    logger.warning(
                        "intake_planner_failed",
                        session_id=session_id,
                        error=str(_planner_exc2),
                    )

            # Economic
            if self._should_execute_stage("economic", pipeline_config, stages_skipped) and "economic" not in completed_stages:
                from app.agents.economic import EconomicAgent
                try:
                    _t0_iso = _now_utc_iso()
                    _notify_job_progress(
                        agent_input.job_id,
                        "economic",
                        88,
                        "Evaluación económica en curso…",
                    )
                    econ_input = agent_input.model_copy(
                        update={
                            "company_data": _economic_company_data_for_run(
                                agent_input,
                                extra={
                                    "compliance_master_list": input_data.get(
                                        "compliance_master_list"
                                    )
                                    or {},
                                },
                            ),
                        }
                    )
                    res = await EconomicAgent(self.context_manager).process(econ_input)
                    _finalize_stage_telemetry(telemetry, "economic", _t0_iso)
                    execution_results["economic"] = res
                    stages_executed.append("economic")

                    econ_st = _result_status_value(res)
                    if econ_st == AgentStatus.WAITING_FOR_DATA.value:
                        # No registrar stage_completed:economic: la etapa no terminó (faltan precios).
                        # Refrescar sesión: save_session(session_state) obsoleto borraba pending_questions
                        # recién escritas por EconomicAgent._save_pending_questions.
                        econ_hints = _economic_waiting_hints_from_output(res)
                        decision = OrchestratorState(
                            stop_reason="ECONOMIC_GAP",
                            aggregate_health="partial",
                            next_steps=next_steps,
                            correlation_id=correlation_id,
                            waiting_hints=econ_hints,
                        ).model_dump()
                        _updates_5: Dict[str, Any] = {"last_orchestrator_decision": decision}
                        if econ_hints is not None:
                            _updates_5["last_economic_waiting_hints"] = econ_hints
                        await _safe_save_session(self.context_manager.memory, session_id, _updates_5)
                        
                        # --- POST-PROCESO PROACTIVO ---
                        await self._proactive_injection_checkpoint(session_id)
                        
                        _notify_job_progress(
                            agent_input.job_id,
                            "economic",
                            90,
                            "Pausa: faltan precios unitarios o datos de expediente para cerrar la propuesta económica.",
                        )
                        return {
                            "status": "waiting_for_data",
                            "session_id": session_id,
                            "chatbot_message": _result_message(res) or "",
                            "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()},
                            "orchestrator_decision": decision,
                        }

                    # CHECKPOINT: Economic completado (sin huecos económicos)
                    await self.context_manager.record_task_completion(
                        session_id=session_id,
                        task_name="stage_completed:economic",
                        result=res if isinstance(res, dict) else res.model_dump()
                    )
                    _notify_job_progress(
                        agent_input.job_id,
                        "economic",
                        93,
                        "Evaluación económica completada; consolidando resultados…",
                    )
                    next_steps.append("economic_analysis_OK")
                except Exception as e:
                    logger.error("economic_stage_failed", session_id=session_id, error=str(e))
            elif "economic" in completed_stages:
                execution_results["economic"] = next(
                    (t["result"] for t in reversed(tasks_completed) if t.get("task") == "stage_completed:economic"),
                    {"status": "resumed"},
                )

            # ComplianceGate 12.1: tras compliance + economic (validaciones y precios actuales).
            session_state = await self.context_manager.memory.get_session(session_id) or session_state
            session_state = await _persist_compliance_recovery_if_needed(
                self.context_manager.memory, session_id, session_state
            )
            try:
                from app.services.economic_capture_matrix_service import economic_capture_status

                if economic_capture_status(session_state).get("capture_complete"):
                    from app.economic_validation.service import refresh_economic_validations_for_session

                    await refresh_economic_validations_for_session(
                        self.context_manager.memory, session_id
                    )
                    session_state = await self.context_manager.memory.get_session(session_id) or session_state
                    for task in reversed(_tasks_completed_list(session_state)):
                        if str(task.get("task") or "") == "economic_proposal":
                            execution_results["economic"] = task.get("result") or execution_results.get(
                                "economic", {}
                            )
                            break
            except Exception as _gate_ref_exc:
                logger.info(
                    "compliance_gate_economic_refresh_skipped",
                    session_id=session_id,
                    error=str(_gate_ref_exc)[:160],
                )

            from app.agents.compliance_gate import ComplianceGate

            gate_payload = _build_compliance_gate_payload(
                session_id, execution_results, session_state
            )
            gate_result = ComplianceGate().evaluate(gate_payload)
            gate_result_dict = ComplianceGate.to_dict(gate_result)
            session_state["compliance_gate_result"] = gate_result_dict
            execution_results["compliance_gate"] = {
                "status": "success",
                "agent_id": "compliance_gate_001",
                "session_id": session_id,
                "data": gate_result_dict,
                "message": "Evaluación determinista 12.1 completada.",
            }
            if gate_result.is_blocking:
                final_metadata = {"telemetry": telemetry}
                decision = OrchestratorState(
                    stop_reason="COMPLIANCE_GATE_BLOCKING",
                    aggregate_health="failed",
                    next_steps=next_steps,
                    correlation_id=correlation_id,
                ).model_dump()
                await _safe_save_session(
                    self.context_manager.memory,
                    session_id,
                    {
                        "last_orchestrator_decision": decision,
                        "last_orchestrator_metadata": final_metadata,
                        "compliance_gate_result": gate_result_dict,
                    },
                )
                self._persist_latest_job_metadata(
                    session_id, "hard_disqualification", final_metadata, decision
                )
                return {
                    "status": "hard_disqualification",
                    "session_id": session_id,
                    "message": _format_compliance_gate_blocking_message(gate_result),
                    "fast_track_document_candidates": fast_track_candidates,
                    "results": {
                        k: (v if isinstance(v, dict) else v.model_dump())
                        for k, v in execution_results.items()
                    },
                    "orchestrator_decision": decision,
                    "metadata": final_metadata,
                }

            # Intake autónomo (Semana 1): consolidar cola HITL post-análisis sin gate duro.
            if settings.AUTONOMOUS_INTAKE_ENABLED and mode in ("full", "analysis_only"):
                try:
                    from app.services.autonomous_intake_coordinator import run_post_analysis_checkpoint

                    _intake_snap = await run_post_analysis_checkpoint(
                        self.context_manager.memory,
                        session_id,
                        mode=mode,
                    )
                    if _intake_snap:
                        execution_results["autonomous_intake"] = {
                            "status": "success",
                            "data": _intake_snap,
                        }
                        session_state = await self.context_manager.memory.get_session(session_id) or session_state
                except Exception as _aic_exc:
                    logger.warning(
                        "autonomous_intake_hook_failed",
                        session_id=session_id,
                        error=str(_aic_exc)[:200],
                    )

            # Generation
            if mode in ["full", "generation", "generation_only"]:
                from app.services.generation_concurrency_controller import (
                    dual_stream_enabled,
                    resolve_generation_stream_from_input,
                    try_acquire_stream_lock,
                )
                from app.services.generation_mode_policy import (
                    economic_snapshot_required_before,
                    resolve_generation_mode_from_input,
                )
                from app.services.generation_wipe_policy import combined_wipe_preserve_subdirs

                generation_mode = resolve_generation_mode_from_input(input_data, session_state)
                generation_stream = resolve_generation_stream_from_input(input_data, generation_mode)
                dual_stream_job_id = str(input_data.get("job_id") or "").strip() or None
                input_data, agent_input = _apply_filtered_compliance_master_list(
                    input_data, agent_input
                )
                from app.agents.data_gap import DataGapAgent
                gen_state = _prepare_generation_queue(
                    session_state,
                    agent_input.resume_generation,
                    mode,
                    generation_mode,
                    generation_stream=generation_stream,
                    job_id=dual_stream_job_id,
                )
                if (
                    dual_stream_enabled()
                    and generation_mode in ("technical", "economic")
                    and dual_stream_job_id
                    and gen_state
                ):
                    lock_result = try_acquire_stream_lock(
                        gen_state,
                        generation_stream if generation_stream in ("technical", "economic") else (
                            "technical" if generation_mode == "technical" else "economic"
                        ),
                        dual_stream_job_id,
                    )
                    if not lock_result.acquired:
                        decision = OrchestratorState(
                            stop_reason="GENERATION_STREAM_BUSY",
                            aggregate_health="partial",
                            next_steps=next_steps,
                            correlation_id=correlation_id,
                        ).model_dump()
                        await _safe_save_session(
                            self.context_manager.memory,
                            session_id,
                            {
                                "generation_state": gen_state,
                                "last_orchestrator_decision": decision,
                            },
                        )
                        return _response_with_generation_state(
                            {
                                "status": "already_running",
                                "session_id": session_id,
                                "chatbot_message": (
                                    "Ya hay una generación en curso para este mismo alcance. "
                                    "Espera a que termine o usa el otro modo (técnica / económica) en paralelo."
                                ),
                                "results": execution_results,
                                "orchestrator_decision": decision,
                                "generation_stream": generation_stream,
                            },
                            session_state,
                            mode,
                        )
                    await _safe_save_session(
                        self.context_manager.memory,
                        session_id,
                        {"generation_state": gen_state},
                    )
                if self._should_execute_stage("datagap", pipeline_config, stages_skipped):
                    if gen_state and _gen_job_status(gen_state, "datagap") == "skipped":
                        execution_results["datagap"] = {"status": "skipped"}
                    else:
                        skip_dg = bool(gen_state and _gen_job_status(gen_state, "datagap") == "done")
                        if skip_dg:
                            execution_results["datagap"] = {"status": "resumed"}
                        else:
                            _notify_job_progress(
                                agent_input.job_id,
                                "generation.datagap",
                                91,
                                "Validando datos mínimos para generación…",
                            )
                            res = await DataGapAgent(self.context_manager).process(agent_input)
                            execution_results["datagap"] = res
                            stages_executed.append("datagap")
                            if _result_status_value(res) == AgentStatus.WAITING_FOR_DATA.value:
                                decision = OrchestratorState(
                                    stop_reason="INCOMPLETE_DATA",
                                    aggregate_health="partial",
                                    next_steps=next_steps,
                                    correlation_id=correlation_id,
                                ).model_dump()
                                if gen_state:
                                    _set_gen_job_status(gen_state, "datagap", "blocked")
                                _updates_6: Dict[str, Any] = {"last_orchestrator_decision": decision}
                                if gen_state:
                                    _updates_6["generation_state"] = gen_state
                                await _safe_save_session(self.context_manager.memory, session_id, _updates_6)
                                
                                # --- POST-PROCESO PROACTIVO ---
                                await self._proactive_injection_checkpoint(session_id)
                                
                                return _response_with_generation_state(
                                    {
                                        "status": "waiting_for_data",
                                        "session_id": session_id,
                                        "chatbot_message": _result_message(res) or "",
                                        "results": {
                                            k: (v if isinstance(v, dict) else v.model_dump())
                                            for k, v in execution_results.items()
                                        },
                                        "orchestrator_decision": decision,
                                    },
                                    session_state,
                                    mode,
                                )
                            _notify_job_progress(
                                agent_input.job_id,
                                "generation.datagap",
                                92,
                                "Validación inicial completa; iniciando generación documental…",
                            )
                            if gen_state:
                                _set_gen_job_status(gen_state, "datagap", "done")

                if settings.DOCUMENT_INVENTORY_MERGE_ENABLED:
                    try:
                        from app.services.document_inventory_merge import (
                            merge_inventory_into_compliance_list,
                        )

                        _cm = input_data.get("compliance_master_list") or {}
                        if not any(_cm.get(k) for k in ("administrativo", "tecnico", "formatos")):
                            comp_task = next(
                                (
                                    t
                                    for t in reversed(
                                        session_state.get("tasks_completed", []) or []
                                    )
                                    if t.get("task") == "stage_completed:compliance"
                                ),
                                {},
                            )
                            rd = comp_task.get("result") or {}
                            if isinstance(rd, dict) and isinstance(rd.get("data"), dict):
                                _cm = rd["data"]
                        _merged = await merge_inventory_into_compliance_list(
                            session_id=session_id,
                            compliance_master_list=_cm,
                            correlation_id=correlation_id,
                        )
                        input_data["compliance_master_list"] = _merged
                        agent_input = agent_input.model_copy(
                            update={
                                "company_data": {
                                    **(agent_input.company_data or {}),
                                    "compliance_master_list": _merged,
                                }
                            }
                        )
                    except Exception as _inv_exc:
                        logger.warning(
                            "document_inventory_merge_failed",
                            session_id=session_id,
                            error=str(_inv_exc),
                        )

                input_data, agent_input, session_state = await _inject_document_inventory_for_generation(
                    memory=self.context_manager.memory,
                    session_id=session_id,
                    session_state=session_state,
                    input_data=input_data,
                    agent_input=agent_input,
                    correlation_id=correlation_id,
                )

                # DocumentInventoryService movido a fase temprana (línea ~950) para alimentar al IntakePlanner

                # ── TAREA 4: Inyectar triage_context en agent_input para agentes de generación ──
                # El triage_context se persiste en session_state durante la fase de análisis.
                # En generation_only, agent_input.triage_context puede estar vacío porque el
                # frontend no lo envía. Los agentes de generación (TechnicalWriter, Formats)
                # necesitan el triage_context para adaptar el quality gate al tipo de licitación.
                if not agent_input.triage_context:
                    _triage_for_gen = session_state.get("triage_context")
                    if _triage_for_gen and isinstance(_triage_for_gen, dict):
                        agent_input = agent_input.model_copy(
                            update={"triage_context": _triage_for_gen}
                        )
                        logger.info(
                            "orchestrator_triage_injected_for_generation",
                            session_id=session_id,
                            tender_category=_triage_for_gen.get("tender_category"),
                            law=_triage_for_gen.get("law"),
                        )

                # Evitar mezclar archivos de corridas fallidas con la salida nueva (conteo/ZIP).
                if getattr(settings, "GENERATION_WIPE_OUTPUTS_BEFORE_WRITERS", True):
                    _should_wipe_disk = True
                    if gen_state and _gen_job_status(gen_state, "technical") != "done":
                        try:
                            from app.api.v1.routes.downloads import resolve_outputs_root
                            from app.services.generation_wipe_policy import (
                                evaluate_pre_generation_wipe,
                            )

                            _out_root = await resolve_outputs_root(session_id)
                            _wipe_decision = evaluate_pre_generation_wipe(
                                generation_mode=generation_mode,
                                gen_state=gen_state,
                                session_output_path=_out_root,
                                company_data=agent_input.company_data or {},
                                session_state=session_state,
                            )
                            _should_wipe_disk = bool(_wipe_decision.get("should_wipe"))
                            if not _should_wipe_disk:
                                logger.info(
                                    "orchestrator_generation_wipe_skipped",
                                    session_id=session_id,
                                    reason=_wipe_decision.get("reason"),
                                    preserved_job_id=_wipe_decision.get("preserved_job_id"),
                                    artifact_count_hint=_wipe_decision.get(
                                        "artifact_count_hint"
                                    ),
                                )
                        except Exception as _wipe_eval_exc:
                            logger.warning(
                                "orchestrator_generation_wipe_eval_failed",
                                session_id=session_id,
                                error=str(_wipe_eval_exc)[:120],
                            )
                    if _should_wipe_disk and gen_state and _gen_job_status(
                        gen_state, "technical"
                    ) != "done":
                        try:
                            from app.services.generated_outputs_cleanup import (
                                wipe_session_output_disk_only,
                            )

                            _preserve = combined_wipe_preserve_subdirs(
                                generation_mode,
                                gen_state,
                            )
                            wipe_res = await wipe_session_output_disk_only(
                                session_id,
                                preserve_subdirs=_preserve or None,
                            )
                            logger.info(
                                "orchestrator_generation_disk_wiped",
                                session_id=session_id,
                                removed=wipe_res.get("removed_count"),
                                preserved=wipe_res.get("preserved_subdirs"),
                                generation_mode=generation_mode,
                            )
                        except Exception as _wipe_exc:
                            logger.warning(
                                "orchestrator_generation_disk_wipe_failed",
                                session_id=session_id,
                                error=str(_wipe_exc)[:120],
                            )
                _gfm = input_data.get("generation_filter_meta")
                if isinstance(_gfm, dict):
                    logger.info(
                        "orchestrator_generation_filter_meta",
                        session_id=session_id,
                        **_gfm,
                    )

                for step, a_cls in [
                    ("technical", "TechnicalWriterAgent"),
                    ("formats", "FormatsAgent"),
                    ("economic_writer", "EconomicWriterAgent"),
                    ("packager", "DocumentPackagerAgent"),
                    ("delivery", "DeliveryAgent"),
                ]:
                    if self._should_execute_stage(step, pipeline_config, stages_skipped):
                        try:
                            if (
                                dual_stream_enabled()
                                and step in ("packager", "delivery")
                                and gen_state
                            ):
                                from app.services.generation_concurrency_controller import (
                                    streams_blocking_shared,
                                )

                                _blocking_streams = streams_blocking_shared(gen_state)
                                if _blocking_streams:
                                    execution_results[step] = {
                                        "status": "deferred",
                                        "reason": "streams_active",
                                        "blocking_streams": _blocking_streams,
                                    }
                                    continue
                            if gen_state and _gen_job_status(gen_state, step) == "skipped":
                                execution_results[step] = {"status": "skipped"}
                                continue
                            skip_step = bool(
                                gen_state and _gen_job_status(gen_state, step) == "done"
                            )
                            if skip_step and step == "packager" and gen_state:
                                from app.agents.document_packager import (
                                    packager_sobres_stale,
                                    validated_pack_complete,
                                )

                                if validated_pack_complete(session_id):
                                    logger.info(
                                        "orchestrator_packager_skip_validated_complete",
                                        session_id=session_id,
                                    )
                                elif packager_sobres_stale(session_id):
                                    logger.warning(
                                        "orchestrator_packager_stale_sobres_forcing_repack",
                                        session_id=session_id,
                                    )
                                    skip_step = False
                                    _set_gen_job_status(gen_state, step, "pending")
                            if skip_step:
                                execution_results[step] = {"status": "resumed"}
                                continue
                            _gate_resp = await _enforce_readiness_generation_gate(
                                step=step,
                                session_id=session_id,
                                session_state=session_state,
                                memory=self.context_manager.memory,
                                company_id=str(agent_input.company_id) if agent_input.company_id else None,
                                correlation_id=correlation_id,
                                gen_state=gen_state,
                                execution_results=execution_results,
                            )
                            if _gate_resp:
                                await self._proactive_injection_checkpoint(session_id)
                                return _response_with_generation_state(
                                    _gate_resp,
                                    session_state,
                                    mode,
                                )
                            if (
                                step == "economic_writer"
                                and "economic_writer"
                                in economic_snapshot_required_before(generation_mode)
                            ):
                                _fresh_session_for_econ = (
                                    await self.context_manager.memory.get_session(session_id) or {}
                                )
                                _econ_ready, _econ_error = await _ensure_economic_snapshot_ready(
                                    self.context_manager,
                                    session_id,
                                    agent_input,
                                    _fresh_session_for_econ,
                                )
                                if _econ_ready and gen_state:
                                    _unblock_generation_jobs_for_economic_retry(gen_state)
                                if not _econ_ready and _econ_error:
                                    _stop_reason = str(
                                        _econ_error.get("stop_reason") or "ECONOMIC_PRICES_INCOMPLETE"
                                    )
                                    _econ_decision = OrchestratorState(
                                        stop_reason=_stop_reason,
                                        aggregate_health="partial",
                                        next_steps=next_steps,
                                        correlation_id=correlation_id,
                                    ).model_dump()
                                    if gen_state:
                                        _set_gen_job_status(gen_state, "economic_writer", "blocked")
                                    _updates_econ: Dict[str, Any] = {
                                        "last_orchestrator_decision": _econ_decision
                                    }
                                    if gen_state:
                                        _updates_econ["generation_state"] = gen_state
                                    await _safe_save_session(
                                        self.context_manager.memory, session_id, _updates_econ
                                    )
                                    await self._proactive_injection_checkpoint(session_id)
                                    return _response_with_generation_state(
                                        {
                                            "status": _econ_error.get("status", "waiting_for_data"),
                                            "session_id": session_id,
                                            "chatbot_message": _econ_error.get("message", ""),
                                            "results": {
                                                k: (v if isinstance(v, dict) else v.model_dump())
                                                for k, v in execution_results.items()
                                            },
                                            "orchestrator_decision": _econ_decision,
                                            "data": _econ_error.get("data"),
                                        },
                                        session_state,
                                        mode,
                                    )
                            if step == "technical":
                                from app.agents.technical_writer import TechnicalWriterAgent as C
                            elif step == "formats":
                                from app.agents.formats import FormatsAgent as C
                            elif step == "economic_writer":
                                from app.agents.economic_writer import EconomicWriterAgent as C
                            elif step == "packager":
                                from app.agents.document_packager import DocumentPackagerAgent as C
                            else:
                                from app.agents.delivery import DeliveryAgent as C

                            # Enriquecer agent_input con documentos_generados acumulados
                            # para DocumentPackagerAgent y DeliveryAgent (Req 5.1, 7.1)
                            pct_start, pct_done, msg_start, msg_done = _generation_progress_for_step(step)
                            _notify_job_progress(
                                agent_input.job_id,
                                f"generation.{step}",
                                pct_start,
                                msg_start,
                            )
                            if step in ("packager", "delivery"):
                                documentos_generados = {
                                    "tecnica": _extract_documentos(execution_results.get("technical")),
                                    "administrativa": _extract_documentos(execution_results.get("formats")),
                                    "economica": _extract_documentos(execution_results.get("economic_writer")),
                                }
                                agent_input = agent_input.model_copy(
                                    update={
                                        "company_data": {
                                            **agent_input.company_data,
                                            "documentos_generados": documentos_generados,
                                        }
                                    }
                                )

                            res = await C(self.context_manager).process(agent_input)
                            execution_results[step] = res

                            # CORTAR SI UN AGENTE REQUIERE DATOS (EVITA GENERACIÓN PARCIAL)
                            if hasattr(res, "status") and res.status == AgentStatus.WAITING_FOR_DATA:
                                logger.info(
                                    "generation_paused_waiting_data",
                                    stage=step,
                                    session_id=session_id,
                                )
                                if _can_continue_generation_past_economic_failure(step, gen_state):
                                    if gen_state:
                                        _set_gen_job_status(gen_state, step, "blocked")
                                    logger.warning(
                                        "generation_economic_waiting_continuing_pipeline",
                                        session_id=session_id,
                                    )
                                    continue
                                quality_hints = _document_quality_waiting_hints_from_output(res)
                                fill_hints = _document_fill_quality_waiting_hints_from_output(res, stage=step)
                                waiting_hints = fill_hints or quality_hints
                                decision = OrchestratorState(
                                    stop_reason=f"INCOMPLETE_{step.upper()}_DATA",
                                    aggregate_health="partial",
                                    next_steps=next_steps,
                                    correlation_id=correlation_id,
                                    waiting_hints=waiting_hints,
                                ).model_dump()
                                if gen_state:
                                    _set_gen_job_status(gen_state, step, "blocked")
                                _updates_7: Dict[str, Any] = {"last_orchestrator_decision": decision}
                                if quality_hints is not None:
                                    _updates_7["last_document_quality_waiting_hints"] = quality_hints
                                if fill_hints is not None:
                                    _updates_7["last_document_fill_quality_waiting_hints"] = fill_hints
                                if gen_state:
                                    _updates_7["generation_state"] = gen_state
                                await _safe_save_session(self.context_manager.memory, session_id, _updates_7)
                                
                                # --- POST-PROCESO PROACTIVO ---
                                await self._proactive_injection_checkpoint(session_id)
                                
                                return _response_with_generation_state(
                                    {
                                        "status": "waiting_for_data",
                                        "session_id": session_id,
                                        "chatbot_message": _agent_output_user_message(res),
                                        "results": {
                                            k: (v if isinstance(v, dict) else v.model_dump())
                                            for k, v in execution_results.items()
                                        },
                                        "orchestrator_decision": decision,
                                    },
                                    session_state,
                                    mode,
                                )

                            # CORTAR SI UN AGENTE REPORTA ERROR (EVITA GENERACIÓN CORRUPTA)
                            if hasattr(res, "status") and res.status == AgentStatus.ERROR:
                                detail = _agent_output_user_message(res)
                                logger.error(
                                    "generation_step_reported_error",
                                    stage=step,
                                    session_id=session_id,
                                    message=detail,
                                )
                                if _can_continue_generation_past_economic_failure(step, gen_state):
                                    if gen_state:
                                        _set_gen_job_status(gen_state, step, "blocked")
                                    logger.warning(
                                        "generation_economic_error_continuing_pipeline",
                                        session_id=session_id,
                                        detail=detail[:200],
                                    )
                                    continue
                                decision = OrchestratorState(
                                    stop_reason=f"ERROR_REPORTED_IN_{step.upper()}",
                                    aggregate_health="failed",
                                    correlation_id=correlation_id,
                                ).model_dump()
                                _updates_8: Dict[str, Any] = {"last_orchestrator_decision": decision}
                                if gen_state:
                                    _set_gen_job_status(gen_state, step, "blocked")
                                    _updates_8["generation_state"] = gen_state
                                await _safe_save_session(self.context_manager.memory, session_id, _updates_8)
                                user_msg = (
                                    f"No se pudo generar la propuesta económica: {detail}. "
                                    "Revisa precios en el chat (`generar propuesta económica`) o vuelve a intentar."
                                )
                                return _response_with_generation_state(
                                    {
                                        "status": "error",
                                        "session_id": session_id,
                                        "message": user_msg,
                                        "chatbot_message": user_msg,
                                        "results": {
                                            k: (v if isinstance(v, dict) else v.model_dump())
                                            for k, v in execution_results.items()
                                        },
                                        "orchestrator_decision": decision,
                                    },
                                    session_state,
                                    mode,
                                )

                            if gen_state and step != "packager":
                                _set_gen_job_status(gen_state, step, "done")
                            _notify_job_progress(
                                agent_input.job_id,
                                f"generation.{step}",
                                pct_done,
                                msg_done,
                            )

                            next_steps.append(f"{step}_OK")

                            # Empaque CompraNet determinista (post DocumentPackager, pre DeliveryAgent)
                            if step == "packager" and hasattr(res, "status") and res.status == AgentStatus.SUCCESS:
                                from app.agents.packager import (
                                    CompraNetPackager,
                                    build_pack_session_data_from_outputs,
                                )
                                from app.services.mini_dictamen_anexos_service import (
                                    build_and_persist_mini_dictamen,
                                    get_blocking_annex_rows_for_stage,
                                )

                                pdata = res.data if hasattr(res, "data") else {}
                                if not isinstance(pdata, dict):
                                    pdata = {}
                                try:
                                    await build_and_persist_mini_dictamen(
                                        self.context_manager.memory, session_id
                                    )
                                    _fresh_session = (
                                        await self.context_manager.memory.get_session(session_id)
                                        or {}
                                    )
                                    _mini_blocking = get_blocking_annex_rows_for_stage(
                                        _fresh_session, "packager"
                                    )
                                    if _mini_blocking:
                                        decision = OrchestratorState(
                                            stop_reason="MINI_DICTAMEN_BLOCKED",
                                            aggregate_health="waiting_for_data",
                                            next_steps=next_steps,
                                            correlation_id=correlation_id,
                                        ).model_dump()
                                        await _safe_save_session(
                                            self.context_manager.memory,
                                            session_id,
                                            {"last_orchestrator_decision": decision},
                                        )
                                        return _response_with_generation_state(
                                            {
                                                "status": "waiting_for_data",
                                                "session_id": session_id,
                                                "message": (
                                                    "El expediente no puede cerrarse porque el mini dictamen "
                                                    "detectó anexos obligatorios aún bloqueados."
                                                ),
                                                "missing": _mini_blocking,
                                                "results": {
                                                    k: (v if isinstance(v, dict) else v.model_dump())
                                                    for k, v in execution_results.items()
                                                },
                                                "orchestrator_decision": decision,
                                            },
                                            session_state,
                                            mode,
                                        )
                                except Exception as _mini_exc:
                                    logger.warning(
                                        "orchestrator_mini_dictamen_pack_guard_failed",
                                        session_id=session_id,
                                        error=str(_mini_exc),
                                    )
                                from app.agents.document_packager import packager_pdata_incomplete

                                incomplete, exp_counts, act_counts = packager_pdata_incomplete(
                                    session_id,
                                    pdata,
                                    agent_input.company_data.get("documentos_generados"),
                                )
                                if incomplete:
                                    if gen_state:
                                        _set_gen_job_status(gen_state, "packager", "blocked")
                                    decision = OrchestratorState(
                                        stop_reason="PACKAGING_INCOMPLETE_SOBRES",
                                        aggregate_health="failed",
                                        next_steps=next_steps,
                                        correlation_id=correlation_id,
                                    ).model_dump()
                                    msg = (
                                        "El empaquetado quedó incompleto: "
                                        f"admin {act_counts.get('sobre_1', 0)}/{exp_counts.get('sobre_1', 0)}, "
                                        f"técnico {act_counts.get('sobre_2', 0)}/{exp_counts.get('sobre_2', 0)}, "
                                        f"económico {act_counts.get('sobre_3', 0)}/{exp_counts.get('sobre_3', 0)}. "
                                        "Pulsa Generar de nuevo; si persiste, revisa Logística y Expedientes."
                                    )
                                    _updates_pack: Dict[str, Any] = {
                                        "last_orchestrator_decision": decision,
                                    }
                                    if gen_state:
                                        _updates_pack["generation_state"] = gen_state
                                    await _safe_save_session(
                                        self.context_manager.memory,
                                        session_id,
                                        _updates_pack,
                                    )
                                    return _response_with_generation_state(
                                        {
                                            "status": "error",
                                            "session_id": session_id,
                                            "message": msg,
                                            "chatbot_message": msg,
                                            "results": {
                                                k: (v if isinstance(v, dict) else v.model_dump())
                                                for k, v in execution_results.items()
                                            },
                                            "orchestrator_decision": decision,
                                        },
                                        session_state,
                                        mode,
                                    )
                                pack_session = build_pack_session_data_from_outputs(
                                    session_id=session_id,
                                    packager_agent_data=pdata,
                                    company_data=agent_input.company_data or {},
                                    session_state=session_state,
                                )
                                pr = CompraNetPackager().pack(pack_session)
                                execution_results["compranet_packaging"] = pr.to_dict()
                                if not pr.success:
                                    logger.error(
                                        "compranet_packaging_failed",
                                        session_id=session_id,
                                        errors=pr.errors,
                                    )
                                    decision = OrchestratorState(
                                        stop_reason="PACKAGING_VALIDATION_FAILED",
                                        aggregate_health="failed",
                                        next_steps=next_steps,
                                        correlation_id=correlation_id,
                                    ).model_dump()
                                    _updates_9: Dict[str, Any] = {"last_orchestrator_decision": decision}
                                    if gen_state:
                                        _updates_9["generation_state"] = gen_state
                                        _set_gen_job_status(gen_state, "packager", "blocked")
                                    await _safe_save_session(self.context_manager.memory, session_id, _updates_9)
                                    return _response_with_generation_state(
                                        {
                                            "status": "error",
                                            "session_id": session_id,
                                            "message": "Validación de empaque CompraNet: "
                                            + "; ".join(pr.errors),
                                            "results": {
                                                k: (v if isinstance(v, dict) else v.model_dump())
                                                for k, v in execution_results.items()
                                            },
                                            "orchestrator_decision": decision,
                                        },
                                        session_state,
                                        mode,
                                    )
                                await self.context_manager.record_task_completion(
                                    session_id=session_id,
                                    task_name="stage_completed:compranet_pack",
                                    result={
                                        "status": "success",
                                        "data": pr.to_dict(),
                                        "message": "Empaque CompraNet validado (manifiesto SHA-256).",
                                    },
                                )
                                if gen_state:
                                    _set_gen_job_status(gen_state, "packager", "done")
                                try:
                                    from app.services.delivery_coverage_report import (
                                        build_and_persist_coverage,
                                    )

                                    await build_and_persist_coverage(
                                        self.context_manager.memory, session_id
                                    )
                                except Exception as _cov_pack_exc:
                                    logger.warning(
                                        "coverage_report_after_pack_failed",
                                        session_id=session_id,
                                        error=str(_cov_pack_exc),
                                    )
                                if getattr(
                                    settings,
                                    "GENERATION_PRUNE_DUPLICATE_OUTPUTS_AFTER_PACK",
                                    True,
                                ):
                                    try:
                                        from app.api.v1.routes.downloads import (
                                            resolve_outputs_root,
                                        )
                                        from app.services.output_delivery_view import (
                                            prune_duplicate_output_copies,
                                        )

                                        out_root = await resolve_outputs_root(session_id)
                                        if out_root:
                                            prune_res = prune_duplicate_output_copies(
                                                out_root
                                            )
                                            logger.info(
                                                "orchestrator_generation_duplicates_pruned",
                                                session_id=session_id,
                                                removed=prune_res.get("removed_count"),
                                                names=prune_res.get("removed_names"),
                                            )
                                    except Exception as _prune_exc:
                                        logger.warning(
                                            "orchestrator_generation_prune_failed",
                                            session_id=session_id,
                                            error=str(_prune_exc)[:200],
                                        )
                        except Exception as e:
                            logger.error(
                                "generation_step_failed",
                                stage=step,
                                session_id=session_id,
                                error=str(e),
                            )
                            decision = OrchestratorState(
                                stop_reason=f"ERROR_IN_{step.upper()}",
                                aggregate_health="failed",
                                correlation_id=correlation_id,
                            ).model_dump()
                            _updates_10: Dict[str, Any] = {"last_orchestrator_decision": decision}
                            if gen_state:
                                _updates_10["generation_state"] = gen_state
                            await _safe_save_session(self.context_manager.memory, session_id, _updates_10)
                            
                            # --- POST-PROCESO PROACTIVO ---
                            await self._proactive_injection_checkpoint(session_id)
                            
                            return _response_with_generation_state(
                                {
                                    "status": "error",
                                    "session_id": session_id,
                                    "message": f"Falló el paso crítico de generación: {step}. Error: {str(e)}",
                                    "orchestrator_decision": decision,
                                },
                                session_state,
                                mode,
                            )

                if (
                    settings.DOCUMENT_INVENTORY_SERVICE_ENABLED
                    and bool(getattr(settings, "DOCUMENT_INVENTORY_SYNC_ENABLED", True))
                    and input_data.get("document_inventory")
                ):
                    try:
                        from app.services.document_inventory_service import DocumentInventoryService

                        _synced_inv = await DocumentInventoryService.sync_inventory_to_session_memory(
                            self.context_manager.memory,
                            session_id,
                            input_data["document_inventory"],
                        )
                        _sync_dump = _synced_inv.model_dump(mode="json")
                        input_data["document_inventory"] = _sync_dump
                        session_state["document_inventory"] = _sync_dump
                        agent_input = agent_input.model_copy(
                            update={
                                "company_data": {
                                    **(agent_input.company_data or {}),
                                    "document_inventory": _sync_dump,
                                }
                            }
                        )
                    except Exception as _sync_exc:
                        logger.warning(
                            "document_inventory_sync_failed",
                            session_id=session_id,
                            error=str(_sync_exc),
                        )

                econ_documents = _extract_documentos(execution_results.get("economic_writer"))
                if gen_state:
                    gen_state["status"] = "completed"
                    await _safe_save_session(
                        self.context_manager.memory, session_id,
                        {"generation_state": gen_state}
                    )

                checklist = await self._generate_checklist(session_id, input_data, execution_results)
                session_state["checklist"] = checklist

                # Ejecutar BiddingBinderAgent al final de la generación
                try:
                    from app.agents.bidding_binder import BiddingBinderAgent
                    _notify_job_progress(
                        agent_input.job_id,
                        "generation.bidding_binder",
                        98,
                        "Compilando Guía de Armado de Sobres y Checklist de Integridad...",
                    )
                    binder_res = await BiddingBinderAgent(self.context_manager).process(agent_input)
                    execution_results["bidding_binder"] = binder_res
                except Exception as e:
                    logger.error("bidding_binder_failed", session_id=session_id, error=str(e))

            # Confidence Summary (Restaurado Fase 1)
            confidence_summary = None
            if settings.CONFIDENCE_ENABLED or settings.CONFIDENCE_SHADOW_MODE:
                scores = []
                for res_val in execution_results.values():
                    # Manejar tanto dict como AgentOutput
                    if hasattr(res_val, 'data'):
                        data = res_val.data or {}
                    elif isinstance(res_val, dict):
                        data = res_val.get("data", {})
                    else:
                        data = {}
                    
                    s = data.get("confidence", {}).get("overall", 0.0)
                    if s: scores.append(s)
                if scores: confidence_summary = {"avg_confidence": sum(scores)/len(scores)}

            # Final Metadata
            final_metadata = {
                "pipeline_config": {
                    "adaptive": settings.ADAPTIVE_ORCHESTRATOR_ENABLED,
                    "pipeline_type": pipeline_config.pipeline_type.value,
                    "stages_planned": pipeline_config.stages,
                    "stages_executed": [s for s in pipeline_config.stages if s in execution_results],
                    "stages_skipped": stages_skipped,
                    "rules_triggered": rules_triggered
                },
                "confidence_summary": confidence_summary,
                "backtracking": {"iterations": bt_iterations, "history": bt_history} if settings.BACKTRACKING_ENABLED else None,
                "feedback_pending": (confidence_summary and confidence_summary.get("avg_confidence", 1.0) < settings.CONFIDENCE_THRESHOLD_DEFAULT) if settings.FEEDBACK_UI_ENABLED else False,
                "fast_track_document_candidates": fast_track_candidates,
                "telemetry": telemetry,
            }
            agg_health = _aggregate_health_from_results(execution_results)
            fresh_for_gate = await self.context_manager.memory.get_session(session_id) or session_state
            from app.services.economic_coverage_gate import (
                evaluate_economic_coverage_before_final_ok,
            )
            from app.agents.economic import _build_structured_price_pending_questions

            coverage_block = evaluate_economic_coverage_before_final_ok(
                fresh_for_gate, session_id
            )
            if coverage_block:
                line_items = list(fresh_for_gate.get("session_line_items") or [])
                from app.services.structured_economic_price_mapper import (
                    build_structured_price_slots,
                )

                slots = build_structured_price_slots(
                    line_items, fresh_for_gate.get("economic_user_inputs")
                )
                missing_slots = [s for s in slots if s.get("captured_price") is None]
                pending_add = _build_structured_price_pending_questions(missing_slots)
                from app.services.hitl_queue_service import normalize_pending_queue

                merged_pending = normalize_pending_queue(
                    list(fresh_for_gate.get("pending_questions") or []) + pending_add
                )
                gate_decision = OrchestratorState(
                    stop_reason="ECONOMIC_COVERAGE_GAP",
                    aggregate_health=agg_health,
                    next_steps=[
                        "Completa los precios pendientes en el chat o en resolución por bloque.",
                    ],
                    correlation_id=correlation_id,
                ).model_dump()
                await _safe_save_session(
                    self.context_manager.memory,
                    session_id,
                    {
                        "last_orchestrator_decision": gate_decision,
                        "pending_questions": merged_pending,
                        "current_question_index": 0,
                        "economic_coverage_gate": coverage_block,
                    },
                )
                return {
                    "status": "waiting_for_data",
                    "session_id": session_id,
                    "message": coverage_block.get("message"),
                    "orchestrator_decision": gate_decision,
                    "correlation_id": correlation_id,
                }

            from app.services.formats_coverage_gate import (
                evaluate_delivery_completeness_before_final_ok,
            )

            delivery_block = evaluate_delivery_completeness_before_final_ok(
                fresh_for_gate, session_id
            )
            if delivery_block:
                gate_decision = OrchestratorState(
                    stop_reason="DELIVERY_COVERAGE_GAP",
                    aggregate_health=agg_health,
                    next_steps=[
                        "Regenera los anexos faltantes y vuelve a empaquetar.",
                        "Revisa el panel «Formatos/Anexos detectados» frente a la entrega.",
                    ],
                    correlation_id=correlation_id,
                ).model_dump()
                await _safe_save_session(
                    self.context_manager.memory,
                    session_id,
                    {
                        "last_orchestrator_decision": gate_decision,
                        "delivery_coverage_gate": delivery_block,
                    },
                )
                return {
                    "status": "waiting_for_data",
                    "session_id": session_id,
                    "message": delivery_block.get("message"),
                    "orchestrator_decision": gate_decision,
                    "correlation_id": correlation_id,
                }

            decision = OrchestratorState(
                stop_reason="FINAL_OK",
                aggregate_health=agg_health,
                next_steps=next_steps,
                correlation_id=correlation_id,
            ).model_dump()
            # Refrescar desde BD para preservar tasks_completed escritos por los agentes
            await _safe_save_session(
                self.context_manager.memory,
                session_id,
                {
                    "last_orchestrator_decision": decision,
                    "last_orchestrator_metadata": final_metadata,
                    "pending_questions": [],
                    "current_question_index": 0,
                    "last_document_quality_waiting_hints": None,
                    "last_document_fill_quality_waiting_hints": None,
                    **({"generation_state": gen_state} if gen_state else {}),
                },
            )
            econ_blocked = (
                gen_state is not None
                and _gen_job_status(gen_state, "economic_writer") == "blocked"
            )
            final_status = "partial" if econ_blocked else "success"
            final_chatbot = None
            if econ_blocked:
                final_chatbot = (
                    "Expediente generado con advertencias: la propuesta técnica y los formatos "
                    "administrativos están listos, pero la propuesta económica no se materializó. "
                    "Ejecuta `generar propuesta económica` en el chat y vuelve a pulsar **Generar Documentos**."
                )
            self._persist_latest_job_metadata(session_id, final_status, final_metadata, decision)
            return _response_with_generation_state(
                {
                    "status": final_status,
                    "session_id": session_id,
                    "chatbot_message": final_chatbot,
                    "fast_track_document_candidates": fast_track_candidates,
                    "results": {
                        k: (v if isinstance(v, dict) else v.model_dump())
                        for k, v in execution_results.items()
                    },
                    "orchestrator_decision": decision,
                    "metadata": final_metadata,
                },
                session_state,
                mode,
            )

    def _persist_latest_job_metadata(
        self,
        session_id: str,
        status: str,
        metadata: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> None:
        """Escribe snapshot legible de telemetría para consumo externo."""
        try:
            out_dir = Path("out") / "metadata"
            out_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "session_id": session_id,
                "status": status,
                "metadata": metadata,
                "orchestrator_decision": decision,
                "generated_at": _now_utc_iso(),
            }
            (out_dir / "latest_job.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("persist_latest_job_metadata_failed", session_id=session_id, error=str(e))

    async def _generate_checklist(self, session_id, input_data, results):
        """
        Hito 7: concilia requisitos de ``compliance_master_list`` con
        ``documentos_generados`` (administrativa / técnica / formatos).
        """
        checklist: List[Dict[str, Any]] = []
        comp = input_data.get("compliance_master_list") or {}
        gen_docs = input_data.get("documentos_generados") or {}

        cat_folder = {
            "administrativo": "administrativa",
            "tecnico": "tecnica",
            "formatos": "formatos",
        }

        def _pick_file(rid: Any, nombre: str, docs: List[Dict[str, Any]]) -> Optional[str]:
            rid_s = str(rid or "").strip()
            for doc in docs or []:
                fname = doc.get("nombre") or doc.get("name") or ""
                if not fname:
                    continue
                if rid_s and rid_s in fname:
                    return fname
                words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{4,}", nombre or "")
                if len(words) >= 2:
                    hits = sum(1 for w in words if w.lower() in fname.lower())
                    if hits >= 2:
                        return fname
                elif len(words) == 1 and words[0].lower() in fname.lower():
                    return fname
            return None

        for cat in ("administrativo", "tecnico", "formatos"):
            folder = cat_folder.get(cat, cat)
            doc_list = gen_docs.get(folder, []) or []
            for r in comp.get(cat, []) or []:
                rid = r.get("id")
                nombre = str(r.get("nombre") or "")
                matched = _pick_file(rid, nombre, doc_list)
                checklist.append(
                    {
                        "req_id": rid,
                        "status": "fulfilled" if matched else "missing",
                        "file": matched,
                    }
                )
        return checklist
