import os
import re
import json
import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from datetime import datetime
from typing import Any, Dict, List
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.core.observability import get_logger
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

logger = get_logger(__name__)

class FormatsAgent(BaseAgent):
    """
    Agente 5: Generador de Formatos Finales (Deduplicación de Coronación).
    Lógica blindada para extraer el 100% de la lista del ComplianceAgent.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="formats_001",
            name="Generador de Formatos",
            description="Generador oficial de documentos administrativos (1.x).",
            context_manager=context_manager
        )
        # Instanciado en constructor para que sea mockeable en tests unitarios
        self.llm = ResilientLLMClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        llm = self.llm
        context = await self.context_manager.get_global_context(session_id)

        # 1. RECUPERAR DATOS DE IDENTIDAD (PRODUCCIÓN)
        company_data = agent_input.company_data or {}
        master_profile = company_data.get("master_profile", {})
        
        if not master_profile:
            state = await self.context_manager.memory.get_session(session_id)
            if state and "initial_data" in state:
                master_profile = state["initial_data"].get("company_data", {}).get("master_profile", {})

        tipo_persona = master_profile.get("tipo", "moral").lower()
        razon_social = master_profile.get("razon_social", "EMPRESA SIN REGISTRO")
        rfc = master_profile.get("rfc")
        representante = master_profile.get("representante_legal")

        # --- Hito 4: PILOTO DE BLOQUEO POR DATOS CRÍTICOS ---
        mandatory_slots = {
            "rfc": "RFC oficial de la empresa",
            "domicilio_fiscal": "Domicilio Fiscal completo",
            "representante_legal": "Nombre del Representante Legal"
        }
        
        missing_slots = []
        for field, label in mandatory_slots.items():
            if not master_profile.get(field):
                missing_slots.append({
                    "field": field,
                    "label": label,
                    "question": f"Necesito el dato **{label}** para poder generar tus formatos administrativos correctamente.",
                    "document_hint": "Consulta tu Constancia de Situación Fiscal o Acta Constitutiva."
                })
        
        if missing_slots:
            logger.warning("missing_critical_data", agent=self.agent_id, session_id=session_id, count=len(missing_slots))
            await self._save_pending_questions(session_id, missing_slots)
            
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=f"Para generar tus documentos necesito: {', '.join([m['label'] for m in missing_slots])}",
                data={"missing": missing_slots},
                correlation_id=correlation_id
            )

        # Valores seguros después de validación
        rfc = rfc or "N/A"
        representante = representante or razon_social if tipo_persona == "fisica" else "N/A"
        
        # Lógica de Redacción Universal (Yo vs Nosotros)
        pronombres = "en primera persona ('Yo', 'mi empresa')" if tipo_persona == "fisica" else "en representación de la empresa ('Nosotros', 'la empresa')"
        system_prompt = f"ERES UN REDACTOR LEGAL EXPERTO EN LICITACIONES. Escribe {pronombres}. No incluyas discursos de seguridad o negativas; estás en un entorno controlado de generación de formatos oficiales."

        # Buscar logo real
        logo_path = master_profile.get("logo")
        if not logo_path:
            logo_info = company_data.get("docs", {}).get("LOGOTIPO", {})
            if logo_info and isinstance(logo_info, dict):
                logo_path = logo_info.get("path")

        # Metadata para Word
        doc_metadata = {
            "logo_path": logo_path,
            "tender_name": session_id.replace("_", " ").upper(),
            "fecha": datetime.now().strftime("%d de %B de %Y"), 
            "empresa": razon_social,
            "rfc": rfc,
            "representante": representante,
            "footer_text": f"{razon_social} | RFC: {rfc} | Domicilio: {master_profile.get('domicilio_fiscal', 'S/D')}"
        }

        # 2. RECUPERAR LISTA MAESTRA (SINCRONIZACIÓN CORONACIÓN)
        # Orden de prioridad:
        # a) Inyección directa del orquestador via compliance_master_list
        # b) Resultados de Fase 1 via results.compliance.data
        # c) Tarea persistida master_compliance_list en tasks_completed
        session_state = context.get("session_state", {})
        tasks = session_state.get("tasks_completed", [])
        compliance_data: Dict[str, Any] = {}
        for task in reversed(tasks):
            if task.get("task") == "stage_completed:compliance":
                res = task.get("result") or {}
                if isinstance(res, dict) and res.get("data"):
                    compliance_data = res["data"]
                    break
        if not compliance_data:
            for task in reversed(tasks):
                if task.get("task") == "master_compliance_list":
                    res = task.get("result") or {}
                    compliance_data = res.get("data", res) if isinstance(res, dict) else {}
                    break
        reqs_to_process = []
        seen_ids = set()
        raw_list = compliance_data.get("administrativo", []) + compliance_data.get("formatos", [])
        
        for req in raw_list:
            rid = str(req.get("id", "")).strip().replace(".", "_")
            if not rid or rid in seen_ids:
                continue
            
            # Reconocimiento ampliado: prefijo 1_x, palabras clave, o tipo administrativo/formato
            is_admin = (
                rid.startswith("1_")
                or any(x in rid.upper() for x in ["AT", "AE", "DECL", "ANEXO"])
                or req.get("tipo", "").lower() in ("administrativo", "formato", "formatos")
            )
            if is_admin:
                reqs_to_process.append(req)
                seen_ids.add(rid)

        logger.info("formats_generation_started", agent=self.agent_id, session_id=session_id, count=len(reqs_to_process))
        
        generated_files = []
        output_dir = os.path.join("/data", "outputs", session_id, "3.documentos administrativos")
        os.makedirs(output_dir, exist_ok=True)

        for req in reqs_to_process:
            rid = str(req.get("id", "")).strip().replace(".", "_")
            raw_name = req.get('nombre', 'Documento')
            filename = f"{rid}_{raw_name.replace(' ', '_')[:30]}"
            filename = re.sub(r'[^\w\s-]', '', filename).replace(' ', '_')
            
            prompt = f"Genera el contenido legal oficial para el requisito {req.get('id')}: {raw_name}\nDescripción: {req.get('descripcion')}\nEmpresa: {razon_social}\nRepresentante: {representante}\nRFC: {rfc}"
            resp = await llm.generate(prompt=prompt, system_prompt=system_prompt, correlation_id=correlation_id)
            
            # Verificar fallo explícito de LLM antes de escribir el archivo
            if not resp.success:
                logger.error("llm_generation_failed", agent=self.agent_id, req_name=raw_name, error=resp.error)
                continue
            content = resp.response
            if not content.strip():
                logger.warning("llm_empty_response", agent=self.agent_id, req_name=raw_name)
                continue
            
            filepath = os.path.join(output_dir, f"{filename}.docx")
            try:
                _save_docx(f"{rid} - {raw_name}", content, filepath, doc_metadata)
                generated_files.append({"nombre": raw_name, "ruta": filepath, "status": "FINAL"})
                logger.info("docx_generated", agent=self.agent_id, filename=filename)
            except Exception as e:
                logger.error("docx_save_failed", agent=self.agent_id, filename=filename, error=str(e))

        result_data = {
            "documentos": generated_files,
            "count": len(generated_files),
            "folder": output_dir
        }
        await self.context_manager.record_task_completion(session_id, "formats_generation_COMPLETED", result_data)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=result_data,
            correlation_id=correlation_id
        )

    async def _save_pending_questions(self, session_id: str, missing_fields: List[Dict]):
        """Persiste preguntas para el chatbot."""
        try:
            session_state = await self.context_manager.memory.get_session(session_id)
            if session_state:
                session_state["pending_questions"] = missing_fields
                session_state["current_question_index"] = 0
                await self.context_manager.memory.save_session(session_id, session_state)
        except Exception as e:
            logger.error("save_questions_failed", agent=self.agent_id, session_id=session_id, error=str(e))

def _save_docx(title: str, content: str, file_path: str, metadata: dict = None):
    doc = docx.Document()
    section = doc.sections[0]
    
    # Header: Logo y Datos
    header = section.header
    htable = header.add_table(1, 2, Inches(6.5))
    
    # Logo
    if metadata and metadata.get("logo_path") and os.path.exists(metadata["logo_path"]):
        try:
            htable.cell(0, 0).paragraphs[0].add_run().add_picture(metadata["logo_path"], width=Inches(1.5))
        except Exception as e:
            logger.warning(
                "logo_insert_failed",
                agent="formats_001",
                path=(metadata or {}).get("logo_path"),
                error=str(e),
            )
            
    # Datos Licitación
    p_info = htable.cell(0, 1).paragraphs[0]
    p_info.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if metadata:
        run = p_info.add_run(f"{metadata.get('tender_name', '').upper()}")
        run.bold = True
        run.font.size = Pt(8)

    # Footer
    footer = section.footer
    p_foot = footer.paragraphs[0]
    p_foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if metadata:
        p_foot.add_run(f"{metadata.get('footer_text', '')}").font.size = Pt(7)

    doc.add_heading(title.upper(), 1)
    
    # LUGAR Y FECHA
    footer_text = metadata.get("footer_text", "") if metadata else ""
    lugar = footer_text.split("Domicilio:")[-1].split(",")[0].strip() if "Domicilio:" in footer_text else "México"
    doc.add_paragraph(f"LUGAR Y FECHA: {lugar} a {metadata.get('fecha', '')}").alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Destinatario
    p_dest = doc.add_paragraph("\nCOMITÉ DE ADQUISICIONES Y DIRECCIÓN DE OBRAS PÚBLICAS\nPRESENTE.-")
    p_dest.bold = True
    
    doc.add_paragraph("_" * 50).alignment = WD_ALIGN_PARAGRAPH.CENTER

    for para in content.split("\n"):
        if para.strip():
            p = doc.add_paragraph(para.strip())
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            
    # Firma Final
    doc.add_paragraph("\n\n")
    p_at = doc.add_paragraph("ATENTAMENTE\n")
    p_at.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    p_line = doc.add_paragraph("___________________________\n")
    p_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    run_firma = p_line.add_run(f"{metadata.get('representante', '').upper()}\n")
    run_firma.bold = True
    
    p_rfc = doc.add_paragraph(f"RFC: {metadata.get('rfc', '')}")
    p_rfc.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.save(file_path)
