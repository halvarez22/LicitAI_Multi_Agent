import logging
import json
import re
from typing import Any, Dict, List, Optional
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.core.observability import get_logger
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.services.resilient_llm import ResilientLLMClient
from app.utils.doc_formatting import ANTI_PLACEHOLDER_PROMPT_RULE

logger = get_logger(__name__)

class WriterAgent(BaseAgent):
    """
    Agente 6: El Brazo Ejecutor (Redactor Proactivo).
    Genera borradores de documentos específicos basados en Gaps de cumplimiento.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="writer_001",
            name="Redactor Estratégico",
            description="Genera borradores de anexos y manifiestos bajo demanda.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """Implementación obligatoria de BaseAgent."""
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            message="El redactor está listo. Usa draft_annex para generar documentos específicos.",
            data={}
        )

    async def draft_annex(self, session_id: str, requirement_id: str, company_id: str) -> Dict[str, Any]:
        """
        Genera un borrador de un anexo específico basado en su ID o nombre.
        """
        # 1. Recuperar contexto de la empresa (Perfil Maestro)
        company = await self.context_manager.memory.get_company(company_id)
        if not company:
            return {"success": False, "reason": "company_not_found"}
        
        master_profile = company.get("master_profile", {})
        
        # 2. Identificar el requerimiento en el dictamen actual
        session = await self.context_manager.memory.get_session(session_id) or {}
        state = session.get("state_data", {})
        dictamen = state.get("dictamen") or state.get("last_analysis") or {}
        
        # Buscar el requerimiento en la lista de causales o gaps
        all_requirements = dictamen.get("causales", [])
        target_req = next((r for r in all_requirements if r.get("id") == requirement_id), None)
        
        if not target_req:
            # Fallback: buscar por texto si el ID es volátil
            target_req = {"texto": requirement_id} # Asumimos que requirement_id es el nombre si no hay ID
            
        req_text = target_req.get("texto", requirement_id)
        
        # 3. RAG: Buscar el formato o instrucciones exactas en las bases
        search_query = f"Formato, anexo o texto requerido para: {req_text}"
        search_results = self.context_manager.vector_db.query_texts(session_id, search_query, n_results=8)
        bases_context = "\n".join(search_results.get("documents", []))
        
        # 4. Generación del Borrador (Contexto Tripartito)
        identity_prompt = f"""
        EMPRESA: {master_profile.get('razon_social', 'N/A')}
        RFC: {master_profile.get('rfc', 'N/A')}
        REPRESENTANTE LEGAL: {master_profile.get('representante_legal', 'N/A')}
        DOMICILIO: {master_profile.get('domicilio_fiscal', 'S/D')}
        TIPO: {master_profile.get('tipo', 'MORAL')}
        """
        
        system_prompt = f"""
        ERES UN REDACTOR LEGAL SENIOR EXPERTO EN LICITACIONES PÚBLICAS.
        Tu misión es redactar un BORRADOR FINAL del anexo solicitado.
        
        REGLAS DE ORO:
        1. USA los datos reales de la empresa proporcionados. No inventes datos.
        2. SIGUE el formato y lenguaje legal encontrado en los fragmentos de las bases.
        3. REDACTA en primera persona ({'Yo' if master_profile.get('tipo') == 'FISICA' else 'Nosotros'}).
        4. {ANTI_PLACEHOLDER_PROMPT_RULE} - No dejes [corchetes] ni espacios vacíos si el dato existe.
        5. Sé asertivo y profesional.
        """
        
        user_prompt = f"""
        REDACTA EL SIGUIENTE DOCUMENTO PARA LA LICITACIÓN:
        
        NOMBRE DEL ANEXO/REQUISITO: {req_text}
        
        DATOS DE LA EMPRESA (USAR ESTOS):
        {identity_prompt}
        
        CONTEXTO DE LAS BASES (FRAGMENTOS DEL PDF):
        {bases_context}
        
        Genera el documento completo en formato Markdown, incluyendo encabezado formal, cuerpo legal y espacio para firma.
        """
        
        response = await self.llm.generate(user_prompt, system_prompt=system_prompt, correlation_id=f"draft-{requirement_id}")
        
        if not response:
            return {"success": False, "reason": "generation_failed"}

        return {
            "success": True,
            "requirement_id": requirement_id,
            "requirement_name": req_text,
            "draft_content": response,
            "metadata": {
                "used_profile": True,
                "used_bases": len(bases_context) > 0,
                "timestamp": str(datetime.now())
            }
        }

from datetime import datetime
