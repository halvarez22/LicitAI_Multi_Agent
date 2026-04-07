import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.core.observability import get_logger, agent_span, generate_correlation_id
from app.contracts.session_contracts import SessionStateMigrator
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.contracts.orchestrator_contracts import OrchestratorState
from app.config.settings import settings
from app.orchestration.pipeline_configurator import PipelineConfigurator, PipelineConfig, ActionType, ConditionType

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

class OrchestratorAgent(BaseAgent):
    """
    Agente 0: Orquestador (Supervisor).
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
            agent_input = AgentInput(
                session_id=session_id,
                company_id=str(input_data.get("company_id")) if input_data.get("company_id") else None,
                mode=(input_data.get("company_data") or {}).get("mode", "full"),
                resume_generation=input_data.get("resume_generation", False),
                correlation_id=correlation_id,
                job_id=input_data.get("job_id")
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
            raw_session_state = await self.context_manager.memory.get_session(session_id)
            if not raw_session_state:
                await self.context_manager.initialize_session(session_id, input_data)
                session_state = await self.context_manager.memory.get_session(session_id)
            else:
                session_state, _ = SessionStateMigrator.migrate(session_id, raw_session_state)
            
            context = await self.context_manager.get_global_context(session_id)
            tasks_completed = context.get("session_state", {}).get("tasks_completed", [])
            execution_results = {}
            next_steps = []

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
            if reuse_prior_stages:
                for task in tasks_completed:
                    task_name = task.get("task", "")
                    if task_name.startswith("stage_completed:"):
                        completed_stage = task_name.split(":", 1)[1]
                        completed_stages.add(completed_stage)
                        logger.info(
                            "resume_skip_stage",
                            stage=completed_stage,
                            session_id=session_id,
                            mode=mode,
                        )

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
                    _notify_job_progress(
                        agent_input.job_id,
                        "analysis",
                        32,
                        "Agente analista: extrayendo requisitos de las bases…",
                    )
                    res = await AnalystAgent(self.context_manager).process(agent_input)
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
                    _notify_job_progress(
                        agent_input.job_id,
                        "compliance",
                        41,
                        "Auditoría forense en curso (map-reduce por zonas)…",
                    )
                    try:
                        res = await ComplianceAgent(self.context_manager).process(agent_input)
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

                # Error check (Legacy Support)
                comp_res = execution_results.get("compliance")
                comp_st = _result_status_value(comp_res)
                if comp_res is not None and comp_st == AgentStatus.ERROR.value:
                    decision = OrchestratorState(stop_reason="COMPLIANCE_ERROR", aggregate_health="failed", next_steps=next_steps, correlation_id=correlation_id).model_dump()
                    # Si es error, guardamos sesión antes de salir
                    session_state["last_orchestrator_decision"] = decision
                    await self.context_manager.memory.save_session(session_id, session_state)
                    return {"status": "success", "session_id": session_id, "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()}, "orchestrator_decision": decision}

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

            # Economic
            if self._should_execute_stage("economic", pipeline_config, stages_skipped) and "economic" not in completed_stages:
                from app.agents.economic import EconomicAgent
                try:
                    _notify_job_progress(
                        agent_input.job_id,
                        "economic",
                        88,
                        "Evaluación económica en curso…",
                    )
                    econ_input = agent_input.model_copy(
                        update={
                            "company_data": {
                                **agent_input.company_data,
                                "compliance_master_list": input_data.get("compliance_master_list") or {},
                            }
                        }
                    )
                    res = await EconomicAgent(self.context_manager).process(econ_input)
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
                        latest_session = await self.context_manager.memory.get_session(session_id) or {}
                        latest_session["last_orchestrator_decision"] = decision
                        if econ_hints is not None:
                            latest_session["last_economic_waiting_hints"] = econ_hints
                        await self.context_manager.memory.save_session(session_id, latest_session)
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

            # Generation
            if mode in ["full", "generation", "generation_only"]:
                from app.agents.data_gap import DataGapAgent
                if self._should_execute_stage("datagap", pipeline_config, stages_skipped):
                    res = await DataGapAgent(self.context_manager).process(agent_input)
                    execution_results["datagap"] = res
                    stages_executed.append("datagap")
                    if res.status == AgentStatus.WAITING_FOR_DATA:
                        decision = OrchestratorState(stop_reason="INCOMPLETE_DATA", aggregate_health="partial", next_steps=next_steps, correlation_id=correlation_id).model_dump()
                        # REFRESH para no borrar pending_questions que DataGap acaba de guardar
                        latest_session = await self.context_manager.memory.get_session(session_id) or {}
                        latest_session["last_orchestrator_decision"] = decision
                        await self.context_manager.memory.save_session(session_id, latest_session)
                        return {
                            "status": "waiting_for_data",
                            "session_id": session_id,
                            "chatbot_message": res.message,
                            "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()},
                            "orchestrator_decision": decision,
                        }
                
                for step, a_cls in [("technical", "TechnicalWriterAgent"), ("formats", "FormatsAgent"), ("economic_writer", "EconomicWriterAgent"), ("packager", "DocumentPackagerAgent"), ("delivery", "DeliveryAgent")]:
                    if self._should_execute_stage(step, pipeline_config, stages_skipped):
                        try:
                            if step == "technical": from app.agents.technical_writer import TechnicalWriterAgent as C
                            elif step == "formats": from app.agents.formats import FormatsAgent as C
                            elif step == "economic_writer": from app.agents.economic_writer import EconomicWriterAgent as C
                            elif step == "packager": from app.agents.document_packager import DocumentPackagerAgent as C
                            else: from app.agents.delivery import DeliveryAgent as C
                            
                            res = await C(self.context_manager).process(agent_input)
                            execution_results[step] = res
                            
                            # CORTAR SI UN AGENTE REQUIERE DATOS (EVITA GENERACIÓN PARCIAL)
                            if hasattr(res, 'status') and res.status == AgentStatus.WAITING_FOR_DATA:
                                logger.info("generation_paused_waiting_data", stage=step, session_id=session_id)
                                decision = OrchestratorState(
                                    stop_reason=f"INCOMPLETE_{step.upper()}_DATA",
                                    aggregate_health="partial",
                                    next_steps=next_steps,
                                    correlation_id=correlation_id
                                ).model_dump()
                                # REFRESH para no borrar pending_questions/metadata persistidos por redactores/formatos
                                latest_session = await self.context_manager.memory.get_session(session_id) or {}
                                latest_session["last_orchestrator_decision"] = decision
                                await self.context_manager.memory.save_session(session_id, latest_session)
                                return {
                                    "status": "waiting_for_data",
                                    "session_id": session_id,
                                    "chatbot_message": res.message,
                                    "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()},
                                    "orchestrator_decision": decision,
                                }
                            
                            # CORTAR SI UN AGENTE REPORTA ERROR (EVITA GENERACIÓN CORRUPTA)
                            if hasattr(res, 'status') and res.status == AgentStatus.ERROR:
                                logger.error("generation_step_reported_error", stage=step, session_id=session_id, message=getattr(res, 'message', 'Error desconocido'))
                                decision = OrchestratorState(
                                    stop_reason=f"ERROR_REPORTED_IN_{step.upper()}",
                                    aggregate_health="failed",
                                    correlation_id=correlation_id
                                ).model_dump()
                                return {
                                    "status": "error",
                                    "session_id": session_id,
                                    "message": f"El agente de {step} reportó un error crítico: {getattr(res, 'message', 'Sin detalle')}",
                                    "orchestrator_decision": decision
                                }

                            next_steps.append(f"{step}_OK")
                        except Exception as e:
                            logger.error("generation_step_failed", stage=step, session_id=session_id, error=str(e))
                            decision = OrchestratorState(
                                stop_reason=f"ERROR_IN_{step.upper()}",
                                aggregate_health="failed",
                                correlation_id=correlation_id
                            ).model_dump()
                            return {
                                "status": "error",
                                "session_id": session_id,
                                "message": f"Falló el paso crítico de generación: {step}. Error: {str(e)}",
                                "orchestrator_decision": decision
                            }

                checklist = await self._generate_checklist(session_id, input_data, execution_results)
                session_state["checklist"] = checklist

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
                "feedback_pending": (confidence_summary and confidence_summary.get("avg_confidence", 1.0) < settings.CONFIDENCE_THRESHOLD_DEFAULT) if settings.FEEDBACK_UI_ENABLED else False
            }
            agg_health = _aggregate_health_from_results(execution_results)
            decision = OrchestratorState(
                stop_reason="FINAL_OK",
                aggregate_health=agg_health,
                next_steps=next_steps,
                correlation_id=correlation_id,
            ).model_dump()
            session_state["last_orchestrator_decision"] = decision
            await self.context_manager.memory.save_session(session_id, session_state)

            return {"status": "success", "session_id": session_id, "results": {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in execution_results.items()}, "orchestrator_decision": decision, "metadata": final_metadata}

    async def _generate_checklist(self, session_id, input_data, results):
        checklist = []
        comp = input_data.get("compliance_master_list", {})
        for cat in ["administrativo", "tecnico", "formatos"]:
            for r in comp.get(cat, []): checklist.append({"req_id": r.get("id"), "status": "pending"})
        return checklist
