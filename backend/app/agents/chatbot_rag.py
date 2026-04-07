import json, logging, re
from typing import Any, Dict, List
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.vector_service import VectorDbServiceClient
from app.services.resilient_llm import ResilientLLMClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

logger = logging.getLogger(__name__)

class ChatbotRAGAgent(BaseAgent):
    """
    Agente 6: Chatbot Conversacional Bidireccional (RAG + Data Intake).
    
    MODO 1 - QUERY: El usuario pregunta sobre las bases → RAG responde con citas.
    MODO 2 - DATA_INTAKE: El usuario proporciona datos de su empresa → extrae, guarda, confirma.
    MODO 3 - PENDING: El chatbot tiene preguntas pendientes del DataGapAgent → las formula proactivamente.
    """

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="chatbot_rag_001",
            name="Asistente Conversacional LicitAI",
            description="Motor conversacional bidireccional: RAG + recopilación inteligente de datos.",
            context_manager=context_manager
        )
        self.vector_db = VectorDbServiceClient()
        self.llm = ResilientLLMClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        user_query = agent_input.company_data.get("query", "").strip()
        company_id = agent_input.company_id or ""

        # =====================================================================
        # FASE 0: Verificar si hay preguntas pendientes del DataGapAgent
        # =====================================================================
        session_state = await self.context_manager.memory.get_session(session_id) or {}
        pending_questions = session_state.get("pending_questions", [])
        current_idx = session_state.get("current_question_index", 0)

        # MODO PROACTIVO: Si hay preguntas pendientes, el chatbot debe mencionarlas 
        # siempre que el usuario salude o cuando el objetivo sea avanzar con el expediente.
        if not pending_questions and (not user_query or any(s in user_query.lower() for s in ["hola", "buenos días", "qué tal", "qué falta"])):
            # ¡GOLPE DE TANGIBILIDAD!: Si no hay preguntas, vamos a BUSCARLAS ahora mismo
            from app.agents.data_gap import DataGapAgent
            logger.info(f"[Chatbot] Ejecutando análisis de brechas proactivo para {session_id}")
            gap_agent = DataGapAgent(self.context_manager)
            gap_input = AgentInput(session_id=session_id, company_id=company_id, company_data=agent_input.company_data)
            gap_res = await gap_agent.process(gap_input)
            
            # ¡CORRECCIÓN!: Aceptar WAITING_FOR_DATA (estatus normal de detección de huecos)
            if gap_res.status in [AgentStatus.SUCCESS, AgentStatus.WAITING_FOR_DATA]:
                # Refrescar estado tras el análisis del DataGapAgent
                session_state = await self.context_manager.memory.get_session(session_id) or {}
                pending_questions = session_state.get("pending_questions", [])
                current_idx = 0

        if pending_questions:
            question = pending_questions[current_idx] if current_idx < len(pending_questions) else None
            
            # Palabras clave de saludos o de intención de generar documentos
            saludos = ["hola", "buenos días", "buenas tardes", "hey", "qué tal"]
            intencion_gen = ["generar", "documento", "formato", "anexo", "propuesta", "adelante", "listo", "falt", "qué sigue"]
            
            q_lower = user_query.lower()
            es_saludo = any(s in q_lower for s in saludos) if q_lower else True
            es_intencion = any(s in q_lower for s in intencion_gen)
            
            # Si el usuario solo saluda, pregunta qué sigue, o quiere generar documentos pero falta info:
            # IMPORTANTE: Solo pedimos datos específicos SI hay una empresa seleccionada. 
            # Si no hay empresa, el flujo debe caer al bloque de bienvenida en la Fase 0 (línea 82+).
            if (es_saludo or es_intencion or not user_query) and question and company_id:
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=f"¡Hola! Entiendo que quieres avanzar. Sin embargo, **aún faltan datos clave de tu empresa** para que podamos generar los documentos.\n\n📋 **{question['label']}:** {question['question']}\n\n_Puedes escribirlos aquí directamente para guardarlos y continuar._",
                    confianza="Alta",
                    tipo="pending_question"
                )

        # Consulta vacía y sin cola pendiente: no llamar al LLM/RAG (antes caía en búsqueda vacía).
        if not user_query:
            if not company_id:
                respuesta = (
                    "✨ ¡Hola! Ya estoy analizando el pliego. **Por favor, selecciona tu empresa en el menú superior** "
                    "para que pueda verificar si nos falta algún dato (como el RFC o domicilio) antes de generar tus documentos."
                )
            elif pending_questions:
                # Si hay pendientes y acabamos de entrar
                question = pending_questions[current_idx]
                respuesta = f"¡Hola! Entiendo que quieres avanzar. Sin embargo, **aún faltan datos clave de tu empresa**.\n\n📋 **{question['label']}:** {question['question']}"
            else:
                respuesta = (
                    "¡Excelente! Ya tengo los datos de tu empresa seleccionada y he analizado el pliego. "
                    "Puedes preguntarme sobre requisitos, fechas o documentos de la licitación."
                )
            
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=respuesta,
                confianza="Alta",
                tipo="welcome_greeting",
            )

        # =====================================================================
        # FASE 1: DETERMINÍSTICA — ¿El usuario pide aclarar qué falta? (Rama de Estado)
        # =====================================================================
        if pending_questions:
            clarification_intent = self._evaluate_clarification_intent(user_query)
            if clarification_intent:
                logger.info(f"[Chatbot] Rama DETERMINÍSTICA detectada para: '{user_query}'")
                return await self._handle_clarification(session_id, pending_questions, correlation_id)

        # =====================================================================
        # FASE 2: Clasificar si el mensaje es una PREGUNTA o una APORTACIÓN DE DATOS
        # =====================================================================
        mode = await self._classify_message(user_query, pending_questions, current_idx, correlation_id)
        print(f"[Chatbot] Modo detectado: {mode} | Query: '{user_query[:60]}'")

        # =====================================================================
        # FASE 3A: DATA_INTAKE — El usuario está proporcionando datos de su empresa
        # =====================================================================
        if mode == "DATA_INTAKE" and pending_questions and company_id:
            logger.info(f"[Chatbot] Iniciando Captura de Datos para campo '{pending_questions[current_idx]['label']}'")
            return await self._handle_data_intake(
                session_id, user_query, company_id,
                pending_questions, current_idx, session_state, correlation_id
            )

        # =====================================================================
        # FASE 3B: META — Consultas sobre el estado del proceso (Hito 8)
        # =====================================================================
        if mode == "META":
            logger.info(f"[Chatbot] Modo META detectado para: '{user_query}'")
            return await self._handle_meta_query(session_id, user_query, session_state, correlation_id)

        # =====================================================================
        # FASE 3C: QUERY — Flujo RAG normal
        # =====================================================================
        return await self._handle_rag_query(session_id, user_query, pending_questions, correlation_id)

    async def _classify_message(self, query: str, pending: List, idx: int, correlation_id: str = "") -> str:
        """Clasifica el mensaje como QUERY (pregunta sobre bases) o DATA_INTAKE (aportación de dato)."""
        print(f"DEBUG_CLASSIFY: pending={pending}, type={type(pending)}")
        if not query:
            return "EMPTY"

        # Precio unitario: el usuario suele responder solo con el número (sin "mi " ni "es ")
        if pending and idx < len(pending) and pending[idx].get("type") == "economic_price":
            stripped = (
                query.strip()
                .replace("$", "")
                .replace("mxn", "")
                .replace("MXN", "")
                .replace(",", "")
                .strip()
            )
            if re.match(r"^-?\d+(?:\.\d+)?$", stripped):
                return "DATA_INTAKE"

        # Heurística rápida
        if pending and idx < len(pending) and len(query) < 120 and "?" not in query:
            lowercase = query.lower()
            # Palabras que indican que el usuario está respondiendo
            data_signals = ["es ", "son ", "mi ", "nuestro", "el número", "la dirección",
                            "no aplica", "n/a", "ninguno", "no tengo", "@", "http", "www.",
                            "555", "612", "800", "+52"]
            if any(s in lowercase for s in data_signals):
                return "DATA_INTAKE"

        # Clasificación LLM (más precisa)
        classification_resp = await self.llm.generate(
            prompt=f"""Clasifica el siguiente mensaje como exactamente UNA de estas tres categorías:
QUERY - si el usuario hace una PREGUNTA sobre los requisitos de la licitación, fechas, documentos, etc. (ej: "¿Cuándo es la junta?", "¿Qué solvencia piden?")
DATA_INTAKE - si el usuario está PROPORCIONANDO datos de su empresa directamente (ej: "Mi RFC es...", "15,000 pesos")
META - si el usuario pregunta sobre el ESTADO del sistema o del proceso de generación (ej: "¿Por qué se detuvo?", "¿Qué falta?", "¿Cómo vamos?", "Qué hiciste")

Mensaje: "{query}"

Responde ÚNICAMENTE con la palabra: QUERY, DATA_INTAKE o META""",
            system_prompt="Eres un clasificador de mensajes experto. Respondes SOLO con la categoría.",
            correlation_id=correlation_id
        )
        result = classification_resp.response.strip().upper() if classification_resp.success else "QUERY"
        if "DATA_INTAKE" in result: return "DATA_INTAKE"
        if "META" in result: return "META"
        return "QUERY"

    async def _handle_data_intake(
        self, session_id: str, user_input: str, company_id: str,
        pending: List, current_idx: int, session_state: Dict, correlation_id: str = ""
    ) -> AgentOutput:
        """Procesa la aportación de datos del usuario, la guarda y avanza al siguiente pendiente."""

        current_q = pending[current_idx]
        field_key = current_q["field"]
        field_label = current_q["label"]

        # Extraer el valor específico del mensaje del usuario
        extract_resp = await self.llm.generate(
            prompt=f"""El usuario está respondiendo la siguiente pregunta: "{field_label}"
Su respuesta es: "{user_input}"

Extrae ÚNICAMENTE el valor que proporcionó (sin explicaciones ni frases de cortesía).
Si dice "no aplica" o equivalente, devuelve: N/A
Si no se puede extraer un valor claro, devuelve: AMBIGUO

Responde SOLO con el valor extraído (máximo 100 caracteres):""",
            system_prompt="Eres un extractor de datos preciso. Devuelves el valor puro o N/A o AMBIGUO.",
            correlation_id=correlation_id
        )
        extracted_value = extract_resp.response.strip() if extract_resp.success else "AMBIGUO"

        if "AMBIGUO" in extracted_value.upper():
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=f"No logré entender bien tu respuesta. ¿Podrías decirme directamente **{field_label}**? (ej: un número, texto, o 'No aplica')",
                confianza="Media",
                tipo="clarification_needed"
            )

        # --- Hito 6: Lógica diferenciada de persistencia (Perfil vs Catálogo) ---
        q_type = current_q.get("type", "profile")
        
        if q_type == "economic_price":
            # Guardar en Catálogo en lugar de Perfil
            saved = await self._save_price_to_catalog(company_id, current_q, extracted_value)
        else:
            # Guardar en Perfil (Default)
            saved = await self._save_field_to_company(company_id, field_key, extracted_value)

        # Avanzar al siguiente pendiente
        next_idx = current_idx + 1
        session_state["current_question_index"] = next_idx
        await self.context_manager.memory.save_session(session_id, session_state)

        # Guardar en historial del chat
        await self._save_chat_history(session_id, user_input, f"Guardé: {field_label} = {extracted_value}")

        # ¿Hay más preguntas?
        if next_idx < len(pending):
            next_q = pending[next_idx]
            resp = (
                f"✅ **¡Dato recibido y procesado!** He guardado **{field_label}** como: `{extracted_value}` en el Perfil Maestro de tu empresa.\n\n"
                f"Para completar tu expediente de STI, aún necesito el siguiente dato:\n\n"
                f"📋 **{next_q['label']}:** {next_q['question']}\n\n"
                f"_Escríbelo aquí mismo para que pueda continuar con la generación de tus documentos._"
            )
        else:
            # ¡Todos los datos completos!
            session_state["pending_questions"] = []
            session_state["current_question_index"] = 0
            await self.context_manager.memory.save_session(session_id, session_state)
            resp = (
                f"🎉 **¡EXCELENTE NOTICIA!** Todo el expediente de STI ha sido recibido, archivado y procesado exitosamente.\n\n"
                f"Ya tengo todos los datos (RFC, domicilio, representantes, etc.) integrados en tu perfil.\n\n"
                f"🚀 **PULSA AHORA EL BOTÓN 'GENERAR PROPUESTA'** a la izquierda. Mi motor industrial producirá ahora mismo tus versiones Word y Excel rellenadas con esta información real."
            )

        return self._format_response(session_id=session_id, correlation_id=correlation_id, respuesta=resp, confianza="Alta", tipo="data_saved")

    async def _handle_rag_query(self, session_id: str, user_query: str, pending: List = [], correlation_id: str = "") -> AgentOutput:
        """Flujo RAG estándar: busca en ChromaDB y genera respuesta fundamentada."""
        all_sources = self.vector_db.get_sources(session_id)
        print(f"DEBUG_SOURCES: all_sources={all_sources}, type={type(all_sources)}")

        # Detectar documento principal (bases/convocatoria)
        primary_keywords = ["bases", "convocatoria", "bases_licitacion"]
        primary_doc = next(
            (s for s in all_sources if any(kw in s.lower() for kw in primary_keywords)),
            None
        )

        if primary_doc:
            search_results = self.vector_db.query_texts_filtered(
                session_id, user_query, source_filter=primary_doc, n_results=6
            )
        else:
            search_results = self.vector_db.query_texts(session_id, user_query, n_results=6)

        context_docs = list(reversed(search_results.get("documents", [])))
        metadatas = list(reversed(search_results.get("metadatas", [])))

        context_parts = []
        for i, doc in enumerate(context_docs):
            meta = metadatas[i] if i < len(metadatas) else {}
            src = meta.get("source", "Documento")
            page = meta.get("page", "?")
            context_parts.append(f"--- [FUENTE: {src} | PÁGINA: {page}] ---\n{doc}\n")

        context_str = "\n".join(context_parts) if context_parts else "No se encontró información de la licitación."

        pending_context = ""
        if pending:
            pending_list = "\n".join([f"- {q['label']}: {q['question']}" for q in pending])
            pending_context = f"\nESTADO ACTUAL DEL EXPEDIENTE (DATOS FALTANTES):\n{pending_list}\n"

        system_prompt = (
            "Eres un experto analista de licitaciones públicas nacionales e internacionales (Obras, Servicios y Adquisiciones). "
            "Tu tarea es responder con máxima precisión y utilidad al usuario basándote en los fragmentos proporcionados.\n\n"
            f"{pending_context}\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. EXAMEN EXHAUSTIVO: Siempre examina TODAS las páginas proporcionadas en el contexto. Nunca ignores ninguna.\n"
            "2. LITERALIDAD: Si encuentras un 'Formato', 'Anexo' o 'Documento' con un nombre o código, inclúyelo EXACTAMENTE como aparece.\n"
            "3. CITAS: Al final de cada dato relevante, indica (Pág. X) de forma obligatoria.\n"
            "4. NO ALUCINES: Solo di 'No se menciona' si después de revisar todos los fragmentos confirmas que no existe ninguna referencia.\n"
            "5. CONTEXTO DE SESIÓN: Si el usuario pregunta por datos que faltan o conceptos que el sistema pidió, utiliza la sección ESTADO ACTUAL DEL EXPEDIENTE arriba mencionada para confirmar qué estamos solicitando y por qué.\n"
        )

        prompt = (
            f"DATOS DE CONTEXTO (EXTRACTOS DEL DOCUMENTO):\n\n{context_str}\n\n"
            f"PREGUNTA DEL USUARIO: {user_query}\n\n"
            "INSTRUCCIÓN: Basándote en los fragmentos anteriores, responde de forma técnica, directa y honesta. "
            "Cita el número de página al final de cada punto relevante."
        )

        llm_response = await self.llm.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_ctx": 16384},
            correlation_id=correlation_id
        )
        content = llm_response.response if llm_response.success else "Lo siento, tuve un problema procesando tu consulta."

        # Citas únicas
        citas = []
        seen = set()
        for meta in metadatas:
            key = (meta.get("source", ""), meta.get("page", ""))
            if key not in seen:
                seen.add(key)
                citas.append({"documento": meta.get("source", "Bases"), "pagina": meta.get("page", 1)})

        await self._save_chat_history(session_id, user_query, content)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "respuesta": content,
                "citas": citas[:5],
                "confianza": "Alta" if context_docs else "Baja",
                "sugerencia": None,
                "tipo": "rag_answer"
            },
            correlation_id=correlation_id
        )

    def _format_response(self, session_id: str, correlation_id: str, respuesta: str, confianza: str = "Alta", tipo: str = "info") -> AgentOutput:
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data={
                "respuesta": respuesta,
                "citas": [],
                "confianza": confianza,
                "sugerencia": None,
                "tipo": tipo
            },
            correlation_id=correlation_id
        )

    async def _save_field_to_company(self, company_id: str, field_key: str, value: str) -> bool:
        """Guarda un campo específico en el master_profile de la empresa usando el gestor de memoria industrial."""
        try:
            company = await self.context_manager.memory.get_company(company_id)
            if company:
                profile = company.get("master_profile", {})
                profile[field_key] = value
                company["master_profile"] = profile
                await self.context_manager.memory.save_company(company_id, company)
                print(f"[Chatbot] Perfil de empresa '{company_id}' actualizado: {field_key} = {value}")
                return True
            else:
                logger.error(f"[Chatbot] No se encontró el perfil de empresa con ID: {company_id}")
        except Exception as e:
            logger.error(f"[Chatbot] Fallo crítico al guardar dato en perfil: {e}")
        return False

    async def _save_chat_history(self, session_id: str, user_msg: str, bot_msg: str):
        """Guarda el par de mensajes en el historial de la conversación."""
        try:
            chat_history = await self.context_manager.memory.get_conversation(session_id)
            new_pair = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": bot_msg}
            ]
            await self.context_manager.memory.save_conversation(session_id, chat_history + new_pair)
        except Exception:
            pass

    async def _handle_meta_query(self, session_id: str, query: str, session_state: Dict, correlation_id: str = "") -> AgentOutput:
        """Explica el estado del sistema basándose en la conciencia del orquestador (Hito 8)."""
        decision = session_state.get("last_orchestrator_decision", {})
        stop_reason = decision.get("stop_reason", "IDLE")
        
        # Mapeo de razones de parada a explicaciones humanas
        explanations = {
            "GENERATION_COMPLETED": "✅ **¡La generación está completa!** Todos los documentos han sido generados y empaquetados exitosamente. Puedes descargarlos desde el panel de entregas.",
            "ANALYSIS_COMPLETED": "✅ **El análisis de bases está completo.** El sistema ha indexado y auditado los documentos. Puedes proceder a generar los anexos y propuestas.",
            "INCOMPLETE_DATA": "Me detuve porque **faltan datos en tu perfil de empresa** (RFC, domicilio, etc.) que son necesarios para los anexos.",
            "INCOMPLETE_FORMAT_DATA": "La generación de formatos administrativos está bloqueada porque **faltan campos obligatorios** que detecté en las bases.",
            "MISSING_PRICES": "El análisis económico detectó que hay **conceptos sin precio** en tu catálogo. Necesito que los cotices para poder generar la propuesta financiera.",
            "ECONOMIC_GAP": "Encontré discrepancias o faltantes en el análisis financiero inicial.",
            "COMPLIANCE_ERROR": "Hubo un problema técnico analizando el cumplimiento de las bases. Por favor, reintenta.",
            "IDLE": "Aún no hemos iniciado ningún proceso. Estoy listo para analizar las bases o generar los anexos cuando gustes."
        }
        
        explanation = explanations.get(stop_reason, f"El proceso se encuentra en estado: {stop_reason}.")
        
        # Si hay campos faltantes, listarlos
        missing = session_state.get("pending_questions", [])
        missing_text = ""
        if missing:
            missing_text = "\n\n**Actualmente necesito:**\n" + "\n".join([f"* {q['label']}" for q in missing])
        
        bot_msg = f"🔍 **Estado del Proceso:**\n\n{explanation}{missing_text}\n\n_Puedes proporcionarme estos datos aquí mismo o subir los documentos faltantes._"
        
        await self._save_chat_history(session_id, query, bot_msg)
        return self._format_response(session_id=session_id, correlation_id=correlation_id, respuesta=bot_msg, tipo="meta_answer")

    @staticmethod
    def _normalize(text: str) -> str:
        """Normaliza el texto para comparaciones robustas (minúsculas y sin tildes)."""
        if not text: return ""
        t = text.lower()
        t = t.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
        # Eliminar signos de puntuación básicos para el match
        t = re.sub(r'[¿?¡!,.]', '', t)
        return t.strip()

    @staticmethod
    def _evaluate_clarification_intent(query: str) -> bool:
        """Determina si el usuario está pidiendo aclarar qué información falta (Robusto)."""
        if not query: return False
        
        q = ChatbotRAGAgent._normalize(query)
        
        # 1. MATCHES DIRECTOS (Señales muy fuertes)
        strong_patterns = [
            r"que\s+(falta|faltan|falte)",
            r"cual(es)?\s+(son|es|pides|pediste|necesitas)",
            r"repite(me)?\s+(lo|los)",
            r"que\s+conceptos",
            r"que\s+concepto",
            r"que\s+datos",
            r"que\s+dato",
            r"que\s+precios",
            r"que\s+precio",
            r"que\s+me\s+pediste",
            r"aclarame",
            r"no\s+se\s+a\s+que",
            r"de\s+que\s+hablas"
        ]
        
        for p in strong_patterns:
            if re.search(p, q):
                return True
        
        # 2. SEÑALES COMBINADAS (Si hay 2 o más señales débiles)
        # Señal A: Interrogación/Confusión
        signals_a = ["que", "cuales", "cual", "no se", "no entiendo", "dime", "explica", "cuales son"]
        # Señal B: Contexto de Datos/Conceptos
        signals_b = ["conceptos", "concepto", "datos", "dato", "precios", "precio", "faltan", "faltante", "requieres", "necesitas", "pediste"]
        
        has_a = any(s in q for s in signals_a)
        has_b = any(s in q for s in signals_b)
        
        # Si tiene un "qué/cuáles" y un "concepto/precio", es aclaración
        if has_a and has_b:
            return True
            
        # 3. CASO ESPECIAL: Pregunta muy corta con palabra clave de contexto
        if len(q.split()) <= 4:
            keywords = ["conceptos", "concepto", "que conceptos", "que concepto", "cuales son", "que falta"]
            if any(k in q for k in keywords):
                return True

        return False

    async def _handle_clarification(self, session_id: str, pending: List, correlation_id: str = "") -> AgentOutput:
        """Responde determinísticamente listando los pendientes actuales (Rama de Estado)."""
        if not pending:
            return self._format_response(session_id, correlation_id, "No hay tareas ni datos pendientes en este momento. ¡Todo está en orden!")
        
        intro = "Claro, aquí tienes el detalle de lo que necesito para completar tu expediente:\n\n"
        details = []
        for i, q in enumerate(pending):
            details.append(f"{i+1}. **{q['label']}**: {q['question']}")
        
        footer = "\n\n_Puedes proporcionar estos datos uno por uno aquí mismo para que pueda continuar._"
        resp = intro + "\n".join(details) + footer
        
        await self._save_chat_history(session_id, "Solicitud de aclaración sobre pendientes", resp)
        return self._format_response(session_id, correlation_id, resp, tipo="clarification_answer")


    async def _save_price_to_catalog(self, company_id: str, question: Dict, value: str) -> bool:
        """Guarda un precio unitario en el catálogo histórico de la empresa (Hito 6)."""
        try:
            # Limpiar valor (quitar $, comas, etc)
            clean_val = value.replace("$", "").replace(",", "").strip()
            # Si el usuario dice 'N/A' o similar, no guardamos números inválidos
            price = 0.0
            try:
                price = float(clean_val)
            except:
                return False

            company = await self.context_manager.memory.get_company(company_id)
            if company:
                catalog = company.get("catalog", [])
                
                # Crear nuevo item del catálogo
                new_item = {
                    "description": question.get("label", "Desconocido").replace("Precio de: ", ""),
                    "price_base": price,
                    "currency": "MXN",
                    "id": question.get("field", ""),
                    "source": "chatbot_intake"
                }
                
                # ¿Ya existe este ID? Si si, actualizar
                found = False
                for i, it in enumerate(catalog):
                    if it.get("id") == new_item["id"] or it.get("description") == new_item["description"]:
                        catalog[i] = new_item
                        found = True
                        break
                
                if not found:
                    catalog.append(new_item)
                
                company["catalog"] = catalog
                await self.context_manager.memory.save_company(company_id, company)
                print(f"[Chatbot] Catálogo de empresa '{company_id}' actualizado (Hito 6).")
                return True
        except Exception as e:
            logger.error(f"[Chatbot] Error en _save_price_to_catalog: {e}")
        return False
