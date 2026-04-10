import os
from typing import Dict, Any, List
from datetime import datetime
from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

class EconomicWriterAgent(BaseAgent):
    """
    Agente: Generador de Propuesta Económica.
    Genera documentos económicos formales (.xlsx y .docx) a partir de los
    ítems ya calculados por EconomicAgent en Fase 1, sin invocar al LLM.

    POLÍTICA DE TOTALES (decisión de negocio):
    Los documentos oficiales aplican IVA 16 % sobre el subtotal de líneas
    renderizadas. EconomicAgent (Fase 1) puede incluir un margen adicional
    (~15 %) para uso interno de la UI; ese margen NO se traslada al sobre
    físico. Si se desea una única cifra en pantalla y en papel, alinear
    ambos agentes bajo la misma regla fiscal.
    """

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="economic_writer",
            name="Economic Writer Agent",
            description="Generador automatizado de propuestas económicas y catálogos de precios.",
            context_manager=context_manager
        )

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        print(f"[{self.name}] 💰 Iniciando generación de Propuesta Económica para {session_id}...", flush=True)

        context = await self.context_manager.get_global_context(session_id)

        # 1. Recuperar contexto de la empresa
        company_data = agent_input.company_data
        master_profile = company_data.get("master_profile", {})
        
        # 2. Obtener propuesta de Fase 1
        # a) Inyección directa del orquestador via economic_data
        economic_data = agent_input.company_data.get("economic_data")
        
        # b) Estructura estándar results.economic.data
        if not economic_data and "results" in agent_input.company_data:
            res = agent_input.company_data["results"]
            if isinstance(res, dict) and "economic" in res:
                econ = res["economic"]
                economic_data = econ.get("data", econ) if isinstance(econ, dict) else None

        # c) Buscar en el estado de la sesión si venimos en modo generation_only
        if not economic_data:
            tasks = context.get("session_state", {}).get("tasks_completed", [])
            for task in reversed(tasks):
                if task.get("task") == "economic_proposal":
                    result_data = task.get("result", {})
                    # extraemos .data del dict o lo asumimos directo
                    economic_data = result_data.get("data", result_data)
                    break
                    
        if not economic_data or not economic_data.get("items"):
            return AgentOutput(
                status=AgentStatus.ERROR,
                agent_id=self.agent_id,
                session_id=session_id,
                error="No se encontró una propuesta económica calculada en Fase 1.",
                correlation_id=correlation_id
            )
            
        # 3. Normalizar items para el renderizado Excel/Word
        mapeo_items = []
        for idx, item in enumerate(economic_data.get("items", [])):
            cantidad = float(item.get("cantidad", 1))
            precio = float(item.get("precio_unitario", 0.0))
            importe = item.get("subtotal", cantidad * precio)
            mapeo_items.append({
                "partida": item.get("partida", idx + 1),
                "descripcion": item.get("concepto", item.get("descripcion", "")),
                "unidad": item.get("unidad", "Servicio"),
                "cantidad": cantidad,
                "precio_unitario": precio,
                "importe": importe
            })
            
        subtotal = sum(i["importe"] for i in mapeo_items)
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        validation_result = (
            economic_data.get("validation_result")
            if isinstance(economic_data.get("validation_result"), dict)
            else {}
        )
        perfil_usado = str(validation_result.get("perfil_usado") or "generic")
        resumen = {
            "subtotal": round(subtotal, 2),
            "iva": iva,
            "total": total,
            "moneda": economic_data.get("currency", "MXN"),
            "fecha": datetime.now().strftime("%d/%m/%Y"),
            "perfil_usado": perfil_usado,
        }
        
        # 4. Generación de Archivos (misma raíz que TechnicalWriter/FormatsAgent)
        output_base_dir = os.path.join("/data", "outputs", session_id, "2.propuesta_economica")
        os.makedirs(output_base_dir, exist_ok=True)
        
        # 4.1 Generar Excel de Precios
        excel_path = os.path.join(output_base_dir, "TABLA_PRECIOS_UNITARIOS.xlsx")
        self._generate_price_excel(excel_path, mapeo_items, master_profile, resumen)
        
        # 4.2 Generar Anexo AE (Word)
        word_path = os.path.join(output_base_dir, "ANEXO_AE_PROPUESTA_ECONOMICA.docx")
        self._generate_anexo_ae(word_path, mapeo_items, resumen, master_profile)
        
        # 4.3 Generar Carta Compromiso (Word)
        carta_path = os.path.join(output_base_dir, "CARTA_COMPROMISO_PRECIOS.docx")
        self._generate_carta_compromiso(carta_path, resumen, master_profile)

        print(f"[{self.name}] ✅ Propuesta económica generada con éxito.", flush=True)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "folder": output_base_dir,
                "documentos": [
                    {"nombre": "Tabla de Precios Unitarios", "ruta": excel_path, "tipo": "tabla_precios"},
                    {"nombre": "Anexo AE - Propuesta Económica", "ruta": word_path, "tipo": "anexo_economico"},
                    {"nombre": "Carta Compromiso de Precios", "ruta": carta_path, "tipo": "carta_compromiso"}
                ],
                "resumen_economico": resumen
            },
            correlation_id=correlation_id
        )



    def _generate_price_excel(self, path: str, items: List[Dict], profile: Dict, resumen: Dict):
        """Crea un Excel profesional con fórmulas y formato."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Propuesta Económica"
        
        # Estilos
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        center_align = Alignment(horizontal="center", vertical="center")
        border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        
        # Encabezado Empresa
        ws.merge_cells('A1:F1')
        ws['A1'] = profile.get("razon_social", "EMPRESA LICITANTE").upper()
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = center_align
        
        # Títulos de Columnas
        headers = ["Partida", "Descripción", "Unidad", "Cantidad", "P. Unitario", "Importe"]
        for col, text in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = border
            
        # Datos
        current_row = 4
        for item in items:
            ws.cell(row=current_row, column=1, value=item.get("partida")).border = border
            ws.cell(row=current_row, column=2, value=item.get("descripcion")).border = border
            ws.cell(row=current_row, column=3, value=item.get("unidad")).border = border
            ws.cell(row=current_row, column=4, value=item.get("cantidad")).border = border
            ws.cell(row=current_row, column=5, value=item.get("precio_unitario")).border = border
            ws.cell(row=current_row, column=6, value=item.get("importe")).border = border
            current_row += 1
            
        # Totales desde resumen (calculados en Fase 1, no se recalculan)
        ws.cell(row=current_row + 1, column=5, value="SUBTOTAL:").font = Font(bold=True)
        ws.cell(row=current_row + 1, column=6, value=resumen["subtotal"]).font = Font(bold=True)
        ws.cell(row=current_row + 2, column=5, value="IVA (16%):").font = Font(bold=True)
        ws.cell(row=current_row + 2, column=6, value=resumen["iva"]).font = Font(bold=True)
        ws.cell(row=current_row + 3, column=5, value="TOTAL:").font = Font(bold=True)
        ws.cell(row=current_row + 3, column=6, value=resumen["total"]).font = Font(bold=True)
        
        # Ajustar anchos
        ws.column_dimensions['B'].width = 50
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 15
        
        wb.save(path)

    def _generate_anexo_ae(self, path: str, items: List[Dict], resumen: Dict, profile: Dict):
        """Genera el Word del Anexo AE (Propuesta Económica Detallada)."""
        doc = Document()
        
        doc.add_heading('ANEXO AE: PROPUESTA ECONÓMICA', 0)
        
        p = doc.add_paragraph()
        run = p.add_run(f"LICITANTE: {profile.get('razon_social', '...')}\n")
        run.bold = True
        p.add_run(f"RFC: {profile.get('rfc', '...')}\n")
        p.add_run(f"REPRESENTANTE: {profile.get('representante_legal', '...')}\n")
        p.add_run(f"FECHA: {resumen['fecha']}")

        doc.add_paragraph("\nPor medio de la presente, sometemos a su consideración nuestra propuesta económica detallada:")

        # Tabla Word
        table = doc.add_table(rows=1, cols=4)
        table.style = 'Light Shading Accent 1'
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Partida'
        hdr_cells[1].text = 'Concepto'
        hdr_cells[2].text = 'Cant.'
        hdr_cells[3].text = 'Importe'

        for item in items:
            row_cells = table.add_row().cells
            row_cells[0].text = str(item.get('partida'))
            row_cells[1].text = item.get('descripcion')
            row_cells[2].text = str(item.get('cantidad'))
            row_cells[3].text = f"${item.get('importe'):,.2f}"

        doc.add_paragraph(f"\nSUBTOTAL: ${resumen['subtotal']:,.2f}")
        doc.add_paragraph(f"IVA (16%): ${resumen['iva']:,.2f}")
        para_total = doc.add_paragraph(f"TOTAL DE LA PROPUESTA: ${resumen['total']:,.2f}")
        para_total.runs[0].bold = True

        doc.add_paragraph("\nVIGENCIA DE LA PROPUESTA: 30 DÍAS NATURALES.")
        
        doc.add_paragraph("\n\n__________________________________")
        doc.add_paragraph(f"{profile.get('representante_legal', 'Representante Legal')}\nfirma")

        doc.save(path)

    def _generate_carta_compromiso(self, path: str, resumen: Dict, profile: Dict):
        """Genera la carta formal de compromiso de precios."""
        doc = Document()
        doc.add_heading('CARTA COMPROMISO DE PRECIOS', 1)
        
        p = doc.add_paragraph(f"\nMéxico, a {resumen['fecha']}\n")
        p.alignment = 2 # Derecha
        
        doc.add_paragraph("A QUIEN CORRESPONDA:")
        
        body = f"""
        Quien suscribe, C. {profile.get('representante_legal', '...')}, en mi carácter de Representante Legal 
        de la empresa {profile.get('razon_social', '...')}, manifiesto bajo protesta de decir verdad que:
        
        Los precios presentados en nuestra propuesta económica de fecha {resumen['fecha']} por un total de 
        ${resumen['total']:,.2f} ({resumen['moneda']}), permanecerán firmes y vigentes durante la totalidad 
        del proceso de adjudicación y, en caso de resultar ganadores, durante la vigencia del contrato respectivo.
        
        Asimismo, garantizamos que los precios no están sujetos a variaciones por fluctuaciones de mercado o 
        costos de insumos durante el periodo mencionado.
        
        Atentamente,
        """
        doc.add_paragraph(body)
        
        doc.add_paragraph("\n\n__________________________________")
        doc.add_paragraph(f"{profile.get('representante_legal', '...')}\n{profile.get('razon_social', '...')}")
        
        doc.save(path)
