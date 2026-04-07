import os
import shutil
import json
from typing import Dict, Any, List
from docx import Document
import docx.shared as docx_shared
from datetime import datetime
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

class DocumentPackagerAgent(BaseAgent):
    """
    Agente: Empacador de Documentos.
    Organiza archivos en carpetas de sobres y genera carátulas e índices.

    Contrato de rutas: raíz de salida → /data/outputs/{session_id}/ (misma clave que API de descargas).
    """

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="document_packager",
            name="Document Packager Agent",
            description="Organizador de expedientes de licitación en estructura de sobres oficiales.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        print(f"[{self.name}] 📦 Iniciando empaquetado de expediente para {session_id}...", flush=True)

        # 1. Recuperar contexto
        context = await self.context_manager.get_global_context(session_id)

        # 2. Recuperar documentos generados y perfil
        gen_docs = agent_input.company_data.get("documentos_generados", {})
        master_profile = agent_input.company_data.get("master_profile", {})

        # 3. Buscar estructura de sobres en las bases (RAG inyectado)
        query = "orden presentación documentos sobre técnica administrativa económica foliado"
        context_rag = await self.smart_search(session_id, query, n_results=5, vector_db=self.vector_db)

        # 4. Mapear documentos a sobres (LLM con fallback determinístico)
        estructura = await self._mapear_sobres_llm(context_rag, gen_docs, correlation_id)

        # 5. Crear estructura física de carpetas y carátulas
        output_base = os.path.join("/data", "outputs", session_id)
        reporte_sobres = {}
        caratulas = []

        for key, info in estructura.items():
            sobre_dir = os.path.join(output_base, info["nombre_carpeta"])
            os.makedirs(sobre_dir, exist_ok=True)

            print(f"[{self.name}] 📨 Organizando {info['titulo']}...", flush=True)

            docs_finales = []
            for i, doc in enumerate(info["documentos"], 1):
                raw_path = doc.get("ruta")
                if raw_path and os.path.exists(raw_path):
                    ext = os.path.splitext(raw_path)[1]
                    nuevo_nombre = f"{i:02d}_{os.path.basename(raw_path)}"
                    destino = os.path.join(sobre_dir, nuevo_nombre)
                    shutil.copy2(raw_path, destino)
                    docs_finales.append({"orden": i, "nombre": doc["nombre"], "archivo": nuevo_nombre})

            caratula_path = os.path.join(sobre_dir, "00_CARATULA_SOBRE.docx")
            self._generate_caratula(caratula_path, info["titulo"], docs_finales, master_profile, session_id)
            caratulas.append(caratula_path)

            reporte_sobres[key] = {
                "nombre": info["titulo"],
                "carpeta": sobre_dir,
                "documentos": docs_finales,
                "total_documentos": len(docs_finales)
            }

        print(f"[{self.name}] ✅ Expediente organizado en {len(reporte_sobres)} sobres.", flush=True)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "estructura_sobres": reporte_sobres,
                "caratulas_generadas": caratulas,
                "folder_raiz": output_base
            },
            correlation_id=correlation_id
        )

    async def _mapear_sobres_llm(self, context: str, gen_docs: Dict, correlation_id: str = "") -> Dict:
        """
        Determina qué documento va en qué sobre basándose en las bases (vía LLM).
        Si el LLM falla o devuelve JSON inválido, aplica un fallback determinístico
        que reparte gen_docs por keys conocidas sin consumir tokens.
        """
        documentos_disponibles = []
        for cat, docs in gen_docs.items():
            if isinstance(docs, list):
                for d in docs:
                    documentos_disponibles.append({"nombre": d.get("nombre"), "ruta": d.get("ruta"), "categoria": cat})

        prompt = f"""
        Eres un Experto en Organización de Expedientes de Licitación. Tu tarea es clasificar los documentos generados
        en la estructura de SOBRES requerida por las bases.

        BASES DE LICITACIÓN (Contexto de sobres):
        {context[:5000]}

        DOCUMENTOS DISPONIBLES PARA EMPACAR:
        {json.dumps(documentos_disponibles, indent=2)}

        INSTRUCCIONES:
        1. Clasifica en 3 grupos: sobre_1_administrativo, sobre_2_tecnico, sobre_3_economico.
        2. Determina el orden lógico (ej. Carta presentación siempre va primero).
        3. Si no hay instrucciones claras en las bases, usa el estándar:
           - Sobre 1: Administrativos (Actas, RFC, Identificaciones).
           - Sobre 2: Propuesta Técnica.
           - Sobre 3: Propuesta Económica.
        4. Devuelve un JSON estructurado así:
           {{
             "sobre_1": {{
               "titulo": "SOBRE No. 1 - DOCUMENTACIÓN ADMINISTRATIVA",
               "nombre_carpeta": "SOBRE_1_ADMINISTRATIVO",
               "documentos": [ {{"nombre": "...", "ruta": "..."}}, ... ]
             }},
             ...
           }}

        RESPONDE SOLO EL JSON, sin explicaciones.
        """

        resp = await self.llm.generate(prompt=prompt, format="json", correlation_id=correlation_id)

        if not resp.success:
            print(f"[{self.name}] ⚠️ LLM error en mapeo de sobres: {resp.error}. Usando fallback determinístico.")
            return self._fallback_estructura_por_claves(gen_docs)

        raw_text = resp.response or ""
        try:
            # Limpiar fences de markdown si el modelo los incluyó
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(raw_text[start:end + 1])
            raise ValueError("No se encontró objeto JSON en la respuesta del LLM.")
        except Exception as e:
            print(f"[{self.name}] ⚠️ JSON inválido del LLM ({e}). Usando fallback determinístico.")
            return self._fallback_estructura_por_claves(gen_docs)

    def _fallback_estructura_por_claves(self, gen_docs: Dict) -> Dict:
        """
        Fallback determinístico: reparte gen_docs a los tres sobres estándar
        usando las claves que el orquestador inyecta (administrativa, tecnica, economica).
        No requiere LLM.
        """
        print(f"[{self.name}] 📋 Usando fallback determinístico (LLM no disponible o JSON inválido).")
        return {
            "sobre_1": {
                "titulo": "SOBRE 1 - DOCUMENTACIÓN ADMINISTRATIVA",
                "nombre_carpeta": "SOBRE_1_ADMINISTRATIVO",
                "documentos": gen_docs.get("administrativa", [])
            },
            "sobre_2": {
                "titulo": "SOBRE 2 - PROPUESTA TÉCNICA",
                "nombre_carpeta": "SOBRE_2_TECNICO",
                "documentos": gen_docs.get("tecnica", [])
            },
            "sobre_3": {
                "titulo": "SOBRE 3 - PROPUESTA ECONÓMICA",
                "nombre_carpeta": "SOBRE_3_ECONOMICO",
                "documentos": gen_docs.get("economica", [])
            }
        }

    def _generate_caratula(self, path: str, titulo: str, docs: List[Dict], profile: Dict, session_id: str):
        """Genera una carátula de sobre profesional."""
        doc = Document()

        for section in doc.sections:
            section.top_margin = docx_shared.Inches(1)

        doc.add_paragraph("\n" * 2)
        p_titulo = doc.add_paragraph()
        run_titulo = p_titulo.add_run(titulo.upper())
        run_titulo.bold = True
        run_titulo.font.size = docx_shared.Pt(24)
        p_titulo.alignment = 1  # Center

        doc.add_paragraph("-" * 40).alignment = 1

        p_licit = doc.add_paragraph()
        p_licit.add_run(f"LICITACIÓN: {session_id.upper()}").bold = True
        p_licit.alignment = 1

        doc.add_paragraph("\n")

        p_empresa = doc.add_paragraph()
        p_empresa.add_run(f"EMPRESA: {profile.get('razon_social', '...')}\n").bold = True
        p_empresa.add_run(f"RFC: {profile.get('rfc', '...')}\n")
        p_empresa.add_run(f"REPRESENTANTE: {profile.get('representante_legal', '...')}")
        p_empresa.alignment = 1

        doc.add_paragraph("\n" * 2)
        doc.add_heading("ÍNDICE DE CONTENIDO", 2)

        for doc_item in docs:
            doc.add_paragraph(f"{doc_item['orden']}. {doc_item['nombre']}", style='List Bullet')

        doc.add_paragraph("\n" * 3)
        doc.add_paragraph(f"FECHA DE GENERACIÓN: {datetime.now().strftime('%d/%m/%Y')}").alignment = 1

        doc.save(path)

