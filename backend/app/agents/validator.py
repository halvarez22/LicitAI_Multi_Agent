import logging
import json
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.core.observability import get_logger, agent_span
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

logger = get_logger(__name__)


class Conflict(BaseModel):
    """Conflicto detectado en validación cruzada Analyst ↔ Compliance."""

    type: str
    description: str = ""


class ValidationReport(BaseModel):
    """Reporte determinístico para backtracking (Fase 3)."""

    consistent: bool = True
    conflicts: List[Conflict] = Field(default_factory=list)
    requires_compliance_revision: bool = False
    requires_analyst_revision: bool = False
    suggested_corrections: Dict[str, Any] = Field(default_factory=dict)


def _unwrap_agent_payload(value: Any) -> Dict[str, Any]:
    """Normaliza salida de agente (``AgentOutput``, dict anidado o plano)."""
    if value is None:
        return {}
    if isinstance(value, AgentOutput):
        data = value.data
        return data if isinstance(data, dict) else {}
    if isinstance(value, dict):
        nested = value.get("data")
        if isinstance(nested, dict):
            return nested
        return value
    return {}


def _collect_requirement_ids(payload: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for item in payload.get("requirements") or []:
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids


def _collect_compliance_ids(payload: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for bucket in ("administrativo", "tecnico", "formatos"):
        for item in payload.get(bucket) or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(str(item["id"]))
    return ids


class ValidatorAgent:
    """
    Validación cruzada determinística entre Analyst y Compliance.

    Usado por el orquestador cuando ``BACKTRACKING_ENABLED`` está activo.
    """

    def validate(self, analyst_out: Any, compliance_out: Any) -> ValidationReport:
        analyst_data = _unwrap_agent_payload(analyst_out)
        compliance_data = _unwrap_agent_payload(compliance_out)
        req_ids = _collect_requirement_ids(analyst_data)
        covered_ids = _collect_compliance_ids(compliance_data)
        missing = sorted(req_ids - covered_ids)

        if not missing:
            return ValidationReport(consistent=True, conflicts=[])

        conflicts = [
            Conflict(
                type="missing_coverage",
                description=f"Requisito {rid} sin cobertura en compliance",
            )
            for rid in missing
        ]
        return ValidationReport(
            consistent=False,
            conflicts=conflicts,
            requires_compliance_revision=True,
            suggested_corrections={rid: "Revisar cobertura en compliance" for rid in missing},
        )


class RequirementValidatorAgent(BaseAgent):
    """
    Agente especializado en el 'Reconocimiento de Carga'.
    Valida si un nuevo documento satisface requerimientos que estaban marcados como FALTANTES.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="validator_001",
            name="Validador de Requerimientos",
            description="Valida documentos contra brechas de cumplimiento detectadas.",
            context_manager=context_manager
        )

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """
        Implementación obligatoria de BaseAgent. 
        Puede usarse para validación masiva de una sesión.
        """
        session_id = agent_input.session_id
        company_id = agent_input.company_id
        
        # Si no se especifica un doc_id en el input, intentamos validar contra todos
        # los documentos ANALYZED recientes (o simplemente devolvemos error si no aplica)
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            message="El validador está listo. Usa validate_document_against_gaps para validaciones individuales.",
            data={}
        )

    async def validate_document_against_gaps(self, session_id: str, doc_id: str, company_id: str) -> Dict[str, Any]:
        """
        Punto de entrada para validar un doc recién subido contra los GAPs de la sesión.
        """
        # 1. Recuperar la sesión y el dictamen actual
        session = await self.context_manager.memory.get_session(session_id)
        if not session:
            return {"success": False, "reason": "session_not_found"}

        state = session.get("state_data", {})
        dictamen = state.get("dictamen") or state.get("last_analysis")
        
        # Si no hay dictamen previo, no hay GAPs que validar todavía
        if not dictamen:
            return {"success": False, "reason": "no_previous_analysis"}

        # Extraer el gap_analysis del reporte de auditoría estratégica
        # El Strategist lo guarda en extracted_data -> data -> audit_report -> gap_analysis
        audit_report = (dictamen.get("extracted_data") or {}).get("data", {}).get("audit_report", {})
        gaps = audit_report.get("gap_analysis", [])
        
        missing_gaps = [g for g in gaps if g.get("estado_empresa") in ("FALTANTE", "VENCIDO", "ERROR")]
        if not missing_gaps:
            return {"success": False, "reason": "no_missing_gaps"}

        # 2. Obtener info del documento
        doc = await self.context_manager.memory.get_document(doc_id)
        filename = doc.get("content", {}).get("filename", "documento")
        
        # 3. Validar cada GAP contra el nuevo documento
        resolved_gaps = []
        updated_gaps = list(gaps)
        
        for gap in missing_gaps:
            req_text = gap.get("requisito")
            # Usamos RAG para ver si el documento tiene la respuesta
            # Limitamos la búsqueda a este documento específico usando su ID como filtro
            # (El smart_search actual busca en toda la sesión, pero aquí queremos foco en el doc)
            
            # TODO: Implementar búsqueda filtrada por doc_id en VectorDbServiceClient
            # Por ahora usamos el contexto global pero enfatizando el doc en el prompt
            
            search_query = f"Busca evidencia para el requisito: {req_text}"
            context = await self.context_manager.vector_db.search_by_session(session_id, search_query, limit=5)
            
            # Filtramos fragmentos que pertenezcan a este documento
            doc_context = [c for c in context if c.get("metadata", {}).get("doc_id") == doc_id]
            if not doc_context:
                continue

            context_text = "\n".join([c.get("text", "") for c in doc_context])
            
            prompt = f"""
            Como Auditor Senior de LicitAI, valida si este documento resuelve el siguiente requerimiento faltante.
            
            REQUERIMIENTO: {req_text}
            DOCUMENTO ACTUAL: {filename}
            
            EXTRACTOS DEL DOCUMENTO:
            {context_text}
            
            ¿El documento satisface plenamente el requerimiento? 
            Responde ÚNICAMENTE con un JSON:
            {{
                "is_satisfied": bool,
                "reason": "Explicación breve de por qué sí o por qué no (máx 20 palabras)",
                "evidence": "Cita breve del texto que lo valida",
                "page": 0
            }}
            """
            
            from app.services.resilient_llm import ResilientLLM
            llm = ResilientLLM()
            response = await llm.generate(prompt, correlation_id=f"val-{doc_id}")
            
            try:
                # Limpiar la respuesta por si el LLM incluye markdown
                clean_response = response.strip()
                if "```json" in clean_response:
                    clean_response = clean_response.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_response:
                    clean_response = clean_response.split("```")[1].strip()
                
                result = json.loads(clean_response)
                
                if result.get("is_satisfied"):
                    # ¡Bingo! Requerimiento resuelto
                    gap["estado_empresa"] = "OK"
                    gap["accion_requerida"] = "Validado automáticamente"
                    gap["evidencia"] = result.get("evidence")
                    gap["razon_validacion"] = result.get("reason")
                    gap["doc_evidencia"] = filename
                    gap["doc_id_evidencia"] = doc_id
                    
                    resolved_gaps.append({
                        "req": req_text,
                        "reason": result.get("reason")
                    })
            except Exception as e:
                logger.error(f"Error parsing validator response: {e}")
                continue

        # 4. Si hubo cambios, persistir el dictamen actualizado
        if resolved_gaps:
            audit_report["gap_analysis"] = updated_gaps
            # Guardamos de vuelta en la sesión
            if "dictamen" in state:
                state["dictamen"]["extracted_data"]["data"]["audit_report"] = audit_report
            if "last_analysis" in state:
                state["last_analysis"]["data"]["audit_report"] = audit_report
                
            await self.context_manager.memory.save_session(session_id, session)
            
            # Generar mensaje de éxito
            msg = f"¡Bingo! He analizado **{filename}** y tengo buenas noticias:\n\n"
            for res in resolved_gaps:
                msg += f"✅ **{res['req']}**: {res['reason']}\n"
            msg += "\nHe actualizado tu estatus de cumplimiento automáticamente."
            
            return {
                "success": True,
                "resolved_count": len(resolved_gaps),
                "message": msg,
                "details": resolved_gaps
            }

        return {"success": False, "reason": "no_resolutions_found"}
