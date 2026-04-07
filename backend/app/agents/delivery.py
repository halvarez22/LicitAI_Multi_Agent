import os
import json
from typing import Dict, Any, List
from datetime import datetime
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

class DeliveryAgent(BaseAgent):
    """
    Agente: Guía de Entrega.
    Detecta la modalidad de entrega y genera manuales de instrucciones paso a paso.
    """

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="delivery_guide",
            name="Delivery Guide Agent",
            description="Generador de manuales de instrucciones y checklists para la entrega de propuestas.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        print(f"[{self.name}] 📋 Generando guía de entrega para {session_id}...", flush=True)
        
        context_global = await self.context_manager.get_global_context(session_id)

        # 2. Buscar en bases la modalidad de entrega (RAG inyectado)
        query = "lugar fecha hora acto presentación apertura proposiciones electrónica presencial oficina portal"
        context_rag = await self.smart_search(session_id, query, n_results=5, vector_db=self.vector_db)
        
        # 3. Analizar modalidad vía LLM
        guia_data = await self._analizar_entrega_llm(context_rag, correlation_id)
        
        # 4. Generar PDF de Instrucciones
        output_dir = os.path.join("/data", "outputs", session_id)
        os.makedirs(output_dir, exist_ok=True)
        pdf_path = os.path.join(output_dir, "LOGISTICA_Y_GUIA_DE_ENTREGA.pdf")
        
        self._generate_pdf_guide(pdf_path, guia_data, session_id)
        
        print(f"[{self.name}] ✅ Guía de entrega generada con éxito.", flush=True)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "tipo_licitacion": guia_data.get("tipo", "No detectada"),
                "guia_pdf": pdf_path,
                "checklist": guia_data.get("checklist", []),
                "alertas": guia_data.get("alertas", [])
            },
            correlation_id=correlation_id
        )

    async def _analizar_entrega_llm(self, context: str, correlation_id: str = "") -> Dict:
        """Extrae los detalles de logística de las bases."""
        prompt = f"""
        Eres un Experto en Logística de Licitaciones Públicas. Tu misión es extraer cómo, cuándo y dónde 
        se debe entregar la oferta a partir de las BASES.

        BASES DE LICITACIÓN (Contexto logístico):
        {context[:8000]}

        INSTRUCCIONES:
        1. Determina el tipo de licitación: "ELECTRONICA" o "PRESENCIAL".
        2. Extrae la dirección física y el horario (si es presencial).
        3. Extrae el nombre del portal y la URL (si es electrónica, ej. CompraNet).
        4. Crea un checklist de 5-10 puntos críticos que el licitante debe verificar.
        5. Extrae la fecha y hora exacta del acto de presentación (Deadline).
        6. Devuelve un JSON con este formato:
           {{
             "tipo": "...", 
             "portal_url": "...", 
             "portal_nombre": "...",
             "direccion_fisica": "...",
             "horario": "...",
             "fecha_limite": "...",
             "pasos": [ {{"paso": 1, "accion": "...", "detalle": "..."}}, ... ],
             "checklist": [ {{"check": "...", "status": "pendiente"}}, ... ],
             "alertas": [ "...", "..." ]
           }}
        
        RECUERDA: Solo responde con el JSON.
        """
        
        resp = await self.llm.generate(prompt=prompt, format="json", correlation_id=correlation_id)
        
        if not resp.success:
            print(f"[{self.name}] ⚠️ LLM error en análisis de entrega: {resp.error}. Usando fallback.")
            return self._get_fallback_guia()

        raw_text = resp.response or ""
        try:
            # Limpiar fences si existen
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(raw_text[start:end + 1])
            
            raise ValueError("No se encontró JSON válido")
        except Exception as e:
            print(f"[{self.name}] ⚠️ Error parseando JSON de entrega ({e}). Usando fallback.")
            return self._get_fallback_guia()

    def _get_fallback_guia(self) -> Dict:
        """Fallback determinístico en caso de fallo del LLM."""
        return {
            "tipo": "DETERMINACIÓN_MANUAL_REQUERIDA",
            "alertas": ["No se pudo determinar la logística de forma automatizada. Por favor, consulte las bases en la sección de 'Presentación y Apertura de Proposiciones'."],
            "checklist": [],
            "pasos": []
        }

    def _generate_pdf_guide(self, path: str, data: Dict, session_id: str):
        """Genera un reporte PDF profesional usando ReportLab."""
        doc = SimpleDocTemplate(path, pagesize=LETTER)
        styles = getSampleStyleSheet()
        elements = []
        
        # Estilos Personalizados
        title_style = ParagraphStyle(
            'TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.navy, spaceAfter=20, alignment=1
        )
        label_style = ParagraphStyle('LabelStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10)
        
        # Título
        elements.append(Paragraph(f" GUÍA DE ENTREGA Y LOGÍSTICA", title_style))
        elements.append(Paragraph(f"LICITACIÓN: {session_id.upper()}", styles['Normal']))
        elements.append(Paragraph(f"FECHA DE INFORME: {datetime.now().strftime('%d/%m/%Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Modalidad
        elements.append(Paragraph(" MODALIDAD DE ENTREGA", styles['Heading2']))
        tipo_color = colors.green if data['tipo'] == "ELECTRONICA" else colors.orange
        elements.append(Paragraph(f"<b>TIPO:</b> {data['tipo']}", styles['Normal']))
        
        if data['tipo'] == "ELECTRONICA":
            elements.append(Paragraph(f"<b>PORTAL:</b> {data.get('portal_nombre', '...')}", styles['Normal']))
            elements.append(Paragraph(f"<b>URL:</b> {data.get('portal_url', '...')}", styles['Normal']))
        else:
            elements.append(Paragraph(f"<b>DIRECCIÓN:</b> {data.get('direccion_fisica', '...')}", styles['Normal']))
            elements.append(Paragraph(f"<b>HORARIO:</b> {data.get('horario', '...')}", styles['Normal']))
            
        elements.append(Paragraph(f"<b>FECHA LÍMITE:</b> {data.get('fecha_limite', '...')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Checklist de Seguridad
        elements.append(Paragraph(" CHECKLIST DE SEGURIDAD (ANTES DE SALIR/SUBIR)", styles['Heading2']))
        checklist_data = [["Requisito", "Estatus"]]
        for item in data.get('checklist', []):
            checklist_data.append([item['check'], "[ ] Pendiente"])
            
        t = Table(checklist_data, colWidths=[400, 100])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.navy),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 1, colors.grey),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(t)
        elements.append(PageBreak())
        
        # Pasos Paso a Paso
        elements.append(Paragraph(" MANUAL PASO A PASO PARA LA ENTREGA", styles['Heading2']))
        for paso in data.get('pasos', []):
            elements.append(Paragraph(f"<b>Paso {paso['paso']}: {paso['accion']}</b>", styles['Normal']))
            elements.append(Paragraph(paso['detalle'], styles['BodyText']))
            elements.append(Spacer(1, 10))
            
        # Alertas Finales
        if data.get('alertas'):
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(" ALERTAS CRÍTICAS", styles['Heading2']))
            for alerta in data['alertas']:
                elements.append(Paragraph(f"• {alerta}", ParagraphStyle('Alert', parent=styles['Normal'], textColor=colors.red)))

        doc.build(elements)
