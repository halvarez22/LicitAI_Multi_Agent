import json
from typing import Any, Dict, List, Optional
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.vector_service import VectorDbServiceClient
from app.services.resilient_llm import ResilientLLMClient
from app.services.slot_inference import SlotInferenceService, INFERRED_TO_PROFILE_MAP
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus


class DataGapAgent(BaseAgent):
    """
    Agente de Completitud de Datos.
    Detecta huecos del ``master_profile`` y, antes de preguntar al usuario,
    intenta auto-rellenar desde RAG en este orden:

    1. Colección ``company_{id}`` (documentos corporativos analizados en Empresas).
    2. PDFs de **Fuentes de Verdad** de la sesión **excluyendo** archivos que parezcan
       bases/convocatoria/pliego (para no mezclar datos del convocante con el oferente).
    """

    # Mapa de campos → cómo buscarlos y cómo preguntarlos
    FIELD_DEFINITIONS = {
        "rfc": {
            "label": "RFC de la empresa",
            "question": "¿Cuál es el **RFC** oficial de {razon_social}? (ej: ABC123456XYZ)",
            "rag_queries": ["RFC", "Cédula de Identificación Fiscal", "CIF", "R.F.C."],
            "document_hint": "Cédula de Identificación Fiscal (CIF)"
        },
        "domicilio_fiscal": {
            "label": "Domicilio Fiscal",
            "question": "Necesito el **domicilio fiscal completo** de {razon_social} para los formatos oficiales.",
            "rag_queries": ["domicilio fiscal", "dirección fiscal", "calle", "colonia", "c.p.", "código postal"],
            "document_hint": "Comprobante de domicilio o Constancia de Situación Fiscal"
        },
        "representante_legal": {
            "label": "Nombre del Representante Legal",
            "question": "¿Quién es el **representante legal** facultado para firmar la propuesta de {razon_social}?",
            "rag_queries": ["representante legal", "apoderado", "administrador único", "personería jurídica"],
            "document_hint": "Acta Constitutiva o Poder Notarial"
        },
        "cedula_representante": {
            "label": "Número de INE/Cédula del Representante Legal",
            "question": "Para las declaraciones y cartas formales necesito el **número de identificación oficial** (INE, Pasaporte o Cédula Profesional) de **{representante}**. ¿Me lo puedes escribir aquí directamente?",
            "rag_queries": ["clave elector", "número INE", "folio", "identificación oficial", "número de pasaporte"],
            "document_hint": "INE, Pasaporte o Cédula Profesional"
        },
        "telefono": {
            "label": "Teléfono de la empresa",
            "question": "¿Cuál es el **teléfono** de {razon_social}? (ej: 612 123 4567)",
            "rag_queries": ["teléfono", "tel.", "número telefónico", "cel."],
            "document_hint": "Membrete corporativo, CIF o comprobante de domicilio"
        },
        "email": {
            "label": "Correo electrónico de la empresa",
            "question": "¿Cuál es el **correo electrónico oficial** de {razon_social}?",
            "rag_queries": ["correo", "e-mail", "email", "@"],
            "document_hint": "Membrete corporativo"
        },
        "web": {
            "label": "Sitio web de la empresa",
            "question": "¿Tiene {razon_social} un sitio web? Escríbelo o escribe **'No aplica'**.",
            "rag_queries": ["www.", "sitio web", "página web", "http"],
            "document_hint": "Membrete corporativo"
        },
        "anos_experiencia": {
            "label": "Años de experiencia en el giro",
            "question": "¿Cuántos **años de experiencia** tiene {razon_social} en la prestación de servicios de este tipo?",
            "rag_queries": ["años de experiencia", "desde el año", "fundada en", "constituida en"],
            "document_hint": "Acta Constitutiva (fecha de constitución)"
        },
        "numero_empleados": {
            "label": "Número de empleados",
            "question": "¿Cuántos **empleados** tiene actualmente {razon_social}?",
            "rag_queries": ["número de trabajadores", "plantilla laboral", "empleados", "personal de base"],
            "document_hint": "Alta patronal IMSS o declaración interna"
        },
    }

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="data_gap_001",
            name="Agente de Completitud de Datos",
            description="Detecta datos faltantes del perfil de empresa y los solicita via chatbot.",
            context_manager=context_manager
        )
        self.vector_db = VectorDbServiceClient()
        self.llm = ResilientLLMClient()
        self.slot_inferer = SlotInferenceService()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        company_id = agent_input.company_id or ""
        master_profile = {}

        # 🚀 CRITICAL: Fetch FRESH profile from DB to skip stale frontend input_data
        if company_id:
            try:
                company = await self.context_manager.memory.get_company(company_id)
                if company:
                    master_profile = company.get("master_profile", {})
                    # Sincronizar agent_input.company_data para que agentes posteriores vean cambios
                    agent_input.company_data["master_profile"] = master_profile
            except Exception as e:
                print(f"[DataGap] ⚠️ Error fetching fresh profile: {e}")

        # Fallback if no company_id or DB error
        if not master_profile:
            master_profile = agent_input.company_data.get("master_profile", {})

        razon_social = master_profile.get("razon_social") or master_profile.get("name") or "la empresa"
        representante = master_profile.get("representante_legal") or "el representante"

        print(f"[DataGap] 🔍 Analizando perfil de {razon_social} (ID: {company_id})...")

        auto_filled = []
        missing_fields = []

        # --- Hito 5: Inferencia Dinámica de Slots desde Compliance ---
        # Compliance data transition handled in Orchestrator usually. 
        # For direct DataGap, we look into global context if needed.
        compliance_data = agent_input.company_data.get("compliance_master_list") or {}
        inferred_slots = set()
        
        # Recuperar caché de inferencia para no repetir LLM
        session_state = await self.context_manager.memory.get_session(session_id) or {}
        slot_cache = session_state.get("compliance_slot_cache", {})
        
        req_list = compliance_data.get("administrativo", []) + compliance_data.get("tecnico", [])
        
        cache_updated = False
        for req in req_list:
            rid = str(req.get("id", ""))
            text = f"{req.get('nombre', '')} {req.get('descripcion', '')}"
            
            if rid in slot_cache:
                slots = slot_cache[rid]
            else:
                # Inferencia híbrida (Reglas -> LLM)
                slots = await self.slot_inferer.infer_all(text, rid)
                slot_cache[rid] = slots
                cache_updated = True
            
            for s in slots: inferred_slots.add(s)
            
        if cache_updated:
            session_state["compliance_slot_cache"] = slot_cache
            await self.context_manager.memory.save_session(session_id, session_state)

        # Mapear slots inferidos a sus claves reales de perfil
        mapped_inferred_slots = set()
        for s in inferred_slots:
            # Si el slot inferido tiene un equivalente en master_profile, usar ese
            # De lo contrario usar el nombre inferido tal cual
            profile_key = INFERRED_TO_PROFILE_MAP.get(s, s)
            mapped_inferred_slots.add(profile_key)

        # Unimos las definiciones fijas con las inferidas (reconciliadas)
        active_fields = list(self.FIELD_DEFINITIONS.keys())
        for s in mapped_inferred_slots:
            if s not in active_fields:
                active_fields.append(s)

        print(f"[DataGap] 🧩 Slots activos reconciliados (Hito 5.1): {active_fields}")

        for field_key in active_fields:
            # Obtener definición (si no existe, crear una genérica básica)
            field_def = self.FIELD_DEFINITIONS.get(field_key, {
                "label": field_key.replace("_", " ").title(),
                "question": f"Necesito el dato **{field_key.replace('_', ' ')}** de {razon_social} para completar los requisitos.",
                "rag_queries": [field_key.replace("_", " ")],
                "document_hint": "Documentos corporativos"
            })
            
            val = master_profile.get(field_key)
            
            # 💡 SMART SANITY CHECK: Detectar basura o placeholders (22, http, denuncas)
            is_valid = self._is_data_valid(field_key, val)
            
            if is_valid:
                continue

            print(f"[DataGap] 🚨 GAP DETECTADO: '{field_key}' tiene datos basura o está vacío ('{val}'). Buscando...")

            # Canal A: buscar en RAG (documentos subidos)
            found_value = await self._search_in_rag(session_id, company_id, field_def["rag_queries"], correlation_id)

            if found_value and self._is_data_valid(field_key, found_value):
                master_profile[field_key] = found_value
                auto_filled.append(field_key)
                print(f"[DataGap] ✅ Auto-extraído SANADO '{field_key}' = '{found_value[:60]}'")
            else:
                question = field_def["question"].format(
                    razon_social=razon_social,
                    representante=representante
                )
                missing_fields.append({
                    "field": field_key,
                    "label": field_def["label"],
                    "question": question,
                    "document_hint": field_def["document_hint"]
                })

        # Guardar campos auto-completados en la BD
        if auto_filled and company_id:
            await self._persist_profile_updates(company_id, master_profile, auto_filled)
            agent_input.company_data["master_profile"] = master_profile

        # Construir mensaje conversacional para el chatbot
        chatbot_message = self._build_chatbot_message(auto_filled, missing_fields)

        # Guardar pending_questions en la sesión para flujo de chat (ChatbotRAG / Intake)
        status = AgentStatus.WAITING_FOR_DATA if missing_fields else AgentStatus.SUCCESS
        if missing_fields:
            await self._save_pending_questions(session_id, missing_fields)

        print(f"[DataGap] 📊 Informe de Sanidad: {status.value} | Faltantes: {[m['field'] for m in missing_fields]}")

        return AgentOutput(
            status=status,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "auto_filled": auto_filled,
                "missing": missing_fields,
            },
            message=chatbot_message,
            correlation_id=correlation_id
        )

    def _is_data_valid(self, field: str, value: Any) -> bool:
        """Validador quirúrgico de sanidad de datos."""
        if not value: return False
        v = str(value).strip().lower()
        
        # 1. Reglas Generales
        if len(v) < 2: return False
        if "[" in v or "placeholder" in v: return False
        
        # 2. Reglas Específicas por Campo
        if field == "cedula_representante":
            # Un INE/RFC/Cédula real tiene al menos 10-18 chars. '22' es basura.
            if len(v) < 8 or v.isdigit() and len(v) < 10: return False
            
        if field == "email":
            # Bloquear correos de prueba o sin formato
            if "@" not in v or "." not in v: return False
            if "denuncas@sat" in v: return False
            
        if field == "web":
            # Bloquear strings incompletos como 'http'
            if v in ["http", "https", "http://", "https://", "www"]: return False
            if len(v) < 6: return False

        if field == "telefono":
            # Bloquear números demasiado cortos
            digits = "".join(filter(str.isdigit, v))
            if len(digits) < 8: return False

        return True

    @staticmethod
    def _filename_looks_like_bases(name: str) -> bool:
        """
        Heurística alineada con ChatbotRAG (documento principal de licitación).
        Fuentes cuyo nombre sugiere bases/convocatoria/pliego no se usan para
        inferir datos del oferente.
        """
        n = (name or "").lower()
        keywords = (
            "convocatoria",
            "bases",
            "bases_licit",
            "pliego",
            "licitacion",
            "licitación",
            "requisitos",
        )
        return any(k in n for k in keywords)

    def _list_session_expediente_sources(self, session_id: str) -> List[str]:
        """Nombres de archivo indexados en la sesión, excluyendo PDFs que parecen bases."""
        try:
            all_src = self.vector_db.get_sources(session_id)
        except Exception as e:
            print(f"[DataGap] ⚠️ get_sources sesión: {e}")
            return []
        out = [s for s in all_src if s and not self._filename_looks_like_bases(s)]
        if out:
            print(f"[DataGap] 📎 Fuentes sesión (expediente, sin bases): {out}")
        return out

    async def _llm_extract_field_from_text(self, query: str, text_fragment: str, correlation_id: str = "") -> Optional[str]:
        """Pide al LLM un valor acotado a partir de un fragmento."""
        extract_resp = await self.llm.generate(
            prompt=(
                f"Del siguiente fragmento, extrae ÚNICAMENTE el valor de '{query}' "
                "si está presente y corresponde al **proveedor u oferente** "
                "(no uses datos de la entidad convocante ni del anexo de licitación salvo que "
                "el fragmento sea claramente membrete o CIF del oferente).\n"
                f"Texto:\n{text_fragment}\n\n"
                "Responde SOLO con el valor encontrado (máximo 80 caracteres) o escribe: NO_ENCONTRADO"
            ),
            system_prompt=(
                "Eres un extractor de datos puntual. Devuelves solo el valor exacto o NO_ENCONTRADO. "
                "Nunca expliques."
            ),
            correlation_id=correlation_id
        )
        value = extract_resp.response.strip() if extract_resp.success else ""
        if value and "NO_ENCONTRADO" not in value.upper() and len(value) < 100:
            return value
        return None

    async def _search_in_rag(self, session_id: str, company_id: str, queries: List[str], correlation_id: str = "") -> Optional[str]:
        """
        Auto-sanación: primero vectores de empresa; luego sesión (solo fuentes no-bases).
        """
        # --- 1) Colección corporativa ---
        if company_id:
            coll = f"company_{company_id}"
            for query in queries:
                try:
                    results = self.vector_db.query_texts(coll, query, n_results=3)
                    docs = results.get("documents", [])
                    if not docs:
                        continue
                    print(f"    [DataGap] 🔎 Empresa '{coll}' | query '{query}'...")
                    got = await self._llm_extract_field_from_text(query, docs[0][:800], correlation_id)
                    if got:
                        return got
                except Exception:
                    continue

        # --- 2) Fuentes de verdad en sesión (PDFs que no parecen convocatoria/bases) ---
        for src in self._list_session_expediente_sources(session_id):
            for query in queries:
                try:
                    results = self.vector_db.query_texts_filtered(
                        session_id, query, src, n_results=5
                    )
                    docs = results.get("documents", [])
                    if not docs:
                        continue
                    print(f"    [DataGap] 🔎 Sesión archivo '{src}' | query '{query}'...")
                    got = await self._llm_extract_field_from_text(query, docs[0][:800], correlation_id)
                    if got:
                        return got
                except Exception:
                    continue
        return None

    def _build_chatbot_message(self, auto_filled: List[str], missing_fields: List[Dict]) -> Optional[str]:
        """Construye un mensaje conversacional claro y amigable para el chatbot."""
        lines = []

        if auto_filled:
            nombres = ", ".join(auto_filled)
            lines.append(f"✅ Extraje automáticamente de tus documentos: **{nombres}**.")

        if missing_fields:
            lines.append(f"\n🔍 Me faltan **{len(missing_fields)}** dato(s) para completar todos los documentos:")
            for m in missing_fields:
                lines.append(f"   • **{m['label']}** _(fuente sugerida: {m['document_hint']})_")

            lines.append(f"\nEmpecemos por el primero:\n")
            lines.append(f"📋 {missing_fields[0]['question']}")
            lines.append(f"\n_También puedes subir el documento **'{missing_fields[0]['document_hint']}'** a Fuentes de Verdad y dar clic en Analizar Fuentes._")
        else:
            lines.append("\n🎉 ¡Tu expediente está completo! Puedes generar los documentos ahora.")

        return "\n".join(lines)

    async def _save_pending_questions(self, session_id: str, missing_fields: List[Dict]):
        """Guarda las preguntas pendientes en la sesión para que el chatbot las gestione."""
        try:
            session_state = await self.context_manager.memory.get_session(session_id) or {}
            session_state["pending_questions"] = missing_fields
            session_state["current_question_index"] = 0
            await self.context_manager.memory.save_session(session_id, session_state)
        except Exception as e:
            print(f"[DataGap] ⚠️ No se pudo guardar pending_questions: {e}")

    async def _persist_profile_updates(self, company_id: str, profile: Dict, fields: List[str]):
        """Persiste los campos auto-completados en PostgreSQL."""
        try:
            company = await self.context_manager.memory.get_company(company_id)
            if company:
                existing = company.get("master_profile", {})
                for f in fields:
                    if profile.get(f):
                        existing[f] = profile[f]
                company["master_profile"] = existing
                await self.context_manager.memory.save_company(company_id, company)
        except Exception as e:
            print(f"[DataGap] ⚠️ Error persistiendo auto-completado: {e}")
