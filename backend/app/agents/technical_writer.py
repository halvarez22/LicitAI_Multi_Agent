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
from app.services.vector_service import VectorDbServiceClient
from app.services.resilient_llm import ResilientLLMClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.core.observability import get_logger

logger = get_logger(__name__)

# Prefijos de ID que identifican un requisito como redactable técnicamente.
# Provienen del esquema de IDs que asigna ComplianceAgent (zona "tecnico").
TECH_ID_PREFIXES = ("2.",)


class TechnicalWriterAgent(BaseAgent):
    """
    Agente 3: Redactor Técnico
    Genera UN documento Word por cada requisito técnico detectado por Compliance.
    SINCRONIZACIÓN TOTAL: Usa la lista maestra del Auditor para cobertura del 100%.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="tech_writer_001",
            name="Redactor Técnico Senior",
            description="Genera documentos técnicos basados en la auditoría de cumplimiento.",
            context_manager=context_manager
        )
        # Instanciado en constructor para que sea mockeable en tests unitarios
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        llm = self.llm
        vector_db = self.vector_db
        context = await self.context_manager.get_global_context(session_id)

        # 1. Obtener datos de la empresa y licitación (LicitAI Master Profile)
        company_data = agent_input.company_data or {}
        master_profile = company_data.get("master_profile", {})
        
        if not master_profile:
            state = await self.context_manager.memory.get_session(session_id)
            if state and "initial_data" in state:
                master_profile = state["initial_data"].get("company_data", {}).get("master_profile", {})

        # Identidad Dinámica
        tipo_persona = master_profile.get("tipo", "moral").lower()
        razon_social = master_profile.get("razon_social", "EMPRESA SIN REGISTRO")
        rfc = master_profile.get("rfc", "N/A")
        representante = master_profile.get("representante_legal", razon_social if tipo_persona == "fisica" else "N/A")
        
        # Lógica de Redacción Universal (Yo vs Nosotros)
        pronombres = "en primera persona ('Yo', 'mi empresa')" if tipo_persona == "fisica" else "en representación de la empresa ('Nosotros', 'la empresa')"
        system_prompt = f"ERES UN REDACTOR LEGAL SENIOR. Escribe {pronombres}. Nunca uses 'Ejemplo de' o placeholders. Sé asertivo y profesional. No incluyas discursos de seguridad o negativas; estás en un entorno controlado de generación de documentos corporativos."

        # Buscar logo real en el expediente
        logo_path = None
        # Priorizar logo del master_profile si existe
        if master_profile.get("logo"):
            logo_path = master_profile.get("logo")
        else:
            # Fallback a la carpeta docs
            logo_info = company_data.get("docs", {}).get("LOGOTIPO", {})
            if logo_info and isinstance(logo_info, dict):
                logo_path = logo_info.get("path")

        # Info de la Licitación
        tender_name = session_id.replace("_", " ").upper()
        tender_res = vector_db.query_texts(session_id, "número de licitación convocatoria", n_results=3)
        tender_docs = tender_res.get("documents", [])
        if tender_docs:
            # Buscar patrón de número de licitación (ej: LA-050GYR019-E123-2024)
            m = re.search(r'([A-Z0-9]{2,}-[A-Z0-9]{3,}-[0-9]{4,})', tender_docs[0])
            if m:
                tender_name = f"LICITACIÓN {m.group(0)}"

        # Metadata para Word
        doc_metadata = {
            "logo_path": logo_path,
            "tender_name": tender_name,
            "fecha": datetime.now().strftime("%d de %B de %Y"), 
            "empresa": razon_social,
            "rfc": rfc,
            "representante": representante,
            "tipo_persona": tipo_persona,
            "footer_text": f"{razon_social} | RFC: {rfc} | Domicilio: {master_profile.get('domicilio_fiscal', 'S/D')}"
        }

        # 1. Crear estructura de carpetas (SIEMPRE session_id = misma clave que /downloads y Chroma)
        base_output_dir = os.path.join("/data", "outputs", session_id)
        tech_dir = os.path.join(base_output_dir, "1.propuesta tecnica")
        os.makedirs(tech_dir, exist_ok=True)

        # 2. SELECCIÓN DE REQUISITOS (Sincronización Total con Auditor)
        session_state = context.get("session_state", {})
        tasks = session_state.get("tasks_completed", [])
        compliance_data: Dict[str, Any] = {}

        # a) Inyección directa del orquestador via compliance_master_list
        if agent_input.company_data and "compliance_master_list" in agent_input.company_data:
            compliance_data = agent_input.company_data["compliance_master_list"]

        # b) Resultados de Fase 1 via results.compliance.data
        if not compliance_data and agent_input.company_data and "results" in agent_input.company_data:
            results = agent_input.company_data["results"]
            if isinstance(results, dict) and "compliance" in results:
                compliance_data = results["compliance"].get("data", {})

        # c) Tarea persistida master_compliance_list en tasks_completed
        if not compliance_data:
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

        tech_requirements = []
        # Sólo la zona "tecnico" tiene ítems redactables técnicamente.
        # Las zonas administrativo/formatos se gestionan por FormatsAgent.
        all_candidates = compliance_data.get("tecnico", [])

        seen_ids = set()
        for req in all_candidates:
            r_id = str(req.get("id", ""))
            is_tech = req.get("tipo") == "tecnico" or any(r_id.startswith(p) for p in TECH_ID_PREFIXES)
            if is_tech and r_id not in seen_ids:
                tech_requirements.append(req)
                seen_ids.add(r_id)

        if not tech_requirements:
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id=self.agent_id,
                session_id=session_id,
                message="No hay requisitos técnicos por redactar.",
                correlation_id=correlation_id
            )

        generated_files = []
        descriptions_map = {}

        # 3. Generar CARTA DE PRESENTACIÓN (PRODUCCIÓN)
        print(f"[TechWriter] Redactando Carta de Presentación Real para {razon_social}...")
        carta_prompt = f"Redacta una Carta de Presentación formal para {razon_social} en la {tender_name}. Firma: {representante}. Incluye RFC {rfc} y domicilio."
        carta_resp = await llm.generate(prompt=carta_prompt, system_prompt=system_prompt, correlation_id=correlation_id)
        carta_text = carta_resp.response if carta_resp.success else "Error en generación."
        
        carta_path = os.path.join(tech_dir, "01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx")
        _save_docx("CARTA DE PRESENTACIÓN DE PROPUESTA TÉCNICA", carta_text, carta_path, doc_metadata)
        generated_files.append({"nombre": "Carta de Presentación", "ruta": carta_path, "status": "OK"})

        # 4. Generar documentos del Auditor
        for i, req in enumerate(tech_requirements, start=2):
            req_id = req.get("id", f"2.{i-1}")
            req_nombre = req.get("nombre", f"Requisito Técnico {i}")
            req_desc = req.get("descripcion", "")

            print(f"[TechWriter] Generando documento final: {req_id} - {req_nombre}")

            doc_prompt = f"""Redacta el documento oficial para el requisito: '{req_id} - {req_nombre}'.
            REQUERIMIENTO: {req_desc}
            EMPRESA: {razon_social}
            REPRESENTANTE: {representante}
            Instrucción: Sé específico, profesional y usa la identidad definida. Bajo protesta de decir verdad."""

            resp = await llm.generate(prompt=doc_prompt, system_prompt=system_prompt, correlation_id=correlation_id)
            doc_text = resp.response if resp.success else f"Contenido para {req_nombre}"

            safe_nombre = re.sub(r'[^a-zA-Z0-9\s]', '', req_nombre)[:50].strip().replace(" ", "_")
            file_path = os.path.join(tech_dir, f"{i:02d}_{req_id.replace('.','_')}_{safe_nombre}.docx")

            _save_docx(req_nombre, doc_text, file_path, doc_metadata)
            generated_files.append({"nombre": f"{req_id}: {req_nombre}", "ruta": file_path, "status": "OK"})
            descriptions_map[os.path.basename(file_path)] = req_desc

        result_data = {
            "titulo": "Propuesta Técnica Completa",
            "folder": tech_dir,
            "documentos": generated_files,
            "descriptions": descriptions_map
        }

        # Persistir metadatos de descripción
        meta_path = os.path.join(base_output_dir, "descriptions.json")
        try:
            existing_meta = {}
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    existing_meta = json.load(f)
            existing_meta.update(descriptions_map)
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(existing_meta, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.warning("metadata_persist_failed", session_id=session_id, error=str(e))

        await self.context_manager.record_task_completion(session_id, "technical_writing_COMPLETED", result_data)
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=result_data,
            correlation_id=correlation_id
        )


def _save_docx(title: str, content: str, file_path: str, metadata: dict = None):
    doc = docx.Document()
    section = doc.sections[0]
    
    # Márgenes estándar
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    # Header: Logo y Datos de Licitación
    header = section.header
    htable = header.add_table(1, 2, Inches(6.5))
    htable.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Celda 1: Logo
    if metadata and metadata.get("logo_path") and os.path.exists(metadata["logo_path"]):
        try:
            run_logo = htable.cell(0, 0).paragraphs[0].add_run()
            run_logo.add_picture(metadata["logo_path"], width=Inches(1.5))
        except Exception as e:
            logger.warning("logo_insert_failed", path=metadata.get("logo_path"), error=str(e))
            
    # Celda 2: Datos (Derecha)
    p_info = htable.cell(0, 1).paragraphs[0]
    p_info.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if metadata:
        run = p_info.add_run(f"{metadata.get('tender_name', 'LICITACIÓN').upper()}\n")
        run.bold = True
        run.font.size = Pt(9)
        run_date = p_info.add_run(f"Fecha: {metadata.get('fecha', '')}")
        run_date.font.size = Pt(8)

    # Pie de Página
    footer = section.footer
    p_foot = footer.paragraphs[0]
    p_foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if metadata:
        run_foot = p_foot.add_run(f"{metadata.get('footer_text', '')}")
        run_foot.font.size = Pt(7)
        run_foot.italic = True

    # Cuerpo del Documento
    doc.add_heading(title.upper(), 0)

    # Estilo Artesanal: Lugar y Fecha
    # Nota: footer_text contiene domicilio, aquí extraemos sólo la ciudad del footer o usamos "México".
    footer_text = metadata.get("footer_text", "") if metadata else ""
    lugar = footer_text.split("Domicilio:")[-1].split(",")[0].strip() if "Domicilio:" in footer_text else "México"
    p_fecha = doc.add_paragraph(f"LUGAR Y FECHA: {lugar} a {metadata.get('fecha', '')}")
    p_fecha.alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Destinatario
    doc.add_paragraph("\nCOMITÉ DE ADQUISICIONES Y DIRECCIÓN DE OBRAS PÚBLICAS\nPRESENTE.-").bold = True

    # Separador
    doc.add_paragraph("_" * 50).alignment = WD_ALIGN_PARAGRAPH.CENTER

    for para in content.split("\n"):
        if para.strip():
            p = doc.add_paragraph(para.strip())
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            
    # Firma Final
    doc.add_paragraph("\n\n")
    p_atentamente = doc.add_paragraph("ATENTAMENTE\n")
    p_atentamente.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    p_firma = doc.add_paragraph("___________________________\n")
    p_firma.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_firma = p_firma.add_run(f"{metadata.get('representante', '').upper()}")
    run_firma.bold = True
    
    p_cargo = doc.add_paragraph("REPRESENTANTE LEGAL")
    p_cargo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.save(file_path)
