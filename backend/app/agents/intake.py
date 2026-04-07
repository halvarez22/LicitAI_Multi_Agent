import logging
from typing import Any, Dict, List, Optional
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.agents.data_gap import DataGapAgent

logger = logging.getLogger(__name__)

class IntakeAgent(BaseAgent):
    """
    Agente 4: Recaudador de Información (Intake).
    Especialista en Conversación y Extracción de Datos Naturales.
    Limpia, Valida y Persiste los Gaps detectados por el Agente de Completitud.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="intake_001",
            name="Agente Recaudador Inteligente",
            description="Procesa respuestas del chat para sanar el perfil de empresa.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()

    async def process_user_response(self, session_id: str, company_id: str, user_text: str) -> Dict[str, Any]:
        """
        Punto de entrada principal para la interacción conversacional.
        Procesa el texto del usuario contra el siguiente GAP pendiente en la sesión.
        """
        # 1. Recuperar estado de la sesión
        session_state = await self.context_manager.memory.get_session(session_id)
        if not session_state:
            return {"status": "error", "message": f"No se encontró la sesión '{session_id}'."}
            
        pending = session_state.get("pending_questions", [])
        if not pending:
            return {"status": "error", "message": "No hay preguntas pendientes en esta sesión."}

        # 2. Identificar el GAP actual (primero de la lista)
        current_gap = pending[0]
        field_key = current_gap["field"]
        label = current_gap["label"]

        print(f"[Intake] Analizando respuesta para '{label}'...")

        # 3. Extracción de Valor vía LLM
        extracted_value = await self._extract_value_with_llm(user_text, label)
        
        if not extracted_value or "NO_PROPORCIONADO" in extracted_value.upper():
            logger.warning(f"[Intake] No se pudo extraer '{label}' del texto: '{user_text[:50]}...'")
            return {
                "status": "ask_again",
                "message": f"Lo siento, no pude identificar el **{label}** en tu respuesta. ¿Me lo puedes repetir de forma clara?"
            }

        # 4. Validación de Calidad (Reglas de Sanidad)
        # Reutilizamos la lógica del DataGap para mantener un criterio de veracidad único
        gap_validator = DataGapAgent(self.context_manager)
        
        if not gap_validator._is_data_valid(field_key, extracted_value):
            logger.warning(f"[Intake] Valor extraído '{extracted_value}' para '{field_key}' falló validación.")
            return {
                "status": "invalid_data",
                "message": f"🚨 El dato '**{extracted_value}**' no parece ser un {label} válido. Por favor, asegúrate de que esté completo y sin errores."
            }

        # 5. Persistencia Industrial
        print(f"[Intake] Dato validado satisfactoriamente: '{extracted_value}'.")
        await self._update_master_profile(company_id, field_key, extracted_value)

        # 6. Avance del Flujo Conversacional
        pending.pop(0) 
        session_state["pending_questions"] = pending
        await self.context_manager.memory.save_session(session_id, session_state)

        if not pending:
            print("[Intake] Expediente completo tras interacción del usuario.")
            return {
                "status": "complete",
                "message": f"¡Perfecto! El dato de **{label}** ha sido guardado. Ya tenemos el expediente completo para esta licitación. 🎉",
                "next_step": "re_run_orchestrator"
            }
        
        next_q = pending[0]
        return {
            "status": "partial",
            "message": f"¡Excelente! Recibí el **{label}**. Ahora, para continuar:\n\n📋 {next_q['question']}",
            "next_field": next_q["field"]
        }

    async def _extract_value_with_llm(self, text: str, label: str) -> Optional[str]:
        prompt = f"""
TAREA: Extrae ÚNICAMENTE el valor solicitado del texto del usuario.
VALOR A BUSCAR: {label}

TEXTO DEL USUARIO: "{text}"

INSTRUCCIONES:
- Si el usuario da el dato, responde SOLO con el dato (ej: '55 1234 5678').
- Si el usuario dice que 'no sabe' o no proporciona el dato real, responde: NO_PROPORCIONADO
- No expliques nada. Sin saludos ni aclaraciones. Solo el valor o NO_PROPORCIONADO.
"""
        resp = await self.llm.generate(
            prompt=prompt, 
            system_prompt="Eres un extractor de datos de chat ultra-preciso y minimalista.",
            format="text"
        )
        if isinstance(resp, dict):
            raw = str(resp.get("response", "")).strip()
            if "success" in resp:
                return raw if resp.get("success") else ""
            return raw
        return resp.response.strip() if getattr(resp, "success", False) else ""

    async def _update_master_profile(self, company_id: str, field: str, value: str):
        try:
            company = await self.context_manager.memory.get_company(company_id)
            if company:
                profile = company.get("master_profile", {})
                profile[field] = value
                company["master_profile"] = profile
                await self.context_manager.memory.save_company(company_id, company)
            else:
                logger.error(f"[Intake] No se pudo encontrar perfil de empresa ID: {company_id}")
        except Exception as e:
            logger.error(f"[Intake] Error en BD: {e}")

    async def process(self, agent_input: AgentInput | str, input_data: Optional[Dict[str, Any]] = None) -> AgentOutput:
        if not isinstance(agent_input, AgentInput):
            payload = input_data or {}
            if not isinstance(payload, dict):
                payload = {}
            agent_input = AgentInput(
                session_id=str(agent_input),
                company_id=str(payload.get("company_id")) if payload.get("company_id") else None,
                company_data=payload.get("company_data") if isinstance(payload.get("company_data"), dict) else payload,
                mode=payload.get("mode", "full"),
                correlation_id=payload.get("correlation_id"),
                resume_generation=bool(payload.get("resume_generation", False)),
                job_id=payload.get("job_id"),
            )
        return AgentOutput(
            status=AgentStatus.ERROR,
            agent_id=self.agent_id,
            session_id=agent_input.session_id,
            error="Use process_user_response_instead for conversational intake",
            correlation_id=agent_input.correlation_id
        )
