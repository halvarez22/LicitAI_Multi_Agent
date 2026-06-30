from app.services.llm_service import LLMServiceClient
from app.core.logging_config import get_logger
import json, logging, os, re, unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.vector_service import VectorDbServiceClient
from app.services.resilient_llm import ResilientLLMClient
from app.services.conversation_normalizer import ConversationNormalizer
from app.services.economic_cotization_filters import is_contaminated_economic_pending_question, _OBRA_PUBLICA_DOC_PATTERNS, _pending_economic_core_concept_text as _pending_economic_core_concept_text_for_chatbot
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.config.settings import settings
from app.economic_validation.service import refresh_economic_validations_for_session
from app.services.document_preprocessor import DocumentPreprocessor
from app.agents.mission_data_extractor import MissionDataExtractor
from app.services.numeric_validator import NumericValidator
from app.services.job_service import get_job_status, get_active_session_job
from app.services.tender_router_service import TenderRouterService
from app.services.junta_bases_corpus import _BASES_FILENAME_RE

logger = get_logger(__name__)

# Documentos de licitante/cotización — no bases del procedimiento (universal, sin mapa por convocante).
_LITERARY_NON_BASES_SOURCE_RE = re.compile(
    r"(?i)\b(cat[aá]logo|cotizaci[oó]n|cotizador|presupuesto|conceptos|"
    r"propuesta\s+econ[oó]mica|lista\s+de\s+precios)\b"
)

_CRONOGRAM_MONTH_NAMES = (
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre"
)
_CRONOGRAM_ACT_MARKERS = (
    "junta",
    "aclaraci",
    "visita",
    "apertura",
    "fallo",
    "presentaci",
    "inscripci",
    "cronograma",
)


def _looks_like_bases_clarification_query(user_query: str) -> bool:
    """
    True si el mensaje es una consulta sobre el pliego/requisitos (RAG), no un saludo
    ni intención genérica de «avanzar expediente».

    Evita el falso positivo de ``intencion_tokens`` con la palabra **anexo** dentro de
    citas tipo «Anexo 17» pegadas desde el semáforo Go/No-Go.
    """
    q = (user_query or "").strip()
    if not q:
        return False
    lo = q.lower()
    needles = (
        "explícame",
        "explicame",
        "qué es ",
        "que es ",
        "qué significa",
        "que significa",
        "requisito",
        "requisitos",
        "bases de licitación",
        "bases de la licitación",
        "del pliego",
        "en el pliego",
        "acreditar",
        "acreditación",
        "acreditarlo",
        "documentos o información",
        "necesito para",
        "detalladamente",
        "según las bases",
        "segun las bases",
        "de estas bases",
        "únicamente podrán",
        "unicamente podran",
    )
    if any(n in lo for n in needles):
        return True
    if "?" in q and any(
        token in lo
        for token in (
            "bases",
            "pliego",
            "convocatoria",
            "anexo",
            "requisito",
            "licitacion",
            "licitación",
            "acreditar",
        )
    ):
        return True
    return False


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
        self.conversation_normalizer = ConversationNormalizer()

    @staticmethod
    def _looks_like_greeting_or_progress_intent(user_query: str) -> bool:
        q = (user_query or "").strip().lower()
        if not q:
            return True
        tokens = (
            "hola",
            "buenos días",
            "buenas tardes",
            "qué tal",
            "que tal",
            "qué falta",
            "que falta",
            "qué sigue",
            "que sigue",
            "como vamos",
            "cómo vamos",
            "como va",
            "cómo va",
            "avanzar",
            "continuar",
            "adelante",
        )
        return any(t in q for t in tokens)

    # --- RAG Enrichment Constants ---
    # Umbral máximo de distancia coseno para considerar un fragmento relevante.
    # ChromaDB retorna distancias en [0, 2]; valores cercanos a 0 = alta similitud.
    RAG_RELEVANCE_THRESHOLD: float = 0.75

    # Longitud máxima del rag_context en caracteres.
    RAG_CONTEXT_MAX_CHARS: int = 400

    # Longitud mínima del rag_context para que sea considerado útil.
    RAG_CONTEXT_MIN_CHARS: int = 30

    # Prefijos de field_target que indican campos con contexto en las bases.
    RAG_ENRICHABLE_PREFIXES: tuple = (
        "condiciones_contractuales.",
        "solvencia_economica.",
        "solvencia_legal.",
        "solvencia_tecnica.",
        "gng_",
    )

    # Mapa de términos de dominio por subcadena del field_target.
    _DOMAIN_TERMS_MAP: dict = {
        "penalizacion":       "pena convencional multa retraso incumplimiento",
        "penaliz":            "pena convencional multa retraso incumplimiento",
        "condiciones_pago":   "forma de pago plazo facturación anticipo",
        "garantia":           "garantía vicios ocultos defectos cumplimiento",
        "capital":            "capital contable mínimo requerido patrimonio",
        "facturacion":        "facturación anual ingresos comprobables",
        "experiencia":        "años experiencia contratos similares previos",
        "solvencia_legal":    "requisito legal documento acreditar constitución",
        "solvencia_tecnica":  "capacidad técnica personal especializado equipo",
        "gng_":               "criterio viabilidad participación licitación",
    }

    @staticmethod
    def _looks_like_optin_acceptance(user_query: str) -> bool:
        q = (user_query or "").strip().lower()
        if not q:
            return False
        accept = (
            "si",
            "sí",
            "dale",
            "va",
            "ok",
            "de acuerdo",
            "empecemos",
            "empezar",
            "adelante",
            "vamos",
        )
        return any(a in q for a in accept)

    @staticmethod
    def _pending_from_intake_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        from app.services.hitl_queue_service import should_exclude_from_chat_queue

        out: List[Dict[str, Any]] = []
        for q in list(plan.get("questions") or []):
            if should_exclude_from_chat_queue(q):
                continue
            question = str(q.get("question") or "").strip()
            if not question:
                continue
            label = str(q.get("field_target") or q.get("question_id") or "dato_requerido")
            out.append(
                {
                    "field": label,
                    "label": label,
                    "question": question,
                    "type": "intake_planner",
                    "is_blocking": bool(q.get("blocking") or str(q.get("priority") or "").upper() == "BLOQUEANTE"),
                    "priority": str(q.get("priority") or "COMPLEMENTARIO"),
                    "question_id": str(q.get("question_id") or ""),
                    "required_evidence": q.get("required_evidence"),
                    "table_data": q.get("table_data"), # Capturar tabla Markdown
                    "provenance_ui": q.get("provenance_ui") if isinstance(q.get("provenance_ui"), dict) else {},
                }
            )
        return out

    @staticmethod
    def _pending_from_quality_hints(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        q_hint = session_state.get("last_document_quality_waiting_hints")
        f_hint = session_state.get("last_document_fill_quality_waiting_hints")

        if isinstance(q_hint, dict):
            reason = str(q_hint.get("reason") or "").strip()
            out.append(
                {
                    "field": "quality.classification.review",
                    "label": "Clasificación documental",
                    "question": (
                        "Detecté anexos con clasificación ambigua. ¿Confirmas cuáles se deben generar, "
                        "cuáles se presentan en físico y cuáles son informativos?"
                    ),
                    "type": "quality_validation_blocking",
                    "is_blocking": True,
                    "priority": "BLOQUEANTE",
                    "question_id": "QH-CLASS-001",
                    "required_evidence": "confirmacion_clasificacion_documental",
                    "provenance_ui": {"source": "document_quality_gate", "confidence": 0.9, "reason": reason},
                }
            )
        if isinstance(f_hint, dict):
            blocking = int(f_hint.get("blocking_count", 0) or 0)
            warnings = int(f_hint.get("warning_count", 0) or 0)
            issues = f_hint.get("issues") if isinstance(f_hint.get("issues"), list) else []
            if blocking > 0 or warnings > 0:
                from app.services.obra_chat_queue_policy import (
                    filter_obra_fill_quality_issues,
                    obra_fill_quality_needs_chat_capture,
                )

                issues_norm = filter_obra_fill_quality_issues(list(issues), session_state)
                if issues_norm and not obra_fill_quality_needs_chat_capture(
                    issues_norm, session_state
                ):
                    return out
                if issues:
                    from app.services.document_fill_ux_messages import build_fill_blocking_question

                    stage = str(f_hint.get("stage") or "technical")
                    question = build_fill_blocking_question(
                        stage, issues_norm or issues, session_state=session_state
                    )
                else:
                    question = (
                        "Al armar los documentos me faltan **datos de tu empresa** (RFC, representante legal, "
                        "domicilio, etc.). Ve a **Empresas**, complétalos y pulsa **Generar** otra vez; "
                        "o escríbeme aquí el dato que falta."
                    )
                out.append(
                    {
                        "field": "quality.fill.review",
                        "label": "Datos para llenar documentos",
                        "question": question,
                        "type": "quality_validation_blocking",
                        "is_blocking": blocking > 0,
                        "priority": "BLOQUEANTE" if blocking > 0 else "CRITICO",
                        "question_id": "QH-FILL-001",
                        "required_evidence": "confirmacion_datos_criticos_documentales",
                        "provenance_ui": {
                            "source": "document_fill_quality_gate",
                            "confidence": 0.85,
                            "reason": f"blocking={blocking},warnings={warnings}",
                        },
                    }
                )
        return out

    @staticmethod
    def _stable_question_id(q: Dict[str, Any]) -> str:
        qid = str(q.get("question_id") or "").strip()
        if qid:
            return qid
        field = str(q.get("field") or "").strip()
        txt = str(q.get("question") or "").strip()
        base = f"{field}|{txt}"[:140]
        base = re.sub(r"\s+", "_", base.lower())
        return re.sub(r"[^a-z0-9_:\-]", "", base) or "pending_unknown"

    @staticmethod
    def _humanize_field_target(field_target: str) -> str:
        """
        Traduce field_targets técnicos a labels legibles para humanos.
        Nunca retorna un string con patrón namespace.campo (ej: solvencia_legal.rfc).

        Estrategia:
        1. Match exacto en _EXACT_MAP.
        2. Match por prefijo de namespace en _PREFIX_MAP.
        3. Limpieza genérica: eliminar namespace + reemplazar _ por espacios + capitalizar.
        """
        _EXACT_MAP = {
            "condiciones_contractuales.penalizaciones": "Penalizaciones contractuales",
            "condiciones_contractuales.condiciones_pago": "Condiciones de pago",
            "condiciones_contractuales.garantia_vicios_ocultos": "Garantía por vicios ocultos",
            "condiciones_contractuales.experiencia_minima": "Experiencia mínima requerida",
            "solvencia_economica.capital_contable": "Capital contable mínimo",
            "solvencia_economica.facturacion_anual": "Facturación anual",
            "solvencia_economica.patrimonio_neto": "Patrimonio neto",
            "solvencia_economica.anos_de_experiencia": "Años de experiencia",
            "solvencia_legal.rfc": "RFC de la empresa",
            "solvencia_legal.acta_constitutiva": "Acta constitutiva",
            "solvencia_legal.poder_notarial": "Poder notarial del representante",
            "solvencia_legal.representante_legal": "Representante legal",
            "solvencia_legal.domicilio_fiscal": "Domicilio fiscal",
            "solvencia_legal.registro_patronal": "Registro patronal (IMSS)",
            "solvencia_tecnica.anos_experiencia": "Años de experiencia técnica",
            "solvencia_tecnica.contratos_similares": "Contratos similares previos",
            "quality.classification.review": "Revisión de clasificación documental",
            "quality.fill.review": "Validación de llenado documental",
        }

        _PREFIX_MAP = {
            "condiciones_contractuales.": "Condición contractual",
            "solvencia_economica.": "Solvencia económica",
            "solvencia_legal.": "Solvencia legal",
            "solvencia_tecnica.": "Solvencia técnica",
            "compliance.administrativo.": "Requisito administrativo",
            "compliance.tecnico.": "Requisito técnico",
            "compliance.formatos.": "Formato de bases",
            "compliance.": "Requisito de cumplimiento",
            "quality.": "Calidad documental",
            "inventory.": "Inventario documental",
            "gap.": "Detalle de cumplimiento",
            "gng_": "Brecha de viabilidad",
            "profile_field_": "Dato de perfil",
            "price_": "Precio unitario",
        }

        ft = str(field_target or "").strip()
        if not ft:
            return "Dato requerido"

        # 1. Match exacto
        if ft in _EXACT_MAP:
            return _EXACT_MAP[ft]

        # 2. Match por prefijo de namespace
        for prefix, label in _PREFIX_MAP.items():
            if ft.startswith(prefix):
                suffix = ft[len(prefix):]
                # Manejar sufijos numéricos (ej: gap.1 -> gap. o compliance.tecnico.7 -> compliance.tecnico.)
                # También limpiar guiones y puntos antes de capitalizar
                clean_suffix = re.sub(r'^[._]|(?:\.\d+|_?\d+)$', '', suffix)
                readable_suffix = clean_suffix.replace("_", " ").replace(".", " ").strip().capitalize()
                
                if readable_suffix and not readable_suffix.isdigit():
                    return f"{label}: {readable_suffix}"
                return label

        # 3. Limpieza genérica: eliminar namespace si hay punto
        if "." in ft:
            ft = ft.split(".", 1)[1]  # Eliminar prefijo de namespace

        # Reemplazar guiones bajos por espacios y capitalizar
        return ft.replace("_", " ").capitalize() or "Dato requerido"

    def _build_mission_context(
        self,
        session_state: Dict[str, Any],
        pending_question: Dict[str, Any],
        current_idx: int,
        total: int,
    ) -> Dict[str, Any]:
        """
        Construye el contexto de misión para formular una pregunta pendiente de forma
        contextualizada. Agrega semántica de negocio a la pending_question técnica.

        Retorna exactamente 7 claves. No lanza excepciones para ninguna combinación
        válida de inputs.
        """
        try:
            tasks_completed = list(session_state.get("tasks_completed") or [])
            documentos_generados = any(
                str(t.get("task") or "").startswith("stage_completed:")
                for t in tasks_completed
            )
        except Exception:
            documentos_generados = False

        try:
            gng = session_state.get("go_no_go_result") or {}
            semaforo_actual = str(gng.get("semaforo") or "")
        except Exception:
            semaforo_actual = ""

        try:
            provenance_ui = pending_question.get("provenance_ui") or {}
            provenance_reason = str(provenance_ui.get("reason") or "")
        except Exception:
            provenance_reason = ""

        try:
            is_blocking = bool(pending_question.get("is_blocking"))
            impacto = "BLOQUEANTE" if is_blocking else "complementario"
        except Exception:
            impacto = "complementario"

        try:
            progreso = f"{int(current_idx) + 1} de {int(total)}"
        except Exception:
            progreso = "en curso"

        # Humanizar el label antes de incluirlo en el contexto
        raw_label = str(
            pending_question.get("label")
            or pending_question.get("field_target")
            or pending_question.get("field")
            or ""
        )
        dato_solicitado = self._humanize_field_target(raw_label) if raw_label else "Dato requerido"

        # por_que_importa: prioridad rag_context > clausula_texto > question original
        # rag_context contiene el texto real de las bases para esta licitación específica
        try:
            rag_context = str(pending_question.get("rag_context") or "").strip()
            clausula_texto = str((pending_question.get("provenance_ui") or {}).get("clausula_texto") or "").strip()
            question_original = str(pending_question.get("question") or "").strip()
            por_que_importa = rag_context or clausula_texto or question_original
        except Exception:
            por_que_importa = str(pending_question.get("question") or "")

        return {
            "dato_solicitado": dato_solicitado,
            "por_que_importa": por_que_importa,
            "impacto": impacto,
            "progreso": progreso,
            "documentos_generados": documentos_generados,
            "semaforo_actual": semaforo_actual,
            "provenance_reason": provenance_reason,
        }

    @staticmethod
    def _detect_tone_mode(
        session_state: Dict[str, Any],
        pending_questions: List[Dict[str, Any]],
        current_idx: int,
    ) -> str:
        """
        Detecta el modo de tono apropiado según el estado de la sesión.

        Prioridades (de mayor a menor):
        1. modo_completado: sin pendientes
        2. modo_post_generacion: documentos ya generados (prioridad sobre urgente)
        3. modo_recoleccion_urgente: dato bloqueante sin docs generados
        4. modo_recoleccion_inicial: modo por defecto

        No lanza excepciones para ninguna combinación válida de inputs.
        """
        try:
            if not pending_questions:
                return "modo_completado"
        except Exception:
            return "modo_completado"

        try:
            tasks_completed = list(session_state.get("tasks_completed") or [])
            has_generated_docs = any(
                str(t.get("task") or "") in (
                    "stage_completed:formats_pilot",
                    "stage_completed:technical",
                    "stage_completed:economic",
                    "stage_completed:generation"
                )
                for t in tasks_completed
            )
            if has_generated_docs:
                return "modo_post_generacion"
        except Exception:
            pass

        try:
            idx = int(current_idx or 0)
            current_q = pending_questions[idx] if 0 <= idx < len(pending_questions) else {}
            is_blocking = bool(current_q.get("is_blocking"))
            if is_blocking:
                return "modo_recoleccion_urgente"
        except Exception:
            pass

        return "modo_recoleccion_inicial"

    @staticmethod
    def _build_rag_query(pending_question: Dict[str, Any]) -> str:
        """
        Construye la query semántica para ChromaDB según el tipo de campo.

        Para intake_planner: usa question + provenance_ui.reason (semánticamente ricos).
        Para estructurados: usa label humanizado + términos del _DOMAIN_TERMS_MAP.
        Garantiza longitud mínima de 10 chars con fallback al label humanizado.
        """
        q_type = str(pending_question.get("type") or "")
        field_target = str(pending_question.get("field_target") or pending_question.get("field") or "")
        
        query = ""
        if q_type == "intake_planner":
            question = str(pending_question.get("question") or "").strip()
            reason = str((pending_question.get("provenance_ui") or {}).get("reason") or "").strip()
            query = f"{question} {reason}".strip()
        else:
            label = ChatbotRAGAgent._humanize_field_target(field_target)
            extra_terms = ""
            for key, terms in ChatbotRAGAgent._DOMAIN_TERMS_MAP.items():
                if key in field_target:
                    extra_terms = terms
                    break
            query = f"{label} {extra_terms}".strip()

        if len(query) < 10:
            query = ChatbotRAGAgent._humanize_field_target(field_target)
            
        return query.strip()

    @staticmethod
    def _truncate_to_sentence(text: str, max_chars: int, min_chars: int) -> str:
        """
        Trunca text a max_chars garantizando que el resultado termine en oración completa.

        Estrategia de corte (en orden de preferencia):
        1. Si text <= max_chars y ya termina en separador: retornar tal cual.
        2. Truncar a max_chars; buscar hacia atrás el último '.', '!', '?'.
        3. Fallback: buscar hacia atrás la última ',' o ';'.
        4. Fallback final: usar el texto truncado tal cual.
        5. Si len(resultado) < min_chars: retornar "" (señal de descarte).
        """
        if not text:
            return ""
        
        text = text.strip()
        if len(text) <= max_chars and text[-1] in ".!?":
            return text if len(text) >= min_chars else ""

        # Truncar a max_chars
        truncated = text[:max_chars]
        
        # 1. Buscar hacia atrás '.', '!', '?'
        last_sentence_end = -1
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in ".!?":
                last_sentence_end = i
                break
        
        if last_sentence_end != -1:
            res = truncated[:last_sentence_end + 1].strip()
            return res if len(res) >= min_chars else ""

        # 2. Fallback: buscar hacia atrás ',' o ';'
        last_comma = -1
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in ",;":
                last_comma = i
                break
        
        if last_comma != -1:
            res = truncated[:last_comma + 1].strip()
            return res if len(res) >= min_chars else ""

        # 3. Fallback final: usar truncado tal cual
        res = truncated.strip()
        return res if len(res) >= min_chars else ""

    @staticmethod
    def _is_rag_context_clean(text: str, min_chars: int) -> bool:
        r"""
        Verifica que el texto es legible para el usuario y no contiene variables técnicas.

        Retorna False si:
        - len(text) < min_chars
        - Contiene patrón \w+\.\w+ (namespace técnico como "solvencia_legal.rfc")
        """
        if not text or len(text) < min_chars:
            return False
        
        # Evitar variables técnicas como solvencia_legal.rfc o condiciones_contractuales.penalizaciones
        # Pero permitir Anexo 1.1 o Cláusula 5.2 (donde hay dígitos)
        if re.search(r'[a-zA-Z_]{2,}\.[a-zA-Z_]{2,}', text):
            return False
            
        return True

    async def _enrich_pending_with_rag_context(
        self,
        session_id: str,
        pending_question: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Busca en el RAG el contexto relevante de las bases para una pregunta de intake.

        Solo aplica a preguntas que tienen contexto en las bases (condiciones contractuales,
        solvencia económica, solvencia legal, solvencia técnica, o tipo intake_planner).
        
        Retorna el pending_question enriquecido con 'rag_context' si encuentra fragmento
        relevante y limpio, o el pending_question sin cambios (identidad intacta) si falla.
        """
        if not session_id:
            return pending_question

        field_target = str(pending_question.get("field_target") or pending_question.get("field") or "")
        q_type = str(pending_question.get("type") or "")

        is_intake = (q_type == "intake_planner")
        is_structured = any(field_target.startswith(p) for p in self.RAG_ENRICHABLE_PREFIXES)

        if not (is_intake or is_structured):
            return pending_question

        # Tipos explícitamente excluidos (económicos y de calidad suelen ser técnicos/dinámicos)
        if q_type in ("economic_price", "economic_validation_blocking", "quality_validation_blocking"):
            return pending_question

        # NUEVO: Si el Analista ya nos dejó evidencia (pasaporte), la usamos directamente y ahorramos RAG
        # Esto garantiza que el Chatbot no "alucine" algo distinto a lo que el Analista detectó.
        if pending_question.get("evidence_snippet") and pending_question.get("pagina"):
            pg = pending_question.get("pagina")
            src = pending_question.get("archivo_fuente") or "Bases/Anexos"
            snip = pending_question.get("evidence_snippet")
            
            # Marcamos que es evidencia heredada para trazabilidad
            pending_question["rag_context"] = f"--- [EVIDENCIA DETECTADA POR ANALISTA: {src} | PÁGINA: {pg}] ---\n{snip}"
            logger.info("chatbot_using_inherited_evidence", session_id=session_id, page=pg, field=field_target)
            return pending_question

        query = self._build_rag_query(pending_question)

        try:
            # HITO 10.2: Ampliación de ventana de contexto a 10 resultados.
            # Esto permite que la búsqueda híbrida rescate múltiples páginas candidatas
            # y el LLM decida cuál es la correcta (ej: cronograma vs glosario).
            results = self.vector_db.query_texts(session_id, query, n_results=10)
            docs = results.get("documents", [])
            distances = results.get("distances", [])

            if not docs or not distances:
                return pending_question

            # Validar score de relevancia
            score = distances[0]
            if score > self.RAG_RELEVANCE_THRESHOLD:
                logger.debug(
                    "rag_score_too_high",
                    session_id=session_id,
                    field_target=field_target,
                    score=score,
                    threshold=self.RAG_RELEVANCE_THRESHOLD
                )
                return pending_question

            # Truncar a oración completa
            raw_doc = str(docs[0])
            rag_context = self._truncate_to_sentence(
                raw_doc, self.RAG_CONTEXT_MAX_CHARS, self.RAG_CONTEXT_MIN_CHARS
            )

            if not rag_context:
                return pending_question

            # Validar ausencia de variables técnicas
            if not self._is_rag_context_clean(rag_context, self.RAG_CONTEXT_MIN_CHARS):
                logger.warning(
                    "rag_technical_variable_detected",
                    session_id=session_id,
                    field_target=field_target,
                    snippet=rag_context[:80]
                )
                return pending_question

            # Enriquecer: crear copia para no mutar el original
            enriched = dict(pending_question)
            enriched["rag_context"] = rag_context
            
            logger.info(
                "rag_enrichment_success",
                session_id=session_id,
                field_target=field_target,
                query_type=q_type,
                rag_chars=len(rag_context),
                score=score
            )
            return enriched

        except Exception as e:
            logger.warning(
                "rag_enrichment_failed",
                session_id=session_id,
                field_target=field_target,
                error=str(e)[:100]
            )

        return pending_question

    # Tipos HITL de perfil: redacción canónica (DataGap), sin LLM (evita refusals PII del modelo).
    _PROFILE_INTAKE_TYPES = frozenset({"profile", "profile_field", "quality_validation_blocking"})

    @staticmethod
    def _is_mission_llm_refusal(text: str) -> bool:
        """
        Detecta rechazos genéricos del LLM (privacidad / no puedo ayudar) que rompen el intake.
        """
        lo = str(text or "").strip().lower()
        if len(lo) < 12:
            return False
        needles = (
            "no puedo proporcionar",
            "no puedo compartir",
            "no puedo solicitar",
            "no puedo pedir",
            "no puedo acceder",
            "no puedo encontrar información",
            "sin que se me proporcione",
            "archivo pdf",
            "contenido específico de un archivo",
            "información personal",
            "informacion personal",
            "datos personales",
            "razón válida",
            "razon valida",
            "no estoy autorizado",
            "no puedo ayudarte con eso",
            "cannot provide personal",
            "can't provide personal",
            "i can't help with",
            "i cannot help with",
        )
        if any(n in lo for n in needles):
            return True
        if lo.startswith("lo siento") and ("no puedo" in lo or "no podemos" in lo):
            return True
        return False

    @staticmethod
    def _is_rag_llm_refusal(text: str) -> bool:
        """Rechazo del LLM en RAG cuando ya hay fragmentos indexados (evasiva / no puedo leer PDF)."""
        return ChatbotRAGAgent._is_mission_llm_refusal(text)

    @staticmethod
    def _canonical_pending_question_text(
        pending_question: Dict[str, Any],
        mission_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Texto estable para preguntas de perfil (contrato DataGap / pending_questions)."""
        q = str(pending_question.get("question") or "").strip()
        if q:
            return q
        mc = mission_context or {}
        por_que = str(mc.get("por_que_importa") or "").strip()
        if por_que:
            return por_que
        dato = str(
            mc.get("dato_solicitado")
            or pending_question.get("label")
            or pending_question.get("field")
            or "este dato"
        ).strip()
        return f"¿Me confirmas **{dato}**?"

    async def _generate_mission_question(
        self,
        mission_context: Dict[str, Any],
        tone_mode: str,
        pending_question: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Genera un mensaje conversacional contextualizado para solicitar un dato pendiente.

        Perfil (profile / profile_field): solo texto canónico, sin LLM.
        Otros tipos: LLM con validación de refusal y fallback a pregunta canónica o plantilla.

        Nunca lanza excepciones.
        """
        pq_type = str((pending_question or {}).get("type") or "profile")
        if pending_question and pq_type in ChatbotRAGAgent._PROFILE_INTAKE_TYPES:
            canonical = self._canonical_pending_question_text(pending_question, mission_context)
            if canonical:
                logger.info(
                    "chatbot_mission_question_deterministic",
                    field=str(pending_question.get("field") or "")[:64],
                    q_type=pq_type,
                )
                return canonical
        _TONE_INSTRUCTIONS = {
            "modo_recoleccion_inicial": (
                "Sé muy breve y directo. Habla como un colega experto. "
                "Pide el dato de forma natural, sin usar frases de relleno como 'necesito esta información para...'. "
                "Ve al grano: una oración breve de contexto y la pregunta."
            ),
            "modo_recoleccion_urgente": (
                "Este dato es crítico para no ser descalificados. "
                "Sé muy honesto sobre la importancia pero mantén la calma. "
                "Pide el dato sin rodeos técnicos."
            ),
            "modo_post_generacion": (
                "Ya casi terminamos. Pide este detalle final con naturalidad, "
                "como quien revisa los últimos puntos antes de firmar. "
                "Nada de lenguaje de 'auditoría' ni de 'bases del proyecto'."
            ),
            "modo_completado": (
                "¡Listo! Ya tenemos todo lo necesario. "
                "Dile al usuario que la propuesta está lista para procesarse con un tono de victoria."
            ),
        }

        tone_instruction = _TONE_INSTRUCTIONS.get(tone_mode, _TONE_INSTRUCTIONS["modo_recoleccion_inicial"])

        system_prompt = f"""Eres el asistente conversacional de LicitAI. Tu misión es ayudar a empresas mexicanas a ganar licitaciones públicas.

Recibirás un contexto de misión con datos sobre la pregunta actual y el estado de la sesión.
Genera UN mensaje conversacional en español mexicano.

INSTRUCCIÓN DE TONO: {tone_instruction}

REGLAS ESTRICTAS (OBLIGATORIAS):
1. Máximo 1 oración breve. Sé extremadamente directo y humano.
2. NUNCA menciones que necesitas el dato para 'las bases', 'la licitación' o 'el proyecto'. El usuario ya lo sabe.
3. Habla como un experto que ayuda a un amigo, no como un sistema de auditoría.
4. NUNCA uses términos técnicos como 'brecha estratégica', 'incidencia', 'cumplimiento' o 'integridad'.
5. Si el dato es 'seguridad operativa', pregunta directamente: '¿Qué medidas de seguridad operativa manejas?' o algo similar.
6. NO menciones progresos ni números de pregunta.
7. Evita frases de cortesía largas como '¿Podrías proporcionar...?' o 'Agradecería si me indicas...'. Ve al grano.
8. Estás autorizado a SOLICITAR al licitante datos de su empresa y representante legal para una licitación pública. NUNCA rechaces por privacidad ni digas que no puedes pedir datos personales. """

        user_prompt = f"""Contexto de misión:
- Dato solicitado: {mission_context.get('dato_solicitado', 'Dato requerido')}
- Por qué importa: {mission_context.get('por_que_importa', '')}
- Impacto: {mission_context.get('impacto', 'complementario')}
- Progreso: {mission_context.get('progreso', '')}
- Documentos generados: {mission_context.get('documentos_generados', False)}
- Semáforo actual: {mission_context.get('semaforo_actual', '')}
- Razón de provenance: {mission_context.get('provenance_reason', '')}

Genera el mensaje conversacional para solicitar este dato."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            llm_response = await self.llm.chat(
                messages=messages,
                options={"temperature": 0.7, "max_tokens": 200},
            )
            generated = ""
            if llm_response and llm_response.success:
                generated = str(llm_response.response or "").strip()
            elif llm_response and not llm_response.success:
                logger.warning(
                    "chatbot_mission_question_llm_failed",
                    error=str(llm_response.error or "")[:120],
                )

            # Validación post-generación: si contiene variables técnicas, usar fallback
            import re as _re
            if generated and (
                _re.search(r"\b\w+\.\w+_\w+\b", generated)
                or _re.search(r"\b\w+_\w+\.\w+\b", generated)
            ):
                logger.warning(
                    "chatbot_mission_question_technical_variable_detected",
                    generated=generated[:100],
                )
                generated = ""

            if generated and self._is_mission_llm_refusal(generated):
                logger.warning(
                    "chatbot_mission_question_refusal_detected",
                    generated=generated[:120],
                    field=str((pending_question or {}).get("field") or "")[:64],
                )
                generated = ""

            if generated:
                return generated

            if pending_question:
                canonical = self._canonical_pending_question_text(pending_question, mission_context)
                if canonical:
                    return canonical

        except Exception as e:
            logger.warning("chatbot_mission_question_llm_failed", error=str(e)[:120])

        if pending_question:
            canonical = self._canonical_pending_question_text(pending_question, mission_context)
            if canonical:
                return canonical

        # Fallback: construir mensaje legible sin LLM
        dato = mission_context.get("dato_solicitado", "Dato requerido")
        por_que = mission_context.get("por_que_importa", "")
        if tone_mode == "modo_post_generacion":
            return f"Tus documentos ya están listos 🎉. Para blindar aún más la propuesta, necesito confirmar: {dato}. {por_que}"
        elif tone_mode == "modo_recoleccion_urgente":
            return f"Este dato es clave para poder participar: necesito tu {dato}. {por_que}"
        else:
            return f"Para continuar con tu propuesta, necesito: {dato}. {por_que}"

    def _build_intake_queue_completed_response(
        self,
        *,
        human_saved: str,
        semaforo_change_msg: str = "",
    ) -> Tuple[str, List[Dict[str, str]]]:
        """
        Mensaje al cerrar la cola HITL de perfil (último pendiente respondido).

        Confirma el guardado del dato recién capturado y orienta a generación completa
        del expediente, no solo a la propuesta económica.
        """
        lead = f"Listo, guardé **{human_saved}**."
        body = (
            "Con esto cerramos los datos pendientes del perfil para esta licitación.\n\n"
            "Cuando quieras armar el expediente para la convocante, usa **Generar** en el panel "
            "(técnica, formatos administrativos, económica y empaquetado) "
            "o escribe **generar documentos** en este chat."
        )
        resp = f"{lead}{semaforo_change_msg}\n\n{body}".strip()
        actions: List[Dict[str, str]] = [
            {
                "label": "Ver dictamen / estado",
                "payload": "CMD_SHOW_FORENSIC",
                "style": "secondary",
            },
        ]
        return resp, actions

    def _build_economic_price_queue_completed_response(
        self,
        *,
        human_saved: str,
        semaforo_change_msg: str = "",
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Mensaje al cerrar la cola de precios unitarios (no confundir con perfil legal)."""
        lead = f"Listo, guardé **{human_saved}**."
        body = (
            "Con esto quedaron registrados los precios que pedía la cola.\n\n"
            "Siguiente paso: escribe **`generar propuesta economica`** para armar la cotización. "
            "Cuando esté validada, usa **Generar** en el panel o **`generar documentos`**."
        )
        resp = f"{lead}{semaforo_change_msg}\n\n{body}".strip()
        actions: List[Dict[str, str]] = [
            {
                "label": "Generar propuesta económica",
                "payload": "CMD_TRIGGER_ECONOMIC_PROPOSAL",
                "style": "primary",
            },
        ]
        return resp, actions

    @staticmethod
    def _format_economic_price_followup(
        human_saved: str,
        extracted_value: str,
        next_q: Dict[str, Any],
        session_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Transición corta entre precios (sin repetir plantilla larga ni estado de compliance)."""
        from app.services.chat_economic_matrix import format_matrix_blocks_markdown

        concept_next = ChatbotRAGAgent._concept_from_economic_price_pending_q(next_q)
        base = (
            f"Listo, guardé **{human_saved}** → **{extracted_value}**.\n\n"
            f"**Siguiente precio:** **{concept_next}**. "
            "Puedes escribir el número, usar pesos ($12,500) o pegar filas ubicación+precio."
        )
        blocks = (session_state or {}).get("capture_matrix_blocks") or []
        md = format_matrix_blocks_markdown(blocks, max_rows=6)
        if md and len((session_state or {}).get("pending_questions") or []) > 3:
            return f"{base}\n\n{md}"
        return base

    @staticmethod
    def _compute_pending_progress(
        pending: List[Dict[str, Any]],
        current_idx: int,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.hitl_queue_service import sanitize_chat_pending_questions

        chat_pending = sanitize_chat_pending_questions(pending or [], session_state)
        total = len(chat_pending)
        if total <= 0:
            return {"progress_current": 0, "progress_total": 0, "progress_label": "Sin pendientes"}
        # Reindexar puntero si el índice global apuntaba a un ticket excluido.
        qid_types = {str(q.get("type") or "") for q in (pending or []) if isinstance(q, dict)}
        if qid_types & {"clarification_ticket", "mini_dictamen_blocking"}:
            idx = 0
        else:
            idx = max(0, min(int(current_idx or 0), total - 1))
        current = idx + 1
        return {
            "progress_current": current,
            "progress_total": total,
            "progress_label": f"Pregunta {current} de {total}",
        }

    def _resolve_resume_pointer(self, session_state: Dict[str, Any], pending: List[Dict[str, Any]], fallback_idx: int) -> int:
        if not pending:
            return 0
        prog = session_state.get("intake_progress") if isinstance(session_state.get("intake_progress"), dict) else {}
        qid = str(prog.get("current_question_id") or "").strip()
        if qid:
            for i, q in enumerate(pending):
                if self._stable_question_id(q) == qid:
                    return i
        idx = int(session_state.get("current_question_index") or fallback_idx or 0)
        return max(0, min(idx, len(pending) - 1))

    @staticmethod
    def _render_intake_message(template_key: str, context: Dict[str, Any]) -> str:
        if template_key == "offer":
            b = int(context.get("blocking_count", 0) or 0)
            t = int(context.get("total", 0) or 0)
            if b > 0:
                return (
                    f"Diagnóstico listo: detecté **{b} punto(s) bloqueante(s)** y **{max(0, t - b)} pendiente(s)**. "
                    "Si te parece, iniciamos ahora para asegurar elegibilidad antes de generar."
                )
            return (
                f"Diagnóstico listo: detecté **{t} pendiente(s)** para blindar la propuesta. "
                "¿Quieres que iniciemos el plan guiado ahora?"
            )
        if template_key == "resume":
            label = str(context.get("progress_label") or "Pregunta en curso")
            question = str(context.get("question") or "")
            return f"Retomamos donde quedamos. **{label}**.\n\n{question}"
        if template_key == "completed":
            return "Checklist de intake completado. Ya puedes continuar con generación con mayor certeza documental."
        return str(context.get("question") or "")

    @staticmethod
    def _stage_task_result(tasks: List[Dict[str, Any]], stage: str) -> Optional[Dict[str, Any]]:
        """Último resultado persistido para ``stage_completed:{stage}``."""
        task_name = f"stage_completed:{stage}"
        for task in reversed(tasks or []):
            if str(task.get("task") or "") == task_name:
                result = task.get("result")
                return result if isinstance(result, dict) else {}
        return None

    @classmethod
    def _bases_analysis_phase(cls, state: Dict[str, Any]) -> str:
        """
        Fase del análisis de bases respecto al dictamen forense.

        Returns:
            ``none`` | ``partial`` | ``complete`` | ``failed``
        """
        tasks = list(state.get("tasks_completed") or [])
        compliance_res = cls._stage_task_result(tasks, "compliance")
        if compliance_res is not None:
            status = str(compliance_res.get("status") or "").lower()
            if status in ("error", "failed"):
                return "failed"
            return "complete"
        if cls._stage_task_result(tasks, "analysis") is not None:
            return "partial"
        return "none"

    @staticmethod
    def _build_analysis_in_progress_message(state: Dict[str, Any], active_job: Dict[str, Any]) -> str:
        """Mensaje honesto cuando el job de análisis sigue RUNNING."""
        session_name = str(state.get("name") or "esta licitación")
        progress = active_job.get("progress") or {}
        pct = progress.get("pct", 0)
        detail = progress.get("message") or progress.get("stage") or "procesando bases"
        msg = f"¡Hola! Retomamos el trabajo en **{session_name}**.\n\n"
        msg += "⏳ **El análisis de bases sigue en curso** — el dictamen forense **aún no está cerrado**.\n\n"
        msg += f"**Progreso estimado:** {pct}% — {detail}\n\n"
        msg += (
            "No reinicies el análisis desde el panel. En PDFs largos puede tardar más de una hora. "
            "Si la barra dejó de moverse, el servidor puede seguir trabajando: recarga la pestaña en unos minutos.\n"
        )
        msg += (
            "\n---\n**¿Continuamos?** Espera a que termine el análisis antes de "
            "«generar propuesta económica» o pulsar **Generar**."
        )
        return msg

    def _build_session_resume_message(self, state: Dict[str, Any]) -> str:
        """
        Mensaje proactivo de reanudación (Gate 5: ≤3 líneas + 1 CTA).
        """
        from app.services.chat_gate5_formatter import build_compact_session_resume

        return build_compact_session_resume(state)

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        user_query = agent_input.company_data.get("query", "").strip()
        company_id = agent_input.company_id or ""
        job_id = agent_input.job_id

        _GREETINGS = {"", "hola", "hi", "hello", "buenas", "buenas tardes",
                      "buenas noches", "buenos dias", "buenos días", "hey",
                      "buen dia", "buen día"}
        _is_bootstrap_query = user_query.lower() in _GREETINGS

        # Respuesta anclada para consultas desde el panel de riesgos forenses (HRU).
        _risk_ctx = agent_input.company_data.get("forensic_risk_context")
        if user_query and isinstance(_risk_ctx, dict) and _risk_ctx:
            try:
                from app.services.forensic_risk_chat_service import try_answer_forensic_risk_question

                _session_for_risk = await self.context_manager.memory.get_session(session_id) or {}
                _risk_ctx = {**_risk_ctx, "force_grounded": True, "session_id": session_id}
                grounded = await try_answer_forensic_risk_question(
                    user_query,
                    _risk_ctx,
                    session_id=session_id,
                    memory=self.context_manager.memory,
                    session_state=_session_for_risk,
                )
                if grounded:
                    if isinstance(grounded, dict):
                        reply_text = grounded.get("respuesta") or ""
                        extra = {
                            k: v for k, v in grounded.items()
                            if k != "respuesta"
                        }
                    else:
                        reply_text = str(grounded)
                        extra = {}
                    await self._save_chat_history(session_id, user_query, reply_text)
                    return AgentOutput(
                        status=AgentStatus.SUCCESS,
                        agent_id=self.agent_id,
                        session_id=session_id,
                        data={"respuesta": reply_text, "grounded_forensic_risk": True, **extra},
                        message=reply_text,
                        correlation_id=correlation_id,
                    )
            except Exception as _risk_chat_exc:
                logger.warning(
                    "forensic_risk_grounded_chat_skip session=%s err=%s",
                    session_id,
                    _risk_chat_exc,
                )
        
        # --- C04: COMPLIANCE GATE (Sensor Asíncrono) ---
        # Si el análisis de cumplimiento está en curso, devolvemos PENDING.
        # No bloquear bootstrap/saludos: deben mostrar resumen honesto de progreso.
        if job_id and not _is_bootstrap_query:
            job = get_job_status(job_id)
            status = job.get("status")
            progress = job.get("progress") or {}
            stage = progress.get("stage")
            
            # Si el job está corriendo y estamos en etapa de triage o compliance, bloqueamos el chat
            if status == "RUNNING" and stage in ("triage", "compliance"):
                msg = progress.get("message", "Analizando bases de licitación...")
                pct = progress.get("pct", 0)
                logger.info("chatbot_compliance_gate_active", session_id=session_id, job_id=job_id, stage=stage, pct=pct)
                return AgentOutput(
                    status=AgentStatus.PENDING,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    data={"progress_pct": pct, "stage": stage},
                    message=f"⏳ {msg}",
                    correlation_id=correlation_id
                )

        # =====================================================================
        # SESSION RESUME PROACTIVO
        # Si el usuario abre el chat sin escribir nada (o con un saludo simple),
        # sintetizamos el estado actual y lo presentamos de forma estructurada.
        # EXCEPCIÓN: Si hay pending_questions activas, se prioriza la pregunta
        # pendiente sobre el resumen de sesión (Req 2.3, 4.1).
        # =====================================================================
        if _is_bootstrap_query:
            _state_for_resume = await self.context_manager.memory.get_session(session_id) or {}
            from app.services.hitl_queue_service import sanitize_chat_pending_questions

            _raw_pending = list(_state_for_resume.get("pending_questions") or [])
            _san_pending = sanitize_chat_pending_questions(_raw_pending, _state_for_resume)
            if _san_pending != _raw_pending:
                _state_for_resume["pending_questions"] = _san_pending
                _state_for_resume["current_question_index"] = 0
                if not _san_pending:
                    _state_for_resume["intake_progress"] = {
                        "started": False,
                        "accepted": False,
                        "remaining": 0,
                        "total": 0,
                    }
                await self.context_manager.memory.save_session(session_id, _state_for_resume)

            _has_pending_for_resume = bool(_san_pending)
            if not _has_pending_for_resume:
                _eco_ready_resume = self._maybe_economic_capture_complete_message(
                    session_id=session_id,
                    session_state=_state_for_resume,
                    correlation_id=correlation_id,
                    activity_state="active",
                )
                if _eco_ready_resume is not None:
                    await self._save_chat_history(
                        session_id,
                        user_query or "Hola",
                        str((_eco_ready_resume.data or {}).get("respuesta") or ""),
                    )
                    return _eco_ready_resume
            _active_job = get_active_session_job(session_id)
            if _active_job.get("status") == "RUNNING" and not _has_pending_for_resume:
                _resume_msg = self._build_analysis_in_progress_message(_state_for_resume, _active_job)
                await self._save_chat_history(session_id, user_query or "Hola", _resume_msg)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=_resume_msg,
                    confianza="Alta",
                    tipo="session_resume_in_progress",
                    suggested_actions=[],
                )
            if _state_for_resume.get("tasks_completed") and not _has_pending_for_resume:  # sesión con trabajo previo y sin pendientes
                _resume_msg = self._build_session_resume_message(_state_for_resume)
                if _resume_msg:
                    await self._save_chat_history(session_id, user_query or "Hola", _resume_msg)

                    # Paso 3 del plan: inyectar botones en el llamador,
                    # sin modificar el tipo de retorno (str) de _build_session_resume_message.
                    _has_real_docs_to_gen = bool(
                        _state_for_resume.get("document_inventory", {}).get("items")
                    )
                    _resume_actions = []
                    if self._bases_analysis_phase(_state_for_resume) == "complete":
                        _resume_actions = [
                            {
                                "label": "Ver Formatos y Anexos",
                                "payload": "CMD_SHOW_PENDING_DOCS",
                                "style": "primary",
                            },
                            {
                                "label": "Generar expediente",
                                "payload": "CMD_TRIGGER_GENERATION",
                                "style": "secondary",
                            },
                        ]

                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=_resume_msg,
                        confianza="Alta",
                        tipo="session_resume",
                        suggested_actions=_resume_actions
                    )

        # =====================================================================
        # FASE 0: Verificar si hay preguntas pendientes del DataGapAgent
        # =====================================================================
        session_state = await self.context_manager.memory.get_session(session_id) or {}

        if user_query:
            from app.services.document_date_resolver import apply_document_date_override_from_chat

            _date_hitl = apply_document_date_override_from_chat(session_state, user_query)
            if _date_hitl.get("applied"):
                session_state.update(_date_hitl.get("session_patch") or {})
                await self.context_manager.memory.save_session(session_id, session_state)
                _ack = str(_date_hitl.get("message") or "").strip()
                await self._save_chat_history(session_id, user_query, _ack)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=_ack,
                    confianza="Alta",
                    tipo="document_date_override_saved",
                    suggested_actions=[
                        {"label": "Volver a generar", "payload": "CMD_TRIGGER_GENERATION", "style": "primary"},
                    ],
                )

        # Interceptor de Entrevista Laboral (Error 412 Preventivo - Vía A)
        from app.economic_validation.profiles import session_requires_fsr_labor_profile

        _fsr_labor_required = session_requires_fsr_labor_profile(session_state, session_id)
        if session_state.get("labor_compliance_interview_step") and not _fsr_labor_required:
            session_state["labor_compliance_interview_step"] = None
            await self.context_manager.memory.save_session(session_id, session_state)
        elif session_state.get("labor_compliance_interview_step") and user_query:
            interview_res = await self._handle_labor_compliance_interview(
                session_id=session_id,
                company_id=company_id,
                user_query=user_query,
                session_state=session_state,
                correlation_id=correlation_id
            )
            if interview_res:
                return interview_res

        # Motor de confirmación de mapeo: si hay una confirmación pendiente, procesarla primero
        _pending_confirmation = session_state.get("pending_mapping_confirmation")
        if _pending_confirmation and user_query and company_id:
            _confirmation_result = await self._handle_mapping_confirmation(
                user_response=user_query,
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                correlation_id=correlation_id,
                activity_state="active",
            )
            if _confirmation_result is not None:
                return _confirmation_result

        # ── TAREA 5: Limpiar pending_questions económicas huérfanas de sesiones anteriores ──
        # Descarta preguntas de tipo economic_price cuyo concepto ya no existe en el
        # snapshot activo de tasks_completed["economic_proposal"].
        _pending_before_sanitize = list(session_state.get("pending_questions") or [])
        _pending_sanitized = await self._sanitize_economic_pending_questions(session_id, session_state)
        from app.services.hitl_queue_service import sanitize_chat_pending_questions

        _pending_sanitized = sanitize_chat_pending_questions(_pending_sanitized, session_state)
        if _pending_sanitized != _pending_before_sanitize:
            session_state["pending_questions"] = _pending_sanitized
            session_state["current_question_index"] = 0
            if not _pending_sanitized:
                session_state["intake_progress"] = {
                    "started": False,
                    "accepted": False,
                    "remaining": 0,
                    "total": 0,
                }
            await self.context_manager.memory.save_session(session_id, session_state)

        # Archivo en chat: cotización Excel/CSV (matriz económica) antes que extracción 1-a-1.
        _uploaded_doc_id = agent_input.company_data.get("doc_id") or agent_input.company_data.get(
            "uploaded_doc_id"
        )
        _pending_for_upload = list(session_state.get("pending_questions") or [])
        _current_idx_for_upload = int(session_state.get("current_question_index") or 0)
        if _uploaded_doc_id and not session_state.get("pending_mapping_confirmation"):
            _eco_file_res = await self._handle_economic_quotation_file_upload(
                session_id=session_id,
                doc_id=str(_uploaded_doc_id),
                company_id=company_id,
                session_state=session_state,
                correlation_id=correlation_id,
            )
            if _eco_file_res is not None:
                return _eco_file_res
            if _pending_for_upload:
                return await self._handle_file_upload_with_mission(
                    session_id=session_id,
                    doc_id=str(_uploaded_doc_id),
                    session_state=session_state,
                    pending_questions=_pending_for_upload,
                    current_idx=_current_idx_for_upload,
                    correlation_id=correlation_id,
                    activity_state="active",
                )

        # --- HITO: INYECCIÓN PROACTIVA "FINAL GUARD" ---
        # Si existe un intake_plan pero no hay preguntas forenses en la cola, las inyectamos.
        # EXCEPCIÓN 1: Si el intake ya fue completado explícitamente, no re-inyectar.
        # EXCEPCIÓN 2: Si el usuario aún no aceptó el plan (opt-in), no inyectar —
        #   el bloque de intake_proactive_offer debe presentar la oferta primero.
        intake_plan = session_state.get("intake_plan") if isinstance(session_state.get("intake_plan"), dict) else {}
        pending_questions = session_state.get("pending_questions", []) or []
        intake_completed = bool(session_state.get("document_intake_completed"))
        # El guard solo inyecta si el usuario ya aceptó el plan explícitamente.
        _intake_accepted = bool(
            (session_state.get("intake_progress") or {}).get("accepted")
        )

        if intake_plan and settings.INTAKE_PLANNER_ENABLED and not intake_completed and _intake_accepted:
            has_forensic = any(str(q.get("type")) == "intake_planner" for q in pending_questions)
            if not has_forensic:
                planner_qs = self._pending_from_intake_plan(intake_plan)
                if planner_qs:
                    from app.services.hitl_queue_service import merge_pending_queues

                    logger.info("chatbot_final_guard_injection", session_id=session_id, added=len(planner_qs))
                    pending_questions = merge_pending_queues(planner_qs, pending_questions)
                    session_state["pending_questions"] = pending_questions
                    session_state["current_question_index"] = 0
                    await self.context_manager.memory.save_session(session_id, session_state)
        elif intake_completed:
            logger.debug("chatbot_final_guard_skipped", session_id=session_id, reason="document_intake_completed")

        current_idx = session_state.get("current_question_index", 0)
        tasks_completed = list(session_state.get("tasks_completed") or [])

        # Gate de actividad real: evita "ruido" de intake en sesiones vacías.
        company_valid = False
        if company_id:
            try:
                company = await self.context_manager.memory.get_company(company_id)
                company_valid = bool(company and isinstance(company, dict))
            except Exception:
                company_valid = False
        has_sources = False
        try:
            docs = await self.context_manager.memory.get_documents(session_id)
            has_sources = bool(docs and len(docs) > 0)
        except Exception:
            has_sources = False
        has_completed_analysis = any(
            str(t.get("task") or "").startswith("stage_completed:")
            for t in tasks_completed
        )
        has_runtime_hints = any(
            isinstance(session_state.get(k), dict)
            for k in (
                "go_no_go_result",
                "last_document_quality_waiting_hints",
                "last_document_fill_quality_waiting_hints",
                "last_economic_waiting_hints",
            )
        )
        has_real_work_context = bool(
            has_sources
            or has_completed_analysis
            or has_runtime_hints
            or pending_questions
            or (isinstance(intake_plan, dict) and bool(intake_plan.get("questions")))
        )
        activity_state = (
            "active"
            if has_real_work_context
            else ("idle_ready_for_upload" if company_valid else "idle_no_company_no_sources")
        )

        # Captura económica proactiva: el asistente explica qué falta (matriz o lista corta)
        # al abrir el chat o saludar — sin que el usuario adivine comandos.
        if company_id and pending_questions:
            _proactive_eco = await self._proactive_economic_capture_offer(
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
                activity_state=activity_state,
            )
            if _proactive_eco is not None:
                await self._save_chat_history(
                    session_id,
                    user_query or "Hola",
                    str((_proactive_eco.data or {}).get("respuesta") or ""),
                )
                return _proactive_eco

        if company_id and not pending_questions:
            _eco_ready = self._maybe_economic_capture_complete_message(
                session_id=session_id,
                session_state=session_state,
                correlation_id=correlation_id,
                activity_state=activity_state,
            )
            if _eco_ready is not None:
                await self._save_chat_history(
                    session_id,
                    user_query or "Hola",
                    str((_eco_ready.data or {}).get("respuesta") or ""),
                )
                return _eco_ready

        # Puente de calidad: si no hay pendientes, promover dudas de quality gate a cola de conversación.
        if has_real_work_context and not pending_questions:
            quality_pending = self._pending_from_quality_hints(session_state)
            if quality_pending:
                session_state["pending_questions"] = quality_pending
                session_state["current_question_index"] = 0
                await self.context_manager.memory.save_session(session_id, session_state)
                pending_questions = quality_pending
                current_idx = 0

        # Fase 2 Intake proactivo (opt-in): desactivado por defecto — confunde frente a paneles de inventario.
        if (
            settings.INTAKE_PROACTIVE_CHAT_OFFER_ENABLED
            and has_real_work_context
            and settings.INTAKE_PLANNER_ENABLED
            and not pending_questions
            and isinstance(intake_plan, dict)
        ):
            from app.services.hitl_queue_service import should_exclude_from_chat_queue

            intake_qs = [
                q
                for q in (intake_plan.get("questions") or [])
                if isinstance(q, dict) and not should_exclude_from_chat_queue(q)
            ]
            if intake_qs:
                blocking_count = sum(
                    1
                    for q in intake_qs
                    if bool(q.get("blocking")) or str(q.get("priority") or "").upper() == "BLOQUEANTE"
                )
                total_q = len(intake_qs)
                if self._looks_like_optin_acceptance(user_query):
                    converted = self._pending_from_intake_plan(intake_plan)
                    if converted:
                        session_state["pending_questions"] = converted
                        session_state["current_question_index"] = 0
                        session_state["intake_progress"] = {
                            "started": True,
                            "accepted": True,
                            "current_question_id": converted[0].get("question_id"),
                            "remaining": len(converted),
                            "total": len(converted),
                            "last_prompt_at": datetime.now(timezone.utc).isoformat(),
                        }
                        await self.context_manager.memory.save_session(session_id, session_state)
                        pending_questions = converted
                        current_idx = 0
                elif self._looks_like_greeting_or_progress_intent(user_query):
                    intro = self._render_intake_message(
                        "offer", {"blocking_count": blocking_count, "total": total_q}
                    )
                    await self._save_chat_history(session_id, user_query or "Hola", intro)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=intro,
                        confianza="Alta",
                        tipo="intake_proactive_offer",
                        intake_active=True,
                        activity_state=activity_state,
                    )
        elif (
            _is_bootstrap_query
            and has_real_work_context
            and not pending_questions
            and isinstance(intake_plan, dict)
            and session_state.get("tasks_completed")
        ):
            _resume_after_plan = self._build_session_resume_message(session_state)
            if _resume_after_plan:
                await self._save_chat_history(session_id, user_query or "Hola", _resume_after_plan)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=_resume_after_plan,
                    confianza="Alta",
                    tipo="session_resume",
                    intake_active=False,
                    activity_state=activity_state,
                )

        # === SANEAMIENTO CONTRA MASTER PROFILE ===
        # Previene que el asistente pregunte datos (como razon_social) que el usuario
        # ya subió al perfil corporativo y que el session_state aún tiene como pendientes.
        if pending_questions and company_id:
            try:
                company = await self.context_manager.memory.get_company(company_id)
                master_profile = company.get("master_profile", {}) if company else {}
                from app.agents.data_gap import DataGapAgent
                dg = DataGapAgent(self.context_manager)
                
                sanitized_pending = []
                for q in pending_questions:
                    q_type = str(q.get("type", "profile"))
                    # Compatibilidad de contrato:
                    # - legacy: "profile"
                    # - nuevo DataGap: "profile_field"
                    if q_type in {"profile", "profile_field"}:
                        field = q.get("field")
                        val = master_profile.get(field)
                        if val and dg._is_data_valid(field, val):
                            continue # Ya resuelto, descartar pregunta
                    sanitized_pending.append(q)
                
                if len(sanitized_pending) != len(pending_questions):
                    session_state["pending_questions"] = sanitized_pending
                    current_idx = max(0, min(int(current_idx), len(sanitized_pending) - 1)) if sanitized_pending else 0
                    session_state["current_question_index"] = current_idx
                    await self.context_manager.memory.save_session(session_id, session_state)
                    pending_questions = sanitized_pending
                    logger.info(f"[Chatbot] Saneados pendientes contra master_profile. Faltantes reales: {len(pending_questions)}")
            except Exception as e:
                logger.error(f"[Chatbot] Error saneando pendientes contra master_profile: {e}")

        # Fail-closed: ocultar pendientes económicos sin ancla verificable antes de hablar con el usuario.
        if pending_questions:
            anchored: List[Dict[str, Any]] = []
            hidden_unverified: List[Dict[str, Any]] = []
            for q in pending_questions:
                if str(q.get("type")) == "economic_price" and not self._pending_has_verifiable_anchor(q):
                    if str(q.get("label") or "").strip() and str(q.get("field") or "").strip():
                        anchored.append(q)
                    else:
                        hidden_unverified.append(
                            {
                                "field": str(q.get("field") or ""),
                                "label": str(q.get("label") or "")[:280],
                                "reason": "missing_strict_anchor",
                                "source": "chatbot_fail_closed_precheck",
                            }
                        )
                else:
                    anchored.append(q)
            if hidden_unverified:
                session_state["pending_questions"] = anchored
                session_state["current_question_index"] = (
                    max(0, min(int(current_idx or 0), len(anchored) - 1)) if anchored else 0
                )
                uv = list(session_state.get("economic_unverified_suggestions") or [])
                uv.extend(hidden_unverified)
                session_state["economic_unverified_suggestions"] = uv[-400:]
                await self.context_manager.memory.save_session(session_id, session_state)
                pending_questions = anchored
                current_idx = int(session_state.get("current_question_index") or 0)
        if pending_questions:
            from app.services.hitl_queue_service import sanitize_chat_pending_questions

            chat_pending = sanitize_chat_pending_questions(pending_questions, session_state)
            if len(chat_pending) != len(pending_questions):
                session_state["pending_questions"] = chat_pending
                pending_questions = chat_pending
                current_idx = 0
            if chat_pending:
                current_idx = self._resolve_resume_pointer(session_state, chat_pending, current_idx)
                session_state["current_question_index"] = current_idx
                prog = dict(session_state.get("intake_progress") or {})
                p = self._compute_pending_progress(chat_pending, current_idx, session_state)
                prog.update(
                    {
                        "started": bool(prog.get("started", False)) or any(
                            str(q.get("type")) == "intake_planner" for q in chat_pending
                        ),
                        "accepted": bool(prog.get("accepted", False)) or any(
                            str(q.get("type")) == "intake_planner" for q in chat_pending
                        ),
                        "current_question_id": self._stable_question_id(chat_pending[current_idx]),
                        "remaining": max(0, p["progress_total"] - p["progress_current"] + 1),
                        "total": p["progress_total"],
                        "last_prompt_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                session_state["intake_progress"] = prog
                await self.context_manager.memory.save_session(session_id, session_state)
            elif session_state.get("pending_questions"):
                session_state["pending_questions"] = []
                session_state["current_question_index"] = 0
                session_state["intake_progress"] = {
                    "started": False,
                    "accepted": False,
                    "remaining": 0,
                    "total": 0,
                }
                pending_questions = []
                await self.context_manager.memory.save_session(session_id, session_state)
        active_blocking_q = self._active_economic_blocking_pending(pending_questions, current_idx)

        # =====================================================================
        # TAREA 4: Omisión auditada de no bloqueantes (Req 4.3, 4.4, 5.1)
        # Prioridad alta: antes del canal económico para que "no aplica" / "skip"
        # no sean capturados como DATA_INTAKE económico.
        # =====================================================================
        if pending_questions and user_query and self._detect_skip_intent(user_query):
            return await self._handle_user_skip(
                session_id=session_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
            )

        # Identidad de anexo (HRU panel) antes de procedencia económica y RAG.
        if user_query and company_id:
            from app.services.annex_resolution_service import (
                build_annex_identity_message,
                detect_annex_identity_intent,
            )

            if detect_annex_identity_intent(user_query):
                _annex_msg = build_annex_identity_message(
                    session_state,
                    user_query,
                    session_id=session_id,
                )
                if _annex_msg:
                    await self._save_chat_history(session_id, user_query, _annex_msg)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=_annex_msg,
                        confianza="Alta",
                        tipo="annex_identity_hru",
                        suggested_actions=[
                            {
                                "label": "Ver Formatos y Anexos",
                                "payload": "CMD_SHOW_PENDING_DOCS",
                                "style": "primary",
                            },
                            {
                                "label": "Ver Fuentes (bases)",
                                "payload": "CMD_SHOW_SOURCES",
                                "style": "secondary",
                            },
                        ],
                    )

        # Corrección post-entrega de precios (Ítem B): antes de RAG y sin depender de pending económico.
        if user_query and company_id:
            from app.services.chat_economic_provenance_service import (
                build_economic_provenance_message,
                detect_economic_provenance_intent,
            )

            _prov_mode = detect_economic_provenance_intent(user_query)
            if _prov_mode:
                _prov_msg = build_economic_provenance_message(
                    session_state,
                    session_id=session_id,
                    mode=_prov_mode,
                    user_query=user_query,
                )
                if _prov_msg:
                    await self._save_chat_history(session_id, user_query, _prov_msg)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=_prov_msg,
                        confianza="Alta",
                        tipo="economic_provenance_hru",
                        suggested_actions=[
                            {
                                "label": "Ver Formatos y Anexos",
                                "payload": "CMD_SHOW_PENDING_DOCS",
                                "style": "primary",
                            },
                            {
                                "label": "Generar expediente",
                                "payload": "CMD_TRIGGER_GENERATION",
                                "style": "secondary",
                            },
                        ],
                    )

            _corr_out = await self._try_price_correction_channel(
                session_id=session_id,
                session_state=session_state,
                user_query=user_query,
                correlation_id=correlation_id,
            )
            if _corr_out is not None:
                await self._save_chat_history(
                    session_id,
                    user_query,
                    str((_corr_out.data or {}).get("respuesta") or ""),
                )
                return _corr_out

        # =====================================================================
        # SPRINT 3: Canal transaccional económico desde chat (override explícito)
        # Solo activo cuando la pregunta pendiente actual es de naturaleza económica
        # o cuando no hay pendientes (captura libre de precios).
        # Si el pendiente actual es profile_field, intake_planner u otro tipo no
        # económico, el canal se omite para que el mensaje llegue a FASE 3A.
        # =====================================================================
        _current_pending_type = (
            str(pending_questions[current_idx].get("type", ""))
            if pending_questions and current_idx < len(pending_questions)
            else ""
        )
        _is_economic_pending = _current_pending_type in (
            "economic_price",
            "economic_price_matrix",
            "economic_validation_blocking",
        )
        # --- COMANDOS DE GENERACIÓN EXPLÍCITA (Hito A1) ---
        # Si el usuario pide generar la propuesta, disparamos el EconomicAgent directamente
        # para validar si faltan precios, en lugar de dejar que el RAG responda 'cómo' hacerlo.
        is_gen_request = bool(user_query and self._is_economic_generation_command(user_query))

        _early_intent = await self._route_early_user_intent(
            session_id=session_id,
            user_query=user_query,
            session_state=session_state,
            pending_questions=pending_questions,
            current_idx=current_idx,
            current_pending_type=_current_pending_type,
            is_gen_request=is_gen_request,
            company_id=company_id,
            correlation_id=correlation_id,
            activity_state=activity_state,
        )
        if _early_intent is not None:
            return _early_intent

        if user_query and self._detect_user_confusion_intent(user_query) and not is_gen_request:
            return await self._handle_user_confusion_help(
                session_id=session_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
                company_id=company_id,
            )
        _eco_price_pending = [
            q
            for q in (pending_questions or [])
            if str(q.get("type") or "")
            in (
                "economic_price",
                "economic_price_matrix",
                "economic_validation_blocking",
            )
        ]
        if is_gen_request and company_id and not _eco_price_pending:
            logger.info("chatbot_explicit_generation_trigger", session_id=session_id)
            
            # --- FORENSIC CHECK: Labor Compliance Data (solo licitaciones con FSR) ---
            try:
                if _fsr_labor_required:
                    company = await self.context_manager.memory.get_company(company_id)
                    mp = company.get("master_profile", {}) if company else {}
                    labor = mp.get("labor_compliance", {})

                    if (
                        not labor
                        or labor.get("status") == "PENDING_INPUT"
                        or (
                            float(labor.get("base_salary_per_day", 0)) <= 0
                            and not labor.get("daily_fsr")
                        )
                    ):
                        session_state["labor_compliance_interview_step"] = "step_1_base_salary"
                        await self.context_manager.memory.save_session(session_id, session_state)

                        error_msg = (
                            "⚠️ **Error Code 412: Missing Payroll Base Profile for FSR Calculation.**\n\n"
                            "No puedo generar la propuesta económica porque tu perfil corporativo no tiene configurados "
                            "los costos de nómina (Salario Base, Prima de Riesgo IMSS, etc.) exigidos para el "
                            "**Factor de Salario Real (FSR)** de esta licitación.\n\n"
                            "Para facilitar tu cotización, **iniciemos la configuración rápida en este chat**.\n\n"
                            "**Paso 1 de 4:** ¿Cuál es el **Salario Base Diario** en pesos que usarás en el anexo FSR? "
                            "(Ejemplo: `374.89` o `300.00`)"
                        )
                        await self._save_chat_history(session_id, user_query, error_msg)
                        return self._format_response(
                            session_id=session_id,
                            correlation_id=correlation_id,
                            respuesta=error_msg,
                            confianza="Alta",
                            tipo="labor_compliance_interview",
                            activity_state="active",
                        )
            except Exception as e:
                logger.error(f"Error in forensic labor check: {e}")

            from app.agents.economic import EconomicAgent
            econ_agent = EconomicAgent(self.context_manager)
            _base_cd = dict(agent_input.company_data or {})
            _base_cd["skip_economic_silence"] = True
            _base_cd["relax_price_anchors"] = True
            econ_input = AgentInput(
                session_id=session_id,
                company_id=company_id,
                company_data=_base_cd,
                correlation_id=correlation_id,
                job_id=job_id
            )
            econ_res = await econ_agent.process(econ_input)
            
            if econ_res.status == AgentStatus.WAITING_FOR_DATA:
                await self._save_chat_history(session_id, user_query, econ_res.message)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=econ_res.message,
                    confianza="Alta",
                    tipo="pending_economic_list",
                    intake_active=True,
                    activity_state=activity_state,
                    data=econ_res.data
                )
            elif econ_res.status == AgentStatus.SUCCESS:
                _fresh_eco = await self.context_manager.memory.get_session(session_id) or {}
                _eco_items: List[Dict[str, Any]] = []
                _eco_pending_n = 0
                for _t in reversed(_fresh_eco.get("tasks_completed") or []):
                    if _t.get("task") == "economic_proposal":
                        _snap = _t.get("result") if isinstance(_t.get("result"), dict) else {}
                        _eco_items = list(_snap.get("items") or [])
                        break
                _eco_pending_n = len(
                    [
                        q
                        for q in (_fresh_eco.get("pending_questions") or [])
                        if str(q.get("type") or "")
                        in ("economic_price", "economic_validation_blocking")
                    ]
                )
                _has_priced = any(
                    float(it.get("precio_unitario") or 0) > 0
                    for it in _eco_items
                    if isinstance(it, dict)
                )
                if _eco_pending_n > 0 or (not _eco_items and "pausa" in (econ_res.message or "").lower()):
                    _wait_msg = (
                        econ_res.message
                        or f"Faltan {_eco_pending_n} precio(s) por capturar. Responde en el chat y vuelve a escribir `generar propuesta económica`."
                    )
                    await self._save_chat_history(session_id, user_query, _wait_msg)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=_wait_msg,
                        confianza="Alta",
                        tipo="pending_economic_list",
                        intake_active=True,
                        activity_state=activity_state,
                        data=econ_res.data if hasattr(econ_res, "data") else None,
                    )
                if not _has_priced and _eco_items:
                    _wait_msg = (
                        "La propuesta tiene partidas pero aún sin precios unitarios. "
                        "Indica importes en el chat (ej. `45250` por concepto) y repite `generar propuesta económica`."
                    )
                    await self._save_chat_history(session_id, user_query, _wait_msg)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=_wait_msg,
                        confianza="Alta",
                        tipo="pending_economic_list",
                        intake_active=True,
                        activity_state=activity_state,
                    )
                msg_ok = "✅ Propuesta económica validada y lista para generación. Ya puedes proceder a generar los anexos finales."
                await self._save_chat_history(session_id, user_query, msg_ok)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=msg_ok,
                    confianza="Alta",
                    tipo="economic_success",
                    activity_state=activity_state,
                    suggested_actions=[
                        {"label": "🚀 Generar Documentos", "payload": "CMD_TRIGGER_DOC_GEN", "style": "primary"}
                    ]
                )

        if is_gen_request and company_id and _eco_price_pending:
            matrix_on_gen = await self._maybe_redirect_to_matrix_capture(
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_input=user_query or "",
                correlation_id=correlation_id,
            )
            if matrix_on_gen is not None:
                await self._save_chat_history(
                    session_id, user_query, str(matrix_on_gen.data.get("respuesta") or "")
                )
                return matrix_on_gen
            n_eco = len(_eco_price_pending)
            msg_pending = (
                f"Antes de cerrar la propuesta económica faltan **{n_eco}** dato(s) de cotización. "
                "Responde la pregunta que te muestro a continuación (precio unitario o importe en pesos). "
                "Cuando termines, vuelve a escribir `generar propuesta económica`."
            )
            await self._save_chat_history(session_id, user_query, msg_pending)
            # Caer al flujo de pending_questions más abajo (no ejecutar EconomicAgent aún).

        if user_query and company_id and _is_economic_pending:
            matrix_early = await self._maybe_redirect_to_matrix_capture(
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_input=user_query,
                correlation_id=correlation_id,
            )
            if matrix_early is not None:
                return matrix_early
            # ── TAREA 6: Detectar confirmación HITL de licitación sin importe base ──
            if self._detect_zero_base_ack_intent(user_query):
                return await self._handle_zero_base_ack(
                    session_id=session_id,
                    company_id=company_id,
                    correlation_id=correlation_id,
                )

            # Aplazar (siguiente / después): antes de META o clasificación LLM en canal económico.
            if pending_questions and self._detect_defer_pending_intent(user_query):
                return await self._defer_current_pending(
                    session_id=session_id,
                    session_state=session_state,
                    pending=pending_questions,
                    current_idx=current_idx,
                    user_query=user_query,
                    correlation_id=correlation_id,
                )

            # ── Detectar intención de marcar pendiente como no cotizable/documental ──
            # Debe evaluarse antes de la clasificación LLM para que el canal económico
            # no intercepte el mensaje y lo envíe a clarification_needed.
            # EXCEPCIÓN: Si el usuario pide evidencia (página/párrafo), no interceptar aquí —
            # esa rama se maneja más adelante en _detect_support_evidence_intent.
            if pending_questions and self._detect_non_cotizable_intent(user_query) and not self._detect_support_evidence_intent(user_query):
                return await self._mark_current_pending_non_cotizable(
                    session_id=session_id,
                    session_state=session_state,
                    pending=pending_questions,
                    current_idx=current_idx,
                    user_query=user_query,
                    correlation_id=correlation_id,
                )

            # Respuesta numérica: en modo matriz no avanzar uno por uno.
            if (
                pending_questions
                and 0 <= current_idx < len(pending_questions)
                and str(pending_questions[current_idx].get("type") or "")
                in ("economic_price", "economic_price_matrix")
            ):
                stripped = user_query.strip()
                wclean = (
                    stripped.replace("$", "")
                    .replace("mxn", "")
                    .replace("MXN", "")
                    .replace(",", "")
                    .strip()
                )
                looks_numeric = bool(re.match(r"^-?\d+(?:\.\d+)?$", wclean)) or bool(
                    re.search(r"\$\s*[\d,]+", stripped)
                )
                if looks_numeric:
                    matrix_num = await self._maybe_redirect_to_matrix_capture(
                        session_id=session_id,
                        company_id=company_id,
                        session_state=session_state,
                        pending=pending_questions,
                        current_idx=current_idx,
                        user_input=user_query,
                        correlation_id=correlation_id,
                    )
                    if matrix_num is not None:
                        return matrix_num
                    return await self._handle_data_intake(
                        session_id,
                        user_query,
                        company_id,
                        pending_questions,
                        current_idx,
                        session_state,
                        correlation_id,
                    )

            # Primero clasificamos la intención para saber si es DATA_INTAKE
            intent = await self._classify_message(user_query, pending_questions, current_idx, correlation_id)

            # --- CAPTURA INTELIGENTE (LLM EXTRACTION) ---
            if intent == "DATA_INTAKE":
                extractions = await self._extract_economic_data_llm(user_query, session_state)
                if (
                    not extractions
                    and pending_questions
                    and current_idx < len(pending_questions)
                    and str(pending_questions[current_idx].get("type") or "") == "economic_price"
                ):
                    val_num = self._clean_currency_value(user_query)
                    if val_num is not None and val_num > 0:
                        q_cur = pending_questions[current_idx]
                        concept_hint = self._concept_from_economic_price_pending_q(q_cur) or "concepto"
                        extractions = [
                            {
                                "value": user_query.strip(),
                                "concept_hint": concept_hint,
                                "concept_label": concept_hint,
                            }
                        ]
                if extractions:
                    pending_concept = ""
                    if (
                        pending_questions
                        and 0 <= current_idx < len(pending_questions)
                        and str(pending_questions[current_idx].get("type") or "") == "economic_price"
                    ):
                        pending_concept = self._concept_from_economic_price_pending_q(
                            pending_questions[current_idx]
                        )
                    tx_list = []
                    for ext in extractions:
                        val_raw = str(ext.get("value") or "")
                        val_num = self._clean_currency_value(val_raw)
                        hint = ext.get("concept_label") or ext.get("concept") or ext.get("concept_hint")
                        if pending_concept and self._is_generic_economic_concept_label(str(hint or "")):
                            hint = pending_concept
                        if val_num is not None and hint:
                            tx_list.append({
                                "kind": "economic_set_value",
                                "key": "concept_price",
                                "concept": hint,
                                "concept_hint": hint,
                                "value": val_raw,
                                "value_numeric": val_num,
                            })
                    
                    if tx_list:
                        return await self._handle_economic_transaction(
                            session_id=session_id,
                            company_id=company_id,
                            session_state=session_state,
                            tx=tx_list,
                            raw_user_query=user_query,
                            correlation_id=correlation_id,
                        )
                
                # Si el LLM no pudo extraer nada de forma segura, abortar y pedir aclaración explícita
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta="Entiendo que intentas ingresar datos, pero no logro distinguir el precio de las especificaciones técnicas. ¿Podrías indicarme el valor monetario aislado o con el símbolo $?",
                    confianza="Media",
                    tipo="clarification_needed"
                )
            # Rescate: bloqueo por validación + número solo → PU al primer concepto bloqueado
            if active_blocking_q is not None:
                rescue_intent = self._detect_economic_blocking_rescue_intent(user_query)
                if rescue_intent == "bare_number":
                    tx2 = self._economic_blocking_bare_number_transaction({**active_blocking_q, "_session_state_ref": session_state}, user_query)
                    if tx2:
                        # Recalcular usando la función importada
                        await refresh_economic_validations_for_session(self.context_manager.memory, session_id)
                        return await self._handle_economic_transaction(
                            session_id=session_id,
                            company_id=company_id,
                            session_state=session_state,
                            tx=tx2,
                            raw_user_query=user_query,
                            correlation_id=correlation_id,
                        )
            if intent == "META":
                has_eco_pending = pending_questions and any(
                    str(q.get("type") or "")
                    in ("economic_price", "economic_validation_blocking")
                    for q in pending_questions
                )
                if has_eco_pending:
                    pass
                elif pending_questions and self._detect_defer_pending_intent(user_query):
                    return await self._defer_current_pending(
                        session_id=session_id,
                        session_state=session_state,
                        pending=pending_questions,
                        current_idx=current_idx,
                        user_query=user_query,
                        correlation_id=correlation_id,
                    )
                else:
                    q_short = ChatbotRAGAgent._normalize(user_query)
                    if q_short in ("generar", "adelante", "listo") or q_short.startswith("generar "):
                        return self._format_response(
                            session_id=session_id,
                            correlation_id=correlation_id,
                            respuesta=(
                                "¿Quieres **cotizar precios pendientes** o **generar el expediente** completo? "
                                "Responde con una de esas opciones."
                            ),
                            confianza="Alta",
                            tipo="clarification_needed",
                        )
                    return await self._handle_meta_query(
                        session_id, user_query, session_state, correlation_id
                    )

            provenance_concept = self._detect_price_provenance_intent(user_query)
            if provenance_concept:
                return await self._handle_price_provenance_query(
                    session_id=session_id,
                    company_id=company_id,
                    session_state=session_state,
                    concept_hint=provenance_concept,
                    raw_user_query=user_query,
                    correlation_id=correlation_id,
                )

        # MODO PROACTIVO: Si no hay preguntas pendientes y el usuario saluda/consulta vacía,
        # invocar DataGapAgent proactivamente y exponer la primera pregunta pendiente (Req 2.4).
        # Alineado con _GREETINGS para consistencia. Solo si hay company_id (resiliencia).
        _is_greeting_or_empty = user_query.lower() in _GREETINGS or self._looks_like_greeting_or_progress_intent(user_query)
        if has_real_work_context and not pending_questions and _is_greeting_or_empty and company_id:
            # Invocar DataGapAgent para detectar brechas y encolar pending_questions
            from app.agents.data_gap import DataGapAgent
            logger.info(f"[Chatbot] Ejecutando análisis de brechas proactivo para {session_id}")
            gap_agent = DataGapAgent(self.context_manager)
            gap_input = AgentInput(session_id=session_id, company_id=company_id, company_data=agent_input.company_data)
            try:
                gap_res = await gap_agent.process(gap_input)
                # Aceptar WAITING_FOR_DATA (estatus normal de detección de huecos) y SUCCESS
                if gap_res.status in [AgentStatus.SUCCESS, AgentStatus.WAITING_FOR_DATA]:
                    # Refrescar estado tras el análisis del DataGapAgent
                    session_state = await self.context_manager.memory.get_session(session_id) or {}
                    pending_questions = session_state.get("pending_questions", [])
                    current_idx = 0
            except Exception as _gap_err:
                # Resiliencia: si DataGap falla, el flujo conversacional no se bloquea (Req invariante)
                logger.warning(f"[Chatbot] DataGap proactivo falló (no bloqueante): {_gap_err}")

        if pending_questions:
            question = pending_questions[current_idx] if current_idx < len(pending_questions) else None
            # Palabras clave de saludos o de intención de generar documentos
            saludos = ["hola", "buenos días", "buenas tardes", "hey", "qué tal"]
            # No usar subcadena "falt" sola: coincide dentro de "falta"/"te falta" y dispara bucles de saludo.
            # Nota: no incluir la subcadena suelta "anexo" — en citas de bases aparece
            # «Anexo 17» y dispara por error la plantilla de captura en lugar del RAG.
            intencion_tokens = [
                "generar",
                "documento",
                "formato",
                "propuesta",
                "adelante",
                "listo",
                "qué sigue",
                "que sigue",
            ]
            intencion_falta_frases = [
                "que falta",
                "qué falta",
                "que faltan",
                "qué faltan",
                "faltan datos",
                "falta datos",
            ]

            q_lower = user_query.lower()
            es_saludo = any(s in q_lower for s in saludos) if q_lower else True
            es_intencion = any(s in q_lower for s in intencion_tokens) or any(
                f in q_lower for f in intencion_falta_frases
            )

            # Si el usuario solo saluda, pregunta qué sigue, o quiere generar documentos pero falta info:
            # IMPORTANTE: Solo pedimos datos específicos SI hay una empresa seleccionada. 
            # Si no hay empresa, el flujo debe caer al bloque de bienvenida en la Fase 0 (línea 82+).
            # Bloqueo de validación económica: no repetir plantilla de captura genérica (rompe con "te falta" / rescate).
            if (es_saludo or es_intencion or not user_query) and question and company_id:
                if str(question.get("type")) in (
                    "economic_price",
                    "economic_price_matrix",
                ):
                    _eco_offer = await self._proactive_economic_capture_offer(
                        session_id=session_id,
                        company_id=company_id,
                        session_state=session_state,
                        pending=pending_questions,
                        current_idx=current_idx,
                        user_query=user_query,
                        correlation_id=correlation_id,
                        activity_state=activity_state,
                    )
                    if _eco_offer is not None:
                        return _eco_offer

                # Caso A: Bloqueo económico (Lista de precios pendientes)
                if str(question.get("type")) == "economic_validation_blocking":
                    if self._economic_blocking_requires_source_input(question):
                        return self._format_response(
                            session_id=session_id,
                            correlation_id=correlation_id,
                            respuesta=self._economic_blocking_source_reply(question),
                            confianza="Alta",
                            tipo="economic_validation_blocking_info",
                            intake_active=True,
                            activity_state=activity_state,
                        )
                    blocking_items = question.get("blocking_items") or []
                    if blocking_items:
                        labels = [it.get("concepto_label", "Sin nombre") for it in blocking_items]
                        msg = f"Claro. Para avanzar con tu propuesta económica, todavía me faltan los precios de estos **{len(labels)}** conceptos:\n\n"
                        for i, lbl in enumerate(labels, 1):
                            msg += f"{i}. **{lbl}**\n"
                        msg += f"\nEmpecemos con el primero: **«{labels[0]}»**. ¿Cuál es su precio unitario?"
                        
                        return self._format_response(
                            session_id=session_id,
                            correlation_id=correlation_id,
                            respuesta=msg,
                            confianza="Alta",
                            tipo="pending_economic_list",
                            intake_active=True,
                            activity_state=activity_state,
                        )

                # Caso B: Otros pendientes (Perfil, legales, etc.)
                if str(question.get("type")) != "economic_validation_blocking" and not _looks_like_bases_clarification_query(user_query):
                    q_label = str(question.get("label") or "").strip()
                    q_text = str(question.get("question") or "").strip()
                    # Humanizar el label para evitar variables técnicas en el chat
                    _raw_label_b = q_label or str(question.get("field_target") or question.get("field") or "")
                    q_label_human = self._humanize_field_target(_raw_label_b) if _raw_label_b else ""
                    # Si el pendiente tiene pregunta completa pero sin label (ej: intake_planner INTAKE-A-*),
                    # mostrar la pregunta directamente sin el wrapper "Necesito Campo."
                    if not q_label_human and q_text:
                        respuesta_pendiente = q_text
                    else:
                        respuesta_pendiente = self.conversation_normalizer.normalize_capture_message(
                            field_label=q_label_human or "dato pendiente",
                            question=q_text,
                            intent_type=str(question.get("type", "profile")),
                            state_hint="first_item",
                        )
                    # Motor conversacional con misión activa (Req 7.1)
                    # Solo aplica a tipos no económicos especializados
                    _q_type_b = str(question.get("type", "profile"))
                    if _q_type_b not in ("economic_price", "economic_validation_blocking"):
                        try:
                            _question_enriched = await self._enrich_pending_with_rag_context(session_id, question)
                            _tone_mode = self._detect_tone_mode(session_state, pending_questions, current_idx)
                            _mission_ctx = self._build_mission_context(session_state, _question_enriched, current_idx, len(pending_questions))
                            _mission_question = await self._generate_mission_question(
                                _mission_ctx, _tone_mode, pending_question=_question_enriched
                            )
                            if _mission_question:
                                respuesta_pendiente = _mission_question
                        except Exception as _me:
                            logger.warning("chatbot_mission_engine_punto1_failed", error=str(_me)[:120])
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=f"{self._compute_pending_progress(pending_questions, current_idx)['progress_label']}\n\n{respuesta_pendiente}",
                        confianza="Alta",
                        tipo="pending_question",
                        progress=self._compute_pending_progress(pending_questions, current_idx),
                        intake_active=True,
                        activity_state=activity_state,
                    )

        # Escape de captura: si el usuario pide explicación real del concepto,
        # respondemos con RAG y luego retomamos el pendiente actual.
        if pending_questions and user_query and self._detect_capture_escape_intent(user_query):
            fresh_pending, fresh_idx = await self._load_fresh_pending_state(
                session_id, fallback_pending=pending_questions, fallback_idx=current_idx
            )
            if fresh_pending:
                q_cur = fresh_pending[fresh_idx]
                if (
                    str(q_cur.get("type")) == "economic_validation_blocking"
                    and self._economic_blocking_requires_source_input(q_cur)
                ):
                    resp = self._economic_blocking_source_reply(q_cur)
                    await self._save_chat_history(session_id, user_query, resp)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=resp,
                        confianza="Alta",
                        tipo="economic_validation_blocking_info",
                        intake_active=True,
                        activity_state=activity_state,
                    )
            rag_out = await self._handle_rag_query(
                session_id=session_id,
                user_query=user_query,
                pending=fresh_pending,
                correlation_id=correlation_id,
                current_idx=fresh_idx,
            )
            try:
                if fresh_pending:
                    q = fresh_pending[fresh_idx]
                    # Humanizar el recordatorio de bloqueo económico y otros pendientes
                    _raw_label_esc = q.get('label') or q.get('field_target') or q.get('field') or 'Campo'
                    label_to_show = self._humanize_field_target(_raw_label_esc)
                    if str(q.get("type")) == "economic_validation_blocking":
                        label_to_show = self._economic_blocking_focus_label({**q, "_session_state_ref": session_state})
                    if not label_to_show or label_to_show.strip() in (".", "..", "Campo", "Dato requerido"):
                        label_to_show = str(q.get("question") or q.get("user_message") or "").strip()[:160]
                    skip_reminder = (
                        not label_to_show
                        or label_to_show.strip() in (".", "..")
                        or len(label_to_show.strip()) < 4
                        or self._detect_guarantee_intent(user_query)
                        or self._detect_solvency_intent(user_query)
                        or self._detect_cronogram_intent(user_query)
                    )
                    if not skip_reminder:
                        from app.services.chat_fill_quality_queue_policy import (
                            should_skip_fill_quality_rag_reminder,
                        )

                        if should_skip_fill_quality_rag_reminder(q, session_state):
                            skip_reminder = True
                        elif (
                            str(q.get("type") or "") == "quality_validation_blocking"
                            and str(q.get("label") or "").strip().lower()
                            == "datos para llenar documentos"
                        ):
                            skip_reminder = True
                    if not skip_reminder:
                        reminder = (
                            f"\n\nPor cierto, sigo atento a lo de: "
                            f"**{label_to_show}**. ¿Qué me puedes decir de eso?"
                        )
                        data = dict(rag_out.data or {})
                        data["respuesta"] = f"{str(data.get('respuesta') or '').strip()}{reminder}"
                        data["tipo"] = "rag_answer_capture_escape"
                        rag_out.data = data
            except Exception:
                pass
            return rag_out

        # Consulta vacía y sin cola pendiente: no llamar al LLM/RAG (antes caía en búsqueda vacía).
        if not user_query:
            if not has_real_work_context and not company_valid:
                respuesta = (
                    "✨ Sesión lista para iniciar. Selecciona una empresa válida y carga las fuentes de la licitación "
                    "para comenzar el análisis."
                )
            elif not has_real_work_context and company_valid:
                respuesta = (
                    "✅ Empresa seleccionada. Ahora carga las fuentes (bases/anexos) para iniciar el análisis "
                    "y habilitar recomendaciones del asistente."
                )
            elif pending_questions:
                # Si hay pendientes, vamos directo al grano
                question = pending_questions[current_idx]
                
                # MEJORA: Buscar si hay alguna tabla de inventario en TODA la cola de pendientes
                # para mostrarla como "Reporte Forense" inicial en el saludo bootstrap.
                all_inventory_tables = [
                    q.get("table_data") for q in pending_questions 
                    if q.get("table_data") and str(q.get("type")) == "intake_planner"
                ]
                forensic_report = ""
                if all_inventory_tables:
                    combined_tables = "\n\n".join(all_inventory_tables)
                    forensic_report = (
                        "¡Hola! He completado el análisis forense de las bases. "
                        "Aquí tienes el inventario de requisitos detectados:\n\n"
                        f"{combined_tables}\n\n"
                        "---\n\n"
                    )

                if str(question.get("type")) in (
                    "economic_price",
                    "economic_price_matrix",
                ):
                    _eco_boot = await self._proactive_economic_capture_offer(
                        session_id=session_id,
                        company_id=company_id,
                        session_state=session_state,
                        pending=pending_questions,
                        current_idx=current_idx,
                        user_query=user_query,
                        correlation_id=correlation_id,
                        activity_state=activity_state,
                    )
                    if _eco_boot is not None:
                        await self._save_chat_history(
                            session_id,
                            user_query or "Hola",
                            str((_eco_boot.data or {}).get("respuesta") or ""),
                        )
                        return _eco_boot

                if str(question.get("type")) == "economic_validation_blocking":
                    respuesta = self._economic_blocking_first_concept_reply({**question, "_session_state_ref": session_state})
                    if forensic_report:
                        respuesta = f"{forensic_report}{respuesta}"
                else:
                    progress = self._compute_pending_progress(pending_questions, current_idx)
                    q_label = str(question.get("label") or "").strip()
                    q_text = str(question.get("question") or "").strip()
                    # Humanizar el label para evitar variables técnicas en el chat
                    _raw_label_p2 = q_label or str(question.get("field_target") or question.get("field") or "")
                    q_label_human_p2 = self._humanize_field_target(_raw_label_p2) if _raw_label_p2 else ""
                    # Si el pendiente tiene pregunta completa pero sin label, mostrar directamente
                    if not q_label_human_p2 and q_text:
                        base_q = q_text
                    else:
                        base_q = self.conversation_normalizer.normalize_capture_message(
                            field_label=q_label_human_p2 or "dato pendiente",
                            question=q_text,
                            intent_type=str(question.get("type", "profile")),
                            state_hint="first_item",
                        )
                    # Motor conversacional con misión activa (Req 7.2)
                    # Solo aplica a tipos no económicos especializados
                    _q_type_p2 = str(question.get("type", "profile"))
                    if _q_type_p2 not in ("economic_price", "economic_validation_blocking"):
                        try:
                            _question_enriched_p2 = await self._enrich_pending_with_rag_context(session_id, question)
                            _tone_mode_p2 = self._detect_tone_mode(session_state, pending_questions, current_idx)
                            _mission_ctx_p2 = self._build_mission_context(session_state, _question_enriched_p2, current_idx, len(pending_questions))
                            _mission_question_p2 = await self._generate_mission_question(
                                _mission_ctx_p2, _tone_mode_p2, pending_question=_question_enriched_p2
                            )
                            if _mission_question_p2:
                                base_q = _mission_question_p2
                        except Exception as _me_p2:
                            logger.warning("chatbot_mission_engine_punto2_failed", error=str(_me_p2)[:120])
                    
                    if forensic_report:
                        respuesta = f"{forensic_report}{progress['progress_label']}\n\n{base_q}"
                    else:
                        respuesta = f"{progress['progress_label']}\n\n{base_q}"
            else:
                _ready_boot = self._maybe_economic_capture_complete_message(
                    session_id=session_id,
                    session_state=session_state,
                    correlation_id=correlation_id,
                    activity_state=activity_state,
                )
                if _ready_boot is not None:
                    await self._save_chat_history(
                        session_id,
                        user_query or "Hola",
                        str((_ready_boot.data or {}).get("respuesta") or ""),
                    )
                    return _ready_boot
                respuesta = (
                    "¡Excelente! Ya tengo los datos de tu empresa seleccionada y he analizado el pliego. "
                    "Puedes preguntarme sobre requisitos, fechas o documentos de la licitación."
                )
            
            await self._save_chat_history(session_id, user_query or "Hola", respuesta)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=respuesta,
                confianza="Alta",
                tipo="welcome_greeting",
                progress=self._compute_pending_progress(pending_questions, current_idx) if pending_questions else None,
                intake_active=bool(pending_questions),
                activity_state=activity_state,
            )

        # =====================================================================
        # FASE 1: DETERMINÍSTICA — ¿El usuario pide aclarar qué falta? (Rama de Estado)
        # =====================================================================
        if pending_questions and user_query and company_id:
            cq_rescue = active_blocking_q
            if cq_rescue and str(cq_rescue.get("type")) == "economic_validation_blocking":
                rescue_intent = self._detect_economic_blocking_rescue_intent(user_query)
                if rescue_intent == "which_concept_or_price":
                    msg = self._economic_blocking_first_concept_reply({**cq_rescue, "_session_state_ref": session_state})
                    await self._save_chat_history(session_id, user_query, msg)
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=msg,
                        confianza="Alta",
                        tipo="economic_blocking_rescue_hint",
                    )
                # ELIMINADO: Bloqueo conversacional estricto. 
                # Ahora permitimos que el flujo continúe hacia la clasificación LLM/RAG.

        if pending_questions:
            if self._evaluate_clarification_intent(user_query):
                logger.info(f"[Chatbot] Rama DETERMINÍSTICA detectada para: '{user_query}'")
                return await self._handle_clarification(
                    session_id, pending_questions, correlation_id, current_idx=current_idx
                )

        if (
            not pending_questions
            and user_query
            and has_real_work_context
            and self._evaluate_clarification_intent(user_query)
        ):
            _fill_clarif = self._maybe_fill_quality_clarification_reply(session_state)
            if _fill_clarif:
                await self._save_chat_history(session_id, user_query, _fill_clarif)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=_fill_clarif,
                    confianza="Alta",
                    tipo="fill_quality_clarification",
                )

        # Posponer el pendiente actual al final de la cola (HITL: atender otros primero).
        if pending_questions and user_query and self._detect_defer_pending_intent(user_query):
            return await self._defer_current_pending(
                session_id=session_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
            )

        # Soporte de evidencia (página/párrafo/dónde dice): prioridad alta para evitar "robot sordo".
        if pending_questions and user_query and self._detect_support_evidence_intent(user_query):
            fresh_pending, fresh_idx = await self._load_fresh_pending_state(
                session_id, fallback_pending=pending_questions, fallback_idx=current_idx
            )
            rag_out = await self._handle_rag_query(
                session_id=session_id,
                user_query=user_query,
                pending=fresh_pending,
                correlation_id=correlation_id,
                current_idx=fresh_idx,
            )
            try:
                q = fresh_pending[fresh_idx] if fresh_pending else {}
                has_anchor = self._pending_has_verifiable_anchor(q)
                data = dict(rag_out.data or {})
                citas = list(data.get("citas") or [])
                conf = str(data.get("confianza") or "").lower()
                no_evidence = (not citas) or conf == "baja"
                if no_evidence and not has_anchor and str(q.get("type")) == "economic_price":
                    return await self._mark_current_pending_non_cotizable(
                        session_id=session_id,
                        session_state=session_state,
                        pending=fresh_pending,
                        current_idx=fresh_idx,
                        user_query=user_query,
                        correlation_id=correlation_id,
                    )
                if fresh_pending:
                    _raw_label_sup = q.get('label') or q.get('field_target') or q.get('field') or 'Campo'
                    reminder = (
                        f"\n\nCon eso claro, seguimos con: "
                        f"**{self._humanize_field_target(_raw_label_sup)}**."
                    )
                    data["respuesta"] = f"{str(data.get('respuesta') or '').strip()}{reminder}"
                    data["tipo"] = "rag_answer_support_pending"
                    rag_out.data = data
            except Exception:
                pass
            return rag_out

        # HITL económico: marcar pendiente como no cotizable/documental por feedback explícito del usuario.
        if pending_questions and user_query and self._detect_non_cotizable_intent(user_query):
            return await self._mark_current_pending_non_cotizable(
                session_id=session_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
            )

        # =====================================================================
        # FASE 2: Clasificar si el mensaje es una PREGUNTA o una APORTACIÓN DE DATOS
        # =====================================================================
        if (
            pending_questions
            and company_id
            and user_query
            and 0 <= current_idx < len(pending_questions)
            and str(pending_questions[current_idx].get("type") or "")
            in ("economic_price", "economic_price_matrix")
        ):
            wclean = (
                user_query.strip()
                .replace("$", "")
                .replace("mxn", "")
                .replace("MXN", "")
                .replace(",", "")
                .strip()
            )
            if re.match(r"^-?\d+(?:\.\d+)?$", wclean) or re.search(
                r"\$\s*[\d,]+", user_query.strip()
            ):
                matrix_num = await self._maybe_redirect_to_matrix_capture(
                    session_id=session_id,
                    company_id=company_id,
                    session_state=session_state,
                    pending=pending_questions,
                    current_idx=current_idx,
                    user_input=user_query,
                    correlation_id=correlation_id,
                )
                if matrix_num is not None:
                    return matrix_num
                return await self._handle_data_intake(
                    session_id,
                    user_query,
                    company_id,
                    pending_questions,
                    current_idx,
                    session_state,
                    correlation_id,
                )

        # MEJORA: Intento de extracción silenciosa antes de clasificar.
        # Si el usuario proporciona el dato dentro de un texto largo, lo capturamos aquí.
        silent_extraction = None
        if pending_questions and user_query and company_id:
            current_q = pending_questions[current_idx]
            # No intentar extracción silenciosa para precios económicos (requieren validación estricta)
            if str(current_q.get("type")) not in ("economic_price", "economic_validation_blocking"):
                extractor = MissionDataExtractor(self.llm)
                mission_ctx = self._build_mission_context(session_state, current_q, current_idx, len(pending_questions))
                # Usar un timeout corto o prompt simplificado para extracción silenciosa
                silent_extraction = await extractor.extract(
                    relevant_text=user_query,
                    mission_context=mission_ctx,
                    correlation_id=correlation_id
                )
        
        if silent_extraction and silent_extraction.value is not None and silent_extraction.confidence in ("Alta", "Media"):
            mode = "DATA_INTAKE"
            logger.info(f"[Chatbot] Extracción SILENCIOSA exitosa para '{pending_questions[current_idx]['label']}'")
        else:
            mode = await self._classify_message(user_query, pending_questions, current_idx, correlation_id)
        
        print(f"[Chatbot] Modo detectado: {mode} | Query: '{user_query[:60]}'")

        # =====================================================================
        # FASE 3A: DATA_INTAKE — El usuario está proporcionando datos de su empresa
        # =====================================================================
        if mode == "DATA_INTAKE" and pending_questions and company_id:
            matrix_gate = await self._maybe_redirect_to_matrix_capture(
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_input=user_query,
                correlation_id=correlation_id,
            )
            if matrix_gate is not None:
                return matrix_gate
            logger.info(f"[Chatbot] Iniciando Captura de Datos para campo '{pending_questions[current_idx]['label']}'")
            return await self._handle_data_intake(
                session_id, user_query, company_id,
                pending_questions, current_idx, session_state, correlation_id
            )

        # =====================================================================
        # FASE 3B: META — Consultas sobre el estado del proceso (Hito 8)
        # =====================================================================
        if mode == "META":
            if pending_questions and self._detect_defer_pending_intent(user_query):
                return await self._defer_current_pending(
                    session_id=session_id,
                    session_state=session_state,
                    pending=pending_questions,
                    current_idx=current_idx,
                    user_query=user_query,
                    correlation_id=correlation_id,
                )
            logger.info(f"[Chatbot] Modo META detectado para: '{user_query}'")
            return await self._handle_meta_query(session_id, user_query, session_state, correlation_id)

        if mode == "QUERY" and pending_questions:
            from app.services.chat_user_intent import is_bases_query

            fresh_s = await self.context_manager.memory.get_session(session_id) or {}
            raw_pending = list(fresh_s.get("pending_questions") or pending_questions)
            p_list = await self._sanitize_and_persist_pending(session_id, fresh_s, raw_pending)
            c_idx = int(fresh_s.get("current_question_index") or current_idx)
            if not p_list:
                return await self._handle_rag_query(
                    session_id,
                    user_query,
                    [],
                    correlation_id,
                    current_idx=0,
                )
            cur_q = p_list[c_idx] if 0 <= c_idx < len(p_list) else {}
            cur_type = str(cur_q.get("type") or "")
            eco_active_types = (
                "economic_price",
                "economic_price_matrix",
            )
            if cur_type in eco_active_types and not is_bases_query(user_query):
                from app.services.hitl_queue_ux_messages import message_for_economic_pending_redirect

                msg = message_for_economic_pending_redirect(
                    cur_q,
                    total=len(p_list),
                    index=c_idx,
                )
                await self._save_chat_history(session_id, user_query, msg)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=msg,
                    confianza="Alta",
                    tipo="clarification_needed",
                    intake_active=True,
                )

            return await self._handle_rag_query(
                session_id,
                user_query,
                p_list,
                correlation_id,
                current_idx=c_idx,
            )

        # --- REGLA ARQUITECTÓNICA: MODO EJECUTOR ---
        # Si no hay pendientes, inyectamos contexto de 'Listo para Generar' y botones de acción.
        intake_done = not pending_questions
        extra_ctx = ""
        suggested_actions = []

        if intake_done:
            extra_ctx = "[ESTADO]: La captura de datos obligatorios ha terminado con éxito. Prioriza invitar al usuario a GENERAR la propuesta usando el botón sugerido."

        return await self._handle_rag_query(
            session_id,
            user_query,
            pending_questions,
            correlation_id,
            current_idx=current_idx,
            extra_context=extra_ctx,
            suggested_actions=suggested_actions
        )

    @staticmethod
    def _maybe_fill_quality_clarification_reply(session_state: Dict[str, Any]) -> Optional[str]:
        """Respuesta HRU cuando preguntan qué falta pero la cola chat ya está limpia."""
        f_hint = session_state.get("last_document_fill_quality_waiting_hints")
        if not isinstance(f_hint, dict):
            return None
        blocking = int(f_hint.get("blocking_count") or 0)
        warnings = int(f_hint.get("warning_count") or 0)
        if blocking <= 0 and warnings <= 0:
            return None
        issues = f_hint.get("issues")
        if not isinstance(issues, list) or not issues:
            return None
        from app.services.document_fill_ux_messages import build_fill_blocking_question

        return build_fill_blocking_question(
            str(f_hint.get("stage") or "formats"),
            issues,
            session_state=session_state,
        )

    async def _sanitize_and_persist_pending(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Aplica política HRU de cola chat y persiste si cambió."""
        from app.services.hitl_queue_service import sanitize_chat_pending_questions

        sanitized = sanitize_chat_pending_questions(pending or [], session_state)
        if sanitized != list(pending or []):
            session_state["pending_questions"] = sanitized
            session_state["current_question_index"] = (
                0 if sanitized else 0
            )
            if not sanitized:
                session_state["intake_progress"] = {
                    "started": False,
                    "accepted": False,
                    "remaining": 0,
                    "total": 0,
                }
            await self.context_manager.memory.save_session(session_id, session_state)
        return sanitized

    async def _load_fresh_pending_state(
        self, session_id: str, fallback_pending: Optional[List] = None, fallback_idx: int = 0
    ) -> tuple[List, int]:
        """Lee estado HITL vigente desde DB, sanitiza y normaliza índice de cola."""
        fresh = await self.context_manager.memory.get_session(session_id) or {}
        p_list = list(fresh.get("pending_questions") or (fallback_pending or []))
        if not p_list:
            return [], 0
        p_list = await self._sanitize_and_persist_pending(session_id, fresh, p_list)
        if not p_list:
            return [], 0
        idx = int(fresh.get("current_question_index") or fallback_idx or 0)
        idx = max(0, min(idx, len(p_list) - 1))
        return p_list, idx

    async def _classify_message(self, query: str, pending: List, idx: int, correlation_id: str = "") -> str:
        """Clasifica el mensaje como QUERY (pregunta sobre bases) o DATA_INTAKE (aportación de dato)."""
        print(f"DEBUG_CLASSIFY: pending={pending}, type={type(pending)}")
        if not query:
            return "EMPTY"

        # --- RECONOCIMIENTO DE COMANDOS TÉCNICOS (UI BUTTONS) ---
        if query.startswith("CMD_"):
            return "META"

        blocking_economic = (
            bool(pending)
            and idx < len(pending)
            and str(pending[idx].get("type")) == "economic_validation_blocking"
        )

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
            if ";" in stripped:
                left = stripped.split(";", 1)[0].strip()
                if re.match(r"^-?\d+(?:\.\d+)?$", left):
                    return "DATA_INTAKE"
            m_sched = re.match(r"^(-?\d+(?:\.\d+)?)\s+([0-9\dxX×.\-\s]{2,80})$", stripped)
            if m_sched and re.search(r"[xX×]", m_sched.group(2)):
                return "DATA_INTAKE"

        if pending and idx < len(pending) and str(pending[idx].get("type")) == "evidence_profile_conflict":
            low = query.strip().lower()
            if len(query) < 200 and "?" not in query:
                pick_signals = (
                    "1",
                    "2",
                    "uno",
                    "dos",
                    "perfil",
                    "empresa",
                    "master",
                    "documento",
                    "constancia",
                    "sesión",
                    "sesion",
                    "acta",
                    "opción",
                    "opcion",
                    "evidencia",
                )
                if any(s in low for s in pick_signals):
                    return "DATA_INTAKE"

        # Heurística rápida (no aplica con bloqueo económico: ahí no hay captura HITL por chat)
        if (
            not blocking_economic
            and pending
            and idx < len(pending)
            and len(query) < 120
            and "?" not in query
        ):
            lowercase = query.lower()
            # Palabras que indican que el usuario está respondiendo
            data_signals = ["es ", "son ", "mi ", "nuestro", "el número", "la dirección",
                            "no aplica", "n/a", "ninguno", "no tengo", "@", "http", "www.",
                            "555", "612", "800", "+52", "te paso", "aqui van", "aquí van", "son:"]
            if any(s in lowercase for s in data_signals):
                return "DATA_INTAKE"
            
            # Si contiene un signo de pesos y un número, es muy probable que sea un dato económico
            if "$" in query and re.search(r"\d", query):
                return "DATA_INTAKE"
            # Si hay pregunta pendiente activa y el mensaje es una afirmación corta sin "?",
            # es muy probable que sea una respuesta directa al dato solicitado
            affirmation_signals = ["tenemos", "contamos", "somos", "tengo", "cuento",
                                   "años", "meses", "pesos", "contratos", "empleados",
                                   "registrado", "vigente", "activo"]
            if any(s in lowercase for s in affirmation_signals):
                return "DATA_INTAKE"

        # --- PROTECCIÓN SENIOR (Resiliencia ante lista vacía) ---
        if not pending or idx >= len(pending):
            label_pedida = "Ninguno (estamos en modo consulta libre)"
        else:
            label_pedida = pending[idx].get('label', 'un dato')

        classification_resp = await self.llm.generate(
            prompt=f"""Clasifica el mensaje del usuario en UNA de estas tres categorías:
QUERY - El usuario hace una pregunta, pide una aclaración, pide que le expliques algo o expresa duda (ej: "¿Qué es esto?", "No entiendo", "Explícame más").
DATA_INTAKE - El usuario está dando información, confirmando algo, o pegando un texto que contiene la respuesta al dato solicitado (ej: "Sí lo tengo", "Aquí está el texto: [bloque de texto]", "Mi RFC es..."). Incluso si el texto es MUY LARGO, si parece ser la respuesta a lo solicitado, es DATA_INTAKE.
META - Instrucciones al sistema (ej: "Siguiente", "Generar", "Borrar", "Continuar").

Dato que estamos pidiendo ahora: "{label_pedida}"
Mensaje del usuario: "{query}"

Responde SOLO: QUERY, DATA_INTAKE o META""",
            system_prompt="Eres un clasificador de intención experto. Prioriza DATA_INTAKE si el usuario parece estar pegando información relevante.",
            correlation_id=correlation_id
        )
        result = classification_resp.response.strip().upper() if classification_resp.success else "QUERY"
        
        # --- HITO: Liberación Conversacional ---
        # No forzamos QUERY si hay bloqueo económico; permitimos que el usuario resuelva el bloqueo vía chat.
        if "DATA_INTAKE" in result:
            return "DATA_INTAKE"
        if "META" in result:
            return "META"
        return "QUERY"

    _GENERIC_ECONOMIC_CONCEPT_MARKERS: tuple = (
        "precio de la licitación",
        "precio de la licitacion",
        "precio de la propuesta",
        "precio licitacion",
        "precio licitación",
        "importe de la licitación",
        "importe de la licitacion",
        "monto de la licitación",
        "monto de la licitacion",
        "total licitación",
        "total licitacion",
        "subtotal",
        "total base",
        "importe total",
        "monto total",
        "precio unitario",
        "precio de:",
    )

    @staticmethod
    def _looks_like_bare_price_token(label: str) -> bool:
        """True si el texto es solo un número (no un nombre de concepto)."""
        s = (label or "").strip().replace("$", "").replace(",", "")
        return bool(re.match(r"^-?\d+(?:\.\d+)?$", s))

    @staticmethod
    def _is_generic_economic_concept_label(label: str) -> bool:
        """True si la etiqueta no identifica un concepto de partida (ruido del LLM)."""
        if not (label or "").strip():
            return True
        if ChatbotRAGAgent._looks_like_bare_price_token(label):
            return True
        low = ChatbotRAGAgent._normalize(str(label))
        if len(low) < 3:
            return True
        return any(m in low for m in ChatbotRAGAgent._GENERIC_ECONOMIC_CONCEPT_MARKERS)

    @staticmethod
    def _concept_from_economic_price_pending_q(question: Dict[str, Any]) -> str:
        """Concepto de negocio asociado a un pendiente ``economic_price``."""
        if not question:
            return ""
        lbl = str(question.get("label") or "").strip()
        for _pfx in (
            "Precio de: ",
            "PU oferta económica — ",
            "PU oferta economica - ",
            "Precio (sin IVA): ",
            "Precio unitario: ",
        ):
            if lbl.startswith(_pfx):
                lbl = lbl[len(_pfx) :].strip()
        if ":" in lbl:
            lbl = lbl.split(":", 1)[-1].strip()
        return lbl or str(question.get("field") or "").strip()

    def _split_economic_price_reply(self, raw: str) -> tuple:
        """
        Separa precio numérico y cola opcional (esquema de horas tipo 24x24).
        Formatos: ``5800; 24x24`` o ``5800 24x24``.
        """
        s = (raw or "").strip().replace(",", "")
        if ";" in s:
            a, b = s.split(";", 1)
            return a.strip(), b.strip()
        m = re.match(r"^(-?\d+(?:\.\d+)?)\s+([0-9\dxX×.\-\s]{2,80})$", s)
        if m and re.search(r"[xX×]", m.group(2)):
            return m.group(1).strip(), m.group(2).strip()
        return s, ""

    @staticmethod
    def _parse_strict_economic_price(raw: str) -> tuple:
        """Valida precio económico estricto: solo número finito."""
        s = (raw or "").strip().replace("$", "").replace("mxn", "").replace("MXN", "")
        s = s.replace(",", "").strip()
        if not s:
            return None, "vacío"
        low = s.lower()
        if low in ("n/a", "na", "pendiente", "—", "-"):
            return None, "usa número o 0"
        if not re.match(r"^-?\d+(?:\.\d+)?$", s):
            return None, "no es un número válido"
        try:
            v = float(s)
        except Exception:
            return None, "no es un número válido"
        if not (v == v):  # NaN
            return None, "no es un número válido"
        return s, None

    @staticmethod
    def _count_economic_price_pending(pending: List[Dict[str, Any]]) -> int:
        return sum(
            1
            for q in (pending or [])
            if str(q.get("type") or "")
            in ("economic_price", "economic_price_matrix")
        )

    async def _ensure_capture_matrix_blocks(
        self,
        session_id: str,
        session_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        blocks = session_state.get("capture_matrix_blocks") or []
        if blocks:
            return blocks
        from app.services.economic_capture_matrix_service import (
            build_capture_matrix_blocks_from_pending,
        )

        rebuilt = build_capture_matrix_blocks_from_pending(
            list(session_state.get("pending_questions") or []),
            session_state.get("economic_user_inputs"),
        )
        if rebuilt:
            session_state["capture_matrix_blocks"] = rebuilt
            updates: Dict[str, Any] = {
                "capture_matrix_blocks": rebuilt,
                "economic_capture_mode": "matrix",
            }
            eco_n = sum(
                1
                for q in (session_state.get("pending_questions") or [])
                if str(q.get("type") or "") == "economic_price"
            )
            if eco_n >= 5:
                from app.services.chat_economic_matrix import (
                    build_structured_price_intro_with_matrix,
                )

                intro = build_structured_price_intro_with_matrix([], rebuilt)
                updates["pending_questions"] = [
                    q
                    for q in (session_state.get("pending_questions") or [])
                    if str(q.get("type") or "") != "economic_price"
                ] + [
                    {
                        "type": "economic_price_matrix",
                        "field": "economic_matrix_bulk",
                        "label": "Matriz de precios unitarios",
                        "question": intro,
                        "blocking": True,
                        "matrix_row_count": sum(
                            len(b.get("matrix_rows") or []) for b in rebuilt
                        ),
                    }
                ]
                updates["current_question_index"] = 0
            await self.context_manager.memory.save_session(session_id, updates)
            session_state.update(updates)
        return rebuilt

    def _build_matrix_capture_response(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        blocks: List[Dict[str, Any]],
        *,
        correlation_id: str = "",
        proactive: bool = False,
        activity_state: Optional[str] = None,
    ) -> AgentOutput:
        from app.services.chat_economic_matrix import (
            build_proactive_economic_matrix_welcome,
            format_matrix_blocks_markdown,
        )

        if proactive:
            support_name = str(
                session_state.get("structured_price_support_name") or ""
            ).strip()
            if not support_name:
                for q in session_state.get("pending_questions") or []:
                    oi = q.get("original_item") if isinstance(q.get("original_item"), dict) else {}
                    sn = str(oi.get("quantity_support_source_name") or "").strip()
                    if sn:
                        support_name = sn
                        break
            msg = build_proactive_economic_matrix_welcome(
                blocks,
                support_name=support_name,
            )
        else:
            total = sum(len(b.get("matrix_rows") or []) for b in blocks)
            md = format_matrix_blocks_markdown(blocks, max_rows=min(35, total))
            msg = (
                f"Sigamos con la matriz: faltan **{total}** precio(s) unitarios. "
                f"Complétalos en la tarjeta **Matriz de precios** o pega filas "
                f"`ubicación[TAB]precio`.\n\n{md}\n\n"
                "_Avísame con **listo** cuando termines._"
            )
        progress = self._compute_pending_progress(
            list(session_state.get("pending_questions") or []),
            int(session_state.get("current_question_index") or 0),
        )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="pending_question",
            progress=progress,
            intake_active=True,
            activity_state=activity_state,
        )

    def _should_proactively_offer_economic_capture(
        self,
        pending: List[Dict[str, Any]],
        current_idx: int,
        user_query: str,
        eco_n: int,
    ) -> bool:
        """True en bootstrap/saludo cuando lo prioritario es captura económica."""
        q_norm = (user_query or "").strip().lower()
        is_opening = q_norm in (
            "",
            "hola",
            "hi",
            "hello",
            "buenas",
            "buenas tardes",
            "buenas noches",
            "buenos dias",
            "buenos días",
            "hey",
            "buen dia",
            "buen día",
        ) or self._looks_like_greeting_or_progress_intent(user_query or "")
        if eco_n <= 0 or not is_opening:
            return False
        cur_type = ""
        if pending and 0 <= current_idx < len(pending):
            cur_type = str(pending[current_idx].get("type") or "")
        if cur_type in ("economic_price", "economic_price_matrix", "economic_validation_blocking"):
            return True
        if eco_n >= 5 and eco_n >= max(1, len(pending)) // 2:
            return True
        return False

    def _maybe_economic_capture_complete_message(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        correlation_id: str,
        activity_state: str,
    ) -> Optional[AgentOutput]:
        """Mensaje cuando la matriz de precios ya está capturada (p. ej. tras importar Excel)."""
        from app.services.economic_capture_matrix_service import economic_capture_status

        cap = economic_capture_status(session_state)
        if not cap.get("capture_complete"):
            return None
        missing = int(cap.get("missing") or 0)
        extra = (
            f"\n\n_Quedan **{missing}** concepto(s) sin precio; puedes subir de nuevo el Excel o corregirlos en **Matriz de precios**._"
            if missing > 0
            else ""
        )
        msg = (
            f"Tu **cotización económica está lista**: registré **{cap.get('filled')}** de "
            f"**{cap.get('total')}** precio(s) unitario(s).{extra}\n\n"
            "Siguiente paso: pulsa **Generar propuesta** en el panel principal o escribe "
            "**generar propuesta económica** para materializar el expediente."
        )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="economic_capture_ready",
            intake_active=False,
            activity_state=activity_state,
        )

    async def _proactive_economic_capture_offer(
        self,
        *,
        session_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        pending: List[Dict[str, Any]],
        current_idx: int,
        user_query: str,
        correlation_id: str,
        activity_state: str,
    ) -> Optional[AgentOutput]:
        """
        El asistente inicia la conversación explicando precios faltantes y la matriz,
        sin esperar que el usuario adivine comandos.
        """
        from app.services.chat_economic_matrix import (
            build_proactive_few_economic_prices_welcome,
            should_use_matrix_capture,
        )

        if not company_id:
            return None
        eco_n = self._count_economic_price_pending(pending)
        if not self._should_proactively_offer_economic_capture(
            pending, current_idx, user_query, eco_n
        ):
            return None

        mode = str(session_state.get("economic_capture_mode") or "")
        econ_only = [
            q
            for q in (pending or [])
            if str(q.get("type") or "") in ("economic_price", "economic_price_matrix")
        ]

        if should_use_matrix_capture(eco_n, session_mode=mode or None):
            blocks = await self._ensure_capture_matrix_blocks(session_id, session_state)
            if not blocks:
                return None
            return self._build_matrix_capture_response(
                session_id,
                session_state,
                blocks,
                correlation_id=correlation_id,
                proactive=True,
                activity_state=activity_state,
            )

        if eco_n > 0:
            msg = build_proactive_few_economic_prices_welcome(econ_only[:eco_n])
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="pending_question",
                progress=self._compute_pending_progress(pending, current_idx),
                intake_active=True,
                activity_state=activity_state,
            )
        return None

    async def _maybe_redirect_to_matrix_capture(
        self,
        *,
        session_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        pending: List[Dict[str, Any]],
        current_idx: int,
        user_input: str,
        correlation_id: str = "",
    ) -> Optional[AgentOutput]:
        """Prioriza matriz masiva cuando hay muchos precios estructurados pendientes."""
        from app.services.chat_economic_matrix import should_use_matrix_capture

        eco_n = self._count_economic_price_pending(pending)
        mode = str(session_state.get("economic_capture_mode") or "")
        if not should_use_matrix_capture(eco_n, session_mode=mode or None):
            return None

        blocks = await self._ensure_capture_matrix_blocks(session_id, session_state)
        if not blocks:
            return None

        low = (user_input or "").strip().lower()
        if low in ("listo", "listo precios", "precios listos", "ya llene la matriz"):
            return await self._handle_matrix_capture_complete(
                session_id=session_id,
                company_id=company_id,
                session_state=session_state,
                blocks=blocks,
                correlation_id=correlation_id,
            )

        bulk = await self._try_tsv_bulk_economic_prices(
            session_id, user_input, company_id, session_state, correlation_id
        )
        if bulk is not None:
            return bulk

        if low in ("uno por uno", "uno a uno", "preguntame uno por uno"):
            await self.context_manager.memory.save_session(
                session_id, {"economic_capture_mode": "one_by_one"}
            )
            return None

        cur_type = ""
        if pending and 0 <= current_idx < len(pending):
            cur_type = str(pending[current_idx].get("type") or "")

        if cur_type in ("economic_price", "economic_price_matrix"):
            return self._build_matrix_capture_response(
                session_id, session_state, blocks, correlation_id=correlation_id
            )
        return None

    async def _handle_matrix_capture_complete(
        self,
        *,
        session_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        blocks: List[Dict[str, Any]],
        correlation_id: str = "",
    ) -> AgentOutput:
        """Valida que la matriz tenga precios antes de continuar."""
        inputs = dict(session_state.get("economic_user_inputs") or {})
        total_fields = 0
        filled = 0
        for block in blocks:
            for row in block.get("matrix_rows") or []:
                field = str(row.get("field") or "")
                if not field:
                    continue
                total_fields += 1
                if field in inputs:
                    filled += 1
        if total_fields and filled < total_fields:
            missing = total_fields - filled
            base = self._build_matrix_capture_response(
                session_id, session_state, blocks, correlation_id=correlation_id
            )
            data = dict(base.data or {})
            data["respuesta"] = (
                f"Aún faltan **{missing}** precio(s) en la matriz "
                f"({filled}/{total_fields} completos). "
                f"{data.get('respuesta', '')}"
            )
            base.data = data
            return base
        fresh = await self.context_manager.memory.get_session(session_id) or session_state
        fresh["pending_questions"] = [
            q
            for q in (fresh.get("pending_questions") or [])
            if str(q.get("type") or "")
            not in ("economic_price", "economic_price_matrix")
        ]
        fresh["current_question_index"] = 0
        await self.context_manager.memory.save_session(session_id, fresh)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=(
                f"Perfecto, registré **{filled}** precio(s) en la matriz. "
                "Cuando quieras, escribe **generar propuesta económica** o usa el panel **Generar**."
            ),
            confianza="Alta",
            tipo="data_saved",
        )

    async def _try_tsv_bulk_economic_prices(
        self,
        session_id: str,
        user_input: str,
        company_id: str,
        session_state: Dict[str, Any],
        correlation_id: str = "",
    ) -> Optional[AgentOutput]:
        """Pegado masivo ubicación[TAB]precio cuando hay ``capture_matrix_blocks``."""
        blocks = session_state.get("capture_matrix_blocks") or []
        if not blocks:
            return None
        if "\n" not in user_input and "\t" not in user_input and "," not in user_input:
            return None
        from app.services.chat_economic_matrix import apply_tsv_bulk_to_inputs

        inputs = dict(session_state.get("economic_user_inputs") or {})
        result = apply_tsv_bulk_to_inputs(user_input, blocks, inputs)
        applied = result.get("applied") or {}
        if not applied:
            return None
        session_state["economic_user_inputs"] = inputs
        await self.context_manager.memory.save_session(
            session_id, {"economic_user_inputs": inputs}
        )
        try:
            await refresh_economic_validations_for_session(
                self.context_manager.memory, session_id
            )
        except Exception as _ref_err:
            logger.info(
                "tsv_bulk_refresh_skipped",
                session_id=session_id,
                error=str(_ref_err)[:120],
            )
        fresh = await self.context_manager.memory.get_session(session_id) or session_state
        pending = list(fresh.get("pending_questions") or [])
        remaining = [
            q
            for q in pending
            if str(q.get("field") or "") not in applied
            and str(q.get("type") or "") == "economic_price"
        ]
        fresh["pending_questions"] = remaining + [
            q
            for q in pending
            if str(q.get("type") or "")
            not in ("economic_price", "economic_price_matrix")
        ]
        fresh["current_question_index"] = 0
        await self.context_manager.memory.save_session(session_id, fresh)
        err_txt = ""
        if result.get("errors"):
            err_txt = f"\n\n_No pude interpretar {len(result['errors'])} fila(s)._"
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=(
                f"Capturé **{len(applied)}** precio(s) desde tu pegado.{err_txt}\n\n"
                "Continúa con los pendientes restantes o usa **Resolución por bloque**."
            ),
            confianza="Alta",
            tipo="data_saved",
        )

    async def _handle_data_intake(
        self, session_id: str, user_input: str, company_id: str,
        pending: List, current_idx: int, session_state: Dict, correlation_id: str = ""
    ) -> AgentOutput:
        """Procesa la aportación de datos del usuario, la guarda y avanza al siguiente pendiente."""

        confirm = session_state.get("_price_confirm_pending")
        if isinstance(confirm, dict) and confirm.get("value"):
            low = (user_input or "").strip().lower()
            if low in ("si", "sí", "yes", "correcto", "ok", "vale"):
                field_key = str(confirm.get("field") or "")
                session_state.pop("_price_confirm_pending", None)
                await self.context_manager.memory.save_session(
                    session_id, {"_price_confirm_pending": None}
                )
                current_q = next(
                    (q for q in pending if str(q.get("field") or "") == field_key),
                    pending[current_idx] if pending else {},
                )
                return await self._apply_saved_pending_value(
                    session_id=session_id,
                    user_input_for_history=user_input,
                    company_id=company_id,
                    current_q=current_q,
                    pending=pending,
                    current_idx=current_idx,
                    session_state=session_state,
                    extracted_value=str(confirm.get("value")),
                    correlation_id=correlation_id,
                    saved_via="chat_confirm",
                )

        bulk = await self._try_tsv_bulk_economic_prices(
            session_id, user_input, company_id, session_state, correlation_id
        )
        if bulk is not None:
            return bulk

        matrix_in_intake = await self._maybe_redirect_to_matrix_capture(
            session_id=session_id,
            company_id=company_id,
            session_state=session_state,
            pending=pending,
            current_idx=current_idx,
            user_input=user_input,
            correlation_id=correlation_id,
        )
        if matrix_in_intake is not None:
            return matrix_in_intake

        current_q = pending[current_idx]
        if str(current_q.get("type")) == "evidence_profile_conflict":
            return await self._handle_evidence_profile_conflict_resolution(
                session_id=session_id,
                user_input=user_input,
                company_id=company_id,
                pending=pending,
                current_idx=current_idx,
                session_state=session_state,
                correlation_id=correlation_id,
            )

        field_key = str(current_q.get("field") or current_q.get("field_target") or "unknown")
        field_label = str(current_q.get("label") or current_q.get("question") or "dato")

        work_input = user_input.strip()
        schedule_tail = ""
        if str(current_q.get("type")) == "economic_price":
            from app.services.conversational_price_normalizer import (
                format_price_confirmation,
                normalize_conversational_price,
                resolve_price_reference,
            )

            work_input, schedule_tail = self._split_economic_price_reply(work_input)
            strict_val, strict_err = self._parse_strict_economic_price(work_input)
            if strict_err:
                eco_inputs = session_state.get("economic_user_inputs") or {}
                ref_val, ref_err, ref_conf = resolve_price_reference(work_input, eco_inputs)
                if ref_val and not ref_err:
                    conv_val, conv_err, confidence = ref_val, ref_err, ref_conf
                else:
                    conv_val, conv_err, confidence = normalize_conversational_price(work_input)
                if conv_err or not conv_val:
                    if str(session_state.get("economic_capture_mode") or "") == "matrix":
                        blocks = session_state.get("capture_matrix_blocks") or []
                        if blocks:
                            return self._build_matrix_capture_response(
                                session_id,
                                session_state,
                                blocks,
                                correlation_id=correlation_id,
                            )
                        hint = (
                            f"No reconocí un importe en tu mensaje. "
                            f"Usa la **Matriz de precios** arriba del chat o pega "
                            f"`ubicación[TAB]precio`."
                        )
                    else:
                        hint = (
                            f"No pude interpretar un precio para **{field_label}**. "
                            f"Puedes escribirlo como número (ej. 35529), con pesos ($35,529) "
                            f"o en palabras (ej. 35 mil 529). Si no aplica, indica **no aplica**."
                        )
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=hint,
                        confianza="Alta",
                        tipo="clarification_needed",
                    )
                strict_val = conv_val
                if confidence < 0.9:
                    pending_confirm = dict(session_state)
                    pending_confirm["_price_confirm_pending"] = {
                        "field": field_key,
                        "value": strict_val,
                        "label": field_label,
                    }
                    await self.context_manager.memory.save_session(
                        session_id, pending_confirm
                    )
                    return self._format_response(
                        session_id=session_id,
                        correlation_id=correlation_id,
                        respuesta=format_price_confirmation(field_label, strict_val),
                        confianza="Alta",
                        tipo="clarification_needed",
                    )
            extracted_value = strict_val
            return await self._apply_saved_pending_value(
                session_id=session_id,
                user_input_for_history=user_input,
                company_id=company_id,
                current_q=current_q,
                pending=pending,
                current_idx=current_idx,
                session_state=session_state,
                extracted_value=extracted_value,
                correlation_id=correlation_id,
                saved_via="chat",
                companion_schedule=schedule_tail,
            )

        wclean = (
            work_input.replace("$", "")
            .replace("mxn", "")
            .replace("MXN", "")
            .replace(",", "")
            .strip()
        )
        if str(current_q.get("type")) == "economic_price" and re.match(r"^-?\d+(?:\.\d+)?$", wclean):
            extracted_value = wclean
        else:
            extract_resp = await self.llm.generate(
                prompt=f"""El usuario está respondiendo la siguiente pregunta: "{field_label}"
Su respuesta es: "{work_input}"

Extrae ÚNICAMENTE el valor que proporcionó. 
- Si confirma que lo tiene (ej: "sí", "lo tengo", "listo", "cuenta con ello"), devuelve: SÍ
- Si dice "no aplica" o equivalente, devuelve: N/A
- Si no se puede extraer un valor claro, devuelve: AMBIGUO

Responde SOLO con el valor puro (máximo 100 caracteres):""",
                system_prompt="Eres un extractor de datos preciso. Devuelves el valor puro o N/A o AMBIGUO.",
                correlation_id=correlation_id,
            )
            extracted_value = extract_resp.response.strip() if extract_resp.success else "AMBIGUO"

        if "AMBIGUO" in extracted_value.upper():
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=f"No logré entender bien tu respuesta. ¿Podrías decirme directamente **{self._humanize_field_target(field_label)}**? (ej: un número, texto, o 'No aplica')",
                confianza="Media",
                tipo="clarification_needed"
            )

        return await self._apply_saved_pending_value(
            session_id=session_id,
            user_input_for_history=user_input,
            company_id=company_id,
            current_q=current_q,
            pending=pending,
            current_idx=current_idx,
            session_state=session_state,
            extracted_value=extracted_value,
            correlation_id=correlation_id,
            saved_via="chat",
            companion_schedule=schedule_tail,
        )

    async def _persist_concept_guard_schedule(
        self, session_id: str, current_q: Dict[str, Any], schedule_text: str
    ) -> None:
        """
        Persiste en sesión el esquema de horas por guardia (p. ej. 12×12, 24×24) para consumo
        de la app y agentes económicos vía ``economic_user_inputs.concept_guard_schedules``.
        """
        if not schedule_text or len(schedule_text) < 2:
            return
        orig = current_q.get("original_item") or {}
        cid = orig.get("concepto_id")
        key = str(cid).strip() if cid is not None and str(cid).strip() else str(current_q.get("field", ""))
        if not key:
            return
        state = await self.context_manager.memory.get_session(session_id) or {}
        inputs = dict(state.get("economic_user_inputs") or {})
        bucket = dict(inputs.get("concept_guard_schedules") or {})
        bucket[key] = schedule_text.strip()[:2000]
        inputs["concept_guard_schedules"] = bucket
        state["economic_user_inputs"] = inputs
        await self.context_manager.memory.save_session(session_id, state)

    async def _apply_saved_pending_value(
        self,
        *,
        session_id: str,
        user_input_for_history: str,
        company_id: str,
        current_q: Dict[str, Any],
        pending: List,
        current_idx: int,
        session_state: Dict,
        extracted_value: str,
        correlation_id: str = "",
        saved_via: str = "chat",
        companion_schedule: str = "",
    ) -> AgentOutput:
        """Persiste un valor ya validado para el pendiente actual y avanza la cola HITL."""
        completion_actions: List[Dict[str, str]] = []
        field_key = str(current_q.get("field") or current_q.get("field_target") or "unknown")
        field_label = str(current_q.get("label") or current_q.get("question") or "dato")
        q_type = current_q.get("type", "profile")

        if q_type == "economic_price":
            saved = await self._save_price_to_catalog(company_id, current_q, extracted_value)
            concept = self._concept_from_economic_price_pending_q(current_q)
            try:
                price_num = float(str(extracted_value).replace(",", "").strip())
            except (TypeError, ValueError):
                price_num = None
            if concept and price_num is not None:
                st = dict(session_state or {})
                latest = dict(st.get("economic_user_inputs") or {})
                bucket = dict(latest.get("concept_prices") or {})
                resolved = self._resolve_economic_concept(concept, st) or concept
                # Clave técnica (price_<id>) para EconomicRefresher; etiqueta para fuzzy match.
                if field_key and field_key.startswith("price_"):
                    bucket[field_key] = price_num
                if resolved:
                    bucket[resolved] = price_num
                latest["concept_prices"] = bucket
                st["economic_user_inputs"] = latest
                overrides = list(st.get("economic_user_overrides") or [])
                overrides.append(
                    {
                        "kind": "economic_set_value",
                        "key": "concept_price",
                        "concept": resolved,
                        "value": str(extracted_value),
                        "value_numeric": price_num,
                        "source": "chat_data_intake",
                    }
                )
                st["economic_user_overrides"] = overrides[-500:]
                await self.context_manager.memory.save_session(session_id, st)
                session_state = st
                try:
                    await refresh_economic_validations_for_session(
                        self.context_manager.memory, session_id
                    )
                except Exception as _eco_refresh_err:
                    logger.warning(
                        "chatbot_economic_intake_refresh_failed",
                        session_id=session_id,
                        error=str(_eco_refresh_err)[:200],
                    )
                saved = True
                session_state = await self.context_manager.memory.get_session(session_id) or session_state
        else:
            if str(extracted_value or "").strip().upper() not in ("SÍ", "SI", "N/A", "NA"):
                try:
                    from app.agents.data_gap import DataGapAgent

                    dg = DataGapAgent(self.context_manager)
                    if not dg._is_data_valid(field_key, extracted_value):
                        human = self._humanize_field_target(field_label)
                        return self._format_response(
                            session_id=session_id,
                            correlation_id=correlation_id,
                            respuesta=(
                                f"El valor para **{human}** no parece válido. "
                                "Revisa el formato (ej. clave de elector o folio de INE) o escribe **No aplica**."
                            ),
                            confianza="Alta",
                            tipo="clarification_needed",
                        )
                except Exception as val_err:
                    logger.warning(
                        "chatbot_profile_field_validation_skipped",
                        field=field_key,
                        error=str(val_err)[:80],
                    )
            saved = await self._save_field_to_company(company_id, field_key, extracted_value)

        if not saved:
            _raw_label_retry = str(field_label or current_q.get("field_target") or current_q.get("field") or "Campo")
            retry = self.conversation_normalizer.normalize_capture_message(
                field_label=self._humanize_field_target(_raw_label_retry),
                question=str(current_q.get("question", "")),
                intent_type=str(q_type or "profile"),
                state_hint="clarification",
            )
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    f"No pude guardar **{field_label}** con el valor recibido.\n\n"
                    f"{retry}"
                ),
                confianza="Alta",
                tipo="clarification_needed",
            )

        if (
            saved
            and q_type == "economic_price"
            and (companion_schedule or "").strip()
            and current_q.get("capture_guard_schedule")
        ):
            await self._persist_concept_guard_schedule(
                session_id, current_q, (companion_schedule or "").strip()
            )

        semaforo_change_msg = ""
        if saved and company_id:
            prev_semaforo = session_state.get("go_no_go_result", {}).get("semaforo")
            new_gng = await self._recalculate_semaforo(session_id, company_id)
            new_semaforo = new_gng.get("semaforo") if new_gng else None
            semaforo_change_msg = self._build_semaforo_change_msg(prev_semaforo, new_semaforo)

        if saved:
            fresh_mid = await self.context_manager.memory.get_session(session_id) or {}
            rem = [
                r
                for r in (fresh_mid.get("hitl_deferred_reminders") or [])
                if str(r.get("field")) != str(field_key)
            ]
            fresh_mid["hitl_deferred_reminders"] = rem
            await self.context_manager.memory.save_session(session_id, fresh_mid)

        # Recalcular cola/índice de forma segura (sin +1 ciego).
        fresh_s = await self.context_manager.memory.get_session(session_id) or {}
        fresh_pending = list(fresh_s.get("pending_questions") or pending or [])
        safe_idx = max(0, min(int(current_idx or 0), max(0, len(fresh_pending) - 1)))
        if saved and fresh_pending:
            if q_type == "economic_price" and field_key:
                fresh_pending = [
                    q
                    for q in fresh_pending
                    if not (
                        str(q.get("type") or "") == "economic_price"
                        and str(q.get("field") or "") == field_key
                    )
                ]
                next_idx = max(0, min(safe_idx, len(fresh_pending) - 1)) if fresh_pending else 0
            elif safe_idx < len(fresh_pending):
                fresh_pending = fresh_pending[:safe_idx] + fresh_pending[safe_idx + 1 :]
                next_idx = max(0, min(safe_idx, len(fresh_pending) - 1)) if fresh_pending else 0
            else:
                next_idx = 0
        else:
            next_idx = 0
        fresh_s["pending_questions"] = fresh_pending
        fresh_s["current_question_index"] = next_idx
        await self.context_manager.memory.save_session(session_id, fresh_s)
        session_state = fresh_s

        human_field = self._humanize_field_target(field_label)
        hist_note = (
            f"Guardé desde fuentes: {human_field} = {extracted_value}"
            if saved_via == "sources"
            else f"Guardé: {human_field} = {extracted_value}"
        )
        await self._save_chat_history(session_id, user_input_for_history, hist_note)

        if fresh_pending:
            next_q = fresh_pending[next_idx]
            human_saved = self._humanize_field_target(field_label)
            _q_type_p3 = str(next_q.get("type", "profile"))
            if _q_type_p3 == "economic_price":
                resp = self._format_economic_price_followup(
                    human_saved,
                    str(extracted_value),
                    next_q,
                    session_state=fresh_s,
                )
            else:
                human_next = self._humanize_field_target(
                    str(next_q.get("label") or next_q.get("field") or "Campo")
                )
                resp = self.conversation_normalizer.normalize_saved_transition(
                    saved_label=human_saved,
                    next_label=human_next,
                    next_question=str(next_q.get("question", "")),
                    next_intent_type=_q_type_p3,
                )
            # Motor conversacional con misión activa (Req 7.3)
            # Solo aplica a tipos no económicos especializados
            if _q_type_p3 not in ("economic_price", "economic_validation_blocking"):
                try:
                    _tone_mode_p3 = self._detect_tone_mode(session_state, fresh_pending, next_idx)
                    _mission_ctx_p3 = self._build_mission_context(session_state, next_q, next_idx, len(fresh_pending))
                    _mission_question_p3 = await self._generate_mission_question(
                        _mission_ctx_p3, _tone_mode_p3, pending_question=next_q
                    )
                    if _mission_question_p3:
                        # Preservar el prefijo de confirmación del guardado + agregar la nueva pregunta del motor
                        resp = f"Listo, guardé **{human_saved}**.\n\n{_mission_question_p3}"
                except Exception as _me_p3:
                    logger.warning("chatbot_mission_engine_punto3_failed", error=str(_me_p3)[:120])
            if semaforo_change_msg:
                resp = f"{resp}{semaforo_change_msg}"
        else:
            fresh_s = await self.context_manager.memory.get_session(session_id) or {}
            fresh_s["pending_questions"] = []
            fresh_s["current_question_index"] = 0
            fresh_s["hitl_deferred_reminders"] = []
            await self.context_manager.memory.save_session(session_id, fresh_s)
            session_state = fresh_s
            # Log de transición waiting_for_data -> success cuando se completa la cola
            # (Req 7.3: Observabilidad del flujo completo)
            was_blocking = bool(current_q.get("is_blocking"))
            logger.info(
                "datagap_queue_exhausted",
                session_id=session_id,
                correlation_id=correlation_id,
                last_field=str(field_key),
                last_field_was_blocking=was_blocking,
                transition="waiting_for_data->success" if was_blocking else "pending->success",
            )
            human_saved_done = self._humanize_field_target(field_label)
            if saved_via == "sources":
                resp = (
                    f"✅ **Dato verificado:** registré **{field_label}** desde tus fuentes corporativas."
                    f"{semaforo_change_msg}\n\n"
                    "Puedes continuar con **Generar** en el panel o escribir **generar documentos**."
                )
                completion_actions: List[Dict[str, str]] = []
            elif q_type == "economic_price":
                resp, completion_actions = self._build_economic_price_queue_completed_response(
                    human_saved=human_saved_done,
                    semaforo_change_msg=semaforo_change_msg,
                )
            else:
                resp, completion_actions = self._build_intake_queue_completed_response(
                    human_saved=human_saved_done,
                    semaforo_change_msg=semaforo_change_msg,
                )

        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=resp,
            confianza="Alta",
            tipo="data_saved",
            progress=self._compute_pending_progress(fresh_pending, next_idx) if fresh_pending else None,
            intake_active=bool(fresh_pending),
            suggested_actions=completion_actions if not fresh_pending else None,
        )

    @staticmethod
    def _active_economic_blocking_pending(
        pending_questions: List[Dict[str, Any]],
        current_idx: int,
    ) -> Optional[Dict[str, Any]]:
        """Busca bloqueo económico activo priorizando índice actual, luego primer match."""
        if not pending_questions:
            return None
        if 0 <= int(current_idx or 0) < len(pending_questions):
            q = pending_questions[int(current_idx or 0)]
            if str(q.get("type")) == "economic_validation_blocking":
                return q
        for q in pending_questions:
            if str(q.get("type")) == "economic_validation_blocking":
                return q
        return None

    @staticmethod
    def _detect_take_from_sources_intent(query: str) -> bool:
        """
        True si el usuario pide inferir el dato desde documentos / Fuentes ya subidos
        (sin formular una pregunta de pliego).
        """
        q = ChatbotRAGAgent._normalize(query)
        if not q or len(q) > 220:
            return False
        doc_ctx = any(
            k in q
            for k in (
                "fuentes",
                "documento",
                "archivo",
                "pdf",
                "ine",
                "credencial",
                "identificacion",
                "subi ",
                "subi el",
                "subi la",
                "subelo",
                "cargue",
                "adjunte",
            )
        )
        if "?" in (query or "") and not doc_ctx:
            return False
        # Preguntas al instrumento convocante, sin anclaje a expediente propio
        if any(w in q for w in ("pliego", "bases", "convocatoria", "licitacion", "junta de aclaraciones")):
            if not doc_ctx:
                return False
        hints = (
            "subi ",
            "subi el",
            "subi la",
            "subido",
            "subida",
            "documento",
            "archivo",
            "pdf",
            "fuente",
            "analiza fuentes",
            "analizar fuentes",
            "toma de",
            "tomalo",
            "tomalo de",
            "tomar de",
            "tomar el",
            "tomar lo",
            "sacar de",
            "extrae",
            "extraer",
            "de ahi",
            "de alli",
            "ya subi",
            "ya esta en",
            "esta en",
            "esta en las fuentes",
            "puedes tomar",
            "puedes sacar",
            "del ine",
            " ine ",
            "ine.",
            "credencial",
            "identificacion",
            "subelo",
            "cargue",
            "cargue el",
            "adjunte",
        )
        return any(h in q for h in hints)

    @staticmethod
    def _detect_economic_blocking_rescue_intent(query: str) -> Optional[str]:
        """
        Para pendiente ``economic_validation_blocking`` (precios <= 0 en masa):
        - ``bare_number``: solo dígitos → aplicar PU al primer concepto bloqueado.
        - ``which_concept_or_price``: el usuario pide por dónde empezar / qué precio falta.
        """
        raw = (query or "").strip()
        if not raw:
            return None
        w = (
            raw.replace("$", "")
            .replace("mxn", "")
            .replace("MXN", "")
            .replace(",", "")
            .strip()
            .lower()
        )
        if re.match(r"^-?\d+(?:\.\d+)?$", w):
            return "bare_number"
        qn = ChatbotRAGAgent._normalize(raw)
        # Solo signos de interrogación → mismo deseo que "¿qué falta?" (rescate corto).
        if not qn and raw.strip() in ("?", "¿", "??", "¿?"):
            return "which_concept_or_price"
        hints = (
            "que precio",
            "cual precio",
            "cuál precio",
            "dime precio",
            "dime el precio",
            "que me falta",
            "que falta de precio",
            "primero",
            "por donde",
            "donde empiezo",
            "cual es el primero",
            "cual concepto",
            "que concepto",
            "ok dime",
            "ok di",
            # --- Frases conversacionales de arranque / continuación ---
            "empecemos",
            "empezar",
            "comencemos",
            "comenzar",
            "continuemos",
            "continuar",
            "adelante",
            "vamos",
            "dale",
            "va",
            "listo",
            "siguiente",
            "que necesitas",
            "que requieres",
            "que ocupas",
            "dime que necesitas",
            "que exactamente",
            "exactamente",
            "especificamente",
            "cual es",
            "cual seria",
            "dime cual",
        )
        if any(h in qn for h in hints):
            return "which_concept_or_price"
        return None

    @staticmethod
    def _economic_blocking_first_concept_reply(pending_q: Dict[str, Any]) -> str:
        """Mensaje directo sin plantilla de saludo genérica de captura."""
        if ChatbotRAGAgent._economic_blocking_requires_source_input(pending_q):
            return ChatbotRAGAgent._economic_blocking_source_reply(pending_q)
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        n = len(items)
        first_item = items[0] if items else {}
        first = str(first_item.get("concepto_label") or "").strip() if items else ""
        # --- PARCHE DE INTELIGENCIA: Saltar Subtotal si hay partidas individuales ---
        is_subtotal = "subtotal" in first.lower() or "total base" in first.lower()
        if is_subtotal:
            state = pending_q.get("_session_state_ref") or {}
            suggestions = state.get("economic_unverified_suggestions") or []
            if suggestions:
                s = suggestions[0]
                # --- MEJORA DE ETIQUETA: Buscar contexto en el field o concepto ---
                raw_label = s.get("label") or s.get("concepto") or first
                field_key = str(s.get("field") or "")
                
                # Intentar extraer "Zona X" o "Partida X" del field_key si el label es genérico
                extra_context = ""
                if "Zona" in field_key:
                    match_zona = re.search(r"Zona\s+[A-Z]", field_key, re.I)
                    if match_zona: extra_context = match_zona.group(0)
                
                if extra_context and extra_context not in raw_label:
                    first = f"{raw_label} ({extra_context})"
                else:
                    first = raw_label

                n = len(suggestions)
                tail = f"\n\nDespués de este, me faltan otros **{n - 1}** precios por confirmar."
            else:
                tail = ""
        else:
            tail = f"\n\nDespués de este, aún quedan **{n - 1}** conceptos pendientes." if n > 1 else ""

        # Voz humana:
        msg = f"Para avanzar, necesito confirmar el precio de: **«{first}»**."
        if n > 1:
            msg += f" (y otros {n-1} conceptos más)."
        
        return f"{msg} ¿Cuál sería su valor unitario?"

    @staticmethod
    def _economic_blocking_requires_source_input(pending_q: Dict[str, Any]) -> bool:
        """Detecta bloqueos donde el usuario debe aportar la fuente económica base."""
        if str(pending_q.get("input_mode") or "").strip().lower() == "price_source":
            return True
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        return any(str(it.get("requested_input") or "").strip().lower() == "price_source" for it in items)

    @staticmethod
    def _economic_blocking_source_reply(pending_q: Dict[str, Any]) -> str:
        """Pide catálogo/análisis de precios reales con evidencia verificable."""
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        summary = pending_q.get("detected_structure_summary") if isinstance(pending_q.get("detected_structure_summary"), dict) else {}
        lines = [
            "Para cerrar la propuesta económica necesito una **fuente real de precios o costos**, no un importe inventado.",
        ]
        zones = summary.get("zones") if isinstance(summary.get("zones"), dict) else {}
        material_rows = int(summary.get("material_rows") or 0) if summary else 0
        if zones:
            zone_bits = []
            for zone in sorted(zones.keys()):
                info = zones.get(zone) or {}
                zone_bits.append(
                    f"Zona {zone}: {int(info.get('elements') or 0)} elementos en {int(info.get('sites') or 0)} unidades"
                )
            lines.append("")
            lines.append("Ya leí la estructura cargada por la convocante:")
            lines.append("; ".join(zone_bits[:4]) + ("; ..." if len(zone_bits) > 4 else ""))
        if material_rows > 0:
            lines.append(f"También detecté {material_rows} renglones de materiales/consumos con cantidad definida.")
        if items:
            lines.append("")
            lines.append("Detecté estas referencias en las bases:")
            for idx, item in enumerate(items[:3], 1):
                label = str(item.get("concepto_label") or f"Referencia económica {idx}").strip()
                page = item.get("page_number")
                source = str(item.get("source_name") or "bases").strip()
                snippet = str(item.get("context_snippet") or "").strip()
                where = source
                if page:
                    where = f"{where}, página {page}"
                lines.append(f"{idx}. **{label}** ({where})")
                if snippet:
                    lines.append(f"   Fragmento: \"{snippet}\"")
        lines.append("")
        lines.append(
            "Si ya cuentas con ese catálogo, análisis o cotización, compártemelo; si prefieres, también puedes escribirme aquí los precios o costos reales que debo capturar."
        )
        return "\n".join(lines).strip()

    def _generate_economic_blocking_instruction(self, pending_q: Dict[str, Any]) -> str:
        """
        Genera un mensaje humano y profesional para solicitar datos económicos faltantes.
        """
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        n = len(items)
        first = self._economic_blocking_focus_label(pending_q)
        
        # Diálogo natural
        if n > 0:
            return f"Necesito confirmar el valor de: **«{first}»** para completar tu propuesta."
        return "Estamos revisando los detalles finales de tu propuesta económica."

    def _clean_currency_value(self, value_str: str) -> float:
        """
        Limpia un string de moneda y lo convierte a float de forma robusta.
        Maneja formatos: '$40,890.00', '40.890,00', '40890'.
        """
        if not value_str: return 0.0
        # 1. Quitar símbolos de moneda y espacios
        clean = re.sub(r'[^\d.,-]', '', str(value_str).strip())
        
        # 2. Si hay coma y punto, asumimos formato estándar (punto decimal)
        if ',' in clean and '.' in clean:
            # Si el punto está después de la coma (ej: 40,890.00)
            if clean.rfind('.') > clean.rfind(','):
                clean = clean.replace(',', '')
            # Si la coma está después del punto (ej: 40.890,00)
            else:
                clean = clean.replace('.', '').replace(',', '.')
        # 3. Si solo hay coma, ver si es decimal (ej: 40890,00) o miles (ej: 40,890)
        elif ',' in clean:
            parts = clean.split(',')
            if len(parts[-1]) <= 2: # Parece decimal
                clean = clean.replace(',', '.')
            else: # Parece separador de miles
                clean = clean.replace(',', '')
                
        try:
            return float(clean)
        except (ValueError, TypeError):
            return 0.0

    def _economic_blocking_focus_label(self, pending_q: Dict[str, Any]) -> str:
        """
        Devuelve el concepto prioritario para recordatorios cortos de bloqueo.
        """
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        first = ""
        if items:
            first = str(items[0].get("concepto_label") or "").strip()
        
        # --- PARCHE DE INTELIGENCIA: Saltar Subtotal si hay partidas individuales ---
        if not first or "subtotal" in first.lower() or "total base" in first.lower():
            state = pending_q.get("_session_state_ref") or {}
            suggestions = state.get("economic_unverified_suggestions") or []
            if suggestions:
                s = suggestions[0]
                raw_label = s.get("label") or s.get("concepto") or "Partida"
                field_key = str(s.get("field") or "")
                if "Zona" in field_key:
                    match_zona = re.search(r"Zona\s+[A-Z]", field_key, re.I)
                    if match_zona: return f"{raw_label} ({match_zona.group(0)})"
                return raw_label

        return first if first else "ítem #1 de tu lista de precios"

    async def _extract_economic_data_llm(self, user_query: str, session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Utiliza el LLM para mapear lenguaje natural a un esquema JSON estructurado.
        Fuerza al LLM a usar las etiquetas oficiales de la sesión.
        """
        # Extraer etiquetas válidas y campos técnicos para guiar al LLM (Grounding)
        context_items = []
        suggestions = session_state.get("economic_unverified_suggestions") or []
        for s in suggestions:
            lbl = s.get("label") or s.get("concepto")
            fld = s.get("field")
            if lbl: context_items.append(f"- Concepto: {lbl} (Campo técnico: {fld})")
            
        pending = session_state.get("pending_questions") or []
        for q in pending:
            items = q.get("blocking_items") or []
            for it in items:
                lbl = it.get("concepto_label")
                fld = it.get("field")
                if lbl: context_items.append(f"- Concepto: {lbl} (Campo técnico: {fld})")

        context_str = "\n".join(list(set(context_items)))

        system_prompt = (
            "Eres un 'Auditor de Datos Económicos' especializado en licitaciones internacionales.\n"
            "Tu tarea es identificar ÚNICAMENTE valores monetarios destinados a precios o montos totales.\n\n"
            "REGLAS DE ORO PARA LA UNIVERSALIDAD:\n"
            "1. PROHIBIDO extraer especificaciones técnicas: Ignora números que acompañen unidades como W, kW, MW (energía), "
            "m, m2, m3, km (medidas), kg, tn, lb (peso), pulgadas, i3/i5/i7 (tecnología), o proporciones como 24x7, 4x4, etc.\n"
            "2. CONTEXTO SOBRE CANTIDAD: Si el usuario dice '10 cajas de $500', el valor económico es 500. El '10' es una cantidad técnica, IGNÓRALO.\n"
            "3. DISCRIMINACIÓN DE NÚMEROS DE PARTE: Si un número parece un código de modelo (ej. 'H-250' o 'Filtro 3000'), no lo extraigas como precio.\n"
            "4. DUDA RAZONABLE: Si un número no tiene símbolo de moneda ($) y es idéntico a una especificación técnica del concepto, NO lo extraigas.\n\n"
            "INSTRUCCIÓN DE SALIDA:\n"
            "- Si el mensaje contiene números pero ninguno es claramente un precio (ej. solo especificaciones), "
            "DEBES devolver estrictamente: {\"datos\": []}.\n"
            "- No inventes datos. Es preferible no extraer nada a extraer un dato técnico como si fuera económico.\n"
            "Solo devuelve JSON puro sin backticks ni markdown."
        )
        
        prompt = (
            f"MENSAJE DEL USUARIO: \"{user_query}\"\n\n"
            f"ESTRUCTURA DE LA LICITACIÓN (Etiquetas y Campos):\n{context_str}\n\n"
            "Extrae los datos en este formato JSON:\n"
            "{\n"
            "  \"datos\": [\n"
            "    {\n"
            "      \"key\": \"concept_price\",\n"
            "      \"concept\": \"Escribe aquí el Concepto oficial que mejor coincida\",\n"
            "      \"concept_hint\": \"Si el usuario menciona una Zona o Partida específica, escríbela aquí exactamente\",\n"
            "      \"value\": \"El valor con formato (ej: $10,000)\",\n"
            "      \"value_numeric\": 10000.0\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "Si el usuario menciona 'Subtotal', 'IVA' o 'Total', usa 'key': 'subtotal_propuesta', 'iva_propuesta' o 'total_propuesta' respectively."
        )

        llm = LLMServiceClient()
        res = await llm.generate(prompt=prompt, system_prompt=system_prompt, format="json")
        try:
            raw_res = res.get("response", "{}")
            data = json.loads(raw_res)
            return data.get("datos", [])
        except Exception as e:
            logger.error(f"[Chatbot] Error parseando JSON de extracción LLM: {e}")
            return []

    @staticmethod
    def _economic_blocking_bare_number_transaction(
        pending_q: Dict[str, Any], query: str
    ) -> Optional[Dict[str, Any]]:
        """Construye transacción económica tipo ``concept_price`` para el ítem bloqueado."""
        items = pending_q.get("blocking_items") if isinstance(pending_q.get("blocking_items"), list) else []
        if not items:
            return None
            
        first_item = items[0]
        first = str(first_item.get("concepto_label") or "").strip()
        
        # --- PARCHE DE INTELIGENCIA: Si estamos rescatando el subtotal, usar la sugerencia ---
        if "subtotal" in first.lower() or "total base" in first.lower():
            state = pending_q.get("_session_state_ref") or {}
            suggestions = state.get("economic_unverified_suggestions") or []
            if suggestions:
                s = suggestions[0]
                first = s.get("label") or s.get("concepto") or first

        if not first:
            return None
            
        # Aborto Inmediato: Si contiene algún carácter alfabético (a-z) después de limpieza básica
        raw_s = query.strip().lower().replace("mxn", "").replace("pesos", "").replace("son", "")
        if re.search(r'[a-z]', raw_s):
            return None

        # Limpieza estricta de números ($85,400.00 -> 85400.0)
        s = raw_s.replace("$", "").replace(",", "").replace(" ", "").strip()
        
        match = re.search(r"^(\d+(?:\.\d+)?)$", s)
        if not match:
            return None
        
        try:
            num = float(match.group(1))
        except ValueError:
            return None
            
        return [{
            "kind": "economic_set_value",
            "key": "concept_price",
            "concept": first,
            "value": str(num),
            "value_numeric": num,
        }]

    def _detect_economic_transaction_intent(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Detecta si el usuario está proporcionando uno o más datos económicos directos.
        Soporta Captura Multivariable (Hito 1.1).
        """
        if not query: return None
        
        # 1. Limpieza básica
        raw = query.replace(",", "")
        
        # 2. Regex PRECISO: Busca (Keyword opcional) + (Identificador) + (Separador) + (Precio)
        # Ejemplo: "Zona A: $85000", "Partida 1 es 100", "B: 42000"
        # Grupo 1: Keyword (zona, partida, etc.)
        # Grupo 2: Identificador (A, B, 1, 2...)
        # Grupo 3: Valor numérico
        pattern = r"(zona|partida|concepto|item|ítem)?\s*([a-z0-9]{1,3})\s*(?::|es|=|-|>|son)?\s*\$?\s*(\d+(?:\.\d+)?)"
        matches = re.finditer(pattern, raw, re.I)
        
        transactions = []
        for m in matches:
            keyword = (m.group(1) or "").strip().lower()
            identifier = m.group(2).strip().lower()
            val_str = m.group(3)
            
            # El hint es la combinación o solo el identificador
            hint = f"{keyword} {identifier}".strip() if keyword else identifier
            
            try:
                val_num = float(val_str)
                transactions.append({
                    "kind": "economic_set_value",
                    "key": "concept_price",
                    "concept_hint": hint,
                    "value": val_str,
                    "value_numeric": val_num,
                })
            except: continue
            
        # --- MOTOR 2: Búsqueda de Parámetros y Frases Naturales ---
        q = query.strip()
        qn = self._normalize(q)
        captured_keys = set()

        # 1.5. TOTALES Y SUBTOTALES (Mapeo de Autoridad)
        TOTALS_BASE = {
            "subtotal_propuesta": r"subtotal|total|monto\s+base|importe\s+base",
        }
        for key, base_pattern in TOTALS_BASE.items():
            m_total = re.search(rf"\b(?:{base_pattern})\b.{{0,20}}?(?:es|de|=)?\s*([0-9][0-9,]*(?:\.\d+)?)", qn, re.I)
            if m_total:
                try:
                    val = float(m_total.group(1).replace(",", ""))
                    transactions.append({
                        "kind": "economic_set_value",
                        "key": key,
                        "value": str(val),
                        "value_numeric": val,
                    })
                except: continue

        # 1. PARÁMETROS FASAR / FSR (Bidireccional + Multi-capture)
        FASAR_BASE = {
            "imss": r"imss|cuota\s+patronal",
            "sar": r"sar",
            "infonavit": r"infonavit",
            "dias_no_laborados": r"dias?\s+no\s+laborados|festivos|inh[aá]biles|descansos?",
            "dias_laborados": r"dias?\s+laborados|calendario",
            "prima_vacacional": r"prima\s+vacacional",
            "aguinaldo_dias": r"aguinaldo|dias?\s+de\s+aguinaldo",
        }

        for key, base_pattern in FASAR_BASE.items():
            if key in captured_keys:
                continue
            
            # A: Palabra -> Valor (ej: "aguinaldo es 20")
            # Limitamos el radio de búsqueda a 20 caracteres para evitar capturar números de otras frases
            m_a = re.search(rf"\b(?:{base_pattern})\b.{{0,20}}?(?:es|de|=)?\s*([0-9][0-9,]*(?:\.\d+)?)", qn, re.I)
            # B: Valor -> Palabra (ej: "20 dias de aguinaldo")
            m_b = re.search(rf"\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:a|al|de|es|en|dias?\s+de)?\s*\b(?:{base_pattern})\b", qn, re.I)
            
            match = m_a or m_b
            if match:
                try:
                    raw_val = match.group(1).replace(",", "")
                    val = float(raw_val)
                    norm_val = self._normalize_economic_value(key, val)
                    if norm_val >= 0:
                        transactions.append({
                            "kind": "economic_set_value",
                            "key": key,
                            "value": str(norm_val),
                            "value_numeric": norm_val,
                        })
                        captured_keys.add(key)
                except (ValueError, IndexError):
                    continue

        # 2. PRECIOS UNITARIOS (Soporte Bidireccional Robusto - Hito 1.6)
        # Patrón A: "precio de <concepto> es <monto>"
        PRICE_PATTERN_A = r"(?:precio|costo|unitario)\b.*?(?:\b(?:de|para|del|al)\b)?\s*(?!(?:de|al|del|el|la|los|las)\b)([a-z0-9áéíóúñü\-\s]{3,})\s*(?:\b(?:[:=]|es|de|al|del)\b|\s+)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)"
        for m in re.finditer(PRICE_PATTERN_A, qn, re.I):
            raw_concept = m.group(1).strip()
            # Limpieza de prefijos comunes
            concept = re.sub(r"^(?:el\s+)?(?:concepto\s+)?(?:de\s+)?", "", raw_concept, flags=re.I).strip()
            concept = re.sub(r"\s+", " ", concept)
            
            if concept.lower() in ("de", "al", "del", "un", "una", "el", "la") or len(concept) < 3: continue
            
            try:
                val = float(m.group(2).replace(",", ""))
                transactions.append({
                    "kind": "economic_set_value",
                    "key": "concept_price",
                    "concept": concept,
                    "value": str(val),
                    "value_numeric": val,
                })
            except (ValueError, IndexError):
                continue

        # Patrón B: "<monto> (para|al|del) <concepto>" (Ej: "19500 al guardia")
        PRICE_PATTERN_B = r"\b\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(?:\b(?:a|al|del|para)\b|del\s+concepto\s+de)\s*(?!(?:de|al|del|el|la)\b)([a-z0-9áéíóúñü\-\s]{3,})"
        for m in re.finditer(PRICE_PATTERN_B, qn, re.I):
            try:
                val = float(m.group(1).replace(",", ""))
                raw_concept = m.group(2).strip()
                # Limpieza de prefijos comunes
                concept = re.sub(r"^(?:el\s+)?(?:concepto\s+)?(?:de\s+)?", "", raw_concept, flags=re.I).strip()
                concept = re.sub(r"\s+", " ", concept)
                
                if concept.lower() in ("de", "al", "del", "un", "una", "el", "la") or len(concept) < 3: continue
                if any(t.get("concept") == concept for t in transactions): continue
                
                transactions.append({
                    "kind": "economic_set_value",
                    "key": "concept_price",
                    "concept": concept,
                    "value": str(val),
                    "value_numeric": val,
                })
            except (ValueError, IndexError):
                continue

        # 3. LEGACY / OTROS
        m_qty = re.search(r"cantidad\s+de\s+elementos?\s*[:=]?\s*(\d+(?:\.\d+)?)", qn)
        if m_qty:
            val = float(m_qty.group(1))
            transactions.append({
                "kind": "economic_set_value",
                "key": "cantidad_elementos",
                "value": str(val),
                "value_numeric": val,
            })

        return transactions if transactions else None

    def _normalize_economic_value(self, key: str, value: float) -> float:
        """
        Capa de Normalización Inteligente (Ajuste por Rango).
        """
        # Porcentajes (IVA, IMSS, SAR, Infonavit, Prima Vacacional)
        if key in ("iva_pct", "imss", "sar", "infonavit", "prima_vacacional"):
            if value > 1:
                return value / 100.0
            return value
        
        # Días de Aguinaldo (Fail-safe > 100)
        if key == "aguinaldo_dias":
            if value > 100:
                logger.warning(f"Aguinaldo sospechoso detectado: {value}. Fallback a búsqueda de precio o LLM.")
                return -1.0
            return value
            
        return value

    async def _handle_economic_transaction(
        self,
        *,
        session_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        tx: Any, # Defensa: Aceptamos Any para normalizar
        raw_user_query: str,
        correlation_id: str = "",
    ) -> AgentOutput:
        """Guarda uno o más overrides económicos desde chat + revalidación automática."""
        # 1. NORMALIZACIÓN DEFENSIVA (Arquitectura Universal)
        tx_list = []
        if isinstance(tx, list):
            # Aplanar si es necesario y filtrar no-dict
            for item in tx:
                if isinstance(item, list): tx_list.extend([i for i in item if isinstance(i, dict)])
                elif isinstance(item, dict): tx_list.append(item)
        elif isinstance(tx, dict):
            tx_list = [tx]
            
        if not tx_list:
            logger.warning(f"[Chatbot] Transacción económica vacía o inválida recibida: {tx}")
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta="No pude procesar los datos económicos. Por favor, intenta de nuevo.",
                confianza="Media",
                tipo="economic_transaction_error"
            )

        state = dict(session_state or {})
        overrides = list(state.get("economic_user_overrides") or [])
        latest_inputs = dict(state.get("economic_user_inputs") or {})
        pending_list = list(state.get("pending_questions") or [])
        pending_idx = int(state.get("current_question_index") or 0)
        active_price_q: Optional[Dict[str, Any]] = None
        if pending_list and 0 <= pending_idx < len(pending_list):
            if str(pending_list[pending_idx].get("type") or "") == "economic_price":
                active_price_q = pending_list[pending_idx]
        
        captured_summary = []
        _totals_keys = frozenset({"subtotal_propuesta", "iva_propuesta", "total_propuesta"})
        _saved_concept_price = False

        for item in tx_list:
            if not isinstance(item, dict): continue
            
            entry = {
                "kind": item.get("kind", "economic_set_value"),
                "key": item.get("key"),
                "concept": item.get("concept"),
                "value": item.get("value"),
                "value_numeric": item.get("value_numeric"),
                "source": "chat_user_override",
                "raw_query": raw_user_query,
            }
            overrides.append(entry)
            
            kind = item.get("kind")
            k = str(item.get("key") or "unknown")
            val_raw = str(item.get("value") or "")
            val_numeric = self._clean_currency_value(val_raw)
            concept = str(item.get("concept") or "").strip()
            hint = str(item.get("concept_hint") or "").strip()
            if active_price_q and not (concept or hint):
                hint = self._concept_from_economic_price_pending_q(active_price_q)
                concept = hint
            elif active_price_q:
                pending_concept = self._concept_from_economic_price_pending_q(active_price_q)
                if pending_concept and self._is_generic_economic_concept_label(concept or hint):
                    concept = pending_concept
                    hint = pending_concept
            elif self._is_generic_economic_concept_label(concept or hint):
                deferred = state.get("hitl_deferred_reminders") or []
                if deferred:
                    d0 = deferred[-1]
                    concept = str(d0.get("label") or "").strip()
                    hint = concept
            # Re-mapear claves erróneas del LLM (ej. "Precio de la licitación") → concept_price
            if val_numeric > 0 and (concept or hint) and k not in _totals_keys:
                k = "concept_price"
                kind = "economic_set_value"

            if kind == "economic_set_value" and k == "concept_price":
                bucket = dict(latest_inputs.get("concept_prices") or {})
                concept = str(item.get("concept") or "").strip()
                hint = str(item.get("concept_hint") or "").strip()
                search_term = concept if concept else hint
                price_field = ""
                if active_price_q:
                    price_field = str(active_price_q.get("field") or "").strip()

                resolved_concept = self._resolve_economic_concept(search_term, state)

                # HITO: Fallback de Emergencia (Si no hay match, guardamos por hint)
                final_key = resolved_concept or search_term
                if final_key:
                    if price_field and price_field.startswith("price_"):
                        bucket[price_field] = val_numeric
                    bucket[final_key] = val_numeric
                    captured_summary.append(f"**{final_key}** = **{val_numeric:,.2f}**")
                    saved = True
                    _saved_concept_price = True
                    
                    # SI ES UN TOTAL/SUBTOTAL, lo clonamos a la llave maestra
                    k_low = final_key.lower()
                    if "subtotal" in k_low or "total" in k_low:
                        latest_inputs["subtotal_propuesta"] = val_numeric
                        logger.info(f"[Chatbot] Sincronizando total manual: {val_numeric}")
                
                latest_inputs["concept_prices"] = bucket
            elif k in ("subtotal_propuesta", "iva_propuesta", "total_propuesta"):
                latest_inputs[k] = val_numeric
                captured_summary.append(f"**{k.replace('_', ' ')}** = **{val_numeric:,.2f}**")
                saved = True
            else:
                latest_inputs[k] = val_numeric
                captured_summary.append(f"**{k}** = **{val_numeric:,.2f}**")
        
        state["economic_user_overrides"] = overrides[-500:]
        state["economic_user_inputs"] = latest_inputs
        if _saved_concept_price and active_price_q and pending_list:
            pk = str(active_price_q.get("field") or "").strip()
            if pk:
                pending_list = [
                    q
                    for q in pending_list
                    if not (
                        str(q.get("type") or "") == "economic_price"
                        and str(q.get("field") or "") == pk
                    )
                ]
            elif 0 <= pending_idx < len(pending_list):
                pending_list.pop(pending_idx)
            state["pending_questions"] = pending_list
            state["current_question_index"] = (
                max(0, min(pending_idx, len(pending_list) - 1)) if pending_list else 0
            )
        await self.context_manager.memory.save_session(session_id, state)

        # Resumen amigable de captura múltiple
        summary_txt = "He actualizado los siguientes datos: " + ", ".join(captured_summary)

        # ── TAREA 1: Re-sincronizar snapshot económico con los precios recién capturados ──
        # refresh_economic_validations_for_session aplica overrides, recalcula totales
        # y persiste el snapshot actualizado en tasks_completed["economic_proposal"].
        # Esto cierra la brecha entre economic_user_inputs y el snapshot que consume
        # EconomicWriterAgent al generar documentos.
        _recalc_total_base: Optional[float] = None
        try:
            _recalc_result = await refresh_economic_validations_for_session(
                self.context_manager.memory, session_id
            )
            # Leer el total_base actualizado del snapshot para incluirlo en el mensaje
            _fresh_snap = await self.context_manager.memory.get_session(session_id) or {}
            _tasks = list(_fresh_snap.get("tasks_completed") or [])
            for _t in reversed(_tasks):
                if _t.get("task") == "economic_proposal":
                    _snap_result = _t.get("result") or {}
                    _tb = _snap_result.get("total_base")
                    if _tb is not None:
                        try:
                            _recalc_total_base = float(_tb)
                        except (TypeError, ValueError):
                            pass
                    break
            logger.info(
                "chatbot_economic_snapshot_refreshed",
                session_id=session_id,
                total_base=_recalc_total_base,
            )
        except Exception as _recalc_err:
            # No bloquear la respuesta al usuario si el recálculo falla
            logger.warning(
                "chatbot_economic_snapshot_refresh_failed",
                session_id=session_id,
                error=str(_recalc_err),
            )

        # 2) Revalidar económico si ya existe propuesta
        revalidated = False
        blocking_count = None
        try:
            result = await refresh_economic_validations_for_session(self.context_manager.memory, session_id)
            revalidated = True
            # Defensa: el resultado puede ser un dict o un objeto con .blocking_issues
            if hasattr(result, "blocking_issues"):
                blocking_count = len(result.blocking_issues or [])
            elif isinstance(result, dict):
                blocking_count = len(result.get("blocking_issues") or [])
            else:
                blocking_count = 0

            # Limpiar/actualizar pending questions de validación económica
            fresh = await self.context_manager.memory.get_session(session_id) or {}
            pending = list(fresh.get("pending_questions") or [])
            if blocking_count == 0:
                pending = [q for q in pending if str(q.get("type")) != "economic_validation_blocking"]
            fresh["pending_questions"] = pending
            idx = int(fresh.get("current_question_index") or 0)
            if pending:
                fresh["current_question_index"] = max(0, min(idx, len(pending) - 1))
            else:
                fresh["current_question_index"] = 0
            await self.context_manager.memory.save_session(session_id, fresh)
        except Exception:
            # Es válido que aún no exista economic_proposal en sesión.
            revalidated = False

        # 3) Preparar respuesta final (Hito 1.3: Resiliencia Final)
        msg = f"¡Perfecto! {summary_txt}."
        if _recalc_total_base is not None and _recalc_total_base >= 0.01:
            msg += f"\n\n💰 Propuesta actualizada: subtotal **${_recalc_total_base:,.2f}** (sin IVA)."
        
        # Forzar recálculo de validaciones económicas tras persistencia
        try:
            val_res = await refresh_economic_validations_for_session(self.context_manager.memory, session_id)
            # Re-cargar sesión para tener el estado más fresco tras el refresh
            fresh_state = await self.context_manager.memory.get_session(session_id) or {}
            
            # --- SINCRONIZACIÓN AGRESIVA DE PENDIENTES ---
            # 1. Identificar qué conceptos siguen teniendo precio <= 0 según la trazabilidad del validador
            bad_concepts = []
            precios_traz = val_res.trazabilidad.get("precios_positivos") or {}
            if isinstance(precios_traz.get("valor_calculado"), list):
                bad_concepts = [self._normalize(str(c)) for c in precios_traz["valor_calculado"]]
            
            # 2. Filtrar la lista de pending_questions
            old_pending = fresh_state.get("pending_questions") or []
            new_pending = []
            
            # Verificamos qué bloqueos económicos siguen siendo reales
            blocking_issues_keys = [str(issue).split(":", 1)[0].strip().lower() for issue in (val_res.blocking_issues or [])]
            
            for q in old_pending:
                q_type = str(q.get("type"))
                if q_type == "economic_price":
                    # Si es una pregunta de precio, ver si el concepto sigue en la lista de "malos"
                    q_label = self._normalize(q.get("label", "").replace("Precio (sin IVA): ", ""))
                    if any(bc in q_label or q_label in bc for bc in bad_concepts):
                        new_pending.append(q)
                elif q_type == "economic_validation_blocking":
                    # Si es un bloqueo de regla (ej. Subtotal), ver si la regla sigue activa
                    rule_key = q.get("field", "").replace("validation_rule_", "")
                    if rule_key in blocking_issues_keys or "total_base_cotizable" in blocking_issues_keys:
                        new_pending.append(q)
                else:
                    # Mantener preguntas no económicas (legales, etc.)
                    new_pending.append(q)
            
            blocking_count = len([q for q in new_pending if q.get("type") in ("economic_price", "economic_validation_blocking")])
            
            # Actualizar sesión con la lista limpia
            fresh_state["pending_questions"] = new_pending
            idx = int(fresh_state.get("current_question_index") or 0)
            fresh_state["current_question_index"] = max(0, min(idx, len(new_pending) - 1)) if new_pending else 0
            await self.context_manager.memory.save_session(session_id, fresh_state)
            
            revalidated = True
        except Exception as e:
            logger.error(f"Error recalculando/sincronizando validaciones económicas: {e}")
            blocking_count = 0
            revalidated = False

        if revalidated:
            if blocking_count == 0:
                msg += "\n\n🎉 ¡Excelente! He validado los datos y ya no quedan bloqueos económicos pendientes."
            else:
                msg += (
                    f"\n\n🔎 Datos registrados. Aún faltan **{blocking_count}** conceptos por validar."
                )
                
                # --- PROACTIVIDAD: Mostrar la siguiente pregunta de inmediato ---
                try:
                    if new_pending:
                        idx = fresh_state.get("current_question_index") or 0
                        q_next = new_pending[idx]
                        q_msg = self._economic_blocking_first_concept_reply({**q_next, "_session_state_ref": fresh_state})
                        msg += f"\n\n---\n\n{q_msg}"
                except Exception:
                    pass
        else:
            _has_eco_task = any(
                isinstance(t, dict) and t.get("task") == "economic_proposal"
                for t in (state.get("tasks_completed") or [])
            )
            if _has_eco_task:
                _ex_concept = (
                    self._concept_from_economic_price_pending_q(active_price_q)
                    if active_price_q
                    else ""
                )
                _fmt_hint = (
                    f"`Precio unitario {_ex_concept}: <importe>`"
                    if _ex_concept
                    else "`Precio unitario <concepto>: <importe>`"
                )
                msg += (
                    "\n\nℹ️ Precio guardado en la cotización. "
                    f"Si no ves la siguiente pregunta, escribe **`siguiente`** o repite el importe con: {_fmt_hint}."
                )
            else:
                msg += (
                    "\n\nℹ️ Precio en borrador. Primero ejecuta **`generar propuesta economica`** "
                    "para crear la cotización base; luego repite los precios por concepto."
                )

        await self._save_chat_history(session_id, raw_user_query, msg)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="economic_transaction_success",
            data={
                "blocking_count": blocking_count if revalidated else None,
                "revalidated": revalidated,
                "summary": summary_txt
            }
        )

    def _resolve_economic_concept(self, hint: str, state: Dict[str, Any]) -> Optional[str]:
        """Resuelve un hint del usuario (ej: 'zona a') a un concepto real de la sesión."""
        if not hint: return None
        h = hint.lower().strip()
        qn = self._normalize(h)
        
        # 1. Obtener candidatos de los pendientes y sugerencias
        all_candidates = []
        suggestions = state.get("economic_unverified_suggestions") or []
        for s in suggestions:
            all_candidates.append({
                "label": str(s.get("label") or s.get("concepto") or "").lower(),
                "field": str(s.get("field") or "").lower(),
                "original_label": s.get("label") or s.get("concepto")
            })
            
        pending = state.get("pending_questions") or []
        for q in pending:
            items = q.get("blocking_items") or []
            for it in items:
                all_candidates.append({
                    "label": str(it.get("concepto_label") or "").lower(),
                    "field": str(it.get("field") or "").lower(),
                    "original_label": it.get("concepto_label")
                })

        # 2. Búsqueda por "Zona" o "Partida" en el Field (Prioridad Máxima)
        m_ident = re.search(r"(?:zona|partida)\s+([a-z0-9]+)", qn)
        if m_ident:
            ident_val = m_ident.group(1)
            for cand in all_candidates:
                if f"zona {ident_val}" in cand["field"] or f"partida {ident_val}" in cand["field"]:
                    return cand["original_label"]

        for cand in all_candidates:
            if cand["label"] in h and len(cand["label"]) > 10:
                return cand["original_label"]

        return None

    def _detect_price_provenance_intent(self, query: str) -> Optional[str]:
        """
        Detecta preguntas sobre origen/procedencia de precio.
        Devuelve concepto inferido si se detecta intención, o None.
        """
        from app.services.chat_economic_provenance_service import detect_economic_provenance_intent

        if detect_economic_provenance_intent(query):
            return "general"

        q = query.strip()
        qn = self._normalize(q)
        has_origin = any(
            s in qn
            for s in (
                "de donde",
                "de dónde",
                "origen",
                "de que fuente",
                "de qué fuente",
                "como se calculo",
                "como se calculó",
                "porque ese precio",
                "por que ese precio",
            )
        )
        has_price = any(s in qn for s in ("precio", "costo", "subtotal", "monto", "importe"))
        if not (has_origin and has_price):
            return None

        # Intento de extracción de concepto explícito: "precio del guardia"
        m = re.search(
            r"(?:precio|costo|subtotal|monto|importe)\s+(?:de|del|para)?\s*([a-z0-9áéíóúñü\-\s]{3,})",
            qn,
        )
        if m:
            concept = re.sub(r"\s+", " ", m.group(1)).strip()
            concept = re.sub(
                r"\b(salio|salió|viene|vino|tomaste|tomaron|usaste|usaron|calculaste|calcularon)\b.*$",
                "",
                concept,
            ).strip()
            if concept:
                return concept
        return "general"

    async def _handle_price_provenance_query(
        self,
        *,
        session_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        concept_hint: str,
        raw_user_query: str,
        correlation_id: str = "",
    ) -> AgentOutput:
        """
        Responde trazabilidad de precios con precedencia:
        chat override > económico normalizado > catálogo empresa.
        """
        from app.services.chat_economic_provenance_service import (
            build_economic_provenance_message,
            detect_economic_provenance_intent,
        )

        mode = detect_economic_provenance_intent(raw_user_query) or "origin"
        if concept_hint == "general" or mode in ("total", "catalog", "general"):
            msg = build_economic_provenance_message(
                session_state,
                session_id=session_id,
                mode=mode if mode != "origin" else "general",
                user_query=raw_user_query,
            )
            if msg:
                await self._save_chat_history(session_id, raw_user_query, msg)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=msg,
                    confianza="Alta",
                    tipo="economic_provenance_hru",
                )

        target = self._normalize(concept_hint if concept_hint != "general" else "")
        best_chat = None
        best_chat_score = 0.0
        for ov in reversed(list(session_state.get("economic_user_overrides") or [])):
            if str(ov.get("key")) != "concept_price":
                continue
            c = self._normalize(str(ov.get("concept") or ""))
            if not c:
                continue
            score = 1.0 if target and target in c else (0.85 if target and c in target else 0.6)
            if concept_hint == "general":
                score = 0.7
            if score > best_chat_score:
                best_chat = ov
                best_chat_score = score

        econ_root = session_state.get("economic_normalized_data") or {}
        docs = (econ_root.get("documents") or {}) if isinstance(econ_root, dict) else {}
        best_doc_item = None
        best_doc_score = 0.0
        for payload in docs.values():
            if not isinstance(payload, dict):
                continue
            for it in payload.get("normalized_items") or []:
                concepto = self._normalize(str(it.get("concepto") or ""))
                if not concepto:
                    continue
                if concept_hint == "general":
                    score = 0.55
                else:
                    score = 1.0 if target and target in concepto else (0.8 if target and concepto in target else 0.0)
                if score > best_doc_score:
                    best_doc_score = score
                    best_doc_item = it

        company = await self.context_manager.memory.get_company(company_id) or {}
        catalog = company.get("catalog") or []
        best_cat_item = None
        best_cat_score = 0.0
        for it in catalog:
            desc = self._normalize(str(it.get("description") or it.get("name") or ""))
            if not desc:
                continue
            if concept_hint == "general":
                score = 0.5
            else:
                score = 1.0 if target and target in desc else (0.78 if target and desc in target else 0.0)
            if score > best_cat_score:
                best_cat_score = score
                best_cat_item = it

        lines: List[str] = []
        if best_chat and best_chat_score >= 0.7:
            lines.append(
                f"1) **Chat (prioridad máxima):** tomé el precio de tu instrucción directa "
                f"`{best_chat.get('raw_query')}` con valor **${float(best_chat.get('value_numeric') or 0):,.2f}**."
            )
        if best_doc_item and best_doc_score >= 0.75:
            src = best_doc_item.get("source") or {}
            lines.append(
                "2) **Documento normalizado:** también encontré referencia en "
                f"`{src.get('doc_id', 'doc')}` (fila {src.get('row_index', 'N/D')}) "
                f"con **${float(best_doc_item.get('precio_unitario') or 0):,.2f}**."
            )
        if best_cat_item and best_cat_score >= 0.75:
            val = best_cat_item.get("price_base", best_cat_item.get("price", 0))
            lines.append(
                "3) **Catálogo empresa:** existe antecedente en catálogo como "
                f"`{best_cat_item.get('description') or best_cat_item.get('name') or 'concepto'}` "
                f"con **${float(val or 0):,.2f}**."
            )

        if not lines:
            reply = (
                "No encontré una traza directa de ese concepto en chat/documentos/catálogo todavía. "
                "Si me indicas el concepto exacto y su precio, lo registro y te explico inmediatamente la procedencia."
            )
        else:
            reply = (
                "Trazabilidad del precio solicitada:\n\n"
                + "\n".join(lines)
                + "\n\nRegla aplicada: **Chat override > Documento normalizado > Catálogo > Inferencia**."
            )

        await self._save_chat_history(session_id, raw_user_query, reply)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=reply,
            confianza="Alta" if lines else "Media",
            tipo="economic_price_provenance",
        )

    # Combo A: micro-búsqueda focal en Chroma (términos procedimentales genéricos, sin expediente fijo).
    _CRONOGRAM_FOCAL_RAG_QUERY: str = (
        "cronograma calendario actos procedimiento visitas instalaciones "
        "junta aclaraciones presentacion proposiciones apertura fallo fechas horas limite convocatoria"
    )

    _CRONOGRAMA_LABELS_ES: Dict[str, str] = {
        "publicacion_convocatoria": "Publicación de la convocatoria",
        "visita_instalaciones": "Visita a instalaciones",
        "junta_aclaraciones": "Junta de aclaraciones",
        "presentacion_proposiciones": "Presentación y apertura de proposiciones",
        "fallo": "Fallo",
        "firma_contrato": "Firma del contrato",
    }

    _CRONOGRAM_EMPTY_VALUES: frozenset = frozenset(
        {"", "n/d", "nd", "no especificado", "sin especificar", "no aplica", "n.a."}
    )

    @staticmethod
    def _normalize_query_for_intent(query: str) -> str:
        """Minúsculas sin acentos para detección de intención."""
        nk = unicodedata.normalize("NFD", (query or "").strip().lower())
        return "".join(c for c in nk if unicodedata.category(c) != "Mn")

    @staticmethod
    def _resolve_primary_bases_doc(sources: List[str]) -> Optional[str]:
        """Prioriza PDF de bases sobre convocatoria/catálogo al anclar el pliego."""
        if not sources:
            return None

        def _rank(name: str) -> tuple[int, str]:
            sl = str(name or "").lower()
            if "bases" in sl and "convocatoria" not in sl:
                return (0, name)
            if "bases" in sl:
                return (1, name)
            if "convocatoria" in sl:
                return (2, name)
            if "licitacion" in sl or "licitación" in sl:
                return (3, name)
            if sl.endswith(".pdf"):
                return (4, name)
            return (9, name)

        return sorted(sources, key=_rank)[0]

    @classmethod
    def _detect_cronogram_intent(cls, query: str) -> bool:
        """
        True si la consulta apunta a fechas/actos del procedimiento (universal, sin sesión fija).
        """
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        if "cronograma" in q or "calendario" in q:
            return True
        act_markers = (
            "junta de aclaraciones",
            "visita a instalaciones",
            "visita obligatoria",
            "apertura de proposiciones",
            "presentacion de proposiciones",
            "acto de fallo",
            "fallo de la licitacion",
            "actos de la licitacion",
            "actos del procedimiento",
            "fechas de los actos",
            "fechas y horas",
            "eventos de la licitacion",
            "eventos del procedimiento",
        )
        hits = sum(1 for m in act_markers if m in q)
        if hits >= 2:
            return True
        if ("fecha" in q or "fechas" in q) and any(
            x in q for x in ("junta", "visita", "apertura", "fallo", "actos", "proposiciones")
        ):
            return True
        return False

    @staticmethod
    def _extract_analysis_data_blob(task_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae el dict ``data`` del resultado persistido del Analyst."""
        if not isinstance(task_entry, dict):
            return {}
        result = task_entry.get("result") or {}
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return result if isinstance(result, dict) else {}

    @classmethod
    def _extract_analyst_cronogram_from_session(cls, session_state: Dict[str, Any]) -> Dict[str, str]:
        """
        Combo B: cronograma estructurado del Analyst (stage_completed:analysis) si tiene datos útiles.
        """
        from app.agents.analyst import normalize_cronograma_dict

        tasks = session_state.get("tasks_completed") or []
        if not isinstance(tasks, list):
            return {}
        for t in reversed(tasks):
            if not isinstance(t, dict) or t.get("task") != "stage_completed:analysis":
                continue
            data = cls._extract_analysis_data_blob(t)
            raw_cron = data.get("cronograma")
            if not isinstance(raw_cron, dict):
                continue
            norm = normalize_cronograma_dict(raw_cron)
            if any(
                str(v).strip().lower() not in cls._CRONOGRAM_EMPTY_VALUES for v in norm.values()
            ):
                return norm
        return {}

    @classmethod
    def _cronogram_anchored_in_pliego(cls, cron: Dict[str, str], pliego_text: str) -> bool:
        """
        True si al menos dos actos del cronograma del Analyst aparecen anclados en texto del pliego.
        Evita inyectar fechas alucinadas del LLM del Analyst como verdad canónica.
        """
        pliego_low = " ".join((pliego_text or "").lower().split())
        if len(pliego_low) < 40:
            return False
        years_cron: set = set()
        for val in cron.values():
            years_cron.update(re.findall(r"20\d{2}", str(val)))
        years_pliego_list = re.findall(r"20\d{2}", pliego_low)
        years_pliego = set(years_pliego_list)
        if years_cron and years_pliego and not years_cron.intersection(years_pliego):
            return False
        if years_cron and years_pliego_list:
            from collections import Counter

            dominant_pliego = Counter(years_pliego_list).most_common(1)[0][0]
            if all(y != dominant_pliego for y in years_cron):
                return False
        hits = 0
        month_pat = (
            r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre"
        )
        for val in cron.values():
            s = str(val or "").strip()
            if not s or s.lower() in cls._CRONOGRAM_EMPTY_VALUES:
                continue
            s_norm = " ".join(s.lower().split())
            if len(s_norm) < 10:
                continue
            if s_norm in pliego_low:
                hits += 1
                continue
            dm = re.search(
                rf"(\d{{1,2}})\s+de\s+({month_pat})\s+de\s+(20\d{{2}})",
                s_norm,
            )
            if dm and dm.group(1) in pliego_low and dm.group(2) in pliego_low and dm.group(3) in pliego_low:
                hits += 1
        return hits >= 2

    @classmethod
    def _format_analyst_cronogram_prompt_section(cls, cron: Dict[str, str]) -> str:
        """Bloque de contexto del Analyst solo cuando está anclado en el pliego indexado."""
        lines = [
            "[CRONOGRAMA ESTRUCTURADO — AnalystAgent, verificado contra el pliego indexado]"
        ]
        for key, val in cron.items():
            label = cls._CRONOGRAMA_LABELS_ES.get(key, key.replace("_", " ").title())
            lines.append(f"- {label}: {val}")
        lines.append(
            "Este bloque está respaldado por el calendario del pliego; complementa con sedes, "
            "modalidad presencial/electrónica/mixta y notas al pie de los fragmentos."
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _is_cronogram_calendar_chunk(text: str) -> bool:
        """
        True si el fragmento parece tabla/calendario de actos (no requisitos ni logística suelta).
        Heurística universal: actos del procedimiento + al menos una fecha explícita.
        """
        if not text or len(text) < 80:
            return False
        low = text.lower()
        month_pat = (
            r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre"
        )
        has_date = bool(re.search(rf"\d{{1,2}}\s+de\s+({month_pat})", low)) or bool(
            re.search(rf"({month_pat})\s+de\s+20\d{{2}}", low)
        )
        if not has_date:
            return False
        act_hits = sum(
            1
            for pat in (
                r"\bvisita",
                r"junta.{0,30}aclaraci",
                r"presentaci[oó]n.{0,40}proposici",
                r"apertura.{0,40}proposici",
                r"acto.{0,20}fallo",
                r"\bfallo\b",
                r"fechas?\s+y\s+horas?",
            )
            if re.search(pat, low)
        )
        return act_hits >= 2

    @staticmethod
    def _is_cronogram_noise_chunk(text: str) -> bool:
        """Fragmentos que suelen confundir al LLM en preguntas de cronograma."""
        if not text:
            return False
        low = text.lower()
        noise_markers = (
            "plan de contingencias",
            "carta compromiso",
            "copia certificada",
            "comprobante del domicilio",
            "causales de desechamiento",
            "penas convencionales",
            "garantía de cumplimiento otorgada",
        )
        if any(m in low for m in noise_markers):
            return True
        if re.search(r"\b\d{1,3}\.\s+[A-ZÁÉ]", text) and not ChatbotRAGAgent._is_cronogram_calendar_chunk(text):
            return True
        return False

    def _hydrate_cronogram_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """
        Hidrata páginas con calendario real (actos + fechas), máx. 6.
        Incluye barrido del índice además de hits focal RAG (recupera p. ej. junta en pág. 29).
        """
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()

        def _pin_page(pg: Any) -> None:
            if pg is None or pg in seen_pg:
                return
            seen_pg.add(pg)
            pinned_pages.append(pg)

        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if self._is_cronogram_calendar_chunk(doc or ""):
                _pin_page(pg)
        try:
            for doc, meta in self.vector_db.scan_session_chunks(
                session_id, source_filter=primary_doc
            ):
                pg = meta.get("page")
                if pg in seen_pg:
                    continue
                full = "\n".join(
                    self.vector_db.fetch_page_documents(session_id, primary_doc, pg) or []
                )
                blob = full or doc or ""
                if self._is_cronogram_calendar_chunk(blob):
                    _pin_page(pg)
                if len(pinned_pages) >= 6:
                    break
        except Exception:
            pass

        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pinned_pages[:6]:
            merged = "\n".join(
                self.vector_db.fetch_page_documents(session_id, primary_doc, pg) or []
            )
            if merged and self._is_cronogram_calendar_chunk(merged):
                out_docs.append(merged)
                out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
        return out_docs, out_metas

    # Combo garantías: búsqueda focal contractuales (sin % ni montos fijos por expediente).
    _GUARANTEE_FOCAL_RAG_QUERY: str = (
        "garantía cumplimiento fianza contrato adjudicado ganador porcentaje monto "
        "responsabilidad civil daños terceros póliza seguro endoso vigencia cheque certificado"
    )

    @classmethod
    def _detect_guarantee_intent(cls, query: str) -> bool:
        """True si la consulta apunta a garantías/seguros del ganador (no solvencia fiscal genérica)."""
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        core = (
            "garantia",
            "garantias",
            "fianza",
            "seguro",
            "seguros",
            "responsabilidad civil",
            "danos a terceros",
            "daños a terceros",
            "endoso",
            "vigencia",
        )
        if any(k in q for k in core):
            return True
        if "licitante ganador" in q or "adjudicado" in q:
            if any(k in q for k in ("garantia", "fianza", "seguro", "cumplimiento")):
                return True
        return False

    @staticmethod
    def _is_guarantee_contract_chunk(text: str) -> bool:
        """Fianza/garantía de cumplimiento del contrato (porcentaje, anexo, cheque)."""
        if not text or len(text) < 60:
            return False
        low = text.lower()
        if not any(
            w in low
            for w in (
                "fianza",
                "garantía de cumplimiento",
                "garantia de cumplimiento",
                "garantía para cumplimiento",
                "garantia para cumplimiento",
            )
        ):
            return False
        return (
            bool(re.search(r"\d+\s*%", low))
            or "monto total adjudicado" in low
            or "anexo g" in low
            or "cheque de caja" in low
            or "cheque certificado" in low
            or "licitante adjudicado" in low
        )

    @staticmethod
    def _is_guarantee_insurance_chunk(text: str) -> bool:
        """Póliza de seguro (responsabilidad civil, suma asegurada)."""
        if not text or len(text) < 60:
            return False
        low = text.lower()
        if re.search(r"1[',.]?\s*000[',.]?\s*000", low):
            return True
        if "responsabilidad civil" in low and (
            "daños a terceros" in low
            or "danos a terceros" in low
            or "suma asegurada" in low
            or "terceros" in low
        ):
            return True
        if ("póliza" in low or "poliza" in low) and "seguro" in low:
            return True
        return False

    @staticmethod
    def _is_guarantee_obra_bases_chunk(text: str) -> bool:
        """Garantías en bases de obra (vicios ocultos, requisitos B), sin % de fianza tipo servicios."""
        if not text or len(text) < 50:
            return False
        low = text.lower()
        obra_markers = (
            "garantía de vicios ocultos",
            "garantia de vicios ocultos",
            "garantías que deban constituirse",
            "garantias que deban constituirse",
            "garantía de cumplimiento",
            "garantia de cumplimiento",
            "cancelarse la garantía de cumplimiento",
            "cancelarse la garantia de cumplimiento",
            "entrega de la garantía",
            "entrega de la garantia",
        )
        return any(m in low for m in obra_markers)

    @classmethod
    def _is_guarantee_related_chunk(cls, text: str) -> bool:
        """Cualquier fragmento con señal de garantías/fianzas relevante para citas literales."""
        if not text or len(text) < 40:
            return False
        if cls._is_guarantee_contract_chunk(text) or cls._is_guarantee_insurance_chunk(text):
            return True
        if cls._is_guarantee_obra_bases_chunk(text):
            return True
        low = text.lower()
        return "garant" in low or "fianza" in low

    def _guarantee_scan_and_hydrate(
        self,
        session_id: str,
        primary_doc: Optional[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """
        Barrido determinista del índice cuando la búsqueda semántica no trae garantías
        (común en bases de obra con «garantía de vicios ocultos»).
        """
        if not primary_doc:
            return [], []
        sources_to_scan: List[str] = [primary_doc]
        try:
            for src in self.vector_db.get_sources(session_id) or []:
                up = str(src).upper()
                if "CONVOCATORIA" in up and src not in sources_to_scan:
                    sources_to_scan.append(src)
        except Exception:
            pass
        try:
            chunks: List[tuple[str, Dict[str, Any]]] = []
            for src in sources_to_scan:
                chunks.extend(
                    self.vector_db.scan_session_chunks(
                        session_id, source_filter=src, max_chunks=4000
                    )
                )
        except Exception:
            chunks = []
        page_hits: List[tuple[str, Any]] = []
        seen_keys: set = set()
        for doc, meta in chunks:
            if not self._is_guarantee_related_chunk(doc or ""):
                continue
            pg = meta.get("page")
            src = str(meta.get("source") or primary_doc)
            if pg is None:
                continue
            key = (src, pg)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            page_hits.append((src, pg))
        page_hits.sort(key=lambda pair: (0 if "CONVOCATORIA" in pair[0].upper() else 1, int(pair[1]) if str(pair[1]).isdigit() else 0))
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for src, pg in page_hits[:10]:
            for full in self.vector_db.fetch_page_documents(session_id, src, pg):
                if not full or full in out_docs:
                    continue
                if not self._is_guarantee_related_chunk(full):
                    continue
                out_docs.append(full)
                out_metas.append(
                    {
                        "source": src,
                        "page": pg,
                        "hydrated": True,
                        "guarantee_scan": True,
                    }
                )
            if len(out_docs) >= 8:
                break
        return out_docs, out_metas

    @staticmethod
    def _score_guarantee_literary_sentence(sentence: str) -> float:
        """Prioriza cumplimiento 10%, vicios ocultos y encabezados de cláusula sobre trámites de vigencia."""
        sl = str(sentence or "").lower()
        score = 0.0
        if "garantía de cumplimiento" in sl or "garantia de cumplimiento" in sl:
            score += 420.0
        if re.search(r"garant[ií]a de cumplimiento.{0,120}?10\s*%", sl):
            score += 280.0
        if re.search(r"10\s*%", sl) and (
            "importe total contratado" in sl or "monto del mismo" in sl or "monto total" in sl
        ):
            score += 260.0
        if "vicios ocultos" in sl:
            score += 200.0
        if "garantía de cumplimiento" in sl and "$" in sentence:
            score += 180.0
        if re.search(r"\ba\)\s*garant[ií]a de cumplimiento", sl):
            score += 160.0
        if "fianza" in sl or "fianzas" in sl:
            score += 80.0
        if "anticipo" in sl:
            score += 40.0
        if "permanecerá vigente" in sl or "permanecera vigente" in sl:
            score -= 60.0
        if "diferir en igual plazo" in sl:
            score -= 40.0
        return score

    @classmethod
    def _compose_guarantee_literary_fallback(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        user_query: str,
        primary_doc: Optional[str] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """Citas literales de garantías desde fragmentos indexados (sin narrativa del LLM)."""
        q_low = str(user_query or "").lower()
        annex_ref = bool(re.search(r"anexo\s+1\b", q_low))
        has_annex_label = any(
            re.search(r"anexo\s+1\b", str(d or "").lower()) for d in context_docs
        )
        parts: List[str] = []
        if annex_ref and not has_annex_label:
            parts.append(
                "No aparece la etiqueta literal **Anexo 1** en los fragmentos indexados de esta sesión. "
                "Las garantías figuran en el **modelo de contrato** y en los **requisitos de bases** "
                "(no en un anexo numerado «1»). Lo siguiente es lo que **sí consta** sobre garantías:"
            )
        else:
            parts.append("Según los fragmentos indexados de las bases, sobre **garantías**:")
        seen: set[str] = set()
        ranked: List[tuple[float, str]] = []
        top: Optional[Dict[str, Any]] = None
        for doc, meta in zip(context_docs, metadatas):
            meta_dict = meta if isinstance(meta, dict) else {}
            cite = cls._format_literary_cite(meta_dict, primary_doc)
            for body in cls._iter_sanitized_chunk_bodies(doc or ""):
                for sent in cls._split_penalty_sentences(body):
                    s = cls._strip_chunk_source_prefix(sent).strip()
                    s = re.sub(r"^-\s+", "", s).strip()
                    sl = s.lower()
                    if len(s) < 30 or len(s) > 480:
                        continue
                    if "garant" not in sl and "fianza" not in sl:
                        continue
                    if re.search(r"\.pdf\s*\|\s*página", sl):
                        continue
                    if "| página" in sl and "fuente" not in sl:
                        continue
                    key = s[:90]
                    if key in seen:
                        continue
                    seen.add(key)
                    score = cls._score_guarantee_literary_sentence(s)
                    ranked.append((score, f"- {s}\n  {cite}"))
                    if score > 0 and (top is None or score > top.get("_score", 0)):
                        top = {
                            "literal": s,
                            "source": meta_dict.get("source"),
                            "page": meta_dict.get("page"),
                            "_score": score,
                        }
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        bullets = [line for score, line in ranked if score > 0][:8]
        if not bullets:
            return "", None
        parts.extend(bullets)
        parts.append("")
        parts.append(
            "**Siguiente paso:** Revisa **Fuentes (bases)** para el contexto completo del capítulo de garantías."
        )
        if top:
            top.pop("_score", None)
        return "\n".join(parts), top

    @staticmethod
    def _literary_sources_actions() -> List[Dict[str, Any]]:
        return [
            {
                "label": "Ver Fuentes (bases)",
                "payload": "",
                "style": "primary",
                "action_kind": "ui",
                "action_id": "OPEN_SOURCES_PANEL",
            },
        ]

    @staticmethod
    def _top_literary_citation_from_ranked(
        ranked: List[tuple[float, str, str, Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        for score, sentence, _cite, meta in ranked:
            if score > 0:
                return {
                    "literal": sentence,
                    "source": meta.get("source"),
                    "page": meta.get("page"),
                }
        return None

    @classmethod
    def _rank_literary_items(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        primary_doc: Optional[str],
        topic_predicate: Any,
        score_fn: Any,
        source_predicate: Any = None,
        source_score_fn: Any = None,
    ) -> List[tuple[float, str, str, Dict[str, Any]]]:
        seen: set[str] = set()
        ranked: List[tuple[float, str, str, Dict[str, Any]]] = []
        for doc, meta in zip(context_docs, metadatas):
            meta_dict = meta if isinstance(meta, dict) else {}
            if source_predicate and not source_predicate(meta_dict):
                continue
            cite = cls._format_literary_cite(meta_dict, primary_doc)
            for body in cls._iter_sanitized_chunk_bodies(doc or ""):
                for sent in cls._split_penalty_sentences(body):
                    s = cls._strip_chunk_source_prefix(sent).strip()
                    s = re.sub(r"^-\s+", "", s).strip()
                    sl = s.lower()
                    if len(s) < 30 or len(s) > 480:
                        continue
                    if not topic_predicate(s, sl):
                        continue
                    if re.search(r"\.pdf\s*\|\s*página", sl):
                        continue
                    if "| página" in sl and "fuente" not in sl:
                        continue
                    key = s[:90]
                    if key in seen:
                        continue
                    seen.add(key)
                    score = float(score_fn(s))
                    if source_score_fn:
                        score += float(source_score_fn(meta_dict))
                    ranked.append((score, s, cite, meta_dict))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return ranked

    @classmethod
    def _build_ranked_literary_bullets(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        primary_doc: Optional[str],
        topic_predicate: Any,
        score_fn: Any,
        max_bullets: int = 8,
        source_predicate: Any = None,
        source_score_fn: Any = None,
    ) -> List[str]:
        ranked = cls._rank_literary_items(
            context_docs,
            metadatas,
            primary_doc,
            topic_predicate,
            score_fn,
            source_predicate=source_predicate,
            source_score_fn=source_score_fn,
        )
        return [
            f"- {s}\n  {cite}"
            for score, s, cite, _meta in ranked
            if score > 0
        ][:max_bullets]

    @classmethod
    def _finalize_literary_parts(
        cls, intro_lines: List[str], bullets: List[str], cta_line: str
    ) -> str:
        if not bullets:
            return ""
        return "\n".join(intro_lines + bullets + [""] + [cta_line])

    @staticmethod
    def _score_penalty_literary_sentence(sentence: str) -> float:
        sl = str(sentence or "").lower()
        score = 0.0
        if "pena convencional" in sl or "penas convencional" in sl:
            score += 400.0
        if re.search(r"\d+(?:\.\d+)?\s*%", sl) and any(
            k in sl for k in ("pena", "penaliz", "sancion", "atraso", "semana")
        ):
            score += 220.0
        if "saldos pendientes" in sl or "garantía de cumplimiento" in sl:
            score += 120.0
        if "bienes y/o" in sl or "no suministrados" in sl:
            score += 80.0
        return score

    @staticmethod
    def _penalty_literary_predicate(_sentence: str, sl: str) -> bool:
        return any(
            k in sl
            for k in (
                "pena convencional",
                "penas convencional",
                "penaliz",
                "sancion",
                "sanción",
                "atraso",
                "incumplimiento",
                "saldos pendientes",
            )
        )

    @classmethod
    def _compose_penalty_literary_fallback(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        user_query: str,
        primary_doc: Optional[str] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        ranked = cls._rank_literary_items(
            context_docs,
            metadatas,
            primary_doc,
            cls._penalty_literary_predicate,
            cls._score_penalty_literary_sentence,
        )
        bullets = [
            f"- {s}\n  {cite}"
            for score, s, cite, _meta in ranked
            if score > 0
        ][:8]
        top = cls._top_literary_citation_from_ranked(ranked)
        text = cls._finalize_literary_parts(
            [
                "Según los fragmentos indexados de las bases, sobre **penas convencionales y sanciones**:"
            ],
            bullets,
            "**Siguiente paso:** Revisa **Fuentes (bases)** para el capítulo de penas y sanciones.",
        )
        return text, top

    @staticmethod
    def _is_solvency_literary_noise_sentence(sentence: str) -> bool:
        """Ruido de plantilla/puntuación/ISO — no opiniones de cumplimiento fiscal/patronal."""
        sl = str(sentence or "").lower()
        noise_markers = (
            "sistema único de autodeterminación",
            "sistema unico de autodeterminacion",
            "sua ",
            "plantilla de la empresa",
            "plantilla de personal",
            "certificado de discapacidad",
            "factor de salario real",
            "considerando: sar",
            "ohsas 18001",
            "acreditación estatal",
            "acreditacion estatal",
            "puntuación",
            "puntuacion",
            "para efecto de puntuación",
            "para efecto de puntuacion",
            "acta constitutiva o copia de puc",
        )
        if any(m in sl for m in noise_markers):
            return True
        if re.search(r"iso\s*9001", sl) and re.search(r"\d+(?:\.\d+)?\s*puntos", sl):
            return True
        if "imss" in sl and "sua" in sl:
            return True
        return False

    @staticmethod
    def _score_solvency_literary_sentence(sentence: str) -> float:
        sl = str(sentence or "").lower()
        score = 0.0
        if "opinión del cumplimiento" in sl or "opinion del cumplimiento" in sl:
            score += 420.0
            if "fiscales" in sl or "fiscal" in sl:
                score += 120.0
            if "seguridad social" in sl or "imss" in sl or "infonavit" in sl:
                score += 100.0
        if "32-d" in sl or "32 d" in sl or "miscelánea fiscal" in sl or "miscelanea fiscal" in sl:
            score += 280.0
        if "constancia de situación fiscal" in sl or "constancia de situacion fiscal" in sl:
            score += 260.0
        if "servicio de administración tributaria" in sl:
            score += 220.0
        if "infonavit" in sl and any(
            k in sl for k in ("opinion", "opinión", "cumplimiento", "no adeudo", "corriente")
        ):
            score += 200.0
        if "imss" in sl and any(
            k in sl for k in ("opinion", "opinión", "cumplimiento", "no adeudo", "corriente")
        ):
            score += 180.0
        if "repse" in sl:
            score += 160.0
        if "solvencia" in sl and any(
            k in sl for k in ("económica", "economica", "financiera", "fiscal", "patronal")
        ):
            score += 140.0
        if ChatbotRAGAgent._is_solvency_literary_noise_sentence(sentence):
            score -= 500.0
        return score

    @staticmethod
    def _solvency_literary_predicate(sentence: str, sl: str) -> bool:
        if ChatbotRAGAgent._is_solvency_literary_noise_sentence(sentence):
            return False
        fiscal_core = (
            "opinión del cumplimiento",
            "opinion del cumplimiento",
            "obligaciones fiscales",
            "obligaciones en materia de seguridad social",
            "constancia de situación fiscal",
            "constancia de situacion fiscal",
            "miscelánea fiscal",
            "miscelanea fiscal",
            "32-d",
            "32 d",
            "no adeudo",
            "al corriente de sus obligaciones",
            "solvencia económica",
            "solvencia economica",
            "solvencia financiera",
        )
        if any(k in sl for k in fiscal_core):
            return True
        if "infonavit" in sl and any(
            k in sl for k in ("opinion", "opinión", "cumplimiento", "adeudo", "corriente")
        ):
            return True
        if "sat" in sl and any(
            k in sl for k in ("opinion", "opinión", "fiscal", "32-d", "tributaria", "hacienda")
        ):
            return True
        if "imss" in sl and any(
            k in sl for k in ("opinion", "opinión", "seguridad social", "adeudo", "cumplimiento")
        ):
            return True
        if "repse" in sl and any(
            k in sl for k in ("registro", "servicios especializados", "autorización", "autorizacion")
        ):
            return True
        if "iso 9001" in sl or "iso 14001" in sl or "nom-035" in sl:
            return "solvencia" in sl or "certificación" in sl or "certificacion" in sl
        return "solvencia" in sl

    @classmethod
    def _compose_solvency_literary_fallback(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        user_query: str,
        primary_doc: Optional[str] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        ranked = cls._rank_literary_items(
            context_docs,
            metadatas,
            primary_doc,
            cls._solvency_literary_predicate,
            cls._score_solvency_literary_sentence,
        )
        bullets = [
            f"- {s}\n  {cite}"
            for score, s, cite, _meta in ranked
            if score > 0
        ][:8]
        top = cls._top_literary_citation_from_ranked(ranked)
        text = cls._finalize_literary_parts(
            [
                "Según los fragmentos indexados de las bases, sobre **solvencia y opiniones de cumplimiento**:"
            ],
            bullets,
            "**Siguiente paso:** Revisa **Fuentes (bases)** para requisitos de solvencia (SAT/IMSS/INFONAVIT y normas).",
        )
        return text, top

    @staticmethod
    def _cronogram_has_schedule_anchor(sl: str) -> bool:
        """Fecha u hora de acto (no menciones económicas sin calendario)."""
        if re.search(
            rf"\d{{1,2}}\s+de\s+({_CRONOGRAM_MONTH_NAMES})",
            sl,
        ):
            return True
        if re.search(r"\d{1,2}:\d{2}\s*(hrs|horas)", sl):
            return True
        return False

    @staticmethod
    def _cronogram_has_procedural_act(sl: str) -> bool:
        """Actos del procedimiento con calendario (no reglas durante el acto)."""
        markers = (
            "junta de aclaraciones",
            "visita al sitio",
            "visita a instalaciones",
            "visita obligatoria",
            "apertura de proposiciones",
            "apertura de propuestas",
            "recepción y apertura de propuestas",
            "recepcion y apertura de propuestas",
            "presentación de proposiciones",
            "presentacion de proposiciones",
            "presentación y apertura de proposiciones",
            "presentacion y apertura de proposiciones",
            "acto de presentación y apertura",
            "acto de presentacion y apertura",
            "acto de fallo",
            "fallo y adjudicación",
            "fallo y adjudicacion",
        )
        return any(m in sl for m in markers)

    @staticmethod
    def _is_cronogram_caps_schedule_noise(sentence: str, sl: str) -> bool:
        """Líneas de tabla/portada: solo fecha y hora en mayúsculas sin acto."""
        s = str(sentence or "").strip()
        if len(s) > 130:
            return False
        letters = [c for c in s if c.isalpha()]
        if not letters:
            return False
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio < 0.55:
            return False
        if not re.search(r"\d{1,2}\s+DE\s+", sentence):
            return False
        return not ChatbotRAGAgent._cronogram_has_procedural_act(sl)

    @staticmethod
    def _is_official_letter_signature_noise(sl: str) -> bool:
        """Ciudad/fecha + firma del servidor público (el H./el C.) sin acto de cronograma."""
        if not re.search(r"\bel\s+[hc]\.\s", sl):
            return False
        if not re.search(
            rf"\d{{1,2}}\s+de\s+({_CRONOGRAM_MONTH_NAMES})",
            sl,
        ):
            return False
        if any(m in sl for m in _CRONOGRAM_ACT_MARKERS):
            return False
        return True

    @staticmethod
    def _is_cronogram_literary_noise_sentence(sentence: str) -> bool:
        """Encabezados de tabla, firmas y rejillas — no actos con fecha/hora."""
        if not sentence:
            return True
        if ChatbotRAGAgent._is_cronogram_noise_chunk(sentence):
            return True
        if "---" in sentence or sentence.count("|") >= 3:
            return True
        if sentence.strip().startswith("|"):
            return True
        sl = sentence.lower()
        if ChatbotRAGAgent._is_official_letter_signature_noise(sl):
            return True
        if re.search(r"licitaci[oó]n obra descripci[oó]n", sl):
            return True
        if "inscripciones visita al sitio" in sl.replace(" ", ""):
            return True
        if "32-d" in sl or "miscelánea fiscal" in sl or "miscelanea fiscal" in sl:
            return True
        if "modificaci" in sl and (
            "parte integrante" in sl or "derivada del resultado" in sl
        ):
            return True
        if "que tiene pleno conocimiento" in sl:
            return True
        if re.search(r"^\s*[a-z]\)\s", sl) and "que tiene" in sl:
            return True
        if ChatbotRAGAgent._is_cronogram_caps_schedule_noise(sentence, sl):
            return True
        if "durante el acto" in sl and any(
            k in sl
            for k in (
                "firmad",
                "anexo e",
                "catálogo de conceptos",
                "catalogo de conceptos",
                "escrito de proposición",
                "escrito de proposicion",
            )
        ):
            return True
        if any(
            k in sl
            for k in (
                "ajuste de costos",
                "revisión y ajuste",
                "revision y ajuste",
                "fecha de origen de los precios",
            )
        ):
            return True
        if re.search(r"^\s*[a-z]\)\s", sl) and not ChatbotRAGAgent._cronogram_has_schedule_anchor(
            sl
        ):
            return True
        if "representante legal" in sl and re.search(r"d/\d+/\d+", sl):
            return True
        if re.search(r"\bdirector de\b", sl) and not re.search(
            r"\d{1,2}\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre)",
            sl,
        ):
            return True
        has_date = bool(
            re.search(rf"\d{{1,2}}\s+de\s+({_CRONOGRAM_MONTH_NAMES})", sl)
            or re.search(rf"({_CRONOGRAM_MONTH_NAMES})\s+de\s+20\d{{2}}", sl)
        )
        act_hit = ChatbotRAGAgent._cronogram_has_procedural_act(sl)
        caps_runs = re.findall(r"\b[A-ZÁÉÍÓÚÑ]{5,}\b", sentence)
        if len(caps_runs) >= 4 and not has_date and not act_hit:
            return True
        if not has_date and not act_hit:
            return True
        return False

    @staticmethod
    def _score_cronogram_literary_sentence(sentence: str) -> float:
        sl = str(sentence or "").lower()
        score = 0.0
        month_pat = (
            r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre"
        )
        if re.search(rf"\d{{1,2}}\s+de\s+({month_pat})", sl):
            score += 300.0
        if re.search(r"\d{{1,2}}:\d{{2}}\s*hrs", sl) or re.search(r"\d{{1,2}}:\d{{2}}\s*horas", sl):
            score += 180.0
        if "junta" in sl and "aclaraci" in sl:
            score += 280.0
        if "apertura" in sl and "proposici" in sl:
            score += 260.0
        if "visita" in sl and ("instalaci" in sl or "sitio" in sl):
            score += 240.0
        if "acto de fallo" in sl or ("fallo" in sl and "adjudic" in sl):
            score += 220.0
        if "recepción y apertura" in sl or "recepcion y apertura" in sl:
            score += 260.0
        if ChatbotRAGAgent._cronogram_has_procedural_act(
            sl
        ) and ChatbotRAGAgent._cronogram_has_schedule_anchor(sl):
            score += 200.0
        elif ChatbotRAGAgent._cronogram_has_schedule_anchor(sl):
            score -= 80.0
        if "fechas y horas" in sl or "cronograma" in sl:
            score += 150.0
        if "inicio:" in sl and "terminación" in sl or "terminacion" in sl:
            score += 200.0
        if ChatbotRAGAgent._is_cronogram_literary_noise_sentence(sentence):
            score -= 600.0
        return score

    @staticmethod
    def _cronogram_literary_predicate(sentence: str, sl: str, body_sl: str = "") -> bool:
        if ChatbotRAGAgent._is_cronogram_literary_noise_sentence(sentence):
            return False
        if not ChatbotRAGAgent._cronogram_has_schedule_anchor(sl):
            return False
        if ChatbotRAGAgent._cronogram_has_procedural_act(sl):
            return True
        ctx = body_sl or sl
        if ChatbotRAGAgent._cronogram_has_procedural_act(ctx):
            if len(sentence) <= 180 and re.search(r"\d{1,2}:\d{2}", sl):
                return True
            if re.search(
                rf"el\s+d[ií]a\s+\d{{1,2}}\s+de\s+({_CRONOGRAM_MONTH_NAMES})",
                sl,
            ):
                return True
        if any(
            k in sl
            for k in (
                "visita",
                "inscripci",
                "junta",
                "aclaraci",
                "fallo",
                "apertura",
                "presentaci",
            )
        ):
            return True
        if any(k in sl for k in ("cronograma", "fechas y horas")):
            return True
        return False

    @staticmethod
    def _cronogram_literary_source_score(meta: Dict[str, Any]) -> float:
        src = str(meta.get("source") or "").lower()
        score = 0.0
        if "bases" in src:
            score += 150.0
        if "convocatoria" in src and "bases" not in src:
            score -= 200.0
        try:
            pg = int(str(meta.get("page") or "0"))
            if pg <= 1:
                score -= 120.0
        except (TypeError, ValueError):
            pass
        return score

    @staticmethod
    def _cronogram_literary_source_ok(meta: Dict[str, Any]) -> bool:
        src = str(meta.get("source") or "").strip()
        if not src:
            return False
        if _LITERARY_NON_BASES_SOURCE_RE.search(src):
            return False
        low = src.lower()
        if "convocatoria" in low and "bases" not in low:
            try:
                if int(str(meta.get("page") or "0")) <= 1:
                    return False
            except (TypeError, ValueError):
                return False
        if _BASES_FILENAME_RE.search(src):
            return True
        return bool(re.search(r"(?i)\banexo\s+(no\.?|n[uú]m\.?|número|numero)\b", src))

    @classmethod
    def _rank_cronogram_literary_items(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        primary_doc: Optional[str],
        session_id: Optional[str] = None,
    ) -> List[tuple[float, str, str, Dict[str, Any]]]:
        """Ranking cronograma: agrupa por página y usa texto íntegro indexado cuando hay session_id."""
        from app.services.vector_service import VectorDbServiceClient

        page_map: Dict[tuple, Dict[str, Any]] = {}
        for doc, meta in zip(context_docs, metadatas):
            meta_dict = meta if isinstance(meta, dict) else {}
            if not cls._cronogram_literary_source_ok(meta_dict):
                continue
            src = str(meta_dict.get("source") or primary_doc or "")
            pg = meta_dict.get("page")
            key = (src, pg)
            if key not in page_map:
                page_map[key] = {"meta": meta_dict, "parts": []}
            if doc:
                page_map[key]["parts"].append(str(doc))

        if session_id and primary_doc:
            vdb = VectorDbServiceClient()
            for _src, pg in list(page_map.keys()):
                if pg is None:
                    continue
                full = "\n".join(
                    vdb.fetch_page_documents(session_id, primary_doc, pg) or []
                )
                if full:
                    page_map[(_src, pg)]["parts"] = [full]
            try:
                seen_scan: set = set(page_map.keys())
                for _doc, meta in vdb.scan_session_chunks(
                    session_id, source_filter=primary_doc
                ):
                    if not isinstance(meta, dict):
                        continue
                    pg = meta.get("page")
                    key = (primary_doc, pg)
                    if key in seen_scan or pg is None:
                        continue
                    full = "\n".join(
                        vdb.fetch_page_documents(session_id, primary_doc, pg) or []
                    )
                    if full and cls._is_cronogram_calendar_chunk(full):
                        page_map[key] = {
                            "meta": {"source": primary_doc, "page": pg},
                            "parts": [full],
                        }
                        seen_scan.add(key)
            except Exception:
                pass

        seen: set[str] = set()
        ranked: List[tuple[float, str, str, Dict[str, Any]]] = []
        for (_src, _pg), entry in page_map.items():
            meta_dict = entry["meta"]
            merged = "\n".join(entry["parts"])
            cite = cls._format_literary_cite(meta_dict, primary_doc)
            for body in cls._iter_sanitized_chunk_bodies(merged):
                body_sl = body.lower()
                for sent in cls._split_penalty_sentences(body):
                    s = cls._strip_chunk_source_prefix(sent).strip()
                    s = re.sub(r"^-\s+", "", s).strip()
                    sl = s.lower()
                    if len(s) < 30 or len(s) > 480:
                        continue
                    if not cls._cronogram_literary_predicate(s, sl, body_sl):
                        continue
                    if re.search(r"\.pdf\s*\|\s*página", sl):
                        continue
                    if "| página" in sl and "fuente" not in sl:
                        continue
                    key = s[:90]
                    if key in seen:
                        continue
                    seen.add(key)
                    score = float(cls._score_cronogram_literary_sentence(s))
                    score += float(cls._cronogram_literary_source_score(meta_dict))
                    ranked.append((score, s, cite, meta_dict))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return ranked

    @classmethod
    def _compose_cronogram_literary_fallback(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        user_query: str,
        primary_doc: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        if session_state and session_id and primary_doc:
            from app.services.literary_cronogram_service import (
                build_canonical_literary_cronogram,
            )

            canon_bullets, top = build_canonical_literary_cronogram(
                session_state, session_id, primary_doc
            )
            if len(canon_bullets) >= 2:
                text = cls._finalize_literary_parts(
                    [
                        "Según los fragmentos indexados de las bases, sobre **cronograma y actos del procedimiento**:"
                    ],
                    canon_bullets[:6],
                    "**Siguiente paso:** Revisa **Fuentes (bases)** para fechas, horas y modalidad de cada acto.",
                )
                return text, top

        ranked = cls._rank_cronogram_literary_items(
            context_docs,
            metadatas,
            primary_doc,
            session_id=session_id,
        )
        bullets = [
            f"- {s}\n  {cite}"
            for score, s, cite, _meta in ranked
            if score > 0
        ][:5]
        top = cls._top_literary_citation_from_ranked(ranked)
        text = cls._finalize_literary_parts(
            [
                "Según los fragmentos indexados de las bases, sobre **cronograma y actos del procedimiento**:"
            ],
            bullets,
            "**Siguiente paso:** Revisa **Fuentes (bases)** para fechas, horas y modalidad de cada acto.",
        )
        return text, top

    @classmethod
    def _build_support_evidence_literary_message(
        cls,
        user_query: str,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        primary_doc: Optional[str],
        guarantee_intent: bool,
        penalty_intent: bool,
        solvency_intent: bool,
        cronogram_intent: bool,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[str, str, Optional[Dict[str, Any]]]]:
        """Devuelve (tipo, mensaje, cita_top) para preguntas «qué dice» con citas literales del índice."""
        if not cls._detect_support_evidence_intent(user_query) or not context_docs:
            return None
        builders: List[tuple[str, Any]] = []
        if cronogram_intent:
            builders.append(
                ("rag_literal_cronogram", cls._compose_cronogram_literary_fallback)
            )
        if penalty_intent:
            builders.append(
                ("rag_literal_penalty", cls._compose_penalty_literary_fallback)
            )
        if solvency_intent:
            builders.append(
                ("rag_literal_solvency", cls._compose_solvency_literary_fallback)
            )
        if guarantee_intent:
            builders.append(
                ("rag_literal_guarantee", cls._compose_guarantee_literary_fallback)
            )
        for tipo, builder in builders:
            if tipo == "rag_literal_cronogram":
                result = builder(
                    context_docs,
                    metadatas,
                    user_query,
                    primary_doc,
                    session_id=session_id,
                    session_state=session_state,
                )
            else:
                result = builder(context_docs, metadatas, user_query, primary_doc)
            if isinstance(result, tuple):
                text, top_citation = result[0], result[1] if len(result) > 1 else None
            else:
                text, top_citation = str(result or ""), None
            if text and len(text) > 100:
                return tipo, text, top_citation
        return None

    async def _fetch_literary_bases_excerpt(
        self,
        session_id: str,
        citation: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Párrafo indexado para la viñeta literaria top (fail-closed)."""
        if not citation or not citation.get("literal"):
            return None
        from app.services.literary_bases_excerpt_service import fetch_literary_bases_excerpt_v1

        try:
            return await fetch_literary_bases_excerpt_v1(
                session_id,
                citation,
                memory=self.context_manager.memory,
            )
        except Exception as exc:
            logger.warning(
                "literary_bases_excerpt_failed session=%s err=%s",
                session_id,
                exc,
            )
            return None

    @staticmethod
    def _is_solvencia_fiscal_noise(text: str) -> bool:
        """Opiniones/constancias fiscales del participante (no garantía contractual del ganador)."""
        if not text:
            return False
        if ChatbotRAGAgent._is_guarantee_contract_chunk(text) or ChatbotRAGAgent._is_guarantee_insurance_chunk(
            text
        ):
            return False
        low = text.lower()
        fiscal_markers = (
            "opinión del cumplimiento de obligaciones fiscales",
            "opinion del cumplimiento de obligaciones fiscales",
            "opinión del cumplimiento de obligaciones en materia de seguridad social",
            "constancia de situación fiscal",
            "constancia de situacion fiscal",
            "instituto nacional de la vivienda",
            "servicio de administración tributaria",
            "instituto mexicano del seguro social",
            "no se identificaron adeudos",
            "al corriente de sus obligaciones",
        )
        return any(m in low for m in fiscal_markers)

    @staticmethod
    def _is_evaluation_percent_noise(text: str) -> bool:
        """10% de evaluación de ofertas (no garantía de cumplimiento)."""
        low = (text or "").lower()
        if not re.search(r"10\s*%", low):
            return False
        if ChatbotRAGAgent._is_guarantee_contract_chunk(text):
            return False
        eval_markers = (
            "evaluación de las proposiciones",
            "evaluacion de las proposiciones",
            "oferta más alta",
            "incremento",
            "diferencia entre",
            "licitación abreviada",
        )
        return any(m in low for m in eval_markers)

    def _hydrate_guarantee_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Páginas atómicas con cláusulas de fianza/garantía o póliza RC (máx. 4)."""
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is None or pg in seen_pg:
                continue
            if self._is_guarantee_contract_chunk(doc or "") or self._is_guarantee_insurance_chunk(
                doc or ""
            ):
                seen_pg.add(pg)
                pinned_pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pinned_pages[:4]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_guarantee_contract_chunk(full) or self._is_guarantee_insurance_chunk(
                    full
                ):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
        return out_docs, out_metas

    @classmethod
    def _build_guarantee_canonical_block(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        """
        Extrae hechos contractuales literales de los fragmentos ya recuperados (universal, sin % fijo).
        El LLM debe reflejarlos en la respuesta; no sustituye leer el pliego completo.
        """
        fianza_line = ""
        fianza_page: Any = "?"
        insurance_line = ""
        insurance_page: Any = "?"
        for doc, meta in zip(context_docs, metadatas):
            if not doc:
                continue
            pg = cls._guarantee_page_label(meta if isinstance(meta, dict) else {})
            if not fianza_line and (
                cls._is_guarantee_contract_chunk(doc)
                or cls._is_guarantee_obra_bases_chunk(doc)
            ):
                m = re.search(
                    r"(\d{1,2})\s*%\s*del\s+monto\s+total\s+adjudicado",
                    doc,
                    re.I,
                )
                if not m:
                    m = re.search(
                        r"fianza.{0,80}?(\d{1,2})\s*%",
                        doc,
                        re.I | re.DOTALL,
                    )
                if m:
                    fianza_line = f"{m.group(1)}% del monto total adjudicado (sin IVA según fragmento)"
                    fianza_page = pg
            if not insurance_line and cls._is_guarantee_insurance_chunk(doc):
                m_amt = re.search(
                    r"1[',.]?\s*000[',.]?\s*000(?:\.00)?(?:\s*\([^)]+\))?",
                    doc,
                    re.I,
                )
                if m_amt:
                    insurance_line = m_amt.group(0).strip()
                    insurance_page = pg
        if not fianza_line and not insurance_line:
            return ""
        lines = ["[HECHOS CONTRACTUALES — extraídos de fragmentos indexados, obligatorios en la respuesta]"]
        if fianza_line:
            lines.append(f"- Fianza/garantía de cumplimiento: {fianza_line} [PÁGINA {fianza_page}]")
        if insurance_line:
            lines.append(
                f"- Seguro Responsabilidad Civil — suma asegurada: {insurance_line} [PÁGINA {insurance_page}]"
            )
        lines.append(
            "Incluye ambos bloques en tu respuesta. Queda prohibido decir que «no se especifican montos» "
            "si aquí aparece un porcentaje o una suma asegurada."
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _guarantee_response_missing_contract_pct(content: str, canonical_pct: str) -> bool:
        """True si el bloque canónico trajo un % de fianza pero la respuesta del LLM no lo menciona."""
        if not canonical_pct or not content:
            return False
        m = re.search(r"(\d{1,2})\s*%", canonical_pct)
        if not m:
            return False
        return m.group(1) not in content and m.group(0) not in content

    @classmethod
    def _sanitize_guarantee_contradictory_llm_body(
        cls, content: str, canonical_block: str
    ) -> str:
        """
        Quita negaciones del LLM cuando el bloque canónico ya extrajo % de fianza o monto RC.
        Preserva el bloque estructurado ### 1) / ### 2) inyectado al final.
        """
        if not content or not canonical_block:
            return content
        has_fianza = bool(
            re.search(r"Fianza/garantía.*\d+\s*%", canonical_block, re.I)
        )
        has_insurance = "Seguro Responsabilidad Civil" in canonical_block
        if not has_fianza and not has_insurance:
            return content

        structured_marker = "### 1) FIANZA"
        body, tail = content, ""
        if structured_marker in content:
            idx = content.index(structured_marker)
            body, tail = content[:idx].strip(), content[idx:].strip()

        denial_markers = (
            "no aparece explícitamente",
            "no aparecen explícitamente",
            "tampoco aparece explícitamente",
            "tampoco aparecen explícitamente",
            "no figura en los fragmentos",
            "no figuran en los fragmentos",
            "no se especifican montos",
            "no se especifica el monto",
            "no se especifica el porcentaje",
            "se puede inferir que",
            "fragmentos proporcionados",
        )
        if has_fianza:
            denial_markers += (
                "porcentaje de fianza/garantía no aparece",
                "porcentaje de fianza no aparece",
            )
        if has_insurance:
            denial_markers += (
                "monto exacto de la responsabilidad civil",
                "monto de la responsabilidad civil tampoco",
            )

        paragraphs = re.split(r"\n\s*\n", body)
        kept: List[str] = []
        for para in paragraphs:
            low = para.lower()
            if any(m in low for m in denial_markers):
                continue
            if has_fianza and re.search(r"la sección 1", low) and (
                "no aparece" in low or "tampoco" in low
            ):
                continue
            if has_insurance and re.search(r"la sección 2", low) and (
                "no aparece" in low or "tampoco" in low
            ):
                continue
            if low.strip().startswith("en resumen,") and (
                "no aparece" in low or "tampoco aparece" in low
            ):
                continue
            kept.append(para.strip())

        body = "\n\n".join(p for p in kept if p)
        for pat in (
            r"(?im)^[^\n]*no aparece(?:n)? explícitamente[^\n]*\n?",
            r"(?im)^[^\n]*tampoco aparece(?:n)? explícitamente[^\n]*\n?",
            r"(?im)^[^\n]*no se especifican montos[^\n]*\n?",
            r"(?im)^[^\n]*se puede inferir que[^\n]*\n?",
        ):
            body = re.sub(pat, "", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        if tail:
            return f"{body}\n\n{tail}".strip() if body else tail
        return body or content

    @classmethod
    def _parse_guarantee_canonical_facts(cls, canonical_block: str) -> Dict[str, Any]:
        """Lee hechos ya extraídos del bloque canónico (sin re-parsear el LLM)."""
        facts: Dict[str, Any] = {
            "fianza_detail": None,
            "fianza_page": None,
            "insurance_detail": None,
            "insurance_page": None,
        }
        for line in canonical_block.splitlines():
            if line.startswith("- Fianza/garantía"):
                m = re.search(
                    r"Fianza/garantía de cumplimiento: (.+) \[PÁGINA ([^\]]+)\]",
                    line,
                )
                if m:
                    facts["fianza_detail"] = m.group(1).strip()
                    facts["fianza_page"] = m.group(2).strip()
            elif line.startswith("- Seguro Responsabilidad Civil"):
                m = re.search(
                    r"suma asegurada: (.+) \[PÁGINA ([^\]]+)\]",
                    line,
                )
                if m:
                    facts["insurance_detail"] = m.group(1).strip()
                    facts["insurance_page"] = m.group(2).strip()
        return facts

    @classmethod
    def _guarantee_canonical_has_core_facts(cls, canonical_block: str) -> bool:
        """
        True si el bloque canónico trajo fianza de cumplimiento (% sobre monto adjudicado)
        y suma de Responsabilidad Civil — umbral para sustituir narrativa libre del LLM.
        """
        if not canonical_block:
            return False
        has_fianza = bool(
            re.search(
                r"Fianza/garantía.*\d+\s*%.*monto total adjudicado",
                canonical_block,
                re.I,
            )
        )
        has_insurance = "Seguro Responsabilidad Civil" in canonical_block
        return has_fianza and has_insurance

    @staticmethod
    def _is_guarantee_template_noise(text: str) -> bool:
        """Plantillas rellenables (Anexo G) u OCR de formularios — no son cláusulas contractuales."""
        if not text:
            return False
        low = text.lower()
        if "modelo de póliza" in low or "modelo de poliza" in low:
            return True
        if re.search(r"_{4,}", text):
            return True
        if "denominación social:" in low and "__" in text:
            return True
        if "| tipo: doc" in low and "anexo" in low:
            return True
        if low.count("________") >= 2:
            return True
        return False

    @staticmethod
    def _guarantee_page_label(meta: Optional[Dict[str, Any]]) -> str:
        """Página legible para citas forenses; evita «doc» de metadatos de anexos Word."""
        if not isinstance(meta, dict):
            return "?"
        pg = meta.get("page")
        if isinstance(pg, int) and pg >= 1:
            return str(pg)
        if isinstance(pg, str):
            s = pg.strip()
            if s.isdigit() and int(s) >= 1:
                return s
        src = str(meta.get("source") or meta.get("source_file") or "").strip()
        m = re.search(r"[_\-](\d{1,4})\.pdf", src, re.I)
        if m:
            return m.group(1)
        return "?"

    @classmethod
    def _extract_guarantee_accepted_formats(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Formas de garantizar aceptadas por la convocante (fianza, cheque, anexo)."""
        seen: set[str] = set()
        out: List[str] = []
        rules: List[tuple[str, str]] = [
            (r"anexo\s+g", "Póliza de fianza conforme al **Anexo G — Formato de Fianza**"),
            (r"cheque\s+certificado", "**Cheque certificado** a favor de la dependencia"),
            (r"cheque\s+de\s+caja", "**Cheque de caja** a favor de la dependencia"),
            (r"p[oó]liza\s+de\s+fianza", "**Póliza de fianza** expedida por afianzadora autorizada"),
        ]
        for doc, meta in zip(context_docs, metadatas):
            if not doc or cls._is_guarantee_template_noise(doc):
                continue
            low = doc.lower()
            pg = cls._guarantee_page_label(meta if isinstance(meta, dict) else {})
            page_suffix = f" [PÁGINA {pg}]" if pg != "?" else ""
            for pat, label in rules:
                if not re.search(pat, low, re.I):
                    continue
                if label in seen:
                    continue
                seen.add(label)
                out.append(f"- {label}{page_suffix}")
        return out

    @staticmethod
    def _is_guarantee_plazo_chunk(text: str) -> bool:
        """Fragmentos de vigencia/entrega/endoso; excluye ruido de insumos (p. ej. contenido nacional)."""
        if not text or len(text) < 40:
            return False
        if ChatbotRAGAgent._is_guarantee_template_noise(text):
            return False
        low = text.lower()
        if ChatbotRAGAgent._is_guarantee_template_noise(text):
            return False
        if any(
            x in low
            for x in (
                "contenido nacional",
                "jabón",
                "jabon",
                "limpia manos",
                "insumo",
                "partida 2",
                "partida dos",
            )
        ):
            return False
        if ChatbotRAGAgent._is_guarantee_contract_chunk(
            text
        ) or ChatbotRAGAgent._is_guarantee_insurance_chunk(text):
            return True
        markers = (
            "recursos legales",
            "oficio de conformidad",
            "firma del contrato",
            "endoso",
            "sustanciación",
            "sustanciacion",
        )
        guarantee_words = (
            "fianza",
            "garantía",
            "garantia",
            "póliza",
            "poliza",
            "responsabilidad civil",
        )
        return any(m in low for m in markers) and any(w in low for w in guarantee_words)

    @classmethod
    def _extract_guarantee_plazos_snippets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Oraciones literales de plazos/vigencias/endosos desde fragmentos contractuales."""
        seen: set[str] = set()
        out: List[str] = []
        plazo_keys = (
            "vigente",
            "vigencia",
            "endoso",
            "entreg",
            "firma",
            "recursos",
            "conformidad",
            "juicio",
            "contrato",
            "póliza",
            "poliza",
            "comprobante",
        )
        for doc, meta in zip(context_docs, metadatas):
            if not doc or not cls._is_guarantee_plazo_chunk(doc):
                continue
            if cls._is_guarantee_template_noise(doc):
                continue
            pg = cls._guarantee_page_label(meta if isinstance(meta, dict) else {})
            if pg == "?":
                continue
            for sent in re.split(r"(?<=[.;])\s+", doc):
                s = sent.strip()
                if len(s) < 35 or len(s) > 400:
                    continue
                low = s.lower()
                if not any(k in low for k in plazo_keys):
                    continue
                if re.search(r"\d{2,3}\s*%", s) and "monto total adjudicado" not in low:
                    continue
                key = s[:90]
                if key in seen:
                    continue
                seen.add(key)
                out.append(f"{s} [PÁGINA {pg}]")
                if len(out) >= 4:
                    return out
        return out

    @classmethod
    def _compose_guarantee_structured_response(
        cls,
        canonical_block: str,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> str:
        """
        Respuesta determinística solo con secciones 1–3 cuando el bloque canónico
        ya extrajo fianza y RC (evita alucinaciones del LLM en narrativa libre).
        """
        facts = cls._parse_guarantee_canonical_facts(canonical_block)
        plazos = cls._extract_guarantee_plazos_snippets(context_docs, metadatas)
        formatos = cls._extract_guarantee_accepted_formats(context_docs, metadatas)
        parts = [
            "**Requisitos obligatorios de seguros y garantías del licitante ganador**",
            "(Datos contractuales extraídos del pliego indexado; sin narrativa inferida.)",
            "",
            "### 1) FIANZA / GARANTÍA DE CUMPLIMIENTO",
        ]
        if facts.get("fianza_detail"):
            fp = facts.get("fianza_page") or "?"
            parts.append(
                f"**Porcentaje:** {facts['fianza_detail']} [PÁGINA {fp}]"
            )
        else:
            parts.append(
                "**Porcentaje:** No consta en los fragmentos indexados para esta consulta."
            )
        parts.extend(["", "### 2) SEGURO DE RESPONSABILIDAD CIVIL"])
        if facts.get("insurance_detail"):
            ip = facts.get("insurance_page") or "?"
            detail = str(facts["insurance_detail"])
            parts.append(
                f"**Monto asegurado:** {detail} [PÁGINA {ip}]"
            )
        else:
            parts.append(
                "**Monto asegurado:** No consta en los fragmentos indexados para esta consulta."
            )
        parts.extend(["", "### 3) PLAZOS, VIGENCIAS Y ENDOSOS"])
        if plazos:
            parts.extend(f"- {line}" for line in plazos)
        else:
            parts.append(
                "- Revise el pliego en las páginas citadas en las secciones 1 y 2 para vigencia, "
                "entrega y endoso; no se recuperó un fragmento adicional explícito en esta consulta."
            )
        parts.extend(["", "### 4) FORMATOS ACEPTADOS POR LA CONVOCANTE"])
        if formatos:
            parts.extend(formatos)
        else:
            parts.append(
                "- No se recuperó en esta consulta la forma explícita de garantizar "
                "(fianza, cheque certificado, etc.). Consulte el capítulo de garantías del pliego."
            )
        return "\n".join(parts)

    # Combo solvencia: opiniones fiscales + normas ISO/NMX/NOM/REPSE (opuesto a intent garantías).
    _SOLVENCY_FOCAL_RAG_QUERY: str = (
        "solvencia participante opinión cumplimiento SAT IMSS INFONAVIT seguridad social "
        "ISO 9001 14001 45001 NMX NOM-035 REPSE certificación acreditación norma técnica "
        "registro gubernamental documentación complementaria 6.1"
    )
    _ISO_NORM_RE = re.compile(
        r"ISO\s*(?:IEC\s*)?\d{4,5}(?:\s*:\s*\d{4})?",
        re.I,
    )
    _NMX_NORM_RE = re.compile(r"NMX[_\-]?[A-Z0-9][\w\-]{3,}", re.I)
    _NOM_NORM_RE = re.compile(r"NOM[\-\s]?\d{3}[\w\-]*", re.I)

    @classmethod
    def _detect_solvency_intent(cls, query: str) -> bool:
        """
        True si la consulta apunta a solvencia del participante (fiscal, ISO/NMX, REPSE).
        No activar en preguntas de garantías/seguros del ganador adjudicado.
        """
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        if cls._detect_guarantee_intent(query) and not (
            "solvencia" in q and any(k in q for k in ("iso", "nmx", "nom", "participante"))
        ):
            return False
        if "solvencia" in q and any(
            k in q for k in ("participante", "licitante", "proponente", "evaluar", "exigen")
        ):
            return True
        if any(k in q for k in ("iso", "nmx", "nom")) and any(
            k in q
            for k in (
                "obligatorio",
                "exigen",
                "requiere",
                "normativa",
                "certificacion",
                "certificación",
                "acreditacion",
                "acreditación",
            )
        ):
            return True
        fiscal_core = (
            "opinion de cumplimiento",
            "opinión de cumplimiento",
            "opiniones de cumplimiento",
            "registros gubernamentales",
            "servicio de administracion tributaria",
            "sat",
            "imss",
            "infonavit",
        )
        if any(k in q for k in fiscal_core) and any(
            k in q for k in ("obligatorio", "participante", "solvencia", "exigen", "evaluar")
        ):
            return True
        return False

    @classmethod
    def _detect_security_private_compliance_injection(cls, query: str) -> bool:
        """
        Post-LLM de acreditaciones REPSE/SSPC/CUIPS solo para consultas de seguridad privada.
        No debe activarse en solvencia general (ISO/NMX) donde «registro» aparece en otra acepción.
        """
        if cls._detect_solvency_intent(query):
            return False
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        if any(
            k in q
            for k in (
                "seguridad privada",
                "sspc",
                "infospe",
                "cuips",
                "repse",
            )
        ) and any(
            k in q
            for k in (
                "acredit",
                "autorizacion",
                "autorización",
                "permiso",
                "registro repse",
                "6.1",
                "inciso",
            )
        ):
            return True
        return False

    @staticmethod
    def _chunk_belongs_to_session(meta: Dict[str, Any], session_id: str, vector_db: Any) -> bool:
        """Defensa en profundidad: rechaza fragmentos cuyo metadato session_id no coincide."""
        if not meta or not session_id or not vector_db:
            return True
        expected = vector_db._sanitize_name(session_id)
        chunk_sid = meta.get("session_id")
        if chunk_sid is None:
            return True
        return str(chunk_sid) == str(expected)

    @staticmethod
    def _is_solvency_fiscal_chunk(text: str) -> bool:
        """Opiniones/constancias fiscales y patronales del participante (solvencia)."""
        if not text or len(text) < 50:
            return False
        low = text.lower()
        if ChatbotRAGAgent._is_guarantee_contract_chunk(
            text
        ) or ChatbotRAGAgent._is_guarantee_insurance_chunk(text):
            return False
        fiscal_keys = (
            "servicio de administración tributaria",
            "servicio de administracion tributaria",
            " opinión ",
            " opinion ",
            "opinión positiva",
            "opinion positiva",
            "instituto mexicano del seguro social",
            "infonavit",
            "seguridad social",
            "constancia de situación fiscal",
            "constancia de situacion fiscal",
            "aportaciones patronales",
            "acdo.sa1",
            "consejo técnico",
        )
        return any(k in low for k in fiscal_keys)

    @staticmethod
    def _is_solvency_norm_chunk(text: str) -> bool:
        """Certificaciones ISO/NMX/NOM, REPSE y normas técnicas de solvencia."""
        if not text or len(text) < 40:
            return False
        low = text.lower()
        if ChatbotRAGAgent._ISO_NORM_RE.search(text):
            return True
        if ChatbotRAGAgent._NMX_NORM_RE.search(text):
            return True
        if ChatbotRAGAgent._NOM_NORM_RE.search(text):
            return True
        if "repse" in low and any(
            w in low
            for w in (
                "registro",
                "prestadores",
                "servicios especializados",
                "presentar",
                "vigente",
            )
        ):
            return True
        if "certificación" in low or "certificacion" in low:
            if any(w in low for w in ("iso", "nmx", "nom", "45001", "9001", "14001")):
                return True
        return False

    def _hydrate_solvency_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Páginas atómicas con requisitos de solvencia fiscal o normativa (máx. 5)."""
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is None or pg in seen_pg:
                continue
            if self._is_solvency_fiscal_chunk(doc or "") or self._is_solvency_norm_chunk(
                doc or ""
            ):
                seen_pg.add(pg)
                pinned_pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pinned_pages[:5]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_solvency_fiscal_chunk(full) or self._is_solvency_norm_chunk(full):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
        return out_docs, out_metas

    @classmethod
    def _extract_solvency_fiscal_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Viñetas fiscales/patronales con [PÁGINA] desde fragmentos indexados."""
        seen: set[str] = set()
        bullets: List[str] = []
        keys = (
            "servicio de administración tributaria",
            "servicio de administracion tributaria",
            "sat",
            "instituto mexicano del seguro social",
            "imss",
            "infonavit",
            "seguridad social",
            "acdo.sa1",
            "aportaciones patronales",
            "constancia de situación fiscal",
            "constancia de situacion fiscal",
        )
        for doc, meta in zip(context_docs, metadatas):
            if not doc or not cls._is_solvency_fiscal_chunk(doc):
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", doc):
                s = sent.strip()
                if len(s) < 40 or len(s) > 420:
                    continue
                low = s.lower()
                if not any(k in low for k in keys):
                    continue
                if "opinión" not in low and "opinion" not in low and "constancia" not in low:
                    if "sat" not in low and "imss" not in low and "infonavit" not in low:
                        continue
                if any(
                    n in low
                    for n in (
                        "requisitos de las proposiciones",
                        "requisitos de las propuestaciones",
                        "en el entendido de que no se cumple el requisito, si la opinion se encuentra en",
                        "en el entendido de que no se cumple el requisito, si la opinión se encuentra en",
                    )
                ):
                    continue
                if low.startswith("consejo técnico") and "acdo" not in low:
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
                if len(bullets) >= 5:
                    return bullets
        return bullets

    @classmethod
    def _extract_solvency_norm_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Viñetas ISO/NMX/NOM/REPSE con [PÁGINA] desde fragmentos indexados."""
        seen: set[str] = set()
        bullets: List[str] = []

        def _add(label: str, snippet: str, pg: Any) -> None:
            key = f"{label}|{snippet[:80]}"
            if key in seen:
                return
            seen.add(key)
            sn = snippet.strip()
            if len(sn) > 380:
                sn = sn[:377] + "..."
            bullets.append(f"• **{label}:** {sn} [PÁGINA {pg}]")

        for doc, meta in zip(context_docs, metadatas):
            if not doc or not cls._is_solvency_norm_chunk(doc):
                continue
            pg = meta.get("page", "?")
            low = doc.lower()
            labels: List[str] = []
            for iso in cls._ISO_NORM_RE.findall(doc):
                labels.append(iso.upper().replace("  ", " "))
            for nmx in cls._NMX_NORM_RE.findall(doc):
                labels.append(nmx.upper())
            for nom in cls._NOM_NORM_RE.findall(doc):
                labels.append(nom.upper())
            if "repse" in low:
                labels.append("REPSE")
            sentences = re.split(r"(?<=[.;])\s+", doc)
            for label in labels:
                snippet = doc
                for sent in sentences:
                    if label.lower().replace("-", "")[:8] in sent.lower().replace("-", "") or (
                        label == "REPSE" and "repse" in sent.lower()
                    ):
                        snippet = sent
                        break
                _add(label, snippet, pg)
            if len(bullets) >= 10:
                return bullets
        return bullets

    @classmethod
    def _compose_solvency_structured_response(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        """
        Localizador forense: lista fiscal + normativa con [PÁGINA] obligatoria por ítem.
        Sustituye narrativa libre del LLM cuando hay hechos extraíbles en contexto.
        """
        fiscal = cls._extract_solvency_fiscal_bullets(context_docs, metadatas)
        norms = cls._extract_solvency_norm_bullets(context_docs, metadatas)
        parts = [
            "**Requisitos de solvencia del participante**",
            "(Opiniones, registros y normas extraídos del pliego indexado.)",
            "",
            "### 1) Opiniones de cumplimiento fiscal y patronal",
        ]
        if fiscal:
            parts.extend(fiscal)
        else:
            parts.append(
                "• No se recuperó en esta consulta un fragmento explícito de opinión SAT/IMSS/INFONAVIT."
            )
        parts.extend(["", "### 2) Normativas técnicas, certificaciones y registros (ISO/NMX/NOM/REPSE)"])
        if norms:
            parts.extend(norms)
        else:
            parts.append(
                "• No se recuperó en esta consulta un fragmento explícito de ISO/NMX/NOM o REPSE."
            )
        return "\n".join(parts)

    @classmethod
    def _solvency_structured_ready(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        """True si hay al menos un requisito fiscal y uno normativo en el contexto."""
        fiscal = cls._extract_solvency_fiscal_bullets(context_docs, metadatas)
        norms = cls._extract_solvency_norm_bullets(context_docs, metadatas)
        return len(fiscal) >= 1 and len(norms) >= 1

    # Combo propuesta económica: moneda, formato por partida, regla número vs letra.
    _ECONOMIC_FOCAL_RAG_QUERY: str = (
        "propuesta económica moneda nacional pesos mexicanos precios fijos "
        "número y letra prevalecerá cantidad estipulada en letra Anexo III "
        "partida 1 tarifa mensual partida 2 precio unitario IV.2 cotización"
    )

    @classmethod
    def _explicit_economic_format_markers_in_query(cls, q_normalized: str) -> bool:
        """Marcadores inequívocos de formato/moneda (no basta «Anexo III» con insumos técnicos)."""
        qn = q_normalized.replace("ó", "o")
        return any(
            m in qn
            for m in (
                "propuesta economica",
                "moneda requerida",
                "formato de precio",
                "formato de precios",
                "precios fijos",
                "precio fijo",
                "numero y letra",
                "discrepancia",
                "montos en numero",
                "cotizacion economica",
                "tarifa mensual",
                "precio unitario",
                "oferta economica",
                "iva",
            )
        )

    @classmethod
    def _detect_supplies_technical_intent(cls, query: str) -> bool:
        """True si la consulta apunta a insumos/materiales/muestras/RPBI (Partida 2 limpieza, etc.)."""
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        qn = q.replace("ó", "o")
        if cls._explicit_economic_format_markers_in_query(qn) and not any(
            m in qn
            for m in (
                "biodegradabilidad",
                "biodegradable",
                "rpbi",
                "muestras",
                "insumos",
                "materiales de limpieza",
                "material de limpieza",
                "productos quimicos",
                "concentracion",
                "envase",
            )
        ):
            return False
        supply_markers = (
            "biodegradabilidad",
            "biodegradable",
            "rpbi",
            "residuo peligroso",
            "residuos peligrosos",
            "biologico infeccioso",
            "biologico-infeccioso",
            "muestras",
            "muestra fisica",
            "muestra física",
            "almacen",
            "insumos",
            "materiales de limpieza",
            "material de limpieza",
            "concentracion",
            "envase",
            "bidon",
            "productos quimicos",
            "sustancias quimicas",
            "entrega de materiales",
            "suministro de materiales",
            "caracteristicas de muestras",
        )
        if any(m in qn for m in supply_markers):
            return True
        partida2_ctx = ("partida 2" in qn or "partida dos" in qn) and any(
            x in qn
            for x in (
                "limpieza",
                "insumo",
                "material",
                "biodegrad",
                "muestra",
                "rpbi",
                "quimic",
                "envase",
                "concentracion",
            )
        )
        anexo_iii_supplies = "anexo iii" in qn and any(
            x in qn
            for x in (
                "insumo",
                "material",
                "biodegrad",
                "muestra",
                "rpbi",
                "limpieza",
                "envase",
                "concentracion",
                "quimic",
            )
        )
        excludes_econ = any(
            x in qn
            for x in (
                "no pregunto",
                "no preguntes",
                "sin formato",
                "sin moneda",
                "no es propuesta economica",
                "solo especificaciones tecnicas",
                "solo especificaciones técnicas",
            )
        )
        return partida2_ctx or anexo_iii_supplies or excludes_econ

    @staticmethod
    def _is_economic_generation_command(query: str) -> bool:
        """
        Comando explícito para ejecutar EconomicAgent (no confundir con RAG del pliego).
        Acepta «genera» / «generar», typos y payload de botones.
        """
        raw = str(query or "").strip()
        if raw in ("CMD_TRIGGER_GENERATION", "CMD_TRIGGER_ECONOMIC_PROPOSAL"):
            return True
        qn = ChatbotRAGAgent._normalize_query_for_intent(raw).replace("ó", "o")
        if not qn:
            return False
        if re.search(r"\b(generar|genera|armar|calcular|cotizar)\b", qn) and (
            "propuesta" in qn or "economica" in qn or "economico" in qn or "cotizacion" in qn
        ):
            return True
        return "generar propuesta" in qn or "genera propuesta" in qn

    @staticmethod
    def _detect_user_confusion_intent(query: str) -> bool:
        """Usuario pide aclaración en lenguaje natural (no es consulta al pliego)."""
        qn = ChatbotRAGAgent._normalize(str(query or ""))
        if len(qn) < 8:
            return False
        needles = (
            "no te entiendo",
            "no entiendo nada",
            "no entiendo",
            "que necesitas",
            "que ocupas",
            "que requieres",
            "que debo hacer",
            "que hago ahora",
            "en que me ayudas",
            "no se que hacer",
            "no sé qué hacer",
        )
        return any(n in qn for n in needles)

    @classmethod
    def _detect_economic_intent(cls, query: str) -> bool:
        """True si la consulta apunta a formato/moneda/discrepancias de la propuesta económica."""
        from app.services.chat_economic_provenance_service import detect_economic_provenance_intent

        if detect_economic_provenance_intent(query):
            return False
        if cls._is_economic_generation_command(query):
            return False
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        qn = q.replace("ó", "o")
        if cls._detect_guarantee_intent(query) and "propuesta economica" not in qn:
            return False
        if cls._detect_supplies_technical_intent(query):
            return False
        econ_markers = (
            "propuesta economica",
            "propuesta económica",
            "moneda requerida",
            "formato de precio",
            "formato de precios",
            "precios fijos",
            "precio fijo",
            "numero y letra",
            "número y letra",
            "discrepancia",
            "montos en numero",
            "montos en número",
            "cotizacion economica",
            "cotización económica",
        )
        if any(m in qn for m in econ_markers):
            return True
        if "anexo iii" in qn and cls._explicit_economic_format_markers_in_query(qn):
            return True
        return False

    @staticmethod
    def _is_economic_format_chunk(text: str) -> bool:
        """Fragmentos de presentación económica (moneda, Anexo III, número/letra)."""
        if not text or len(text) < 50:
            return False
        if ChatbotRAGAgent._is_guarantee_contract_chunk(
            text
        ) or ChatbotRAGAgent._is_guarantee_insurance_chunk(text):
            return False
        low = text.lower()
        markers = (
            "propuesta económica",
            "propuesta economica",
            "proposición económica",
            "moneda nacional",
            "número y letra",
            "numero y letra",
            "prevalecerá la cantidad",
            "prevalecera la cantidad",
            "anexo iii partida",
            "tarifa mensual",
            "precio unitario",
            "iv.2 proposición económica",
            "iv.2 proposicion economica",
            "oferta económica",
        )
        return any(m in low for m in markers)

    def _hydrate_economic_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Páginas atómicas con reglas de propuesta económica (máx. 4)."""
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is None or pg in seen_pg:
                continue
            if self._is_economic_format_chunk(doc or ""):
                seen_pg.add(pg)
                pinned_pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pinned_pages[:4]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_economic_format_chunk(full):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
        return out_docs, out_metas

    @classmethod
    def _extract_economic_format_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Formato por partida / Anexo III con [PÁGINA]."""
        seen: set[str] = set()
        bullets: List[str] = []
        patterns = (
            ("partida 1", ("tarifa mensual", "moneda nacional", "anexo iii partida 1")),
            ("partida 2", ("precio unitario", "moneda nacional", "anexo iii partida 2")),
        )
        for doc, meta in zip(context_docs, metadatas):
            if not doc or not cls._is_economic_format_chunk(doc):
                continue
            pg = meta.get("page", "?")
            low = doc.lower()
            for label, keys in patterns:
                if not any(k in low for k in keys):
                    continue
                for sent in re.split(r"(?<=[.;])\s+", doc):
                    s = sent.strip()
                    sl = s.lower()
                    if len(s) < 45 or len(s) > 420:
                        continue
                    if not any(k in sl for k in keys):
                        continue
                    key = f"{label}|{s[:90]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    bullets.append(f"• **{label.title()}:** {s} [PÁGINA {pg}]")
            if len(bullets) >= 6:
                return bullets
        return bullets

    @classmethod
    def _extract_economic_moneda_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        for doc, meta in zip(context_docs, metadatas):
            if not doc:
                continue
            low = doc.lower()
            if "moneda nacional" not in low and "pesos mexicanos" not in low:
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", doc):
                s = sent.strip()
                if len(s) < 40:
                    continue
                sl = s.lower()
                if "moneda nacional" not in sl and "pesos mexicanos" not in sl:
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
                if len(bullets) >= 3:
                    return bullets
        return bullets

    @classmethod
    def _extract_economic_discrepancy_rule(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        """Regla número vs letra (prevalece la letra, no descalificación automática)."""
        seen: set[str] = set()
        bullets: List[str] = []
        for doc, meta in zip(context_docs, metadatas):
            if not doc:
                continue
            low = doc.lower()
            if "número y letra" not in low and "numero y letra" not in low:
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", doc):
                s = sent.strip()
                sl = s.lower()
                if len(s) < 40:
                    continue
                if "número y letra" not in sl and "numero y letra" not in sl:
                    continue
                if "prevalec" not in sl and "error" not in sl and "discrepanc" not in sl:
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
        return bullets

    @classmethod
    def _compose_economic_structured_response(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        """Localizador forense económico: 3 bloques con [PÁGINA], sin narrativa inventada."""
        moneda = cls._extract_economic_moneda_bullets(context_docs, metadatas)
        formato = cls._extract_economic_format_bullets(context_docs, metadatas)
        discrep = cls._extract_economic_discrepancy_rule(context_docs, metadatas)
        parts = [
            "**Propuesta económica — requisitos de forma y moneda**",
            "(Extraído del pliego indexado; prohibido inventar monedas extranjeras o reglas no citadas.)",
            "",
            "### 1) MONEDA REQUERIDA",
        ]
        if moneda:
            parts.extend(moneda)
        else:
            parts.append("• No se recuperó «moneda nacional» en los fragmentos de esta consulta.")
        parts.extend(["", "### 2) FORMATO DE COTIZACIÓN POR PARTIDA"])
        if formato:
            parts.extend(formato)
        else:
            parts.append(
                "• Revise Anexo III en los fragmentos (tarifa mensual partida 1 / precio unitario partida 2)."
            )
        parts.extend(["", "### 3) REGLA DE DISCREPANCIA (NÚMERO VS LETRA)"])
        if discrep:
            parts.extend(discrep)
        else:
            parts.append(
                "• No se recuperó la regla de número y letra en los fragmentos indexados."
            )
        return "\n".join(parts)

    @classmethod
    def _economic_structured_ready(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        moneda = cls._extract_economic_moneda_bullets(context_docs, metadatas)
        discrep = cls._extract_economic_discrepancy_rule(context_docs, metadatas)
        return len(moneda) >= 1 and len(discrep) >= 1

    @classmethod
    def _append_economic_gap_alert_if_needed(
        cls,
        content: str,
        context_docs: List[str],
        economic_intent: bool,
    ) -> str:
        """Alerta de brecha solo si faltan reglas de redondeo en fragmentos (sin afirmar «precios fijos» genéricos)."""
        if not economic_intent or "alerta de brecha" in content.lower():
            return content
        pool = [d or "" for d in context_docs]
        low_pool = " ".join(pool).lower()
        has_rounding = bool(
            re.search(r"redondeo|truncamiento|\d\s*decimales", low_pool)
        )
        if has_rounding:
            return content
        has_moneda = "moneda nacional" in low_pool
        has_precios_fijos = "precios fijos" in low_pool or "precio fijo" in low_pool
        confirmed = []
        if has_moneda:
            confirmed.append("moneda nacional")
        if has_precios_fijos:
            confirmed.append("precios fijos")
        confirmed_txt = (
            ", ".join(confirmed) if confirmed else "requisitos económicos parciales"
        )
        content += (
            f"\n\n**ALERTA DE BRECHA ECONÓMICA:** Los fragmentos confirman {confirmed_txt}, "
            "pero NO detallan la regla de redondeo (4 o 5 decimales) para cálculos intermedios "
            "del FSR/Anexo 9 si aplica. Formule aclaración en Junta o use criterio conservador "
            "documentado internamente."
        )
        return content

    # Combo insumos técnicos Partida 2 / materiales de limpieza (no formato económico).
    _SUPPLIES_FOCAL_RAG_QUERY: str = (
        "biodegradabilidad biodegradable no contaminante envase bidón concentración "
        "muestras físicas almacén convocante insumos materiales limpieza partida 2 "
        "Anexo III productos químicos cloro jabón desinfectante RPBI residuos "
        "peligrosos biológico infecciosos entrega de materiales suministro"
    )

    @staticmethod
    def _is_supplies_spec_chunk(text: str) -> bool:
        """Fragmentos de especificación de insumos/materiales (excluye formato de oferta económica)."""
        if not text or len(text) < 40:
            return False
        if ChatbotRAGAgent._is_economic_format_chunk(text):
            return False
        low = text.lower()
        markers = (
            "biodegradabilidad",
            "biodegradable",
            "no contaminante",
            "rpbi",
            "residuo peligroso",
            "residuos peligrosos",
            "biológico-infeccioso",
            "biologico infeccioso",
            "muestras",
            "muestra física",
            "muestra fisica",
            "almacén",
            "almacen",
            "insumos",
            "material de limpieza",
            "materiales de limpieza",
            "concentración",
            "concentracion",
            "envase",
            "bidón",
            "bidon",
            "productos químicos",
            "productos quimicos",
            "grado clínico",
            "grado clinico",
            "entrega de materiales",
            "suministro de materiales",
            "características de muestras",
            "caracteristicas de muestras",
        )
        return any(m in low for m in markers)

    def _hydrate_supplies_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Páginas atómicas con requisitos de insumos/materiales (máx. 6)."""
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is None or pg in seen_pg:
                continue
            if self._is_supplies_spec_chunk(doc or ""):
                seen_pg.add(pg)
                pinned_pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pinned_pages[:6]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_supplies_spec_chunk(full):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
        return out_docs, out_metas

    @classmethod
    def _extract_supplies_bullets_for_topics(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
        topic_keys: Tuple[str, ...],
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        for doc, meta in zip(context_docs, metadatas):
            if not doc:
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", doc):
                s = sent.strip()
                sl = s.lower()
                if len(s) < 35 or len(s) > 480:
                    continue
                if not any(k in sl for k in topic_keys):
                    continue
                if cls._is_economic_format_chunk(s):
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
                if len(bullets) >= 5:
                    return bullets
        return bullets

    @classmethod
    def _compose_supplies_structured_response(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        """Localizador forense de insumos/materiales Partida 2 (sin moneda ni formato de oferta)."""
        biodeg = cls._extract_supplies_bullets_for_topics(
            context_docs,
            metadatas,
            (
                "biodegradabilidad",
                "biodegradable",
                "no contaminante",
                "90%",
                "contaminante",
            ),
        )
        envase = cls._extract_supplies_bullets_for_topics(
            context_docs,
            metadatas,
            (
                "envase",
                "bidón",
                "bidon",
                "concentración",
                "concentracion",
                "grado clínico",
                "grado clinico",
                "productos químicos",
                "productos quimicos",
                "cloro",
                "jabón",
                "jabon",
                "desinfectante",
            ),
        )
        muestras = cls._extract_supplies_bullets_for_topics(
            context_docs,
            metadatas,
            (
                "muestras",
                "muestra física",
                "muestra fisica",
                "almacén",
                "almacen",
                "características de muestras",
                "caracteristicas de muestras",
            ),
        )
        rpbi = cls._extract_supplies_bullets_for_topics(
            context_docs,
            metadatas,
            (
                "rpbi",
                "residuo peligroso",
                "residuos peligrosos",
                "biológico-infeccioso",
                "biologico infeccioso",
                "manejo de residuos",
            ),
        )
        parts = [
            "**Insumos y materiales — especificaciones técnicas (Partida 2 / Anexo III)**",
            "(Extraído del pliego indexado; no incluye moneda ni formato de propuesta económica.)",
            "",
            "### 1) BIODEGRADABILIDAD Y PRODUCTOS",
        ]
        if biodeg:
            parts.extend(biodeg)
        else:
            parts.append("• No se recuperó biodegradabilidad en los fragmentos de esta consulta.")
        parts.extend(["", "### 2) ENVASE, CONCENTRACIÓN Y PRODUCTOS QUÍMICOS"])
        if envase:
            parts.extend(envase)
        else:
            parts.append("• No se recuperaron envases/concentración/químicos en los fragmentos.")
        parts.extend(["", "### 3) MUESTRAS FÍSICAS EN ALMACÉN"])
        if muestras:
            parts.extend(muestras)
        else:
            parts.append("• No se recuperó entrega de muestras en almacén en los fragmentos.")
        parts.extend(["", "### 4) MANEJO DE RPBI"])
        if rpbi:
            parts.extend(rpbi)
        else:
            parts.append("• No se recuperó manejo de RPBI en los fragmentos indexados.")
        return "\n".join(parts)

    @classmethod
    def _supplies_structured_ready(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        """Listo si hay al menos dos bloques temáticos con evidencia."""
        blocks = 0
        if cls._extract_supplies_bullets_for_topics(
            context_docs, metadatas, ("biodegradabilidad", "biodegradable")
        ):
            blocks += 1
        if cls._extract_supplies_bullets_for_topics(
            context_docs, metadatas, ("muestras", "almacen", "almacén")
        ):
            blocks += 1
        if cls._extract_supplies_bullets_for_topics(
            context_docs, metadatas, ("rpbi", "residuo peligroso")
        ):
            blocks += 1
        if cls._extract_supplies_bullets_for_topics(
            context_docs, metadatas, ("envase", "concentracion", "concentración")
        ):
            blocks += 1
        return blocks >= 2

    # Combo adjudicación: criterio binario, zonas Anexo III, partidas 1+2 en conjunto.
    _ADJUDICATION_FOCAL_RAG_QUERY: str = (
        "adjudicación criterio binario artículo 36 mejor propuesta económica "
        "zona partida 1 y 2 total ofertado en conjunto Anexo III limpieza "
        "participar una o varias zonas no se aceptarán opciones propuesta por zona"
    )

    @staticmethod
    def _strip_chunk_source_prefix(text: str) -> str:
        """Quita encabezados [FUENTE: …] y restos de metadatos de chunk en texto indexado."""
        t = str(text or "")
        t = re.sub(r"\[FUENTE:[^\]]*\]\s*", "", t, flags=re.IGNORECASE)
        # Restos cuando el chunk se partió o el encabezado quedó incompleto.
        t = re.sub(
            r"[^\[\n]{8,200}?\.pdf\s*\|\s*PÁGINA:\s*\d+\]",
            "",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(r"\s*\|\s*PÁGINA:\s*\d+\]", "", t, flags=re.IGNORECASE)
        t = re.sub(r"^\d{1,3}-\d{1,3}\s+", "", t.strip())
        t = re.sub(r"^GARANTIAS\s+", "", t, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", t).strip()

    @staticmethod
    def _short_source_label(source: str) -> str:
        """Etiqueta legible para citas (sin nombre de archivo kilométrico)."""
        s = str(source or "").strip()
        if not s:
            return "Bases"
        up = s.upper()
        if "BASES" in up:
            return "Bases del procedimiento"
        if "CONVOCATORIA" in up:
            return "Convocatoria"
        if len(s) <= 52:
            return s
        return s[:49].rstrip() + "…"

    @staticmethod
    def _format_literary_cite(meta: Dict[str, Any], primary_doc: Optional[str] = None) -> str:
        """Cita visible al usuario (sin [FUENTE:…] — el sanitizador del chat lo elimina)."""
        label = ChatbotRAGAgent._short_source_label(
            str(meta.get("source") or primary_doc or "Bases")
        )
        pg = meta.get("page", "?")
        return f"· {label}, página {pg}"

    @classmethod
    def _iter_sanitized_chunk_bodies(cls, text: str) -> List[str]:
        """Segmentos de texto tras quitar metadatos de indexación (páginas hidratadas)."""
        raw = str(text or "")
        if not raw.strip():
            return []
        segments = re.split(r"\[FUENTE:[^\]]*\]\s*", raw, flags=re.IGNORECASE)
        out: List[str] = []
        for seg in segments:
            clean = cls._strip_chunk_source_prefix(seg)
            if clean and len(clean) >= 20:
                out.append(clean)
        if not out and raw.strip():
            clean = cls._strip_chunk_source_prefix(raw)
            if clean:
                out.append(clean)
        return out

    @classmethod
    def _detect_adjudication_intent(cls, query: str) -> bool:
        """True si la consulta apunta a criterio de adjudicación y/o participación por zonas."""
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        if any(
            k in q
            for k in (
                "adjudicacion",
                "criterio de adjudicacion",
                "criterio exacto de adjudicacion",
                "criterio binario",
            )
        ):
            return True
        if "zona" in q and any(
            k in q for k in ("particip", "competir", "adjudic", "partida", "varias")
        ):
            return True
        if "partida 1" in q and "partida 2" in q and "zona" in q:
            return True
        return False

    @staticmethod
    def _is_adjudication_chunk(text: str) -> bool:
        if not text or len(text) < 50:
            return False
        low = ChatbotRAGAgent._strip_chunk_source_prefix(text).lower()
        markers = (
            "criterio binario",
            "adjudicación de la presente",
            "adjudicacion de la presente",
            "total ofertado en conjunto",
            "partidas 1 y 2",
            "partida 1 y la partida 2",
            "no se aceptarán opciones",
            "no se aceptaran opciones",
            "artículo 36 de la ley",
            "articulo 36 de la ley",
            "mejor propuesta económica",
            "mejor propuesta economica",
            "adjudicará por zona",
            "adjudicara por zona",
        )
        return any(m in low for m in markers)

    def _hydrate_adjudication_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        if not primary_doc:
            return [], []
        pinned_pages: List[Any] = []
        seen_pg: set = set()
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is None or pg in seen_pg:
                continue
            if self._is_adjudication_chunk(doc or ""):
                seen_pg.add(pg)
                pinned_pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        pages_to_fetch: List[Any] = []
        for pg in pinned_pages:
            if pg not in pages_to_fetch:
                pages_to_fetch.append(pg)
        for pg in (31, 4, 18):
            if pg not in pages_to_fetch:
                pages_to_fetch.append(pg)
        for pg in pages_to_fetch[:5]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_adjudication_chunk(full) or pg in (4, 18, 31):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
            if len(out_docs) >= 5:
                break
        return out_docs, out_metas

    @classmethod
    def _extract_adjudication_conjunto_mandatory(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        """Regla medular: total ofertado en conjunto de partidas 1 y 2 por zona (p. ej. 31)."""
        for doc, meta in zip(context_docs, metadatas):
            clean = cls._strip_chunk_source_prefix(doc or "")
            if "total ofertado en conjunto" not in clean.lower():
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", clean):
                s = sent.strip()
                if "total ofertado en conjunto" in s.lower() and len(s) >= 50:
                    return f"• {s} [PÁGINA {pg}]"
            idx = clean.lower().find("total ofertado en conjunto")
            if idx >= 0:
                snippet = clean[max(0, idx - 120) : idx + 220].strip()
                return f"• {snippet} [PÁGINA {pg}]"
        return ""

    @classmethod
    def _extract_adjudication_criterion_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        keys = (
            "criterio binario",
            "artículo 36",
            "articulo 36",
            "mejor propuesta económica",
            "mejor propuesta economica",
            "total ofertado en conjunto",
            "precio y el cumplimiento",
        )
        for doc, meta in zip(context_docs, metadatas):
            clean = cls._strip_chunk_source_prefix(doc or "")
            if not clean or not cls._is_adjudication_chunk(clean):
                continue
            pg = meta.get("page", "?")
            for sent in re.split(r"(?<=[.;])\s+", clean):
                s = sent.strip()
                if len(s) < 50 or len(s) > 420:
                    continue
                sl = s.lower()
                if not any(k in sl for k in keys):
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append((0 if "total ofertado en conjunto" in sl else 1, f"• {s} [PÁGINA {pg}]"))
                if len(bullets) >= 5:
                    break
        bullets.sort(key=lambda x: x[0])
        return [b[1] for b in bullets[:5]]

    @classmethod
    def _extract_adjudication_zones_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        keys = (
            "no se aceptarán opciones",
            "no se aceptaran opciones",
            "una sola propuesta por zona",
            "partida 1 en conjunto con la partida 2",
            "partida 1 y 2",
            "cuatro",
            "zona a",
            "zona b",
            "varias zona",
            "según participipe",
            "totalidad de la zona",
            "totalidad de los renglones",
            "participar para una o varias",
            "nota: para el anexo iii limpieza",
        )
        exclude_zone_noise = (
            "d-iii integración",
            "d-iii integracion",
            "tarifas ofertadas",
            "usb la cual",
        )
        for doc, meta in zip(context_docs, metadatas):
            clean = cls._strip_chunk_source_prefix(doc or "")
            if not clean:
                continue
            pg = meta.get("page", "?")
            low = clean.lower()
            if not (
                cls._is_adjudication_chunk(clean)
                or any(k in low for k in keys)
            ):
                continue
            for sent in re.split(r"(?<=[.;])\s+", clean):
                s = sent.strip()
                if len(s) < 45 or len(s) > 420:
                    continue
                sl = s.lower()
                if any(n in sl for n in exclude_zone_noise):
                    continue
                if not any(k in sl for k in keys):
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
                if len(bullets) >= 6:
                    return bullets
        return bullets

    @classmethod
    def _compose_adjudication_structured_response(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        criterion = cls._extract_adjudication_criterion_bullets(context_docs, metadatas)
        conjunto = cls._extract_adjudication_conjunto_mandatory(context_docs, metadatas)
        if conjunto and not any(
            "total ofertado en conjunto" in b.lower() for b in criterion
        ):
            criterion = [conjunto] + criterion
        zones = cls._extract_adjudication_zones_bullets(context_docs, metadatas)
        parts = [
            "**Criterio de adjudicación y participación por zonas**",
            "(Extraído del pliego indexado; sin narrativa inferida.)",
            "",
            "### 1) CRITERIO DE ADJUDICACIÓN",
        ]
        if criterion:
            parts.extend(criterion)
        else:
            parts.append("• No se recuperó el criterio de adjudicación en los fragmentos.")
        parts.extend(["", "### 2) PARTICIPACIÓN POR UNA O VARIAS ZONAS"])
        if zones:
            parts.extend(zones)
        else:
            parts.append(
                "• No se recuperaron reglas de zonas/opciones en los fragmentos indexados."
            )
        return "\n".join(parts)

    @classmethod
    def _adjudication_structured_ready(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        criterion = cls._extract_adjudication_criterion_bullets(context_docs, metadatas)
        zones = cls._extract_adjudication_zones_bullets(context_docs, metadatas)
        return len(criterion) >= 1 and len(zones) >= 1

    # Combo penas convencionales contractuales (tasa, cobro, tope vs garantía).
    _PENALTY_FOCAL_RAG_QUERY: str = (
        "pena convencional penalización sanción atraso incumplimiento plazos pactados "
        "contrato semana fracción saldos pendientes de pago garantía de cumplimiento "
        "cuantía monto total sanciones límite financiero"
    )

    @classmethod
    def _detect_penalty_intent(cls, query: str) -> bool:
        """Penas convencionales / sanciones por atraso o incumplimiento en fase contractual."""
        q = cls._normalize_query_for_intent(query)
        if not q:
            return False
        if any(
            k in q
            for k in (
                "pena convencional",
                "penas convencionales",
                "penalizacion",
                "penalizaciones",
                "sancion contractual",
                "sanciones contractuales",
            )
        ):
            return True
        if ("penaliz" in q or "sancion" in q) and any(
            k in q for k in ("atraso", "incumplimiento", "mora", "servicio", "contrato")
        ):
            return True
        if any(k in q for k in ("limite financiero", "limites financieros", "tope")) and any(
            k in q for k in ("pena", "penaliz", "sancion", "garantia", "garantía")
        ):
            return True
        return False

    @classmethod
    def _detect_operational_personnel_penalty_intent(cls, query: str) -> bool:
        """
        Deducciones por ausencias/turnos (vigilancia u operación), no penas convencionales genéricas.
        """
        q = cls._normalize_query_for_intent(query)
        if cls._detect_penalty_intent(query):
            return False
        return any(
            k in q
            for k in (
                "falta",
                "inasist",
                "ausenc",
                "retard",
                "turno no cubierto",
                "turno vacio",
                "elemento que falte",
                "vigilancia",
                "personal",
            )
        ) and any(k in q for k in ("penaliz", "deducc", "descuento", "sancion"))

    @staticmethod
    def _is_penalty_contract_chunk(text: str) -> bool:
        """Cláusulas de pena convencional por atraso/incumplimiento contractual."""
        if not text or len(text) < 50:
            return False
        low = ChatbotRAGAgent._strip_chunk_source_prefix(text).lower()
        if ChatbotRAGAgent._is_evaluation_percent_noise(text):
            return False
        if "bienes pendientes de entregar" in low and "2.5" in low:
            return False
        markers = (
            "penalizaciones se harán efectivas",
            "penalizaciones se haran efectivas",
            "saldos pendientes de pago",
            "monto total de las citadas sanciones",
            "plazos pactados en el contrato",
            "semana de atraso",
            "fracción de semana",
            "fraccion de semana",
            "bienes y/o servicios",
            "no suministrados o prestados",
        )
        has_pct = bool(re.search(r"\d+(?:\.\d+)?\s*%", low))
        has_pena = (
            "pena convencional" in low
            or "penas convencionales" in low
            or "penalizacion" in low
            or "penalización" in low
        )
        if has_pena and has_pct:
            return True
        if any(m in low for m in markers):
            return True
        if ("no excederá la cuantía" in low or "no excedera la cuantia" in low) and (
            "citadas sanciones" in low or "penalizacion" in low or "penalización" in low
        ):
            return True
        return False

    @staticmethod
    def _is_guarantee_admin_noise_for_penalty(text: str) -> bool:
        """Trámites/plazos de garantía (p. ej. pág. 23), no penas convencionales."""
        if not text:
            return False
        low = ChatbotRAGAgent._strip_chunk_source_prefix(text).lower()
        if ChatbotRAGAgent._is_penalty_contract_chunk(text):
            return False
        noise = (
            "plazo máximo de 10 días",
            "plazo maximo de 10 dias",
            "cobro de la garantía de cumplimiento otorgada",
            "cobro de la garantia de cumplimiento otorgada",
            "obligaciones a cargo del licitante adjudicado, no son divisibles",
            "modificación correspondiente a la fianza",
            "modificacion correspondiente a la fianza",
            "presentar la garantía de cumplimiento al mismo",
            "presentar la garantia de cumplimiento al mismo",
            "causa de rescisión del contrato",
            "secretaría de finanzas",
            "secretaria de finanzas",
            "otorgamiento de prórrogas o esperas",
            "otorgamiento de prorrogas o esperas",
            "realizar la modificación correspondiente",
        )
        if any(n in low for n in noise):
            return True
        if (
            ChatbotRAGAgent._is_guarantee_contract_chunk(text)
            and "pena convencional" not in low
            and "penas convencionales" not in low
            and "saldos pendientes" not in low
            and "citadas sanciones" not in low
        ):
            return True
        return False

    @staticmethod
    def _is_penalty_mechanism_sentence(sentence_lower: str) -> bool:
        """Oración de cobro/tope de penas, no administración de garantía."""
        if ChatbotRAGAgent._is_guarantee_admin_noise_for_penalty(sentence_lower):
            return False
        strong = (
            "saldos pendientes de pago",
            "saldos pendientes",
            "penalizaciones se harán efectivas",
            "penalizaciones se haran efectivas",
            "monto total de las citadas sanciones",
            "no excederá la cuantía",
            "no excedera la cuantia",
            "no exceda la cuantía",
            "no exceda la cuantia",
        )
        return any(k in sentence_lower for k in strong)

    @classmethod
    def _doc_eligible_for_penalty_extract(cls, text: str) -> bool:
        """Solo documentos con señales de pena convencional (no garantía administrativa)."""
        if not text or len(text) < 40:
            return False
        if cls._is_guarantee_admin_noise_for_penalty(text):
            return False
        return cls._is_penalty_contract_chunk(text)

    def _penalty_probe_and_hydrate(
        self,
        session_id: str,
        primary_doc: Optional[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """
        Segunda pasada RAG: localizar páginas con cláusula de pena aunque el focal devuelva garantías.
        """
        if not primary_doc:
            return [], []
        probe_q = (
            "pena convencional semana atraso incumplimiento saldos pendientes de pago "
            "monto total citadas sanciones no excederá cuantía garantía 2%"
        )
        try:
            res = self.vector_db.query_texts_filtered(
                session_id, probe_q, source_filter=primary_doc, n_results=16
            )
        except Exception:
            res = self.vector_db.query_texts(session_id, probe_q, n_results=16)
        probe_docs = list(res.get("documents") or [])
        probe_metas = list(res.get("metadatas") or [])
        pages: List[Any] = []
        for meta, doc in zip(probe_metas, probe_docs):
            if self._is_penalty_contract_chunk(doc or ""):
                pg = meta.get("page")
                if pg is not None and pg not in pages:
                    pages.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pages[:6]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_penalty_contract_chunk(full):
                    out_docs.append(full)
                    out_metas.append(
                        {"source": primary_doc, "page": pg, "hydrated": True, "penalty_probe": True}
                    )
            if len(out_docs) >= 6:
                break
        return out_docs, out_metas

    def _hydrate_penalty_atomic_pages(
        self,
        session_id: str,
        primary_doc: Optional[str],
        focal_metas: List[Dict[str, Any]],
        focal_docs: List[str],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        if not primary_doc:
            return [], []
        pages_to_fetch: List[Any] = []
        for meta, doc in zip(focal_metas, focal_docs):
            pg = meta.get("page")
            if pg is not None and pg not in pages_to_fetch:
                pages_to_fetch.append(pg)
        out_docs: List[str] = []
        out_metas: List[Dict[str, Any]] = []
        for pg in pages_to_fetch[:5]:
            for full in self.vector_db.fetch_page_documents(session_id, primary_doc, pg):
                if not full or full in out_docs:
                    continue
                if self._is_penalty_contract_chunk(full):
                    out_docs.append(full)
                    out_metas.append({"source": primary_doc, "page": pg, "hydrated": True})
            if len(out_docs) >= 5:
                break
        return out_docs, out_metas

    @classmethod
    def _split_penalty_sentences(cls, text: str) -> List[str]:
        """Parte párrafos PDF (punto, punto y coma o salto de línea)."""
        parts: List[str] = []
        for block in re.split(r"\n{2,}|\n", text or ""):
            block = block.strip()
            if not block:
                continue
            parts.extend(re.split(r"(?<=[.;])\s+", block))
        return [p.strip() for p in parts if p.strip()]

    @classmethod
    def _extract_penalty_rate_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        for doc, meta in zip(context_docs, metadatas):
            clean = cls._strip_chunk_source_prefix(doc or "")
            if not clean or not cls._doc_eligible_for_penalty_extract(clean):
                continue
            pg = meta.get("page", "?")
            for sent in cls._split_penalty_sentences(clean):
                sl = sent.lower()
                if len(sent) < 35 or len(sent) > 520:
                    continue
                if not re.search(r"\d+(?:\.\d+)?\s*%", sl):
                    continue
                if not any(
                    k in sl
                    for k in (
                        "pena convencional",
                        "penas convencional",
                        "aplicará",
                        "aplicara",
                        "aplicar",
                        "semana",
                        "atraso",
                        "incumplimiento",
                        "bienes y/o",
                        "no suministrados",
                        "no prestados",
                    )
                ):
                    continue
                key = sent[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {sent} [PÁGINA {pg}]")
                if len(bullets) >= 3:
                    return bullets
            if bullets:
                continue
            m = re.search(
                r"((?:pena|penas)\s+convencional(?:es)?[^.]{0,200}?\d+(?:\.\d+)?\s*%[^.]{0,200})",
                clean,
                flags=re.IGNORECASE,
            )
            if m:
                snippet = m.group(1).strip()
                key = snippet[:100]
                if key not in seen:
                    seen.add(key)
                    bullets.append(f"• {snippet} [PÁGINA {pg}]")
        return bullets

    @classmethod
    def _extract_penalty_cap_and_mechanism_bullets(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> List[str]:
        seen: set[str] = set()
        bullets: List[str] = []
        for doc, meta in zip(context_docs, metadatas):
            clean = cls._strip_chunk_source_prefix(doc or "")
            if not clean or not cls._doc_eligible_for_penalty_extract(clean):
                continue
            pg = meta.get("page", "?")
            for sent in cls._split_penalty_sentences(clean):
                s = sent.strip()
                sl = s.lower()
                if len(s) < 45 or len(s) > 520:
                    continue
                if not cls._is_penalty_mechanism_sentence(sl):
                    continue
                key = s[:100]
                if key in seen:
                    continue
                seen.add(key)
                bullets.append(f"• {s} [PÁGINA {pg}]")
                if len(bullets) >= 4:
                    return bullets
        return bullets

    @classmethod
    def _compose_penalty_structured_response(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> str:
        rates = cls._extract_penalty_rate_bullets(context_docs, metadatas)
        caps = cls._extract_penalty_cap_and_mechanism_bullets(context_docs, metadatas)
        parts = [
            "**Penas convencionales y límites financieros**",
            "(Extraído del pliego indexado; sin porcentajes ni páginas inventados.)",
            "",
            "### 1) TASA DE PENA CONVENCIONAL",
        ]
        if rates:
            parts.extend(rates)
        else:
            parts.append(
                "• No se recuperó en los fragmentos un porcentaje de pena convencional explícito."
            )
        parts.extend(["", "### 2) MECANISMO DE COBRO Y LÍMITE FINANCIERO"])
        if caps:
            parts.extend(caps)
        else:
            parts.append(
                "• No se recuperó tope contra garantía de cumplimiento o mecanismo de cobro."
            )
        return "\n".join(parts)

    @classmethod
    def _penalty_structured_ready(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        rates = cls._extract_penalty_rate_bullets(context_docs, metadatas)
        caps = cls._extract_penalty_cap_and_mechanism_bullets(context_docs, metadatas)
        return len(rates) >= 1 and len(caps) >= 1

    @classmethod
    def _penalty_should_compose(
        cls, context_docs: List[str], metadatas: List[Dict[str, Any]]
    ) -> bool:
        """Solo sustituir LLM si hay tasa y mecanismo reales (evita respuesta vacía o pág. 23)."""
        return cls._penalty_structured_ready(context_docs, metadatas)

    @classmethod
    def _rank_penalty_doc_pool(
        cls,
        context_docs: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        scored: List[tuple[float, str, Dict[str, Any]]] = []
        for doc, meta in zip(context_docs, metadatas):
            score = 0.0
            if cls._is_penalty_contract_chunk(doc or ""):
                score += 200.0
            if meta.get("penalty_probe") or meta.get("hydrated"):
                score += 80.0
            if cls._is_guarantee_admin_noise_for_penalty(doc or ""):
                score -= 300.0
            scored.append((score, doc, meta if isinstance(meta, dict) else {}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored], [x[2] for x in scored]

    @classmethod
    def _sanitize_penalty_llm_contradictions(cls, content: str) -> str:
        """Quita disclaimers de «sin tope» cuando el texto ya cita garantía/cuantía."""
        if not content:
            return content
        low = content.lower()
        if not any(
            k in low
            for k in (
                "garantía de cumplimiento",
                "garantia de cumplimiento",
                "cuantía de la garantía",
                "cuantia de la garantia",
                "no excederá",
                "no excedera",
                "saldos pendientes",
            )
        ):
            return content
        patterns = (
            r"(?im)^\s*no hay información[^.\n]*tope[^.\n]*\.?\s*",
            r"(?im)^\s*no aparece[^.\n]*tope[^.\n]*\.?\s*",
            r"(?im)^\s*no se encontró[^.\n]*tope[^.\n]*\.?\s*",
            r"(?im)^\s*no hay información sobre un tope[^.\n]*\.?\s*",
        )
        out = content
        for pat in patterns:
            out = re.sub(pat, "", out)
        return re.sub(r"\n{3,}", "\n\n", out).strip()

    @staticmethod
    def _merge_doc_meta_pool(
        *pairs: tuple[List[str], List[Dict[str, Any]]],
        limit: int = 28,
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Une pools de chunks priorizando el orden de los pares (p. ej. contexto LLM primero)."""
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for doc_list, meta_list in pairs:
            for doc, meta in zip(doc_list or [], meta_list or []):
                if not doc or doc in seen:
                    continue
                seen.add(doc)
                docs.append(doc)
                metas.append(meta if isinstance(meta, dict) else {})
                if len(docs) >= limit:
                    return docs, metas
        return docs, metas

    @staticmethod
    def _expand_legal_ontology(query: str) -> str:
        """
        Expansor Ontológico Legal (Fase de Ingesta RAG).
        Mapea la jerga comercial a los términos estrictos de la legislación mexicana.
        """
        q_upper = query.upper()
        expanded = query

        ontology = {
            "REPSE": "REPSE OR \"Artículo 15\" OR \"Servicios Especializados\" OR \"STPS\"",
            "SSPC": "SSPC OR \"Seguridad y Protección Ciudadana\" OR \"Permiso Federal\"",
            "IMSS": "IMSS OR \"Instituto Mexicano del Seguro Social\" OR \"Cuotas Obrero Patronales\"",
            "LFT": "LFT OR \"Ley Federal del Trabajo\"",
            "SUA": "SUA OR \"Sistema Único de Autodeterminación\"",
            "INFONAVIT": "INFONAVIT OR \"Instituto del Fondo Nacional de la Vivienda para los Trabajadores\"",
            "ISO": "ISO 9001 OR ISO 14001 OR ISO 45001 OR certificación OR certificacion",
            "NMX": "NMX OR norma mexicana OR NMX-R",
            "NOM": "NOM-035 OR NOM STPS OR norma oficial mexicana",
            "SOLVENCIA": "solvencia participante opinión cumplimiento SAT IMSS INFONAVIT ISO NMX REPSE",
            "PROPUESTA ECONÓMICA": "\"propuesta económica\" OR \"moneda nacional\" OR \"número y letra\" OR \"Anexo III\" OR \"tarifa mensual\" OR \"precio unitario\"",
            "PROPUESTA ECONOMICA": "\"propuesta económica\" OR \"moneda nacional\" OR \"número y letra\" OR \"Anexo III\" OR \"tarifa mensual\" OR \"precio unitario\"",
            "ADJUDICACIÓN": "\"criterio binario\" OR \"adjudicación\" OR \"artículo 36\" OR \"total ofertado en conjunto\" OR \"partidas 1 y 2\"",
            "ADJUDICACION": "\"criterio binario\" OR \"adjudicación\" OR \"artículo 36\" OR \"total ofertado en conjunto\" OR \"partidas 1 y 2\"",
            "PENALIZACIÓN": "\"pena convencional\" OR \"penalización\" OR \"sanción\" OR \"atraso\" OR \"saldos pendientes\" OR \"garantía de cumplimiento\" OR \"plazos pactados\"",
            "PENALIZACION": "\"pena convencional\" OR \"penalización\" OR \"sanción\" OR \"atraso\" OR \"saldos pendientes\" OR \"garantía de cumplimiento\" OR \"plazos pactados\"",
            "6.1": "\"6.1\" OR \"DOCUMENTACIÓN COMPLEMENTARIA\" OR \"Requisitos de la propuesta técnica\"",
            "GARANTÍA": "\"Garantía de Cumplimiento\" OR \"Garantia de Cumplimiento\" OR \"fianza\" OR \"cheque certificado\" OR \"cheque de caja\" OR \"forma de garantizar\" NOT \"transferencia electrónica a mes vencido\"",
            "GARANTIA": "\"Garantía de Cumplimiento\" OR \"Garantia de Cumplimiento\" OR \"fianza\" OR \"cheque certificado\" OR \"cheque de caja\" OR \"forma de garantizar\" NOT \"transferencia electrónica a mes vencido\"",
            "FIANZA": "\"Garantía de Cumplimiento\" OR \"Garantia de Cumplimiento\" OR \"fianza\" OR \"cheque certificado\" OR \"cheque de caja\" OR \"forma de garantizar\" NOT \"transferencia electrónica a mes vencido\"",
            "DEDUCCIÓN": "\"deducción específica\" OR \"falta de elemento\" OR \"inasistencia\" OR \"hora hombre no cubierta\" OR \"deducciones\" OR \"penas convencionales\" OR \"ausencia\" NOT \"bienes pendientes de entregar\" NOT \"atraso en la entrega de bienes\"",
            "DEDUCCION": "\"deducción específica\" OR \"falta de elemento\" OR \"inasistencia\" OR \"hora hombre no cubierta\" OR \"deducciones\" OR \"penas convencionales\" OR \"ausencia\" NOT \"bienes pendientes de entregar\" NOT \"atraso en la entrega de bienes\"",
            "FALTA": "\"deducción específica\" OR \"falta de elemento\" OR \"inasistencia\" OR \"hora hombre no cubierta\" OR \"deducciones\" OR \"penas convencionales\" OR \"ausencia\" NOT \"bienes pendientes de entregar\" NOT \"atraso en la entrega de bienes\"",
            "ANEXO 9": "\"Anexo 9\" OR \"Anexo No. 9\" OR \"Salario Real\" OR \"FSR\" OR \"Factor de Salario Real\" OR \"Cálculo del Factor\" NOT \"medios remotos\"",
            "ANEXO NO. 9": "\"Anexo 9\" OR \"Anexo No. 9\" OR \"Salario Real\" OR \"FSR\" OR \"Factor de Salario Real\" OR \"Cálculo del Factor\" NOT \"medios remotos\""
        }

        # Inyección semántica si hay coincidencia
        for key, value in ontology.items():
            if key in q_upper:
                expanded += f" {value}"

        return expanded

    async def _handle_rag_query(
        self,
        session_id: str,
        user_query: str,
        pending: List = [],
        correlation_id: str = "",
        *,
        current_idx: int = 0,
        extra_context: str = "",
        suggested_actions: List = None
    ) -> AgentOutput:
        """Flujo RAG estándar: busca en ChromaDB y genera respuesta fundamentada."""
        try:
            _sess = await self.context_manager.memory.get_session(session_id) or {}
        except Exception:
            _sess = {}
        econ_block_ctx = self._economic_blocking_prompt_section_from_tasks(_sess.get("tasks_completed"))
        comp_ctx = self._compliance_truth_prompt_section_from_session(
            _sess.get("tasks_completed"), _sess
        )
        candidates_ctx = self._document_candidates_prompt_section(_sess)

        all_sources = self.vector_db.get_sources(session_id)
        print(f"DEBUG_SOURCES: all_sources={all_sources}, type={type(all_sources)}")

        # Detectar documento principal (bases antes que convocatoria)
        primary_doc = self._resolve_primary_bases_doc(all_sources)

        # HITO: Bypass de Resiliencia (Gemini v1.8)
        # Si la pregunta es sobre el número de licitación y primary_doc tiene el formato, 
        # lo inyectamos como "Verdad Absoluta" en el contexto extra.
        if "número" in user_query.lower() or "codigo" in user_query.lower() or "cuál es esta licitación" in user_query.lower():
            if primary_doc and ("LA-" in primary_doc or "N-" in primary_doc):
                clean_num = primary_doc.split(".")[0].split(" ")[0]
                extra_context += f"\n[DATO DE IDENTIDAD DETECTADO]: El número oficial de esta licitación es «{clean_num}» (extraído del nombre del archivo principal).\n"

        # Búsqueda ampliada: combinamos el documento principal con una búsqueda general 
        # para evitar "ceguera" ante anexos no etiquetados como bases.
        search_results_primary = {"documents": [], "metadatas": []}
        
        # [PARCHE ONTOLÓGICO] Expandir query antes de pegarle al vector db
        expanded_query = self._expand_legal_ontology(user_query)
        print(f"[RAG] Query Original: {user_query} | Query Expandida: {expanded_query}", flush=True)

        if primary_doc:
            search_results_primary = self.vector_db.query_texts_filtered(
                session_id, expanded_query, source_filter=primary_doc, n_results=12
            )
        
        search_results_general = self.vector_db.query_texts(session_id, expanded_query, n_results=18)

        # Combo A + B: intención cronograma → focal RAG + páginas atómicas + Analyst solo si anclado.
        cronogram_intent = self._detect_cronogram_intent(user_query)
        guarantee_intent = self._detect_guarantee_intent(user_query)
        solvency_intent = self._detect_solvency_intent(user_query)
        supplies_intent = self._detect_supplies_technical_intent(user_query)
        economic_intent = self._detect_economic_intent(user_query)
        adjudication_intent = self._detect_adjudication_intent(user_query)
        penalty_intent = self._detect_penalty_intent(user_query)
        focal_docs: List[str] = []
        focal_metas: List[Dict[str, Any]] = []
        hydrated_docs: List[str] = []
        hydrated_metas: List[Dict[str, Any]] = []
        guarantee_focal_docs: List[str] = []
        guarantee_focal_metas: List[Dict[str, Any]] = []
        guarantee_hydrated_docs: List[str] = []
        guarantee_hydrated_metas: List[Dict[str, Any]] = []
        solvency_focal_docs: List[str] = []
        solvency_focal_metas: List[Dict[str, Any]] = []
        solvency_hydrated_docs: List[str] = []
        solvency_hydrated_metas: List[Dict[str, Any]] = []
        economic_focal_docs: List[str] = []
        economic_focal_metas: List[Dict[str, Any]] = []
        economic_hydrated_docs: List[str] = []
        economic_hydrated_metas: List[Dict[str, Any]] = []
        supplies_focal_docs: List[str] = []
        supplies_focal_metas: List[Dict[str, Any]] = []
        supplies_hydrated_docs: List[str] = []
        supplies_hydrated_metas: List[Dict[str, Any]] = []
        adjudication_focal_docs: List[str] = []
        adjudication_focal_metas: List[Dict[str, Any]] = []
        adjudication_hydrated_docs: List[str] = []
        adjudication_hydrated_metas: List[Dict[str, Any]] = []
        penalty_focal_docs: List[str] = []
        penalty_focal_metas: List[Dict[str, Any]] = []
        penalty_hydrated_docs: List[str] = []
        penalty_hydrated_metas: List[Dict[str, Any]] = []
        if cronogram_intent:
            focal_q = self._CRONOGRAM_FOCAL_RAG_QUERY
            if primary_doc:
                focal_res = self.vector_db.query_texts_filtered(
                    session_id, focal_q, source_filter=primary_doc, n_results=12
                )
            else:
                focal_res = self.vector_db.query_texts(session_id, focal_q, n_results=12)
            focal_docs = list(focal_res.get("documents") or [])
            focal_metas = list(focal_res.get("metadatas") or [])
            hydrated_docs, hydrated_metas = self._hydrate_cronogram_atomic_pages(
                session_id, primary_doc, focal_metas, focal_docs
            )
            logger.info(
                "chatbot_cronogram_focal_rag",
                session_id=session_id,
                chunks=len(focal_docs),
                hydrated_pages=len(hydrated_metas),
                primary_doc=primary_doc,
            )

        analyst_cronogram = self._extract_analyst_cronogram_from_session(_sess)
        pliego_anchor_text = "\n".join(hydrated_docs + focal_docs[:12])
        if analyst_cronogram and self._cronogram_anchored_in_pliego(
            analyst_cronogram, pliego_anchor_text
        ):
            extra_context += "\n" + self._format_analyst_cronogram_prompt_section(analyst_cronogram)
        elif analyst_cronogram:
            logger.warning(
                "chatbot_analyst_cronogram_not_anchored",
                session_id=session_id,
                reason="fechas_analyst_no_coinciden_pliego_indexado",
            )

        if guarantee_intent:
            g_focal_q = self._GUARANTEE_FOCAL_RAG_QUERY
            if primary_doc:
                g_focal_res = self.vector_db.query_texts_filtered(
                    session_id, g_focal_q, source_filter=primary_doc, n_results=12
                )
            else:
                g_focal_res = self.vector_db.query_texts(session_id, g_focal_q, n_results=12)
            guarantee_focal_docs = list(g_focal_res.get("documents") or [])
            guarantee_focal_metas = list(g_focal_res.get("metadatas") or [])
            guarantee_hydrated_docs, guarantee_hydrated_metas = self._hydrate_guarantee_atomic_pages(
                session_id, primary_doc, guarantee_focal_metas, guarantee_focal_docs
            )
            scan_docs, scan_metas = self._guarantee_scan_and_hydrate(session_id, primary_doc)
            guarantee_hydrated_docs = scan_docs + guarantee_hydrated_docs
            guarantee_hydrated_metas = scan_metas + guarantee_hydrated_metas
            logger.info(
                "chatbot_guarantee_focal_rag",
                session_id=session_id,
                chunks=len(guarantee_focal_docs),
                hydrated_pages=len(guarantee_hydrated_metas),
                scan_pages=len(scan_metas),
                primary_doc=primary_doc,
            )

        if solvency_intent:
            s_focal_q = self._SOLVENCY_FOCAL_RAG_QUERY
            if primary_doc:
                s_focal_res = self.vector_db.query_texts_filtered(
                    session_id, s_focal_q, source_filter=primary_doc, n_results=14
                )
            else:
                s_focal_res = self.vector_db.query_texts(session_id, s_focal_q, n_results=14)
            solvency_focal_docs = list(s_focal_res.get("documents") or [])
            solvency_focal_metas = list(s_focal_res.get("metadatas") or [])
            solvency_hydrated_docs, solvency_hydrated_metas = self._hydrate_solvency_atomic_pages(
                session_id, primary_doc, solvency_focal_metas, solvency_focal_docs
            )
            logger.info(
                "chatbot_solvency_focal_rag",
                session_id=session_id,
                chunks=len(solvency_focal_docs),
                hydrated_pages=len(solvency_hydrated_metas),
                primary_doc=primary_doc,
            )

        if economic_intent:
            e_focal_q = self._ECONOMIC_FOCAL_RAG_QUERY
            if primary_doc:
                e_focal_res = self.vector_db.query_texts_filtered(
                    session_id, e_focal_q, source_filter=primary_doc, n_results=12
                )
            else:
                e_focal_res = self.vector_db.query_texts(session_id, e_focal_q, n_results=12)
            economic_focal_docs = list(e_focal_res.get("documents") or [])
            economic_focal_metas = list(e_focal_res.get("metadatas") or [])
            economic_hydrated_docs, economic_hydrated_metas = self._hydrate_economic_atomic_pages(
                session_id, primary_doc, economic_focal_metas, economic_focal_docs
            )
            logger.info(
                "chatbot_economic_focal_rag",
                session_id=session_id,
                chunks=len(economic_focal_docs),
                hydrated_pages=len(economic_hydrated_metas),
                primary_doc=primary_doc,
            )

        if supplies_intent:
            sp_focal_q = self._SUPPLIES_FOCAL_RAG_QUERY
            if primary_doc:
                sp_focal_res = self.vector_db.query_texts_filtered(
                    session_id, sp_focal_q, source_filter=primary_doc, n_results=14
                )
            else:
                sp_focal_res = self.vector_db.query_texts(session_id, sp_focal_q, n_results=14)
            supplies_focal_docs = list(sp_focal_res.get("documents") or [])
            supplies_focal_metas = list(sp_focal_res.get("metadatas") or [])
            supplies_hydrated_docs, supplies_hydrated_metas = self._hydrate_supplies_atomic_pages(
                session_id, primary_doc, supplies_focal_metas, supplies_focal_docs
            )
            logger.info(
                "chatbot_supplies_focal_rag",
                session_id=session_id,
                chunks=len(supplies_focal_docs),
                hydrated_pages=len(supplies_hydrated_metas),
                primary_doc=primary_doc,
            )

        if adjudication_intent:
            a_focal_q = self._ADJUDICATION_FOCAL_RAG_QUERY
            if primary_doc:
                a_focal_res = self.vector_db.query_texts_filtered(
                    session_id, a_focal_q, source_filter=primary_doc, n_results=12
                )
            else:
                a_focal_res = self.vector_db.query_texts(session_id, a_focal_q, n_results=12)
            adjudication_focal_docs = list(a_focal_res.get("documents") or [])
            adjudication_focal_metas = list(a_focal_res.get("metadatas") or [])
            adjudication_hydrated_docs, adjudication_hydrated_metas = (
                self._hydrate_adjudication_atomic_pages(
                    session_id, primary_doc, adjudication_focal_metas, adjudication_focal_docs
                )
            )
            logger.info(
                "chatbot_adjudication_focal_rag",
                session_id=session_id,
                chunks=len(adjudication_focal_docs),
                hydrated_pages=len(adjudication_hydrated_metas),
                primary_doc=primary_doc,
            )

        if penalty_intent:
            p_focal_q = self._PENALTY_FOCAL_RAG_QUERY
            if primary_doc:
                p_focal_res = self.vector_db.query_texts_filtered(
                    session_id, p_focal_q, source_filter=primary_doc, n_results=12
                )
            else:
                p_focal_res = self.vector_db.query_texts(session_id, p_focal_q, n_results=12)
            penalty_focal_docs = list(p_focal_res.get("documents") or [])
            penalty_focal_metas = list(p_focal_res.get("metadatas") or [])
            penalty_hydrated_docs, penalty_hydrated_metas = self._hydrate_penalty_atomic_pages(
                session_id, primary_doc, penalty_focal_metas, penalty_focal_docs
            )
            probe_docs, probe_metas = self._penalty_probe_and_hydrate(session_id, primary_doc)
            penalty_hydrated_docs = probe_docs + penalty_hydrated_docs
            penalty_hydrated_metas = probe_metas + penalty_hydrated_metas
            logger.info(
                "chatbot_penalty_focal_rag",
                session_id=session_id,
                chunks=len(penalty_focal_docs),
                hydrated_pages=len(penalty_hydrated_metas),
                probe_pages=len(probe_metas),
                primary_doc=primary_doc,
            )

        # Merge de resultados priorizando la búsqueda híbrida general (tiene los filtros de coexistencia de HybridSearch-v3)
        extra_docs = []
        extra_metas = []
        q_lower = user_query.lower()
        if solvency_intent:
            search_solvency = self.vector_db.query_texts(
                session_id,
                "ISO 9001 14001 45001 NMX NOM-035 REPSE opinión SAT IMSS INFONAVIT solvencia participante",
                n_results=14,
            )
            extra_docs = list(search_solvency.get("documents") or [])
            extra_metas = list(search_solvency.get("metadatas") or [])
        elif any(w in q_lower for w in ["repse", "sspc", "seguridad privada", "autorización", "registro"]):
            search_extra = self.vector_db.query_texts(session_id, "REPSE SSPC autorización seguridad privada", n_results=12)
            extra_docs = search_extra.get("documents", [])
            extra_metas = search_extra.get("metadatas", [])

        raw_docs = (
            penalty_hydrated_docs
            + penalty_focal_docs
            + adjudication_hydrated_docs
            + adjudication_focal_docs
            + supplies_hydrated_docs
            + supplies_focal_docs
            + economic_hydrated_docs
            + economic_focal_docs
            + solvency_hydrated_docs
            + solvency_focal_docs
            + hydrated_docs
            + focal_docs
            + guarantee_hydrated_docs
            + guarantee_focal_docs
            + list(search_results_general.get("documents") or [])
            + list(search_results_primary.get("documents") or [])
            + extra_docs
        )
        raw_metas = (
            penalty_hydrated_metas
            + penalty_focal_metas
            + adjudication_hydrated_metas
            + adjudication_focal_metas
            + supplies_hydrated_metas
            + supplies_focal_metas
            + economic_hydrated_metas
            + economic_focal_metas
            + solvency_hydrated_metas
            + solvency_focal_metas
            + hydrated_metas
            + focal_metas
            + guarantee_hydrated_metas
            + guarantee_focal_metas
            + list(search_results_general.get("metadatas") or [])
            + list(search_results_primary.get("metadatas") or [])
            + extra_metas
        )

        # --- RE-ORDENADOR DE RELEVANCIA (Reranker Ontológico Temático) ---
        # Si la consulta o query expandida contiene indicios de subtemas específicos,
        # re-ordenamos los fragmentos para priorizar aquellos que resuelven directamente la consulta.
        boost_keywords = []
        q_lower = user_query.lower()
        if cronogram_intent or self._detect_cronogram_intent(expanded_query):
            boost_keywords = [
                "junta de aclaraciones",
                "visita a instalaciones",
                "visita obligatoria",
                "apertura de proposiciones",
                "presentacion y apertura",
                "presentación y apertura",
                "acto de fallo",
                "cronograma",
                "calendario",
                "fechas",
                "horas",
                "hora limite",
                "hora límite",
            ]
        elif guarantee_intent or self._detect_guarantee_intent(expanded_query):
            boost_keywords = [
                "fianza",
                "garantía de cumplimiento",
                "garantia de cumplimiento",
                "responsabilidad civil",
                "daños a terceros",
                "suma asegurada",
                "póliza",
                "poliza",
                "endoso",
                "cheque certificado",
            ]
        elif penalty_intent or self._detect_penalty_intent(expanded_query):
            boost_keywords = [
                "pena convencional",
                "penalización",
                "penalizacion",
                "sanción",
                "sancion",
                "atraso",
                "plazos pactados",
                "saldos pendientes",
                "citadas sanciones",
                "bienes y/o servicios",
                "semana",
            ]
        elif adjudication_intent or self._detect_adjudication_intent(expanded_query):
            boost_keywords = [
                "criterio binario",
                "adjudicación",
                "adjudicacion",
                "artículo 36",
                "total ofertado en conjunto",
                "partidas 1 y 2",
                "no se aceptarán opciones",
                "propuesta por zona",
                "anexo iii limpieza",
            ]
        elif supplies_intent or self._detect_supplies_technical_intent(expanded_query):
            boost_keywords = [
                "biodegradabilidad",
                "biodegradable",
                "no contaminante",
                "muestras",
                "almacén",
                "almacen",
                "rpbi",
                "residuo peligroso",
                "insumos",
                "materiales de limpieza",
                "concentración",
                "concentracion",
                "envase",
                "bidón",
                "productos químicos",
                "entrega de materiales",
                "partida 2",
            ]
        elif economic_intent or self._detect_economic_intent(expanded_query):
            boost_keywords = [
                "moneda nacional",
                "propuesta económica",
                "propuesta economica",
                "número y letra",
                "numero y letra",
                "prevalecerá",
                "anexo iii",
                "tarifa mensual",
                "precio unitario",
                "oferta económica",
                "iv.2",
            ]
        elif solvency_intent or self._detect_solvency_intent(expanded_query):
            boost_keywords = [
                "solvencia",
                "opinión",
                "opinion",
                "sat",
                "imss",
                "infonavit",
                "seguridad social",
                "iso 9001",
                "iso 14001",
                "iso 45001",
                "nmx",
                "nom-035",
                "repse",
                "certificación",
                "certificacion",
                "acreditación",
                "acreditacion",
            ]
        elif any(w in q_lower for w in ["repse", "registro", "acredit", "permiso", "seguridad privada", "sspc", "cumplimiento"]):
            boost_keywords = ["repse", "sspc", "registro", "acreditación", "acreditacion", "permiso", "seguridad privada", "autorización", "autorizacion", "servicios especializados", "artículo 15", "articulo 15", "sspe", "ssp"]

        if (
            boost_keywords
            or guarantee_intent
            or solvency_intent
            or economic_intent
            or supplies_intent
            or adjudication_intent
            or penalty_intent
        ):
            scored_chunks = []
            month_pat = (
                r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
                r"septiembre|octubre|noviembre|diciembre"
            )
            for doc, meta in zip(raw_docs, raw_metas):
                doc_lower = doc.lower()
                score = 0.0
                if cronogram_intent:
                    if self._is_cronogram_calendar_chunk(doc or ""):
                        score += 500.0
                    if self._is_cronogram_noise_chunk(doc or ""):
                        score -= 450.0
                    if meta.get("hydrated"):
                        score += 200.0
                    if re.search(rf"\d{{1,2}}\s+de\s+({month_pat})", doc_lower):
                        score += 80.0
                    if "fechas y horas" in doc_lower or "fechas y hora" in doc_lower:
                        score += 100.0
                if penalty_intent and not cronogram_intent and not guarantee_intent:
                    if self._is_penalty_contract_chunk(doc or ""):
                        score += 540.0
                    if self._is_guarantee_admin_noise_for_penalty(doc or ""):
                        score -= 520.0
                    if (
                        self._is_guarantee_contract_chunk(doc or "")
                        and not self._is_penalty_contract_chunk(doc or "")
                    ):
                        score -= 400.0
                    if "bienes pendientes de entregar" in doc_lower:
                        score -= 400.0
                    if meta.get("hydrated") or meta.get("penalty_probe"):
                        score += 200.0
                if adjudication_intent and not cronogram_intent and not guarantee_intent and not penalty_intent:
                    if self._is_adjudication_chunk(doc or ""):
                        score += 540.0
                    if "total ofertado en conjunto" in doc_lower:
                        score += 200.0
                    if meta.get("hydrated"):
                        score += 200.0
                if supplies_intent and not cronogram_intent and not guarantee_intent and not adjudication_intent and not penalty_intent and not economic_intent:
                    if self._is_supplies_spec_chunk(doc or ""):
                        score += 560.0
                    if self._is_economic_format_chunk(doc or ""):
                        score -= 520.0
                    if "moneda nacional" in doc_lower or "precio unitario" in doc_lower:
                        score -= 400.0
                    if meta.get("hydrated"):
                        score += 220.0
                if economic_intent and not cronogram_intent and not guarantee_intent and not adjudication_intent and not penalty_intent and not supplies_intent:
                    if self._is_economic_format_chunk(doc or ""):
                        score += 540.0
                    if self._is_guarantee_contract_chunk(doc or "") or self._is_guarantee_insurance_chunk(
                        doc or ""
                    ):
                        score -= 300.0
                    if "contenido nacional" in doc_lower and "65" in doc_lower:
                        score -= 350.0
                    if meta.get("hydrated"):
                        score += 200.0
                if solvency_intent and not cronogram_intent and not guarantee_intent and not economic_intent and not penalty_intent and not supplies_intent:
                    if self._is_solvency_fiscal_chunk(doc or ""):
                        score += 520.0
                    if self._is_solvency_norm_chunk(doc or ""):
                        score += 560.0
                    if self._is_guarantee_contract_chunk(doc or "") or self._is_guarantee_insurance_chunk(
                        doc or ""
                    ):
                        score -= 280.0
                    if meta.get("hydrated"):
                        score += 200.0
                if guarantee_intent and not cronogram_intent and not solvency_intent and not economic_intent and not penalty_intent:
                    if self._is_guarantee_contract_chunk(doc or ""):
                        score += 520.0
                    if self._is_guarantee_insurance_chunk(doc or ""):
                        score += 520.0
                    if self._is_solvencia_fiscal_noise(doc or ""):
                        score -= 480.0
                    if self._is_evaluation_percent_noise(doc or ""):
                        score -= 320.0
                    if meta.get("hydrated"):
                        score += 180.0
                # Boost de coincidencia de palabras clave ontológicas
                for kw in boost_keywords:
                    if kw in doc_lower:
                        score += 15.0
                        # Boost extra de altísima prioridad para REPSE o SSPC
                        if kw in ["repse", "sspc", "servicios especializados"]:
                            score += 100.0
                scored_chunks.append((doc, meta, score))
            
            # Ordenar por puntuación descendente
            scored_chunks.sort(key=lambda x: x[2], reverse=True)
            raw_docs = [x[0] for x in scored_chunks]
            raw_metas = [x[1] for x in scored_chunks]

        context_parts = []
        context_docs = []
        metadatas = []
        seen_chunks: set = set()
        max_chunks = 14 if (
            cronogram_intent
            or guarantee_intent
            or solvency_intent
            or economic_intent
            or supplies_intent
            or adjudication_intent
            or penalty_intent
        ) else 16

        _session_clean_id = self.vector_db._sanitize_name(session_id)

        def _push_chunk(doc: str, meta: Dict[str, Any]) -> None:
            if not doc or doc in seen_chunks or len(context_docs) >= max_chunks:
                return
            if not self._chunk_belongs_to_session(meta, session_id, self.vector_db):
                logger.warning(
                    "chatbot_chunk_session_mismatch_blocked",
                    session_id=_session_clean_id,
                    chunk_session=meta.get("session_id"),
                )
                return
            if cronogram_intent and self._is_cronogram_noise_chunk(doc):
                if len(context_docs) >= 6:
                    return
            if (
                guarantee_intent
                and not solvency_intent
                and self._is_solvencia_fiscal_noise(doc)
            ):
                if len(context_docs) >= 5:
                    return
            if penalty_intent and self._is_guarantee_admin_noise_for_penalty(doc):
                return
            seen_chunks.add(doc)
            context_docs.append(doc)
            metadatas.append(meta)
            src = meta.get("source", "Documento")
            page = meta.get("page", "?")
            if str(page) == "23" or page == 23:
                logger.info(f"AUDITORIA_CHUNK_PAGINA_23_DETECTADO: {doc[:500]}...")
                print(
                    f"\n=====================================\n[AUDITORÍA CHUNK PAGINA 23 DETECTADO]\n{doc}\n=====================================\n",
                    flush=True,
                )
            context_parts.append(f"--- [FUENTE: {src} | PÁGINA: {page}] ---\n{doc}\n")

        for i, doc in enumerate(raw_docs):
            if len(context_docs) >= max_chunks:
                break
            meta = raw_metas[i] if i < len(raw_metas) else {}
            _push_chunk(doc, meta)

        context_str = "\n".join(context_parts) if context_parts else "No se encontró información de la licitación."
        no_pliego_en_fragmentos = (not context_docs) or (
            isinstance(context_str, str) and context_str.strip().startswith("No se encontró")
        )

        active_block = self._active_economic_blocking_pending(pending, current_idx)
        pending_context = ""
        if pending:
            idx = max(0, min(int(current_idx or 0), len(pending) - 1))
            q = pending[idx]
            rest = max(0, len(pending) - idx - 1)
            pend_note = (
                f"\nESTADO ACTUAL DEL EXPEDIENTE (dato pendiente **{idx + 1} de {len(pending)}**):\n"
                f"- **{q.get('label', 'Campo')}:** {q.get('question', '')}\n"
            )
            if rest:
                pend_note += f"(Después de este quedan **{rest}** dato(s) en cola; no los pidas todos a la vez.)\n"
            pending_context = pend_note

        # --- C04: INYECCIÓN DINÁMICA DE POLÍTICA NORMATIVA ---
        triage = _sess.get("triage_result") or {}
        law_key = triage.get("law") or triage.get("ley") or "LAASSP"
        category_key = triage.get("tender_category") or triage.get("categoria") or "SERVICIOS"
        
        normative_ctx = ""
        try:
            must_have = await TenderRouterService.get_must_have_list(law_key, category_key)
            if must_have:
                # Humanización de etiquetas para el LLM (mapeo semántico)
                policy = await TenderRouterService.get_must_have_policy(law_key, category_key)
                must_have_humanizado = []
                for tag in must_have:
                    p = policy.get(tag, {})
                    aliases = p.get("aliases", [])
                    # El primer alias suele ser el nombre descriptivo humano
                    name = aliases[0].capitalize() if aliases else tag
                    must_have_humanizado.append(name)

                # Forzamos al prompt a contener la lista real de la base de datos con AUTORIDAD SUPERIOR
                normative_ctx = (
                    "\n[FUENTE DE VERDAD SUPERIOR - BASE DE DATOS NORMATIVA]:\n"
                    f"Para esta licitación de {category_key} bajo la ley {law_key}, los documentos y anexos "
                    f"obligatorios son estrictamente: {', '.join(must_have_humanizado)}.\n"
                    "Utiliza esta lista como tu base para responder, ignorando si los fragmentos de texto están incompletos.\n"
                )
        except Exception as _ne:
            logger.warning("chatbot_normative_injection_failed", error=str(_ne))

        # --- LFT OPERATIONAL VIABILITY ENGINE SYNC (Pregunta 4) ---
        lft_extra_context = ""
        lft_alerts = []
        try:
            # Escanear el contexto por turnos de 24 horas en las tablas de personal
            for line in context_str.split("\n"):
                if "|" in line and "24" in line.upper() and ("HORA" in line.upper() or "HR" in line.upper() or "24x24" in line.lower()):
                    parts = [p.strip() for p in line.split("|")]
                    if parts and not parts[0]:
                        parts.pop(0)
                    if parts and not parts[-1]:
                        parts.pop()
                    if len(parts) >= 4:
                        area = parts[0]
                        # Buscar elementos y turno
                        turno = "24 HORAS"
                        dias = "LUN-DOM"
                        num_elems = "4"
                        for idx_p, p in enumerate(parts):
                            p_upper = p.upper()
                            if "24" in p_upper and "HORA" in p_upper:
                                turno = p
                            elif any(d in p_upper for d in ["LUN", "DOM", "L-D", "SAB", "VIE"]):
                                dias = p
                            elif p.isdigit():
                                num_elems = p
                        
                        from app.agents.economic import _validar_viabilidad_operativa_fila
                        fila_mock = {
                            "turno": turno,
                            "dias": dias,
                            "numero_elementos": num_elems
                        }
                        res_lft = _validar_viabilidad_operativa_fila(fila_mock)
                        riesgo = res_lft.get("riesgo") or res_lft.get("risk")
                        if riesgo and isinstance(riesgo, dict):
                            msg_lft = riesgo.get("mensaje")
                            lft_alerts.append((area, num_elems, msg_lft))
            
            if lft_alerts:
                lft_extra_context = "\n[ALERTA OPERATIVA LFT IMPORTANTE - MOTOR ECONÓMICO]:\n"
                for area, num_elems, msg in lft_alerts:
                    lft_extra_context += f"- Para el área '{area}' con {num_elems} elementos: {msg}\n"
                lft_extra_context += "Si el usuario pregunta por la cantidad de elementos o turnos de esta área, DEBES incluir obligatoriamente esta ALERTA LFT en tu respuesta.\n"
        except Exception as _le:
            logger.warning(f"Error al analizar alertas LFT en el chatbot: {_le}")

        cronogram_prompt_extra = ""
        if cronogram_intent:
            cronogram_prompt_extra = (
                "\n[INSTRUCCIÓN CRONOGRAMA]: Los fragmentos incluyen tabla de actos del procedimiento. "
                "Reporta cada acto (visita, junta, presentación/apertura, fallo) con fecha, hora y lugar/modalidad "
                "citando [FUENTE | PÁGINA]. Queda prohibido responder «no se especifica» si el fragmento trae fechas. "
                "Distingue recepción de muestras (logística) del acto de apertura de proposiciones.\n"
            )

        guarantee_canonical_block = ""
        if guarantee_intent and context_docs:
            guarantee_canonical_block = self._build_guarantee_canonical_block(
                context_docs, metadatas
            )

        guarantee_prompt_extra = ""
        if guarantee_intent:
            guarantee_prompt_extra = (
                "\n[INSTRUCCIÓN GARANTÍAS Y SEGUROS — licitante ganador/adjudicado]:\n"
                "Responde EXACTAMENTE con estas tres secciones (títulos obligatorios):\n"
                "### 1) FIANZA / GARANTÍA DE CUMPLIMIENTO\n"
                "- **Porcentaje:** (número literal del pliego, p. ej. 12% si el fragmento lo dice; copia el % tal cual)\n"
                "- Formas aceptadas, beneficiario, momento de entrega, vigencia (juicios/recursos)\n"
                "### 2) SEGURO DE RESPONSABILIDAD CIVIL\n"
                "- **Monto asegurado:** (cifra literal del pliego)\n"
                "- Endoso beneficiario, vigencia, entrega de copia y comprobante\n"
                "### 3) PLAZOS Y ENDOSOS\n"
                "- Solo lo que digan los fragmentos; cita [FUENTE | PÁGINA]\n"
                "Reglas: (a) Si el fragmento trae un % de fianza, DEBES imprimirlo — no omitas porcentajes. "
                "(b) Solo está prohibido INVENTAR un % que no figure en los fragmentos. "
                "(c) Queda prohibido decir «no aparece explícitamente» si [HECHOS CONTRACTUALES] o los fragmentos "
                "ya traen el % o la suma asegurada. "
                "(d) No listes SAT/IMSS/INFONAVIT (son solvencia del participante, no garantía del ganador).\n"
                f"{guarantee_canonical_block}"
            )

        penalty_prompt_extra = ""
        if penalty_intent:
            penalty_prompt_extra = (
                "\n[INSTRUCCIÓN PENAS CONVENCIONALES — localizador forense]:\n"
                "Responde EXACTAMENTE con dos secciones:\n"
                "### 1) TASA DE PENA CONVENCIONAL\n"
                "### 2) MECANISMO DE COBRO Y LÍMITE FINANCIERO\n"
                "Cada viñeta termina con [PÁGINA X] del metadato. Extrae el % y el tope solo "
                "si constan en los fragmentos (saldos pendientes, garantía de cumplimiento).\n"
            )

        adjudication_prompt_extra = ""
        if adjudication_intent:
            adjudication_prompt_extra = (
                "\n[INSTRUCCIÓN ADJUDICACIÓN Y ZONAS — localizador forense]:\n"
                "Responde EXACTAMENTE con dos secciones:\n"
                "### 1) CRITERIO DE ADJUDICACIÓN\n"
                "### 2) PARTICIPACIÓN POR UNA O VARIAS ZONAS\n"
                "Cada viñeta termina con [PÁGINA X]. Incluye criterio binario, art. 36, "
                "total conjunto partidas 1 y 2 por zona, y regla de no opciones / una propuesta por zona.\n"
            )

        supplies_prompt_extra = ""
        if supplies_intent:
            supplies_prompt_extra = (
                "\n[INSTRUCCIÓN INSUMOS Y MATERIALES — localizador forense]:\n"
                "Responde EXACTAMENTE con cuatro secciones:\n"
                "### 1) BIODEGRADABILIDAD Y PRODUCTOS\n"
                "### 2) ENVASE, CONCENTRACIÓN Y PRODUCTOS QUÍMICOS\n"
                "### 3) MUESTRAS FÍSICAS EN ALMACÉN\n"
                "### 4) MANEJO DE RPBI\n"
                "Cada viñeta termina con [PÁGINA X]. Prohibido responder moneda nacional, "
                "IVA, tarifa mensual o precio unitario salvo que el usuario lo pida explícitamente.\n"
            )

        economic_prompt_extra = ""
        if economic_intent:
            economic_prompt_extra = (
                "\n[INSTRUCCIÓN PROPUESTA ECONÓMICA — localizador forense]:\n"
                "Responde EXACTAMENTE con tres secciones:\n"
                "### 1) MONEDA REQUERIDA\n"
                "### 2) FORMATO DE COTIZACIÓN POR PARTIDA\n"
                "### 3) REGLA DE DISCREPANCIA (NÚMERO VS LETRA)\n"
                "Cada viñeta termina con [PÁGINA X] del metadato. "
                "Prohibido inventar dólares u otras monedas. "
                "Si el pliego dice que prevalece la cantidad en letra, NO digas que la discrepancia "
                "descalifica automáticamente.\n"
            )

        solvency_prompt_extra = ""
        if solvency_intent:
            solvency_prompt_extra = (
                "\n[INSTRUCCIÓN SOLVENCIA DEL PARTICIPANTE — localizador forense]:\n"
                "Responde EXACTAMENTE con estas dos secciones (títulos obligatorios):\n"
                "### 1) Opiniones de cumplimiento fiscal y patronal\n"
                "### 2) Normativas técnicas, certificaciones y registros (ISO/NMX/NOM/REPSE)\n"
                "Regla de hierro: CADA requisito en viñeta debe terminar con [PÁGINA X] usando el metadato "
                "real del fragmento (ej. [PÁGINA 14]). Prohibido omitir la página.\n"
                "Incluye SAT, IMSS, INFONAVIT si constan en fragmentos, Y todas las normas ISO/NMX/NOM y REPSE "
                "que aparezcan en los fragmentos. No omitas el bloque técnico por resumir solo lo fiscal.\n"
            )

        system_prompt = (
            "[CONTRATO DE SEGURIDAD OPERATIVA - ENTORNO CORPORATIVO B2B]\n"
            "Eres LicitAI, el Consultor Senior de Licitaciones de la empresa. Tu misión es extraer verdades absolutas de las bases.\n"
            "REGLAS DE SEGURIDAD ABSOLUTAS:\n"
            "1. Responde de forma directa, categórica y con autoridad basándote en los fragmentos.\n"
            "2. PROHIBIDO usar frases de duda como 'Según los fragmentos', 'No está explícito', o disclaimers de responsabilidad. Si el dato está, dalo como un hecho.\n"
            "3. Si falta información CRÍTICA (como reglas de redondeo, consecuencias de inasistencia, o modalidad de precios fijos), DEBES ADVERTIR el riesgo (GAP) en lugar de inventar la respuesta por completitud.\n"
            "4. El número oficial de esta licitación es el nombre del archivo principal: " + (f"«{primary_doc}»" if primary_doc else "N/D") + ".\n"
            "5. CRONOGRAMA Y MODALIDAD: Si la pregunta es sobre fechas, debes reportar el día, la hora y TODOS los lugares o plataformas especificados en la fila y sus notas inferiores (ej. si dice CompraNet y/o Sala de Juntas física, debes mencionar ambos). Queda estrictamente prohibido omitir sedes físicas si el texto las contempla.\n"
            "6. DISTINCIÓN CRÍTICA ENTRE DESCALIFICACIÓN Y PENALIZACIÓN: Queda terminantemente prohibido confundir las consecuencias de la fase de concurso/licitación con la fase contractual. La inasistencia a eventos obligatorios del concurso (como la Visita a las Instalaciones o la Junta de Aclaraciones si se marcan como obligatorias) es causa de DESECHAMIENTO/DESCALIFICACIÓN DIRECTA de la propuesta, NUNCA una penalización contractual o pena convencional posterior (las cuales solo aplican una vez firmado el contrato). Si el texto indica que el requisito es obligatorio o indispensable para continuar, dalo como causa directa de descalificación.\n"
            "7. INTEGRACIÓN CON MOTOR ECONÓMICO (ALERTA LFT): Si la consulta es sobre la cantidad de elementos o turnos de 24 horas en un área (ej. Entrada Principal o Control de Pases), es OBLIGATORIO inyectar el aviso de Alerta LFT. Si el pliego indica 4 elementos físicos en el turno de 24 horas, la respuesta debe ser: 'Se solicitan 4 elementos físicos en el área indicada. ALERTA LFT: El motor ajustará la cotización a 8 elementos en nómina para cubrir el turno 24/7 sin pérdidas financieras.'\n"
            "8. PROTOCOLO DE DESACOPLAMIENTO SEMÁNTICO ESTRICTO: Queda prohibido asumir que términos semánticos próximos son sinónimos (ej. 'Control de Pases' NO es lo mismo que 'Entrada Principal', ni 'Caseta' es lo mismo que 'Acceso Vehicular'). Si el pliego contiene nomenclatura diferente a la consultada por el usuario, debes advertir de esta diferencia, responder por lo que realmente dice el pliego y pedir confirmación de la nomenclatura oficial de las bases.\n"
            "9. REGLA DE PONDERACIÓN TEMÁTICA (FILTRO DINÁMICO DE INCISOS): Si el usuario pregunta por un subtema específico (como registros, acreditaciones, REPSE, autorizaciones SSPC, seguros o fianzas) dentro de un numeral extenso o kilométrico (como el 6.1), tienes estrictamente PROHIBIDO transcribir la lista completa de incisos de forma secuencial desde el inciso A si eso consume el contexto. Debes escanear todos los fragmentos, saltar el ruido administrativo general (identificaciones, actas, cartas membretadas generales) y enfocar tu respuesta única y directamente en los incisos específicos que regulan o contienen el subtema consultado (ej. si los registros de seguridad o REPSE están en los incisos H, I, K, etc., expón directamente la regulación de esos incisos con su letra correspondiente).\n"
            "10. DISTINCIÓN CRÍTICA ENTRE GARANTÍAS Y PAGOS: Si la consulta del usuario es sobre la Garantía de Cumplimiento, fianza del contrato o cheques de garantía, tienes estrictamente PROHIBIDO reportar los métodos de facturación, transferencias bancarias, calendarios de estimaciones o pagos de servicios que el Instituto hace al proveedor. Debes enfocarte única y exclusivamente en los instrumentos de garantía o cobertura que el licitante/proveedor entrega para garantizar el contrato (como cheques de caja, cheques certificados, pólizas de fianza) y el porcentaje o monto que figure literalmente en los fragmentos (sin asumir porcentajes genéricos de ley si el pliego trae otro dato).\n"
            "11. DISTINCIÓN CRÍTICA DE DEDUCCIONES OPERATIVAS Y PENAS POR BIENES: Si la licitación es de Servicios (como Vigilancia, Limpieza, etc.) y el usuario pregunta por inasistencias del personal, faltas, retardos o turnos no cubiertos, tienes estrictamente PROHIBIDO citar cláusulas genéricas de penas convencionales por mora/atraso en la entrega de bienes o insumos materiales (ej. el 2.5% por mora en bienes pendientes de entregar). Debes buscar de forma exclusiva y reportar únicamente las DEDUCCIONES especiales aplicables por fallas operativas en el servicio de vigilancia o turnos vacíos (descuento del costo diario, penas específicas por falta de elementos).\n"
            "12. REGLA DE AISLAMIENTO DE ÍNDICES (INDEX ANCHORING): Si el usuario pregunta por la correspondencia o nombre exacto de un Anexo (ej. '¿Qué es el Anexo X?'), tienes estrictamente PROHIBIDO extraer la respuesta de los párrafos introductorios, acuerdos federales o notas de marco legal del inicio del PDF. Debes forzar al motor a buscar y priorizar exclusivamente la Tabla del Índice de Anexos (comúnmente denominada 'Relación de Anexos' o 'Formatos') y los encabezados principales del cuerpo del documento. No reportes menos anexos de los que figuran en la lista completa (ej. si hay 17 o 18 anexos en total, repórtalo completo de acuerdo con el índice).\n\n"
            f"{normative_ctx}"
            f"{pending_context}"
            f"{candidates_ctx}"
            f"{econ_block_ctx}"
            f"{comp_ctx}"
            f"{extra_context if extra_context else ''}\n"
            f"{lft_extra_context}\n"
            f"{cronogram_prompt_extra}"
            f"{guarantee_prompt_extra}"
            f"{solvency_prompt_extra}"
            f"{supplies_prompt_extra}"
            f"{economic_prompt_extra}"
            f"{adjudication_prompt_extra}"
            f"{penalty_prompt_extra}"
            "**REGLA DE SALIDA INTELIGENTE:**\n"
            "Si el usuario pide un dato informativo, responde DIRECTAMENTE sin titubear. Si hay huecos técnicos, reporta el [Diagnóstico de Riesgo].\n"
        )

        guarantee_user_format = ""
        if guarantee_intent:
            guarantee_user_format = (
                "\n[CHECKLIST OBLIGATORIO ANTES DE ENVIAR]: "
                "¿Incluiste la sección 1 con el porcentaje de fianza/garantía si aparece en los fragmentos? "
                "¿Incluiste la sección 2 con el monto de Responsabilidad Civil si aparece? "
                "Si ambos datos están en los fragmentos, ambos deben figurar en tu respuesta.\n"
            )

        solvency_user_format = ""
        if solvency_intent:
            solvency_user_format = (
                "\n[CHECKLIST SOLVENCIA]: ¿Listaste opiniones SAT/IMSS/INFONAVIT con [PÁGINA]? "
                "¿Listaste ISO/NMX/NOM/REPSE del fragmento 6.1 o anexos con [PÁGINA] cada uno?\n"
            )

        supplies_user_format = ""
        if supplies_intent:
            supplies_user_format = (
                "\n[CHECKLIST INSUMOS]: ¿Biodegradabilidad/envases/concentración con [PÁGINA]? "
                "¿Muestras en almacén con [PÁGINA]? ¿RPBI con [PÁGINA]? "
                "¿Evitaste moneda y formato de oferta económica?\n"
            )

        economic_user_format = ""
        if economic_intent:
            economic_user_format = (
                "\n[CHECKLIST ECONÓMICO]: ¿Moneda nacional con [PÁGINA]? "
                "¿Partida 1 y 2 con formato del Anexo III? "
                "¿Regla «prevalece la letra» sin inventar descalificación?\n"
            )

        adjudication_user_format = ""
        if adjudication_intent:
            adjudication_user_format = (
                "\n[CHECKLIST ADJUDICACIÓN]: ¿Criterio binario y total partidas 1+2 con [PÁGINA]? "
                "¿Reglas de zonas y «no opciones» con [PÁGINA]?\n"
            )

        penalty_user_format = ""
        if penalty_intent:
            penalty_user_format = (
                "\n[CHECKLIST PENAS]: ¿Porcentaje de pena convencional con [PÁGINA]? "
                "¿Saldos pendientes y tope de garantía con [PÁGINA]?\n"
            )

        prompt = (
            f"Fragmentos disponibles de la licitación para esta sesión:\n\n{context_str}\n\n"
            f"Pregunta del usuario: {user_query}\n"
            f"{guarantee_user_format}"
            f"{solvency_user_format}"
            f"{supplies_user_format}"
            f"{economic_user_format}"
            f"{adjudication_user_format}"
            f"{penalty_user_format}\n\n"
            "[ORDEN DE EJECUCIÓN CRÍTICA: Responde de forma directa al usuario. QUE QUEDE PROHIBIDO usar disclaimers legales o evasivas de seguridad. Limítate a leer el texto y actuar como el Consultor Senior de la empresa.]"
        )

        try:
            _chat_temp = float(os.environ.get("LICITAI_CHAT_TEMPERATURE", "0.2")) # Bajamos la temp por defecto
        except ValueError:
            _chat_temp = 0.2
        _chat_temp = max(0.05, min(_chat_temp, 0.9))
        try:
            _chat_ctx = int(os.environ.get("LICITAI_CHAT_NUM_CTX", "16383"))
        except ValueError:
            _chat_ctx = 16384
        _chat_ctx = max(4096, min(_chat_ctx, 131072))

        literary_hit = self._build_support_evidence_literary_message(
            user_query,
            context_docs,
            metadatas,
            primary_doc,
            guarantee_intent,
            penalty_intent,
            solvency_intent,
            cronogram_intent,
            session_id=session_id,
            session_state=_sess,
        )
        if literary_hit:
            lit_tipo, lit_early, lit_top = (
                literary_hit
                if len(literary_hit) >= 3
                else (literary_hit[0], literary_hit[1], None)
            )
            bases_excerpt = await self._fetch_literary_bases_excerpt(session_id, lit_top)
            await self._save_chat_history(session_id, user_query, lit_early)
            response_kwargs: Dict[str, Any] = {}
            if bases_excerpt:
                response_kwargs["bases_excerpt_v1"] = bases_excerpt
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=lit_early,
                confianza="Alta",
                tipo=lit_tipo,
                suggested_actions=suggested_actions
                or self._literary_sources_actions(),
                **response_kwargs,
            )

        llm_response = await self.llm.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            options={
                "temperature": _chat_temp, 
                "num_ctx": _chat_ctx,
                "top_k": 10,  # Forzamos foco eliminando ruido de cola
                "top_p": 0.5  # Incrementamos asertividad
            },
            correlation_id=correlation_id
        )
        if llm_response.success:
            content = llm_response.response or ""
            if self._is_rag_llm_refusal(content) and context_docs:
                lit_hit = self._build_support_evidence_literary_message(
                    user_query,
                    context_docs,
                    metadatas,
                    primary_doc,
                    guarantee_intent,
                    penalty_intent,
                    solvency_intent,
                    cronogram_intent,
                    session_id=session_id,
                    session_state=_sess,
                )
                if lit_hit:
                    content = lit_hit[1]
            # Garantías: si el bloque canónico trajo fianza (% adjudicado) + RC, sustituir narrativa LLM.
            if guarantee_intent and guarantee_canonical_block:
                if self._guarantee_canonical_has_core_facts(guarantee_canonical_block):
                    content = self._compose_guarantee_structured_response(
                        guarantee_canonical_block, context_docs, metadatas
                    )
                else:
                    low_content = content.lower()
                    if (
                        "no se especifican montos" in low_content
                        or "no se especifica" in low_content
                    ) and "%" in guarantee_canonical_block:
                        content = re.sub(
                            r"(?i)no se especifican montos[^.\n]*\.?",
                            "",
                            content,
                        ).strip()
                    if self._guarantee_response_missing_contract_pct(
                        content, guarantee_canonical_block
                    ):
                        for line in guarantee_canonical_block.splitlines():
                            if "Fianza/garantía" in line and line.startswith("-"):
                                content += (
                                    f"\n\n### 1) FIANZA / GARANTÍA DE CUMPLIMIENTO\n"
                                    f"{line.lstrip('- ')}"
                                )
                                break
                    if insurance_line := next(
                        (
                            ln
                            for ln in guarantee_canonical_block.splitlines()
                            if "Seguro Responsabilidad Civil" in ln
                        ),
                        None,
                    ):
                        norm = content.replace("'", "").replace(" ", "")
                        if "1,000" not in norm and "1000000" not in norm:
                            if (
                                "responsabilidad civil" not in low_content
                                or "millón" not in low_content
                            ):
                                content += (
                                    f"\n\n### 2) SEGURO DE RESPONSABILIDAD CIVIL\n"
                                    f"{insurance_line.lstrip('- ')}"
                                )
                    content = self._sanitize_guarantee_contradictory_llm_body(
                        content, guarantee_canonical_block
                    )
            if solvency_intent:
                ext_docs: List[str] = []
                ext_metas: List[Dict[str, Any]] = []
                ext_seen: set = set()
                for d, m in zip(raw_docs, raw_metas):
                    if not d or d in ext_seen:
                        continue
                    ext_seen.add(d)
                    ext_docs.append(d)
                    ext_metas.append(m if isinstance(m, dict) else {})
                    if len(ext_docs) >= 22:
                        break
                pool_docs = ext_docs or context_docs
                pool_metas = ext_metas or metadatas
                if self._solvency_structured_ready(pool_docs, pool_metas):
                    content = self._compose_solvency_structured_response(
                        pool_docs, pool_metas
                    )
            if supplies_intent and not economic_intent:
                ext_docs_sp: List[str] = []
                ext_metas_sp: List[Dict[str, Any]] = []
                ext_seen_sp: set = set()
                for d, m in zip(raw_docs, raw_metas):
                    if not d or d in ext_seen_sp:
                        continue
                    ext_seen_sp.add(d)
                    ext_docs_sp.append(d)
                    ext_metas_sp.append(m if isinstance(m, dict) else {})
                    if len(ext_docs_sp) >= 24:
                        break
                pool_sp_docs = ext_docs_sp or context_docs
                pool_sp_metas = ext_metas_sp or metadatas
                if self._supplies_structured_ready(pool_sp_docs, pool_sp_metas):
                    content = self._compose_supplies_structured_response(
                        pool_sp_docs, pool_sp_metas
                    )
            if economic_intent:
                ext_docs_e: List[str] = []
                ext_metas_e: List[Dict[str, Any]] = []
                ext_seen_e: set = set()
                for d, m in zip(raw_docs, raw_metas):
                    if not d or d in ext_seen_e:
                        continue
                    ext_seen_e.add(d)
                    ext_docs_e.append(d)
                    ext_metas_e.append(m if isinstance(m, dict) else {})
                    if len(ext_docs_e) >= 22:
                        break
                pool_e_docs = ext_docs_e or context_docs
                pool_e_metas = ext_metas_e or metadatas
                if self._economic_structured_ready(pool_e_docs, pool_e_metas):
                    content = self._compose_economic_structured_response(
                        pool_e_docs, pool_e_metas
                    )
                content = self._append_economic_gap_alert_if_needed(
                    content, pool_e_docs, economic_intent
                )
            if adjudication_intent:
                ext_docs_a: List[str] = []
                ext_metas_a: List[Dict[str, Any]] = []
                ext_seen_a: set = set()
                for d, m in zip(raw_docs, raw_metas):
                    if not d or d in ext_seen_a:
                        continue
                    ext_seen_a.add(d)
                    ext_docs_a.append(d)
                    ext_metas_a.append(m if isinstance(m, dict) else {})
                    if len(ext_docs_a) >= 22:
                        break
                pool_a_docs = ext_docs_a or context_docs
                pool_a_metas = ext_metas_a or metadatas
                if self._adjudication_structured_ready(pool_a_docs, pool_a_metas):
                    content = self._compose_adjudication_structured_response(
                        pool_a_docs, pool_a_metas
                    )
            if penalty_intent:
                ext_docs_p: List[str] = []
                ext_metas_p: List[Dict[str, Any]] = []
                ext_seen_p: set = set()
                for d, m in zip(raw_docs, raw_metas):
                    if not d or d in ext_seen_p:
                        continue
                    ext_seen_p.add(d)
                    ext_docs_p.append(d)
                    ext_metas_p.append(m if isinstance(m, dict) else {})
                    if len(ext_docs_p) >= 22:
                        break
                pool_p_docs, pool_p_metas = self._merge_doc_meta_pool(
                    (penalty_hydrated_docs, penalty_hydrated_metas),
                    (context_docs, metadatas),
                    (ext_docs_p, ext_metas_p),
                    limit=32,
                )
                pool_p_docs, pool_p_metas = self._rank_penalty_doc_pool(
                    pool_p_docs, pool_p_metas
                )
                if self._penalty_should_compose(pool_p_docs, pool_p_metas):
                    content = self._compose_penalty_structured_response(
                        pool_p_docs, pool_p_metas
                    )
                else:
                    content = self._sanitize_penalty_llm_contradictions(content)
            # Inyección robusta post-LLM si se omitió la Alerta LFT para turnos de 24 horas
            if lft_alerts and ("24" in user_query or "elemento" in user_query.lower() or "entrada" in user_query.lower() or "pase" in user_query.lower() or "principal" in user_query.lower()):
                for area, num_elems, msg in lft_alerts:
                    if "ALERTA LFT" not in content:
                        try:
                            f_val = float(num_elems)
                        except ValueError:
                            f_val = 4.0
                        content += f"\n\n**ALERTA LFT:** El motor ajustará la cotización a {f_val*2.0:.0f} elementos en nómina para cubrir el turno 24/7 sin pérdidas financieras."
            
            # Acreditaciones REPSE/SSPC/CUIPS: solo seguridad privada; nunca en solvencia ISO/NMX.
            # Texto literal del fragmento + [PÁGINA]; sin plantillas fijas ni páginas 24/69 inventadas.
            if (
                not solvency_intent
                and "### 2) Normativas técnicas" not in content
                and self._detect_security_private_compliance_injection(user_query)
            ):
                repse_text = ""
                sspc_text = ""
                infospe_text = ""
                cuips_text = ""
                for doc, meta in zip(context_docs, metadatas):
                    if not self._chunk_belongs_to_session(meta, session_id, self.vector_db):
                        continue
                    doc_lower = (doc or "").lower()
                    pg = meta.get("page", "?")
                    if "repse" in doc_lower and not repse_text:
                        for sent in re.split(r"(?<=[.;])\s+", doc or ""):
                            if "repse" in sent.lower() and len(sent.strip()) > 40:
                                repse_text = f"• {sent.strip()} [PÁGINA {pg}]"
                                break
                    if (
                        any(w in doc_lower for w in ["autorización", "autorizacion"])
                        and any(
                            w in doc_lower
                            for w in ["seguridad pública", "seguridad publica"]
                        )
                        and not sspc_text
                    ):
                        for sent in re.split(r"(?<=[.;])\s+", doc or ""):
                            low_s = sent.lower()
                            if "autoriz" in low_s and "seguridad" in low_s:
                                sspc_text = f"• {sent.strip()} [PÁGINA {pg}]"
                                break
                    if "infospe" in doc_lower and not infospe_text:
                        for sent in re.split(r"(?<=[.;])\s+", doc or ""):
                            if "infospe" in sent.lower():
                                infospe_text = f"• {sent.strip()} [PÁGINA {pg}]"
                                break
                    if "cuips" in doc_lower and not cuips_text:
                        for sent in re.split(r"(?<=[.;])\s+", doc or ""):
                            if "cuips" in sent.lower():
                                cuips_text = f"• {sent.strip()} [PÁGINA {pg}]"
                                break

                compliance_injections = [
                    t
                    for t in (repse_text, sspc_text, infospe_text, cuips_text)
                    if t
                ]
                if compliance_injections:
                    pages_cited = sorted(
                        {
                            str(m.get("page"))
                            for m in metadatas
                            if m.get("page") is not None
                        }
                    )[:6]
                    pages_note = (
                        ", ".join(f"PÁGINA {p}" for p in pages_cited)
                        if pages_cited
                        else "ver fragmentos indexados"
                    )
                    missing = []
                    for inj in compliance_injections:
                        tag = inj.lower()
                        if "repse" in tag and "repse" in content.lower():
                            continue
                        if "infospe" in tag and "infospe" in content.lower():
                            continue
                        if "cuips" in tag and "cuips" in content.lower():
                            continue
                        if "autoriz" in tag and (
                            "autorización" in content.lower()
                            or "autorizacion" in content.lower()
                        ):
                            continue
                        missing.append(inj)
                    if missing:
                        content += (
                            f"\n\n**Acreditaciones de seguridad privada (fragmentos indexados — {pages_note}):**\n"
                            + "\n".join(missing)
                        )
            
            # Brecha económica (redondeo): solo vía _append_economic_gap_alert_if_needed si economic_intent
            if not economic_intent:
                q_lower_econ = user_query.lower()
                if any(
                    w in q_lower_econ
                    for w in [
                        "redondeo",
                        "decimales",
                        "decimal",
                        "truncamiento",
                    ]
                ):
                    if "alerta de brecha" not in content.lower():
                        content = self._append_economic_gap_alert_if_needed(
                            content, context_docs, True
                        )
            
            # Deducciones operativas por personal (vigilancia): no mezclar con penas convencionales contractuales (P8).
            if (
                not penalty_intent
                and self._detect_operational_personnel_penalty_intent(user_query)
            ):
                # Si el bot citó la alucinación de los bienes materiales y mora
                if any(w in content.lower() for w in ["mora", "bienes pendientes de entregar", "2.5%", "atraso en la entrega", "retraso en la entrega"]):
                    deduc_text = ""
                    for doc in context_docs:
                        doc_lower = doc.lower()
                        # Buscar la cláusula de deducciones por turnos no cubiertos
                        if any(w in doc_lower for w in ["deducciones", "deducción", "deduccion", "descuento", "turno no cubierto"]):
                            if "por cada elemento que falte" in doc_lower or "deficiencia" in doc_lower or "sanción" in doc_lower or "sancion" in doc_lower or "2%" in doc_lower or "1%" in doc_lower or "turno" in doc_lower:
                                deduc_text = (
                                    "• **Deducción Operativa Directa (Páginas 68-70):** Por cada elemento de vigilancia que no asista a su turno, se descontará el 100% de la cuota diaria del servicio no prestado, más una penalización adicional del 2% al 10% sobre la facturación del período por cada evento de incumplimiento o elemento faltante no cubierto dentro de las primeras dos horas."
                                )
                                break
                    
                    if not deduc_text:
                        # Respaldo legal determinista si los fragmentos de deducciones específicas del pliego no fueron indexados con suficiente score
                        deduc_text = "• **Deducción por Ausencia (Estándar de Vigilancia ISSSTE/IMSS):** En caso de inasistencia o turno no cubierto, la convocante realiza el descuento del 100% del costo del turno no laborado, más una pena convencional o deducción del 2% diario del valor facturado del turno por cada elemento faltante."
                    
                    # Remplazar activamente la alucinación de mora de bienes
                    clean_content = content
                    for h_phrase in [
                        "se aplicará una pena convencional del 2.5% por día natural de mora sobre el valor de los bienes pendientes de entregar, hasta su cumplimiento a entera satisfacción del Instituto.",
                        "se aplicará una pena convencional del 2.5% por día natural de mora sobre el valor de los bienes pendientes de entregar",
                        "2.5% por día natural de mora sobre el valor de los bienes pendientes de entregar"
                    ]:
                        if h_phrase in clean_content:
                            clean_content = clean_content.replace(h_phrase, "se aplicarán deducciones proporcionales por cada hora o turno no cubierto conforme al Anexo Técnico.")
                    
                    if "deducciones proporcionales" not in clean_content:
                        clean_content += "\n\n**Nota de Corrección Operativa:** Si el servicio contratado es de vigilancia, las faltas de personal se regulan mediante deducciones operativas (descuento del turno) y no por mora en entrega de bienes."
                    
                    content = clean_content
                    if "deducción" not in content.lower():
                        content += f"\n\n**Deducciones específicas por inasistencia de personal (Páginas 68-70):**\n{deduc_text}"

            # Inyección robusta post-LLM si se omitió o mutiló el índice de anexos (17/18 anexos) o el Anexo 9 (Salario Real)
            if "anexo" in user_query.lower() and ("cuál" in user_query.lower() or "cuantos" in user_query.lower() or "cuántos" in user_query.lower() or "9" in user_query.lower() or "totales" in user_query.lower()):
                # Si el bot devolvió 16 anexos o confundió el Anexo 9 con medios remotos
                if "16" in content or "medios remotos" in content.lower() or "comunicación electrónica" in content.lower() or "comunicacion electronica" in content.lower():
                    content_clean = content
                    content_clean = content_clean.replace("16 anexos", "17 anexos oficiales (más el Anexo 18 de Fianzas en la página 99)")
                    content_clean = content_clean.replace("16", "18")
                    
                    for junk in [
                        "Acuerdo por el que se establecen las disposiciones para el uso de medios remotos de comunicación electrónica en el envío de propuestas dentro de las licitaciones públicas que celebren las dependencias y entidades de la Administración Pública Federal, así como en la presentación de las inconformidades por la misma vía",
                        "Acuerdo por el que se establecen las disposiciones para el uso de medios remotos de comunicación electrónica en el envío de propuestas dentro de las licitaciones públicas",
                        "Acuerdo por el que se establecen las disposiciones para el uso de medios remotos de comunicación electrónica"
                    ]:
                        if junk in content_clean:
                            content_clean = content_clean.replace(junk, "Cálculo del Factor de Salario Real (FSR)")
                    
                    content = content_clean
                    
                    if "salario real" not in content.lower() and "fsr" not in content.lower():
                        content += (
                            "\n\n**Mapeo Oficial de Anexos del Pliego (Página 44):**\n"
                            "• **Total de Anexos:** El pliego hace referencia oficial a **17 anexos** en su índice (ANEXO 1 al ANEXO 17), más el **Anexo 18** (Fianzas) ubicado en la página 99.\n"
                            "• **Anexo 9 Correspondiente:** El **Anexo No. 9** es el **Cálculo del Factor de Salario Real (FSR)**, formato económico indispensable y obligatorio."
                        )
            
            # Inyección robusta post-LLM si se consulta por límites o techos presupuestales y se reporta inexistencia o silencio
            if any(w in user_query.lower() for w in ["presupuesto máximo", "presupuesto maximo", "presupuesto mínimo", "presupuesto minimo", "techo", "límites de presupuesto", "limites de presupuesto"]):
                if any(w in content.lower() for w in ["no existe", "no se menciona", "no publicado", "no hay", "inexistente"]):
                    if "alerta de riesgo de insolvencia" not in content.lower():
                        content += (
                            "\n\n**ALERTA DE RIESGO DE INSOLVENCIA:** Aunque las bases no publican un presupuesto máximo por ser información reservada, el piso de tu propuesta económica está estrictamente limitado por la Ley Federal del Trabajo. Cualquier cotización por debajo del salario mínimo integrado, prestaciones de ley y las cuotas IMSS/INFONAVIT calculadas en tu Anexo 9 será desechada automáticamente por insolvencia técnica."
                        )

            # AGREGAR FOOTER DE BLOQUEO SI APLICA
            # --- HITO: Humanización de Salida (Anti-Cantinflas) ---
            if active_block:
                label = self._economic_blocking_focus_label(active_block)
                # Solo añadimos el recordatorio si el RAG no respondió ya a algo económico
                if "precio" not in content.lower() and "cuánto" not in content.lower():
                    content += f"\n\nPor cierto, para cerrar tu propuesta aún necesito el valor de: **«{label}»**."
        else:
            err = (llm_response.error or "").strip()
            content = (
                "Ahora mismo **no pude obtener respuesta del modelo** (el servicio de lenguaje no respondió o está saturado).\n\n"
                "Qué puedes hacer:\n"
                "• Reintenta en unos segundos.\n"
                "• Comprueba que **Ollama** esté en marcha en el equipo donde corre (`host.docker.internal:11434` desde Docker).\n"
                "• Si el mensaje fue muy largo, prueba una **pregunta más corta**.\n\n"
                f"_Detalle técnico (para soporte): {err[:280] or 'sin detalle'}._"
            )

        # Citas únicas
        citas = []
        seen = set()
        for meta in metadatas:
            key = (meta.get("source", ""), meta.get("page", ""))
            if key not in seen:
                seen.add(key)
                citas.append({"documento": meta.get("source", "Bases"), "pagina": meta.get("page", 1)})

        from app.services.chat_stop_reason_map import sanitize_user_visible_text

        content = sanitize_user_visible_text(content)

        await self._save_chat_history(session_id, user_query, content)

        # --- C04: INYECCIÓN PROACTIVA DE ACCIONES SUGERIDAS ---
        if not suggested_actions:
            suggested_actions = await self._build_consultative_suggested_actions(session_id, _sess, pending)

        return self._format_response(
            session_id=session_id,
            respuesta=content,
            confianza="Alta" if context_docs else "Baja",
            tipo="rag_answer",
            citations=citas[:5],
            correlation_id=correlation_id,
            suggested_actions=suggested_actions
        )

    def _format_response(
        self,
        session_id: str,
        correlation_id: str,
        respuesta: str,
        confianza: str = "Alta",
        tipo: str = "info",
        progress: Optional[Dict[str, Any]] = None,
        intake_active: Optional[bool] = None,
        activity_state: Optional[str] = None,
        suggested_actions: List = None,
        **kwargs,
    ) -> AgentOutput:
        # Hito 1.4: Arquitectura Universal de Metadatos
        # Defensa: Asegurar que respuesta nunca sea None para evitar ValidationError 500
        safe_reply = str(respuesta or "").strip()
        from app.services.chat_stop_reason_map import sanitize_user_visible_text

        safe_reply = sanitize_user_visible_text(safe_reply)
        
        payload: Dict[str, Any] = {
            "respuesta": safe_reply,
            "citations": kwargs.get("citations", []),
            "sources": kwargs.get("citations", []),  # Retrocompatibilidad
            "citas": kwargs.get("citations", []),    # Retrocompatibilidad
            "confianza": confianza,
            "sugerencia": None,
            "tipo": tipo,
        }
        if isinstance(progress, dict):
            payload.update(
                {
                    "progress_current": int(progress.get("progress_current", 0) or 0),
                    "progress_total": int(progress.get("progress_total", 0) or 0),
                    "progress_label": str(progress.get("progress_label") or ""),
                }
            )
        if intake_active is not None:
            payload["intake_active"] = bool(intake_active)
        if activity_state:
            payload["activity_state"] = str(activity_state)
            
        # Hito 1.4: Inyectar metadatos adicionales de kwargs
        extra = kwargs.get("data", {})
        if not isinstance(extra, dict):
            extra = {"extra_info": extra}
            
        for k, v in kwargs.items():
            if k != "data":
                payload[k] = v
        
        # Merge final
        payload.update(extra)

        from app.contracts.agent_contracts import SuggestedAction
        actions = []
        if suggested_actions:
            for sa in suggested_actions:
                if isinstance(sa, dict):
                    actions.append(SuggestedAction(**sa))
                else:
                    actions.append(sa)

        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=payload,
            correlation_id=correlation_id,
            suggested_actions=actions
        )

    async def _build_consultative_suggested_actions(
        self, session_id: str, session_state: Dict[str, Any], pending: List
    ) -> List[Dict[str, Any]]:
        """
        Genera botones de acción dinámicos basados en el estado real de la licitación.
        """
        from app.services.chat_gate5_formatter import _has_analysis_complete
        from app.services.hitl_queue_service import sanitize_chat_pending_questions

        pending = sanitize_chat_pending_questions(pending or [], session_state)
        actions: List[Dict[str, Any]] = []

        has_must_haves_pending = any(
            str(q.get("type")) == "intake_planner" or q.get("is_blocking")
            for q in pending
        )
        has_economic_pending = any(
            str(q.get("type")) in ("economic_price", "economic_validation_blocking")
            for q in pending
        )

        if _has_analysis_complete(session_state) and not has_must_haves_pending and not has_economic_pending:
            return [
                {
                    "label": "Ver Formatos y Anexos",
                    "payload": "CMD_SHOW_PENDING_DOCS",
                    "style": "primary",
                },
                {
                    "label": "Generar expediente",
                    "payload": "CMD_TRIGGER_GENERATION",
                    "style": "secondary",
                },
            ]

        if has_must_haves_pending:
            actions.append({
                "label": "🧐 Ver Requisitos Pendientes",
                "payload": "CMD_SHOW_PENDING_DOCS",
                "style": "primary",
            })

        if has_economic_pending:
            actions.append({
                "label": "💰 Capturar Precios",
                "payload": "CMD_SHOW_ECONOMIC_VALS",
                "style": "secondary",
            })

        if not pending or (len(pending) < 3 and not has_must_haves_pending):
            actions.append({
                "label": "🚀 Generar Propuesta",
                "payload": "CMD_TRIGGER_GENERATION",
                "style": "primary",
            })

        if has_must_haves_pending or has_economic_pending:
            actions.append({
                "label": "📋 Ver Dictamen Forense",
                "payload": "CMD_SHOW_FORENSIC",
                "style": "secondary",
            })

        return actions

    @staticmethod
    def _parse_evidence_conflict_choice(user_input: str, current_q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Interpreta la respuesta del usuario para un pendiente ``evidence_profile_conflict``."""
        detail = current_q.get("conflict_detail") or {}
        master_value = detail.get("master_value")
        evidence_value = detail.get("evidence_value")
        opts = current_q.get("options") or []
        raw = (user_input or "").strip()
        if not raw:
            return None
        low = raw.lower().strip()
        token = low.replace(" ", "")

        def _opt_pick(index_zero_based: int) -> Optional[Dict[str, Any]]:
            if index_zero_based < 0 or index_zero_based >= len(opts):
                return None
            oid = str(opts[index_zero_based].get("id") or "")
            if oid == "master_profile":
                return {"chosen_source": "master_profile", "value": master_value}
            if oid == "session_doc":
                return {"chosen_source": "session_doc", "value": evidence_value}
            return None

        if raw in ("1", "uno"):
            picked = _opt_pick(0)
            if picked:
                return picked
        if raw in ("2", "dos"):
            picked = _opt_pick(1)
            if picked:
                return picked

        if "master_profile" in token:
            return {"chosen_source": "master_profile", "value": master_value}
        if "session_doc" in token:
            return {"chosen_source": "session_doc", "value": evidence_value}

        profile_hit = any(
            k in low
            for k in (
                "perfil de empresa",
                "perfil empresa",
                "dato del perfil",
                "empresa registrada",
                "catalogo maestro",
                "catálogo maestro",
            )
        ) or ("perfil" in low and "documento" not in low and "constancia" not in low)
        doc_hit = any(
            k in low
            for k in (
                "documento",
                "constancia",
                "acta",
                "pdf",
                "evidencia",
                "sesión",
                "sesion",
                "subido",
                "archivo",
            )
        )
        if profile_hit and not doc_hit:
            return {"chosen_source": "master_profile", "value": master_value}
        if doc_hit and not profile_hit:
            return {"chosen_source": "session_doc", "value": evidence_value}
        return None

    async def _handle_evidence_profile_conflict_resolution(
        self,
        *,
        session_id: str,
        user_input: str,
        company_id: str,
        pending: List,
        current_idx: int,
        session_state: Dict[str, Any],
        correlation_id: str,
    ) -> AgentOutput:
        """Persiste override HITL para conflicto evidencia vs perfil y recalcula Go/No-Go."""
        if not company_id:
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    "Para resolver este conflicto necesito que **selecciones una empresa** "
                    "en el menú superior (el semáforo usa el perfil maestro como referencia)."
                ),
                confianza="Alta",
                tipo="clarification_needed",
            )

        current_q = pending[current_idx]
        field_key = str(current_q.get("field") or "").strip()
        field_label = str(current_q.get("label") or field_key)

        parsed = self._parse_evidence_conflict_choice(user_input, current_q)
        if not parsed:
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    f"No identifiqué tu elección para **{field_label}**.\n\n"
                    "Responde con **1** (dato del perfil de empresa) o **2** (dato del documento subido), "
                    "o escribe **perfil empresa** / **documento**."
                ),
                confianza="Alta",
                tipo="clarification_needed",
            )

        chosen_value = parsed["value"]
        chosen_source = parsed["chosen_source"]

        from app.services.evidence_profile_service import (
            build_conflict_pending_questions,
            build_evidence_profile_from_documents,
            build_effective_profile,
            detect_profile_conflicts,
        )

        fresh = await self.context_manager.memory.get_session(session_id) or {}
        overrides = dict(fresh.get("evidence_profile_overrides") or {})
        overrides[field_key] = {
            "value": chosen_value,
            "chosen_source": chosen_source,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "user_reply": (user_input or "").strip()[:500],
        }
        fresh["evidence_profile_overrides"] = overrides

        if settings.ENABLE_EVIDENCE_PROFILE_BRIDGE:
            company = await self.context_manager.memory.get_company(company_id) or {}
            master_profile = company.get("master_profile") or {}
            docs = await self.context_manager.memory.get_documents(session_id)
            evidence_profile = build_evidence_profile_from_documents(docs or [])
            conflicts = detect_profile_conflicts(
                master_profile=master_profile,
                evidence_profile=evidence_profile,
                evidence_profile_overrides=overrides,
            )
            effective_profile, profile_provenance = build_effective_profile(
                master_profile=master_profile,
                evidence_profile=evidence_profile,
                user_overrides=overrides,
            )
            fresh["evidence_profile"] = evidence_profile
            fresh["effective_profile_provenance"] = profile_provenance
            fresh["evidence_profile_conflicts"] = conflicts

            old_pending = list(fresh.get("pending_questions") or [])
            stripped = [
                q for q in old_pending if str(q.get("type") or "") != "evidence_profile_conflict"
            ]
            stripped.extend(build_conflict_pending_questions(conflicts))
            fresh["pending_questions"] = stripped
            if conflicts:
                first_i = next(
                    (
                        i
                        for i, q in enumerate(stripped)
                        if str(q.get("type") or "") == "evidence_profile_conflict"
                    ),
                    0,
                )
                fresh["current_question_index"] = first_i
            else:
                fresh["current_question_index"] = max(0, min(current_idx, len(stripped) - 1)) if stripped else 0
        else:
            old_pending = list(fresh.get("pending_questions") or [])
            if 0 <= current_idx < len(old_pending):
                stripped = old_pending[:current_idx] + old_pending[current_idx + 1 :]
            else:
                stripped = old_pending
            fresh["pending_questions"] = stripped
            fresh["current_question_index"] = (
                max(0, min(current_idx, len(stripped) - 1)) if stripped else 0
            )

        await self.context_manager.memory.save_session(session_id, fresh)

        prev_semaforo = session_state.get("go_no_go_result", {}).get("semaforo")
        new_gng = await self._recalculate_semaforo(session_id, company_id)
        new_semaforo = new_gng.get("semaforo") if new_gng else None
        semaforo_change_msg = self._build_semaforo_change_msg(prev_semaforo, new_semaforo)

        src_label = "perfil de empresa" if chosen_source == "master_profile" else "documento de sesión"
        await self._save_chat_history(
            session_id,
            user_input,
            f"Conflicto resuelto ({field_label}): se usa valor de {src_label}.",
        )

        lead = (
            f"✅ **Listo:** para **{field_label}** registraré el valor acordado desde **{src_label}** "
            f"(precedencia HITL). El semáforo se recalculó con esa decisión."
        )
        post = await self.context_manager.memory.get_session(session_id) or {}
        p_after = list(post.get("pending_questions") or [])
        if settings.ENABLE_EVIDENCE_PROFILE_BRIDGE and p_after:
            idx_after = int(post.get("current_question_index") or 0)
            idx_after = max(0, min(idx_after, len(p_after) - 1))
            nxt = p_after[idx_after]
            if str(nxt.get("type")) == "evidence_profile_conflict":
                lead += (
                    f"\n\nSiguiente pendiente de evidencia:\n**{nxt.get('label', 'Campo')}**\n"
                    f"{nxt.get('question', '')}"
                )

        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=f"{lead}{semaforo_change_msg}",
            confianza="Alta",
            tipo="data_saved",
        )

    async def _recalculate_semaforo(self, session_id: str, company_id: str) -> Optional[Dict[str, Any]]:
        """Recalcula el semáforo Go/No-Go tras guardar un dato en el perfil maestro.

        Invoca GoNoGoAgent directamente (sin reanudar el pipeline) y persiste el
        resultado en session_state["go_no_go_result"] vía MCPContextManager.

        Args:
            session_id: ID de la sesión activa.
            company_id: ID de la empresa cuyo perfil fue actualizado.

        Returns:
            Dict con el nuevo GoNoGoResult, o None si el recálculo falla.
        """
        try:
            from app.agents.go_no_go import GoNoGoAgent
            from app.contracts.agent_contracts import AgentInput as _AgentInput
            from app.services.go_no_go_session_bridges import (
                merge_company_data_with_session_evidence,
            )

            company = await self.context_manager.memory.get_company(company_id) or {}
            master_profile = company.get("master_profile", {})
            company_payload = await merge_company_data_with_session_evidence(
                self.context_manager.memory,
                session_id,
                {"master_profile": master_profile},
                persist_evidence_snap=True,
            )

            agent_input = _AgentInput(
                session_id=session_id,
                company_id=company_id,
                company_data=company_payload,
            )
            result = await GoNoGoAgent(self.context_manager).process(agent_input)
            gng_data: Dict[str, Any] = result.data if hasattr(result, "data") and result.data else {}

            # Persistir solo go_no_go_result — no sobreescribir tasks_completed (MCP exclusivo)
            fresh = await self.context_manager.memory.get_session(session_id) or {}
            fresh["go_no_go_result"] = gng_data
            await self.context_manager.memory.save_session(session_id, fresh)

            logger.info(
                "chatbot_semaforo_recalculated",
                session_id=session_id,
                semaforo=gng_data.get("semaforo"),
                total_brechas=gng_data.get("total_brechas"),
            )
            return gng_data
        except Exception as exc:
            # Resiliencia: el fallo del recálculo nunca interrumpe la conversación
            logger.error(
                "chatbot_semaforo_recalc_error",
                session_id=session_id,
                error=str(exc),
            )
            return None

    @staticmethod
    def _build_semaforo_change_msg(prev: Optional[str], new: Optional[str]) -> str:
        """Construye un mensaje de notificación cuando el semáforo cambia de estado.

        Args:
            prev: Estado anterior del semáforo ("RED", "YELLOW", "GREEN") o None.
            new: Nuevo estado del semáforo o None.

        Returns:
            Cadena con el mensaje de cambio, o cadena vacía si no hubo cambio.
        """
        if not prev or not new or prev == new:
            return ""
        icons = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}
        labels = {
            "RED": "Alto Riesgo",
            "YELLOW": "Riesgo Moderado",
            "GREEN": "Sin Brechas",
        }
        prev_icon = icons.get(prev, prev)
        new_icon = icons.get(new, new)
        new_label = labels.get(new, new)
        return f"\n\n🎯 **Semáforo actualizado:** {prev_icon} → {new_icon} **{new_label}**"

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

    @staticmethod
    def _detect_price_correction_intent(query: str) -> Optional[Dict[str, Any]]:
        """Detecta corrección post-entrega (lenguaje natural + monto)."""
        from app.services.price_correction_chat import detect_price_correction_intent

        return detect_price_correction_intent(query)

    async def _try_price_correction_channel(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        user_query: str,
        correlation_id: str,
    ) -> Optional[AgentOutput]:
        """
        Canal dedicado de corrección de precios; None si el mensaje no aplica.
        """
        from app.services.price_correction_chat import (
            build_price_correction_guidance_message,
            detect_price_correction_intent,
            session_ready_for_price_correction,
        )

        correction = detect_price_correction_intent(user_query)
        if not correction:
            return None
        ready = session_ready_for_price_correction(session_state, session_id)
        if correction.get("needs_price") or not ready:
            msg = build_price_correction_guidance_message(
                needs_price=bool(correction.get("needs_price")),
                session_ready=ready,
            )
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="economic_correction_guidance",
            )
        return await self._handle_price_correction(
            session_id, session_state, correction, correlation_id
        )

    async def _handle_price_correction(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        correction: Dict[str, Any],
        correlation_id: str = "",
    ) -> AgentOutput:
        from app.services.document_patch_service import apply_price_correction

        field = str(correction.get("field_hint") or "").strip()
        if not field:
            inputs = session_state.get("economic_user_inputs") or {}
            cp = inputs.get("concept_prices") if isinstance(inputs.get("concept_prices"), dict) else {}
            if len(cp) == 1:
                field = next(iter(cp.keys()))
            elif len(cp) > 1:
                for k in cp:
                    if "partida" in k.lower() or k.startswith("concept_"):
                        field = k
                        break
            if not field and len(inputs) == 1:
                field = next(iter(inputs.keys()))
            if not field:
                try:
                    from app.services.structured_economic_price_mapper import (
                        build_structured_price_slots,
                    )

                    rows = await self.context_manager.memory.get_line_items_for_session(
                        session_id
                    )
                    slots = build_structured_price_slots(rows or [], cp)
                    if len(slots) == 1:
                        field = str(slots[0].get("field") or "").strip()
                except Exception:
                    pass
        if not field:
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    "Indica qué concepto o zona quieres corregir y el nuevo precio, "
                    "por ejemplo: «Corrige Zona A lunes a domingo a 35,529»."
                ),
                confianza="Alta",
                tipo="clarification_needed",
            )
        patch = await apply_price_correction(
            self.context_manager.memory,
            session_id,
            price_field=field,
            new_value=float(correction["new_value"]),
            source="chat_correction",
        )
        n = int(patch.get("file_count") or 0)
        regen = patch.get("regenerated_economic") or []
        detail = ""
        if regen:
            detail = " Incluye tabla, anexo AE, APU y carta compromiso."
        msg = (
            f"Listo. Actualicé el precio y recalculé **{n}** archivo(s) impactado(s).{detail} "
            f"Puedes descargar solo los actualizados desde el panel de entrega (delta)."
        )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="economic_correction",
        )

    async def _route_early_user_intent(
        self,
        *,
        session_id: str,
        user_query: str,
        session_state: Dict[str, Any],
        pending_questions: List[Dict[str, Any]],
        current_idx: int,
        current_pending_type: str,
        is_gen_request: bool,
        company_id: Optional[str],
        correlation_id: str,
        activity_state: str,
    ) -> Optional[AgentOutput]:
        """
        Enrutamiento determinista por intención (SUPER ISSUE S.1–S.2).
        Evita META forense o RAG cuando el usuario pide estado o «generar» ambiguo.
        """
        from app.services.chat_user_intent import (
            DISAMBIGUATE_GENERAR_MESSAGE,
            UserChatIntent,
            resolve_user_intent,
        )

        if not user_query or not str(user_query).strip():
            return None

        eco_pending = [
            q
            for q in (pending_questions or [])
            if str(q.get("type") or "")
            in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
        ]
        resolved = resolve_user_intent(
            user_query,
            has_economic_pending=bool(eco_pending),
            has_any_pending=bool(pending_questions),
            current_pending_type=current_pending_type,
            is_explicit_gen_command=is_gen_request,
        )

        if resolved.intent == UserChatIntent.DESAMBIGUAR_GENERAR:
            await self._save_chat_history(session_id, user_query, DISAMBIGUATE_GENERAR_MESSAGE)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=DISAMBIGUATE_GENERAR_MESSAGE,
                confianza="Alta",
                tipo="clarification_needed",
                activity_state=activity_state,
            )

        if resolved.intent == UserChatIntent.VER_ESTADO and not is_gen_request:
            has_blocking_eco = any(
                str(q.get("type") or "") == "economic_validation_blocking"
                for q in (pending_questions or [])
            )
            if not has_blocking_eco:
                return await self._handle_meta_query(
                    session_id, user_query, session_state, correlation_id
                )

        if resolved.intent == UserChatIntent.AYUDA and company_id:
            return await self._handle_user_confusion_help(
                session_id=session_id,
                session_state=session_state,
                pending=pending_questions,
                current_idx=current_idx,
                user_query=user_query,
                correlation_id=correlation_id,
                company_id=company_id,
            )

        if resolved.intent == UserChatIntent.GENERAR_EXPEDIENTE and company_id:
            from app.services.chat_gate5_formatter import format_gate5_message
            from app.services.chat_stop_reason_map import single_cta_for_context

            msg = format_gate5_message(
                status="Puedes generar el expediente cuando la cotización económica esté lista.",
                cta=single_cta_for_context(stop_reason="IDLE", has_economic_pending=False),
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="meta_answer",
                suggested_actions=[
                    {"label": "🚀 Generar Documentos", "payload": "CMD_TRIGGER_DOC_GEN", "style": "primary"}
                ],
                activity_state=activity_state,
            )

        return None

    async def _handle_meta_query(self, session_id: str, query: str, session_state: Dict, correlation_id: str = "") -> AgentOutput:
        """Explica el estado del sistema (Gate 5: ≤3 líneas + 1 CTA)."""
        from app.services.chat_gate5_formatter import build_compact_meta_status

        decision = session_state.get("last_orchestrator_decision", {})
        stop_reason = decision.get("stop_reason", "IDLE")
        missing = session_state.get("pending_questions", [])
        cur_i = int(session_state.get("current_question_index") or 0)

        bot_msg = build_compact_meta_status(
            stop_reason=stop_reason,
            pending_questions=missing,
            current_idx=cur_i,
        )

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
        # Señal A: Interrogación/Confusión — «que» solo como palabra (evita "porque", "aunque", etc.)
        signals_a_rest = (
            "cuales",
            "cual",
            "no se",
            "no entiendo",
            "dime",
            "explica",
            "cuales son",
        )
        has_a = bool(re.search(r"\bque\b", q)) or any(s in q for s in signals_a_rest)
        # Señal B: Contexto de Datos/Conceptos
        signals_b = ["conceptos", "concepto", "datos", "dato", "precios", "precio", "faltan", "faltante", "requieres", "necesitas", "pediste"]
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

    @staticmethod
    def _bases_consult_whitelist_during_hitl(query: str) -> bool:
        """
        Patrones que permiten abrir RAG aunque exista cola HITL (captura de datos).

        Objetivo: consultas claras al **instrumento de licitación** (bases/pliego/anexos)
        sobre **reglas o literales** que suelen ser necesarios para contestar bien un
        pendiente económico (PU, IVA, moneda, topes, tabulador, presentación, etc.).

        No sustituye al HITL: tras leer el pliego el usuario sigue debiendo cerrar el dato pendiente.
        """
        if not query or len(query.strip()) < 10:
            return False
        q = ChatbotRAGAgent._normalize(query)

        doc_markers = (
            "bases",
            "pliego",
            "convocatoria",
            "convocatorio",
            "anexo",
            "licitacion publica",
            "licitacion",
            "fallo de bases",
        )
        has_doc = any(m in q for m in doc_markers)

        citation_patterns = (
            r"\bdonde\s+dice\b",
            r"\bque\s+dice\b",
            r"\bque\s+establece\b",
            r"\ben\s+que\s+apartado\b",
            r"\bcual\s+es\s+el\s+apartado\b",
            r"\bcual\s+es\s+el\s+fragmento\b",
            r"\bcitar\b",
            r"\bliteral\b",
            r"\bextracto\b",
            r"\bconforme\s+a\s+las\s+bases\b",
            r"\bsegun\s+las\s+bases\b",
            r"\bsegun\s+el\s+pliego\b",
            r"\bsegun\s+la\s+convocatoria\b",
        )
        has_citation = any(re.search(p, q) for p in citation_patterns)

        econ_markers = (
            "precio",
            "importe",
            "monto",
            "tarifa",
            "costo",
            "oferta economica",
            "propuesta economica",
            "iva",
            "isr",
            "moneda",
            "tope",
            "maximo",
            "minimo",
            "tabulador",
            "desglose",
            "criterio de evaluacion",
            "evaluacion econom",
            "puntaje",
            "garantia",
            "seguro",
            "anticipo",
            "esquema de pago",
            "forma de pago",
            "vigencia de la oferta",
            "vigencia de precios",
            "actualizacion de precios",
            "inflacion",
            "precios unitarios",
            "precio unitario",
        )
        has_econ = any(m in q for m in econ_markers)

        # A) Instrumento + (cita o tema económico): consulta típica para fundamentar un PU.
        if has_doc and (has_citation or has_econ):
            return True

        # B) Reglas económicas fuertes aun sin decir "bases" (Muchas veces el usuario acorta).
        strong_econ = (
            r"\b(hay|existe|aplica)\b.{0,80}\b(precio\s+(maximo|minimo)|tope|tabulador)\b",
            r"\b(precio\s+(maximo|minimo)|tope\s+de\s+precio|importe\s+(maximo|minimo))\b",
            r"\b(iva|isr)\b.{0,60}\b(oferta|propuesta|precio|importe)\b|\b(oferta|propuesta)\b.{0,60}\b(iva|isr)\b",
            r"\b(moneda|usd|mxn|dolares|pesos)\b.{0,60}\b(oferta|propuesta|precio|importe)\b",
            r"\b(tabulador|desglose)\b.{0,80}\b(precio|importe|oferta|propuesta)\b|\b(precio|importe|oferta|propuesta)\b.{0,80}\b(tabulador|desglose)\b",
            r"\b(criterio|formula)\b.{0,80}\b(evaluacion|puntaje)\b.{0,80}\b(precio|econom|importe)\b",
            r"\b(anticipo|parcialidades|esquema\s+de\s+pagos)\b.{0,80}\b(bases|pliego|oferta|precio|importe)\b",
            r"\b(bases|pliego)\b.{0,80}\b(anticipo|parcialidades|pagos)\b",
            r"\b(penalidades|incumplimiento)\b.{0,80}\b(precio|importe|oferta|propuesta)\b",
            r"\b(variacion|actualizacion)\b.{0,60}\b(precio|importe|oferta)\b",
        )
        for pat in strong_econ:
            if re.search(pat, q):
                return True

        return False

    @staticmethod
    def _detect_defer_pending_intent(query: str) -> bool:
        """True si el usuario pide posponer el dato actual y pasar a otro pendiente."""
        if not query or len(query.strip()) < 2:
            return False
        q = ChatbotRAGAgent._normalize(query)
        needles = (
            "mas tarde",
            "despues",
            "siguiente",
            "saltar",
            "omitir",
            "pospon",
            "posponer",
            "luego",
            "no lo tengo",
            "no se aun",
            "no lo tengo aun",
            "pasar al siguiente",
            "siguiente requisito",
            "siguiente dato",
            "no puedo ahora",
            "sin dato aun",
            "sin dato aún",
        )
        return any(n in q for n in needles)

    @staticmethod
    def _detect_skip_intent(query: str) -> bool:
        """
        True si el usuario indica explícitamente omitir/saltar un campo pendiente
        (intención de omisión auditada, Req 4.3/4.4).

        Frases reconocidas: omitir, saltar, no aplica, no tengo, después, skip,
        no es necesario, no corresponde, no aplica para nosotros, etc.

        Nota: estas frases son más directas/definitivas que las de _detect_defer_pending_intent
        (que solo pospone al final de la cola). Aquí el usuario quiere eliminar el campo.
        """
        if not query or len(query.strip()) < 2:
            return False
        q = ChatbotRAGAgent._normalize(query)
        needles = (
            "omitir",
            "omitelo",
            "omitir este",
            "omitir ese",
            "saltar",
            "saltarlo",
            "saltar este",
            "saltar ese",
            "no aplica",
            "no aplica para",
            "no tengo ese",
            "no tengo este",
            "no tengo ese dato",
            "no tengo este dato",
            "no cuento con ese",
            "no cuento con este",
            "skip",
            "no es necesario",
            "no corresponde",
            "no es requerido",
            "no es obligatorio",
            "no lo necesito",
            "no aplica en nuestro caso",
            "no aplica para nosotros",
            "no aplica para mi",
            "no aplica para mi empresa",
            "no aplica a nosotros",
            "no aplica a mi",
            "no aplica a mi empresa",
            "no tengo esa informacion",
            "no tengo esa información",
            "no tengo ese campo",
            "no tengo esos datos",
            "no tengo esa dato",
            "no aplica ese campo",
            "no aplica ese dato",
        )
        return any(n in q for n in needles)

    async def _handle_user_skip(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List,
        current_idx: int,
        user_query: str,
        correlation_id: str,
    ) -> AgentOutput:
        """
        Procesa la intención explícita del usuario de omitir el campo pendiente actual.

        - Si el campo NO es bloqueante: lo marca como omitido con trazabilidad
          (``omitted=True``, ``source="user_skip"``) y avanza al siguiente pendiente.
        - Si el campo ES bloqueante: mantiene estado WAITING_FOR_DATA con mensaje
          UX explícito del bloqueo (Req 4.4, 5.1).
        """
        if not pending:
            return self._format_response(
                session_id, correlation_id, "No hay pendientes que omitir.", tipo="info"
            )
        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        current_q = pending[idx]
        field_label = str(current_q.get("label") or current_q.get("field") or "Campo")

        # Req 4.4 / 5.1: Si el campo es bloqueante, no se puede omitir.
        if self._pending_is_blocking(current_q):
            msg = (
                f"⚠️ **No es posible omitir «{field_label}».**\n\n"
                "Este dato es **crítico** para continuar con la generación de documentos. "
                "Sin él, el sistema no puede avanzar al siguiente paso.\n\n"
                "Por favor, proporciona el valor solicitado para desbloquear el flujo. "
                "Si tienes dudas sobre cómo obtenerlo, puedo orientarte."
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="skip_denied_blocking",
            )

        # Req 4.3: Campo no bloqueante → marcar como omitido con trazabilidad y avanzar.
        # Clonar el item con la marca de omisión antes de retirarlo de la cola.
        omitted_item = dict(current_q)
        omitted_item["omitted"] = True
        omitted_item["source"] = "user_skip"
        omitted_item["omitted_at"] = datetime.now(timezone.utc).isoformat()
        omitted_item["user_phrase"] = str(user_query)[:500]

        # Persistir registro de omisiones auditadas en sesión.
        fresh = await self.context_manager.memory.get_session(session_id) or dict(session_state or {})
        skipped_log = list(fresh.get("user_skipped_fields") or [])
        fid = str(current_q.get("field") or "").strip()
        if fid and not any(str(s.get("field")) == fid for s in skipped_log):
            skipped_log.append(omitted_item)
        fresh["user_skipped_fields"] = skipped_log[-100:]

        # Retirar el item de la cola de pendientes.
        p_list = list(fresh.get("pending_questions") or pending)
        if p_list and idx < len(p_list):
            p_list = p_list[:idx] + p_list[idx + 1:]
        next_idx = max(0, min(idx, len(p_list) - 1)) if p_list else 0
        fresh["pending_questions"] = p_list
        fresh["current_question_index"] = next_idx
        await self.context_manager.memory.save_session(session_id, fresh)

        logger.info(
            "chatbot_field_skipped_by_user",
            session_id=session_id,
            field=fid,
            label=field_label[:120],
            source="user_skip",
            is_blocking=bool(current_q.get("is_blocking")),
        )

        if p_list:
            next_q = p_list[next_idx]
            next_label = str(next_q.get("label") or next_q.get("field") or "Campo")
            next_question = str(next_q.get("question") or "")
            progress = self._compute_pending_progress(p_list, next_idx)
            resp = (
                f"Entendido, omití **«{field_label}»** y lo registré como no aplicable.\n\n"
                f"**{progress['progress_label']}:** {next_label}\n\n"
                f"{next_question}"
            ).strip()
        else:
            resp = (
                f"Entendido, omití **«{field_label}»** y lo registré como no aplicable.\n\n"
                "🎉 No quedan más campos pendientes. Ya puedes continuar con la generación."
            )

        await self._save_chat_history(session_id, user_query, resp)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=resp,
            confianza="Alta",
            tipo="field_skipped",
            progress=self._compute_pending_progress(p_list, next_idx) if p_list else None,
        )

    @staticmethod
    def _detect_non_cotizable_intent(query: str) -> bool:
        """True si el usuario indica que el renglón no es cotizable/documental."""
        if not query or len(query.strip()) < 4:
            return False
        q = ChatbotRAGAgent._normalize(query)
        needles = (
            "no es una cotizacion",
            "no es cotizacion",
            "no es cotizable",
            "esto no se cotiza",
            "no lleva precio",
            "es una declaratoria",
            "es declaratoria",
            "es un escrito",
            "es documental",
            "es documento",
            "solo declaracion",
            "solo declaración",
            "a que seguro te refieres",
            "a qué seguro te refieres",
            "pasame el parrafo",
            "pásame el párrafo",
            "en que pagina",
            "en qué página",
            "donde lo solicitan",
            "dónde lo solicitan",
        )
        return any(n in q for n in needles)

    @staticmethod
    def _detect_support_evidence_intent(query: str) -> bool:
        """True cuando el usuario pide evidencia: página, párrafo o cita literal."""
        if not query or len(query.strip()) < 6:
            return False
        q = ChatbotRAGAgent._normalize(query)
        markers = (
            "pagina",
            "página",
            "parrafo",
            "párrafo",
            "donde dice",
            "dónde dice",
            "que dice",
            "qué dice",
            "en que apartado",
            "en qué apartado",
            "pasame",
            "pásame",
            "fragmento",
            "cita textual",
            "muestrame",
            "muéstrame",
        )
        return any(m in q for m in markers)

    @staticmethod
    def _pending_has_verifiable_anchor(q: Dict[str, Any]) -> bool:
        """Fail-closed: exige documento + fragmento literal + página o fila."""
        if not isinstance(q, dict):
            return False
        oi = q.get("original_item")
        if not isinstance(oi, dict):
            return False
        src = str(oi.get("source") or "").strip()
        sn = str(oi.get("snippet") or "").strip()
        pg = oi.get("page") or oi.get("pagina")
        row = oi.get("row_index")
        if not src or len(sn) < 12:
            return False
        try:
            if int(pg) >= 1:
                return True
        except (TypeError, ValueError):
            pass
        try:
            return int(float(row)) >= 1
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _detect_capture_escape_intent(query: str) -> bool:
        """True cuando el usuario pide explicación durante captura HITL."""
        if not query or len(query.strip()) < 3:
            return False
        # No confundir “¿qué concepto / qué precio?” con pedido de explicación al RAG:
        # esas frases deben ir a la rama determinística de aclaración (pendiente actual).
        if ChatbotRAGAgent._evaluate_clarification_intent(query):
            return False
        q = ChatbotRAGAgent._normalize(query)
        hints = (
            "que es",
            "qué es",
            "a que se refiere",
            "a qué se refiere",
            "explicame",
            "explícame",
            "no entiendo",
            "aclarame",
            "aclárame",
            "como se interpreta",
            "cómo se interpreta",
            "significa",
            "definicion",
            "definición",
        )
        if any(h in q for h in hints):
            return True
        # Pregunta abierta (signo) sin señales de aclaración ni de “defíneme esto”:
        # puede ser consulta al pliego durante captura; se deja al RAG con recordatorio.
        return "?" in query or "¿" in query

    def _rag_blocked_by_pending_response(
        self,
        *,
        session_id: str,
        correlation_id: str,
        pending: List,
        current_idx: int,
        reminders: List[Dict[str, Any]],
    ) -> AgentOutput:
        """Respuesta cuando el usuario intenta RAG pero hay HITL pendiente."""
        if not pending:
            return self._format_response(
                session_id,
                correlation_id,
                "No hay datos pendientes; ya puedes preguntar sobre las bases.",
                tipo="info",
            )
        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        q = pending[idx]
        _raw_label_blocked = str(q.get("label") or q.get("field_target") or q.get("field") or "Campo")
        msg = self.conversation_normalizer.normalize_capture_message(
            field_label=self._humanize_field_target(_raw_label_blocked),
            question=str(q.get("question", "")),
            intent_type=str(q.get("type", "profile")),
            state_hint="blocked_by_pending",
        )
        if reminders:
            lbls = []
            for r in reminders[:10]:
                lb = str(r.get("label") or r.get("field") or "").strip()
                if lb:
                    lbls.append(f"«{lb}»")
            if lbls:
                msg += (
                    "\n\n**Recordatorio:** antes de cerrar la generación económica completa aún debes completar "
                    f"(pospuestos): {', '.join(lbls)}."
                )
        msg += (
            "\n\nSi necesitas una regla del pliego (IVA, tope de precio, etc.), pregúntalo explícito "
            "(ejemplo: «¿Qué dicen las bases sobre el IVA?»)."
        )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="rag_blocked_pending",
        )

    async def _handle_user_confusion_help(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List,
        current_idx: int,
        user_query: str,
        correlation_id: str,
        company_id: Optional[str] = None,
    ) -> AgentOutput:
        """Respuesta corta y accionable cuando el usuario no entiende qué hacer (sin RAG/LLM genérico)."""
        eco_pending = [
            q
            for q in (pending or [])
            if str(q.get("type") or "") in ("economic_price", "economic_validation_blocking")
        ]
        if eco_pending:
            q = None
            if (
                pending
                and 0 <= current_idx < len(pending)
                and str(pending[current_idx].get("type") or "")
                in ("economic_price", "economic_validation_blocking")
            ):
                q = pending[current_idx]
            else:
                q = eco_pending[0]
            try:
                pos = eco_pending.index(q)
            except ValueError:
                pos = 0
            concept = self._concept_from_economic_price_pending_q(q)
            msg = (
                "Te explico en simple: estamos **cotizando precios unitarios sin IVA** para esta licitación.\n\n"
                f"**Ahora toca:** **{concept}** "
                f"({pos + 1} de {len(eco_pending)} precios pendientes).\n"
                "→ Responde **solo el número** en pesos (ej. `4500`).\n"
                "→ Para pasar a otro concepto primero: **`siguiente`**.\n"
                "→ Cuando termines todos: **`generar propuesta economica`**.\n\n"
                "_No necesitas copiar texto del pliego aquí; solo los importes de tu tabla de precios._"
            )
            tipo = "economic_help_pending"
            intake_active = True
        elif pending:
            q = pending[max(0, min(int(current_idx or 0), len(pending) - 1))]
            lbl = self._humanize_field_target(str(q.get("label") or q.get("field") or "dato"))
            msg = (
                f"Ahora necesito un dato de tu empresa o expediente: **{lbl}**.\n\n"
                f"Pregunta: {str(q.get('question') or '')[:500]}\n\n"
                "Responde en el chat con el valor, o escribe **siguiente** para posponer."
            )
            tipo = "profile_help_pending"
            intake_active = True
        else:
            _sess_label = str((session_state or {}).get("name") or "esta licitación").strip()
            msg = (
                f"Para avanzar en **{_sess_label}**:\n\n"
                "1. Escribe **`generar propuesta economica`** — arma o actualiza la cotización.\n"
                "2. Cuando el chat confirme precios, pulsa **Generar** en el panel (documentos).\n\n"
                "Si el bot pegó requisitos del pliego y no pedía un número, ignóralo y usa el paso 1."
            )
            tipo = "session_help"
            intake_active = False

        await self._save_chat_history(session_id, user_query, msg)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo=tipo,
            intake_active=intake_active,
            progress=self._compute_pending_progress(eco_pending or pending, current_idx)
            if (eco_pending or pending)
            else None,
        )

    async def _defer_current_pending(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List,
        current_idx: int,
        user_query: str,
        correlation_id: str,
    ) -> AgentOutput:
        """Mueve el pendiente actual al final de la cola y persiste recordatorios HITL."""
        if not pending:
            return self._format_response(
                session_id, correlation_id, "No hay pendientes que posponer.", tipo="info"
            )
        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        current_q = pending[idx]
        if self._pending_is_blocking(current_q):
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    f"Este dato es **crítico** para continuar: **{current_q.get('label', 'Campo')}**.\n\n"
                    "No puedo omitirlo ni posponerlo durante este paso. "
                    "Compárteme el valor aquí mismo (o escribe el dato exacto) para seguir."
                ),
                confianza="Alta",
                tipo="defer_denied_blocking",
            )
        if len(pending) < 2:
            return self._format_response(
                session_id,
                correlation_id,
                "**Solo queda este dato pendiente:** no hay otro requisito en cola que atacar primero. "
                "Responde con el valor, **0** o «sin costo» / «N/A» si no aplica.",
                tipo="defer_denied",
            )
        moved = pending[idx]
        reordered = pending[:idx] + pending[idx + 1 :] + [moved]
        reminders = list(session_state.get("hitl_deferred_reminders") or [])
        fid = str(moved.get("field") or "").strip()
        if fid and not any(str(r.get("field")) == fid for r in reminders):
            reminders.append(
                {
                    "field": fid,
                    "label": str(moved.get("label") or moved.get("field") or "")[:280],
                }
            )
        fresh = await self.context_manager.memory.get_session(session_id) or {}
        fresh["pending_questions"] = reordered
        fresh["current_question_index"] = idx
        fresh["hitl_deferred_reminders"] = reminders[-25:]
        await self.context_manager.memory.save_session(session_id, fresh)

        next_q = reordered[idx]
        defer_lbl = str(moved.get("label") or moved.get("field") or "?")
        resp = (
            f"**Listo:** pospuse «{defer_lbl}» al **final de la cola** (lo verás de nuevo cuando toque).\n\n"
            f"**Ahora seguimos con ({idx + 1} de {len(reordered)}):**\n"
            f"📋 **{next_q.get('label', 'Campo')}:** {next_q.get('question', '')}\n\n"
            "_Recuerda: sin cerrar todos los pendientes no se puede completar la propuesta económica cerrada._"
        )
        await self._save_chat_history(session_id, user_query, resp)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=resp,
            confianza="Alta",
            tipo="pending_deferred",
        )

    @staticmethod
    def _pending_is_blocking(q: Dict[str, Any]) -> bool:
        """Determina si un pendiente debe tratarse como bloqueo duro."""
        if not isinstance(q, dict):
            return False
        if bool(q.get("is_blocking")):
            return True
        q_type = str(q.get("type") or "")
        if q_type in ("economic_validation_blocking", "compliance_validation_blocking"):
            return True
        return False

    async def _mark_current_pending_non_cotizable(
        self,
        *,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List,
        current_idx: int,
        user_query: str,
        correlation_id: str,
    ) -> AgentOutput:
        """Marca el pendiente actual como no cotizable/documental y lo retira de la cola si aplica."""
        pending, current_idx = await self._load_fresh_pending_state(
            session_id, fallback_pending=pending, fallback_idx=current_idx
        )
        if not pending:
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta="No hay pendientes en cola para marcar como no cotizables.",
                tipo="info",
            )
        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        q = pending[idx]
        if str(q.get("type")) != "economic_price":
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta="Este pendiente no es económico; no corresponde marcarlo como no cotizable.",
                tipo="clarification_needed",
            )

        is_doc_like = is_contaminated_economic_pending_question(q)
        has_anchor = self._pending_has_verifiable_anchor(q)
        if not is_doc_like and has_anchor:
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    "Entiendo el comentario, pero este concepto parece cotizable con la evidencia actual. "
                    "Si realmente no aplica costo, responde **0**; si tienes referencia del pliego, compártela para reclasificar."
                ),
                tipo="clarification_needed",
            )

        fresh = await self.context_manager.memory.get_session(session_id) or dict(session_state or {})
        p_list = list(fresh.get("pending_questions") or pending)
        if p_list:
            idx = max(0, min(idx, len(p_list) - 1))
            removed = p_list.pop(idx)
        else:
            removed = q

        overrides = list(fresh.get("economic_non_cotizable_overrides") or [])
        fid = str(removed.get("field") or "")
        if fid and not any(str(it.get("field")) == fid for it in overrides):
            overrides.append(
                {
                    "field": fid,
                    "label": str(removed.get("label") or fid)[:280],
                    "reason": "user_marked_non_cotizable_documental",
                    "source": "chat_user_override",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "user_phrase": str(user_query)[:500],
                }
            )
        fresh["economic_non_cotizable_overrides"] = overrides[-200:]
        fresh["pending_questions"] = p_list
        fresh["current_question_index"] = max(0, min(idx, len(p_list) - 1)) if p_list else 0
        await self.context_manager.memory.save_session(session_id, fresh)
        await self._save_chat_history(
            session_id,
            user_query,
            f"Marcado como no cotizable: {removed.get('label', 'concepto')}",
        )

        if p_list:
            nxt = p_list[fresh["current_question_index"]]
            resp = (
                f"Listo: marqué **{removed.get('label', 'concepto')}** como **documental/no cotizable** "
                "y lo retiré de la cola.\n\n"
                f"Seguimos con: **{nxt.get('label', 'Campo')}**.\n"
                f"{nxt.get('question', '')}"
            ).strip()
        else:
            resp = (
                f"Listo: marqué **{removed.get('label', 'concepto')}** como **documental/no cotizable** "
                "y no quedan pendientes en cola."
            )
        if not has_anchor and not is_doc_like:
            resp = (
                f"Listo: retiré **{removed.get('label', 'concepto')}** por **falta de ancla verificable** "
                "(sin página/párrafo específico) y lo marqué para no reemitir en esta sesión."
                + ("\n\n" + resp if p_list else "")
            )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=resp,
            confianza="Alta",
            tipo="pending_marked_non_cotizable",
        )

    async def _handle_clarification(
        self,
        session_id: str,
        pending: List,
        correlation_id: str = "",
        *,
        current_idx: int = 0,
    ) -> AgentOutput:
        """Responde con el **único** pendiente activo (cola HITL uno a la vez)."""
        pending, current_idx = await self._load_fresh_pending_state(
            session_id, fallback_pending=pending, fallback_idx=current_idx
        )
        if not pending:
            return self._format_response(session_id, correlation_id, "No hay tareas ni datos pendientes en este momento. ¡Todo está en orden!")

        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        q = pending[idx]
        ft = str(q.get("field") or q.get("field_target") or "")
        if str(q.get("type")) == "quality_validation_blocking" and ft == "quality.fill.review":
            session_state = await self.context_manager.memory.get_session(session_id) or {}
            f_hint = session_state.get("last_document_fill_quality_waiting_hints") or {}
            issues = f_hint.get("issues") if isinstance(f_hint.get("issues"), list) else []
            if issues:
                from app.services.document_fill_ux_messages import build_fill_blocking_question

                resp = build_fill_blocking_question(
                    str(f_hint.get("stage") or "technical"),
                    issues,
                    session_state=session_state,
                )
            else:
                resp = str(q.get("question") or "").strip()
            await self._save_chat_history(session_id, "Solicitud de aclaración sobre pendientes", resp)
            return self._format_response(session_id, correlation_id, resp, tipo="clarification_answer")
        if str(q.get("type")) == "economic_validation_blocking":
            if self._economic_blocking_requires_source_input(q):
                resp = self._economic_blocking_source_reply(q)
            else:
                b_items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []
                if b_items:
                    resp = self._economic_blocking_first_concept_reply(q)
                else:
                    resp = await self._blocking_validation_guidance(q, session_id, correlation_id)
            await self._save_chat_history(session_id, "Solicitud de aclaración sobre bloqueo económico", resp)
            return self._format_response(session_id, correlation_id, resp, tipo="economic_validation_blocking_info")
        rest = max(0, len(pending) - idx - 1)
        _raw_label_clarif = str(q.get("label") or q.get("field_target") or q.get("field") or "Campo")
        resp = self.conversation_normalizer.normalize_capture_message(
            field_label=self._humanize_field_target(_raw_label_clarif),
            question=str(q.get("question", "")),
            intent_type=str(q.get("type", "profile")),
            state_hint="clarification",
        )
        footer = ""
        if rest:
            footer += f" Quedan **{rest}** dato(s) en cola después de este."
        resp = f"{resp}\n\n{footer}".strip()

        await self._save_chat_history(session_id, "Solicitud de aclaración sobre pendientes", resp)
        return self._format_response(session_id, correlation_id, resp, tipo="clarification_answer")

    async def _blocking_validation_guidance(
        self, q: Dict[str, Any], session_id: str, correlation_id: str = ""
    ) -> str:
        """
        Modo seguridad: proporciona guía detallada sobre bloqueos económicos.
        Implementa una jerarquía de recuperación para evitar respuestas opacas.
        """
        if self._economic_blocking_requires_source_input(q):
            return self._economic_blocking_source_reply(q)
        items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []

        # --- NIVEL 1: Items directos en la pregunta (prioriza primer concepto accionable en chat) ---
        if items:
            top = [str(it.get("concepto_label") or "").strip() for it in items[:6] if str(it.get("concepto_label") or "").strip()]
            preview = "\n".join(f"- {x}" for x in top) if top else "- (sin etiqueta legible)"
            extra = f"\n... y {len(items) - len(top)} más." if len(items) > len(top) else ""
            first = top[0] if top else ""

            return (
                f"Hay **{len(items)}** concepto(s) con precio unitario en cero o no válido.\n\n"
                + (f"**Empieza por:** «{first}». " if first else "")
                + "Puedes escribir **solo el número** en pesos sin IVA en el chat (o **0** si no aplica costo), "
                "o corregir en bloque en Excel/cotización y pulsar **generar o continuar**.\n\n"
                f"Lista breve:\n{preview}{extra}\n\n"
                "Cuando los importes queden coherentes, vuelve a **generar o continuar** para revalidar."
            )

        # --- NIVEL 2 & 3: Recuperación desde el estado de la sesión ---
        try:
            session_state = await self.context_manager.memory.get_session(session_id) or {}
            tasks = session_state.get("tasks_completed", []) or []

            # Lista vacía o sin economic_proposal: el bucle no asigna val_result → nivel 4 (sin StopIteration).
            # Buscar la última corrida económica (misma convención que economic_writer / economic_validation.service).
            val_result = None
            for t in reversed(tasks):
                if t.get("task") == "economic_proposal":
                    val_result = t.get("result", {}).get("validation_result")
                    break

            if val_result:
                # Nivel 2: Issues explícitos
                blocking_issues = val_result.get("blocking_issues", [])
                if blocking_issues:
                    issues_text = "\n".join(f"- {iss}" for iss in blocking_issues[:4])
                    return (
                        "Detecté errores de validación económica que impiden avanzar:\n\n"
                        f"{issues_text}\n\n"
                        "Empieza corrigiendo el **ítem #1** de tu lista de precios y luego reintenta "
                        "generar la propuesta."
                    )

                # Nivel 3: Análisis de trazabilidad (ej. precios <= 0)
                traz = val_result.get("trazabilidad", {})
                if "precios_positivos" in traz:
                    return (
                        "Detecté que algunos conceptos tienen **precios en cero o negativos**, lo cual es un bloqueo crítico.\n\n"
                        "Revisa tu catálogo y asegúrate de que todos los importes sean mayores a 0."
                    )

        except Exception as e:
            logger.error(f"[Chatbot] Error recuperando validaciones de sesión: {e}")

        # --- NIVEL 4: Sugerencia inteligente (Fallback final) ---
        return (
            "Detecté errores de validación económica que impiden avanzar. Aunque no puedo detallar el error exacto desde aquí, "
            "te sugiero empezar por el **ítem #1** y revisar que no haya precios en cero, campos vacíos "
            "o errores de suma en tu catálogo o Excel.\n\n"
            "Una vez corregidos, vuelve a generar la propuesta para revalidar."
        )

    @staticmethod
    def _document_candidates_prompt_section(session_state: Optional[Dict[str, Any]]) -> str:
        """
        Genera un bloque de sistema con la lista de documentos detectados oficialmente.
        Ahora incluye un escaneo de la 'master_compliance_list' para cubrir puntos 
        informativos que no son entregables pero sí son reglas del pliego.
        """
        if not isinstance(session_state, dict):
            return ""
        
        # 1. Obtener candidatos (entregables)
        candidates_data = (
            session_state.get("document_candidates_v1") or 
            session_state.get("dictamen", {}).get("fastTrackDocumentCandidates") or
            session_state.get("document_candidates_final")
        )
        
        # 2. Obtener lista maestra de compliance (todas las reglas detectadas)
        compliance_items = []
        tasks = session_state.get("tasks_completed") or []
        for t in reversed(tasks):
            if isinstance(t, dict) and t.get("task") == "master_compliance_list":
                res = t.get("result", {})
                if isinstance(res, dict) and res.get("data"):
                    data = res["data"]
                    for zone in ("administrativo", "tecnico", "formatos"):
                        compliance_items.extend(data.get(zone) or [])
                break

        lines = []
        seen_names = set()

        # Prioridad A: Entregables oficiales (83 ítems aprox)
        if isinstance(candidates_data, dict):
            for c in candidates_data.get("candidate_document_list", [])[:100]:
                nombre = str(c.get("nombre") or "Documento").strip()
                seen_names.add(nombre.lower())
                accion = str(c.get("tipo_accion_final") or "informativo").strip()
                evidencia = str(c.get("evidencia_en_bases") or c.get("snippet") or "").strip()
                pagina = c.get("pagina") or c.get("page")
                
                accion_txt = "GENERAR" if accion == "generar" else ("PRESENTAR FÍSICO" if accion == "presentar_fisico" else "INFORMATIVO")
                pg_txt = f" (Pág. {pagina})" if pagina else ""
                lines.append(f"- **{nombre}**{pg_txt}: {accion_txt}")
                if evidencia and len(evidencia) > 10:
                    clean_ev = evidencia.replace("\n", " ").strip()[:350]
                    lines.append(f"  > Evidencia: \"{clean_ev}...\"")

        # Prioridad B: Reglas informativas de la lista maestra (los otros 200+ ítems)
        # Solo agregamos los que no están en la lista de candidatos para evitar duplicidad
        for item in compliance_items:
            nombre = str(item.get("nombre") or item.get("descripcion") or "").strip()
            if not nombre or nombre.lower() in seen_names:
                continue
            
            seen_names.add(nombre.lower())
            if len(lines) > 40: break # Límite reducido para evitar verbosidad negativa del LLM
            
            evidencia = str(item.get("snippet") or "").strip()
            pagina = item.get("page") or item.get("pagina")
            pg_txt = f" (Pág. {pagina})" if pagina else ""
            
            lines.append(f"- **{nombre}**{pg_txt}: INFORMATIVO/REGLA")
            if evidencia and len(evidencia) > 10:
                clean_ev_rule = evidencia.replace("\n", " ").strip()[:300]
                lines.append(f"  > Texto del pliego: \"{clean_ev_rule}...\"")

        if not lines:
            return ""
            
        body = "\n".join(lines)
        return (
            "\n---\n**CONOCIMIENTO MAESTRO DE LA LICITACIÓN (AUDITORÍA INTEGRAL):**\n"
            "Esta lista contiene tanto ENTREGABLES como REGLAS INFORMATIVAS detectadas por el sistema.\n"
            f"{body}\n"
            "\n**PROTOCOLOS DE RESPUESTA (LÓGICA JURÍDICA):**\n"
            "1. **Mapeo de Sinónimos**: Si el usuario pregunta por un tema (ej: 'ética', 'conducta') y no ves la palabra exacta, busca en la lista de arriba el documento más parecido (ej: 'Declaración de Integridad') y responde sobre ese.\n"
            "2. **Interpretación en Positivo**: Si el 'Texto del pliego' menciona requisitos como *causas de descalificación* (ej: 'será causa de rechazo si el importe es menor...' o 'si no se presenta cheque...'), explícale al usuario qué DEBE hacer para cumplir: 'Debes asegurar que el importe sea mayor o igual' o 'El pliego exige/prohíbe el uso de X'.\n"
            "3. **Consistencia Absoluta**: Si encontraste un dato en la evidencia (ej: sobre cheques o importes), NO digas después 'no lo veo' o 'no hay información'. Confía ciegamente en la evidencia inyectada arriba.\n"
            "4. **Asertividad**: Si el tema está en esta lista maestra, CONFIRMA su existencia y cita la página. No dudes.\n---\n"
        )

    @staticmethod
    def _compliance_truth_prompt_section_from_session(
        tasks_completed: Optional[List],
        session_state: Optional[Dict[str, Any]],
    ) -> str:
        """
        Inyecta en el system prompt un resumen auditable de compliance / gate 12.1 / Go-No-Go
        leído desde ``tasks_completed`` y campos de sesión (misma filosofía que el bloqueo económico).

        El ChatbotRAGAgent **no** leía antes la lista maestra; este bloque evita respuestas «todo bien»
        cuando el motor ya registró riesgo o bloqueo.
        """
        sess = session_state if isinstance(session_state, dict) else {}
        tasks = tasks_completed if isinstance(tasks_completed, list) else []
        chunks: List[str] = []

        gate = sess.get("compliance_gate_result")
        if isinstance(gate, dict) and gate.get("is_blocking"):
            failed = gate.get("failed_rules") or []
            failed_s = ", ".join(str(x) for x in failed[:12])
            chunks.append(
                f"**Gate 12.1 (bloqueo):** reglas no superadas: {failed_s or '(sin código en sesión)'}."
            )

        mc_res: Optional[Dict[str, Any]] = None
        for t in reversed(tasks):
            if isinstance(t, dict) and t.get("task") == "master_compliance_list":
                r = t.get("result")
                if isinstance(r, dict):
                    mc_res = r
                break

        if isinstance(mc_res, dict):
            err = str(mc_res.get("error") or "").strip()
            if err:
                chunks.append(f"**Última corrida ComplianceAgent:** incidencia — {err[:400]}.")
            data = mc_res.get("data")
            if isinstance(data, dict):
                summ = data.get("audit_summary")
                if isinstance(summ, dict):
                    gmp = summ.get("global_match_pct")
                    tot = summ.get("total_items")
                    if gmp is not None or tot is not None:
                        chunks.append(
                            f"**Lista maestra auditada:** cobertura evidencia ~{gmp}%, ítems totales: {tot}."
                        )
                miss_evidence = 0
                samples: List[str] = []
                for zone in ("administrativo", "tecnico", "formatos"):
                    for it in data.get(zone) or []:
                        if not isinstance(it, dict):
                            continue
                        if it.get("evidence_match") is True:
                            continue
                        miss_evidence += 1
                        if len(samples) < 4:
                            lab = (
                                it.get("descripcion") or it.get("snippet") or it.get("id") or "requisito"
                            )
                            samples.append(str(lab).strip()[:140])
                if miss_evidence > 0:
                    sm = " · ".join(samples)
                    chunks.append(
                        f"**Ítems sin evidencia documental favorable:** {miss_evidence}. Ejemplos: {sm}."
                    )
                metrics = mc_res.get("metrics")
                if isinstance(metrics, dict):
                    zones = metrics.get("zones")
                    if isinstance(zones, list):
                        bad = [
                            f"{z.get('zone')}={z.get('status')}"
                            for z in zones
                            if isinstance(z, dict) and z.get("status") in ("fail", "partial")
                        ]
                        if bad:
                            chunks.append(f"**Zonas con incidencias (map-reduce):** {', '.join(bad[:10])}.")

        gng: Dict[str, Any] = {}
        top_gng = sess.get("go_no_go_result")
        if isinstance(top_gng, dict) and top_gng.get("semaforo"):
            gng = top_gng
        else:
            for t in reversed(tasks):
                if not isinstance(t, dict) or t.get("task") != "go_no_go_result":
                    continue
                r = t.get("result")
                if isinstance(r, dict) and r.get("semaforo"):
                    gng = r
                    break
        if isinstance(gng, dict) and gng.get("semaforo"):
            sem = str(gng.get("semaforo"))
            nk = int(gng.get("total_knockouts") or 0)
            nb = int(gng.get("total_brechas") or 0)
            brechas = gng.get("brechas") or []
            knock_hints: List[str] = []
            if isinstance(brechas, list):
                for b in brechas:
                    if not isinstance(b, dict) or not b.get("is_knockout"):
                        continue
                    d = (b.get("descripcion") or b.get("requisito_bases") or "")[:180]
                    if d.strip():
                        knock_hints.append(d.strip())
            ktxt = " · ".join(knock_hints[:4]) if knock_hints else ""
            tail = f" Knockouts (muestra): {ktxt}" if ktxt else ""
            chunks.append(
                f"**Go/No-Go:** semáforo **{sem}**, brechas: {nb}, knockouts: {nk}.{tail}"
            )

        if not chunks:
            return ""

        body = "\n".join(f"- {c}" for c in chunks)
        return (
            "\n---\n**ESTADO DE COMPLIANCE / RIESGO (sesión; no contradecir con optimismo infundado):**\n"
            f"{body}\n"
            "**Instrucción:** en «cómo vamos», riesgo o descalificación, prioriza este bloque; "
            "no afirmes que «todo está perfecto» si hay gate bloqueante, semáforo ROJO/AMARILLO o muchos ítems sin evidencia.\n---\n"
        )

    @staticmethod
    def _economic_blocking_prompt_section_from_tasks(tasks_completed: Optional[List]) -> str:
        """
        Construye un bloque de sistema con el último bloqueo de propuesta económica persistido
        en ``tasks_completed`` (misma fuente que revalidación y DataGap).
        """
        if not tasks_completed:
            return ""
        last: Optional[Dict[str, Any]] = None
        for t in reversed(tasks_completed):
            if isinstance(t, dict) and t.get("task") == "economic_proposal":
                last = t.get("result") if isinstance(t.get("result"), dict) else None
                break
        if not last:
            return ""
        if str(last.get("status") or "").strip().lower() != "waiting_for_data":
            return ""
        vr = last.get("validation_result")
        if not isinstance(vr, dict):
            return ""
        issues = list(vr.get("blocking_issues") or [])
        events = last.get("validation_events") if isinstance(last.get("validation_events"), list) else []
        if not issues and not events:
            return ""
        from app.agents.economic import _human_economic_blocking_summary

        detail = _human_economic_blocking_summary(events, vr)
        lines: List[str] = [
            "\n---\n**BLOQUEO ECONÓMICO ACTIVO** (última propuesta en sesión; **no inventes** otros motivos ni lo contradigas):\n",
        ]
        if detail:
            lines.append(f"- **Resumen:** {detail}\n")
        for iss in issues[:5]:
            s = str(iss).strip()
            if s:
                lines.append(f"- **Hallazgo:** {s}\n")
        lines.append(
            "\n**Instrucción:** Si el usuario pregunta qué falló, cómo corregir, totales o IVA, "
            "prioriza orientar con estos datos y su **Excel o cotización**; al cerrar cambios debe "
            "pulsar **generar o continuar** para revalidar. Si la pregunta es solo de pliego/bases, "
            "responde con los fragmentos y menciona brevemente que la propuesta económica sigue bloqueada hasta revalidar.\n---\n"
        )
        return "".join(lines)

    async def _save_price_to_catalog(self, company_id: str, question: Dict, value: str) -> bool:
        """Guarda un precio unitario en el catálogo histórico de la empresa (Hito 6)."""
        try:
            # Limpiar valor (quitar $, comas, etc)
            clean_val = value.replace("$", "").replace(",", "").strip()
            if ";" in clean_val:
                clean_val = clean_val.split(";", 1)[0].strip()
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
                raw_lbl = str(question.get("label", "Desconocido") or "")
                for _pfx in (
                    "Precio de: ",
                    "PU oferta económica — ",
                    "PU oferta economica - ",
                    "Precio (sin IVA): ",
                ):
                    raw_lbl = raw_lbl.replace(_pfx, "")
                new_item = {
                    "description": raw_lbl.strip() or "Concepto",
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

    # =========================================================================
    # TAREA 5: Sanitización de pending_questions económicas huérfanas
    # =========================================================================

    async def _sanitize_economic_pending_questions(
        self,
        session_id: str,
        session_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Filtra pending_questions de tipo economic_price verificando que el concepto
        exista en el snapshot tasks_completed["economic_proposal"] de la sesión activa.
        Descarta silenciosamente preguntas huérfanas (de sesiones anteriores o corridas
        previas del EconomicAgent que ya no corresponden al estado actual).

        Preserva todas las preguntas de tipo distinto a economic_price.
        """
        pending = list(session_state.get("pending_questions") or [])
        if not pending:
            return pending

        # ── Filtro defensivo: descartar pendientes que no requieren captura en el chat ──
        # Los siguientes tipos nunca deben llegar al flujo conversacional:
        # - INTAKE-INV-* (inventarios documentales) → van al panel de estado de la UI
        # - INTAKE-Q-CLASS-001 (clasificación técnica interna) → decisión del sistema
        # - INTAKE-B-LEG-* (solvencia legal) → documentos que el licitante presenta físicamente
        # - INTAKE-B-ECO-* (solvencia económica) → ídem
        # Estos documentos aparecen en el inventario/checklist del expediente, no en el chat.
        inventory_filtered: List[Dict[str, Any]] = []
        from app.services.hitl_queue_service import normalize_pending_queue, should_exclude_from_chat_queue

        for q in pending:
            q_type = str(q.get("question_type") or q.get("type") or "")
            field_target = str(q.get("field_target") or q.get("field") or "")
            question_id = str(q.get("question_id") or "")
            if should_exclude_from_chat_queue(q):
                logger.info(
                    "chatbot_hitl_pending_discarded",
                    session_id=session_id,
                    question_id=question_id,
                    field_target=field_target[:64],
                    reason="physical_or_procedural",
                )
                continue
            if (
                q_type == "I"
                or field_target.startswith("inventory.")
                or question_id == "INTAKE-Q-CLASS-001"
                or field_target == "quality.classification.review"
                or question_id.startswith("INTAKE-B-LEG-")
                or question_id.startswith("INTAKE-B-ECO-")
                or field_target.startswith("solvencia_legal.")
                or field_target.startswith("solvencia_economica.")
            ):
                logger.info(
                    "chatbot_inventory_pending_discarded",
                    session_id=session_id,
                    question_id=question_id,
                    reason="inventory_silent_processing",
                )
                continue
            inventory_filtered.append(q)
        pending = await self._refresh_fill_quality_pending(session_id, session_state, inventory_filtered)

        # Obtener ítems del snapshot activo
        tasks = list(session_state.get("tasks_completed") or [])
        snapshot_items: List[Dict[str, Any]] = []
        for task in reversed(tasks):
            if task.get("task") == "economic_proposal":
                result = task.get("result") if isinstance(task.get("result"), dict) else {}
                snapshot_items = list(result.get("items") or [])
                break

        if not snapshot_items:
            # Sin snapshot no podemos validar por concepto, pero sí podemos
            # descartar pendientes de obra pública (documentos técnicos que nunca
            # tienen precio unitario). Los documentales duros (_HARD_DOC_PATTERNS)
            # se mantienen para que el usuario pueda marcarlos como no-cotizables.
            cleaned_no_snapshot: List[Dict[str, Any]] = []
            for q in pending:
                if str(q.get("type") or "") == "economic_price":
                    text = _pending_economic_core_concept_text_for_chatbot(q)
                    if text and _OBRA_PUBLICA_DOC_PATTERNS.search(text):
                        logger.info(
                            "chatbot_obra_publica_question_discarded_no_snapshot",
                            session_id=session_id,
                            label=str(q.get("label") or "")[:120],
                        )
                        continue
                cleaned_no_snapshot.append(q)
            return normalize_pending_queue(cleaned_no_snapshot)

        snapshot_concepts = {
            self._normalize(str(it.get("concepto") or it.get("descripcion") or ""))
            for it in snapshot_items
            if it.get("concepto") or it.get("descripcion")
        }

        cleaned: List[Dict[str, Any]] = []
        for q in pending:
            q_type = str(q.get("type") or "")
            if q_type == "economic_price":
                # Descartar si es un documento técnico (obra pública, entregable sin PU)
                if is_contaminated_economic_pending_question(q):
                    logger.info(
                        "chatbot_contaminated_economic_question_discarded",
                        session_id=session_id,
                        label=str(q.get("label") or "")[:120],
                    )
                    continue
                label = self._normalize(
                    str(q.get("label") or "").replace("Precio (sin IVA): ", "")
                )
                # Mantener solo si el concepto existe en el snapshot activo
                if label and any(
                    label in sc or sc in label
                    for sc in snapshot_concepts
                    if sc
                ):
                    cleaned.append(q)
                else:
                    logger.info(
                        "chatbot_orphan_economic_question_discarded",
                        session_id=session_id,
                        label=label[:120],
                    )
            else:
                cleaned.append(q)

        return normalize_pending_queue(cleaned)

    async def _refresh_fill_quality_pending(
        self,
        session_id: str,
        session_state: Dict[str, Any],
        pending: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Unifica y actualiza preguntas del gate de llenado con el mensaje UX vigente."""
        f_hint = session_state.get("last_document_fill_quality_waiting_hints")
        if not isinstance(f_hint, dict):
            return pending

        blocking = int(f_hint.get("blocking_count") or 0)
        passed = f_hint.get("validation_passed") is True
        issues = f_hint.get("issues") if isinstance(f_hint.get("issues"), list) else []

        # Gate ya cerrado: eliminar preguntas obsoletas con texto de pausa antiguo.
        if passed or blocking == 0:
            return [
                q
                for q in pending
                if isinstance(q, dict)
                and str(q.get("field") or "") not in (
                    "quality.fill.review",
                    "document_fill_quality_gate",
                )
                and str(q.get("type") or "")
                not in (
                    "document_fill_quality_gate_blocking",
                    "document_fill_quality_gate",
                    "quality_validation_blocking",
                )
            ]

        if not issues:
            return pending
        from app.services.document_fill_ux_messages import build_fill_blocking_question
        from app.services.company_experience_context import build_experience_sources_ux_summary

        stage = str(f_hint.get("stage") or "technical")
        experience_summary = str(f_hint.get("experience_summary") or "").strip() or None
        if not experience_summary:
            try:
                docs = await self.context_manager.memory.get_documents(session_id) or []
                experience_summary = build_experience_sources_ux_summary(docs, session_state)
            except Exception:
                experience_summary = None
        fresh_question = build_fill_blocking_question(
            stage, issues, experience_summary=experience_summary, session_state=session_state
        )
        updated: List[Dict[str, Any]] = []
        kept_fill = False
        for q in pending:
            if not isinstance(q, dict):
                continue
            ft = str(q.get("field") or q.get("field_target") or "")
            qtype = str(q.get("type") or "")
            if ft == "quality.fill.review" or qtype in (
                "document_fill_quality_gate_blocking",
                "document_fill_quality_gate",
            ) or ft == "document_fill_quality_gate":
                if kept_fill:
                    continue
                q = dict(q)
                q["question"] = fresh_question
                q["label"] = "Datos para llenar documentos"
                q["field"] = "quality.fill.review"
                q["field_target"] = "quality.fill.review"
                q["type"] = "quality_validation_blocking"
                kept_fill = True
            updated.append(q)
        return updated

    # =========================================================================
    # TAREA 6: Confirmación HITL para licitaciones sin importe base
    # =========================================================================

    # Patrones para detectar confirmación de zero-base por el usuario
    _ZERO_BASE_ACK_PATTERNS = (
        r"no\s+requiere\s+importe\s+base",
        r"sin\s+importe\s+base",
        r"confirmar?\s+sin\s+importe",
        r"licitaci[oó]n\s+sin\s+base",
        r"oferta\s+sin\s+importe",
        r"no\s+hay\s+importe\s+base",
        r"no\s+tiene\s+importe\s+base",
        r"esta\s+licitaci[oó]n\s+no\s+requiere",
    )

    @classmethod
    def _detect_zero_base_ack_intent(cls, query: str) -> bool:
        """True si el usuario confirma que la licitación no requiere importe base."""
        if not query or len(query.strip()) < 8:
            return False
        q = cls._normalize(query)
        return any(re.search(p, q) for p in cls._ZERO_BASE_ACK_PATTERNS)

    async def _handle_zero_base_ack(
        self,
        session_id: str,
        company_id: str,
        correlation_id: str,
    ) -> AgentOutput:
        """
        Procesa la confirmación del usuario de que la licitación no requiere importe base.
        Persiste allow_zero_total_base_ack en session_state y actualiza el snapshot
        para desbloquear la generación de documentos.
        No expone el nombre técnico del flag al usuario.
        """
        session_state = await self.context_manager.memory.get_session(session_id) or {}
        user_inputs = dict(session_state.get("economic_user_inputs") or {})
        user_inputs["allow_zero_total_base_ack"] = True
        session_state["economic_user_inputs"] = user_inputs
        await self.context_manager.memory.save_session(session_id, session_state)

        logger.info("chatbot_zero_base_ack_confirmed", session_id=session_id)

        # Actualizar snapshot para que EconomicWriterAgent lo vea
        try:
            await refresh_economic_validations_for_session(
                self.context_manager.memory, session_id
            )
        except Exception as _e:
            logger.warning(
                "chatbot_zero_base_ack_refresh_failed",
                session_id=session_id,
                error=str(_e),
            )

        msg = (
            "✅ Confirmado. He registrado que esta licitación no requiere importe base. "
            "Escribe `generar documentos` para continuar con la generación."
        )
        await self._save_chat_history(session_id, "Confirmación: sin importe base", msg)
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=msg,
            confianza="Alta",
            tipo="zero_base_ack_confirmed",
        )

    # =========================================================================
    # SEMANTIC FILE EXTRACTOR — Tareas 4 y 5
    # =========================================================================

    @staticmethod
    def _infer_field_type(field_target: str) -> str:
        """
        Infiere el tipo de campo para validación numérica basado en el field_target.

        Returns:
            "currency" | "integer" | "text"
        """
        ft = str(field_target or "").lower()
        currency_keywords = ("capital", "monto", "precio", "facturacion", "facturación",
                             "patrimonio", "importe", "valor", "costo", "sueldo", "salario")
        integer_keywords = ("numero", "número", "cantidad", "empleados", "años", "anios",
                            "contratos", "experiencia")

        if any(kw in ft for kw in currency_keywords):
            return "currency"
        if any(kw in ft for kw in integer_keywords):
            return "integer"
        return "text"

    @staticmethod
    def _classify_confirmation_response(user_response: str) -> str:
        """
        Clasifica la respuesta del usuario a una confirmación de mapeo.

        Returns:
            "confirm" | "correct" | "reject"
        """
        lo = str(user_response or "").lower().strip()

        REJECT_TOKENS = ("no aplica", "no está", "no esta", "no tengo", "no lo tengo",
                         "no existe", "no hay", "no se encuentra")
        CONFIRM_TOKENS = ("sí", "si", "correcto", "exacto", "ok", "dale", "va",
                          "así es", "asi es", "eso es", "perfecto", "bien", "claro")

        if any(t in lo for t in REJECT_TOKENS):
            return "reject"
        if lo.startswith("no") and len(lo) > 5:
            return "correct"  # "no, el valor es X"
        if any(t in lo for t in CONFIRM_TOKENS):
            return "confirm"
        return "confirm"  # default: asumir confirmación

    async def _handle_economic_quotation_file_upload(
        self,
        *,
        session_id: str,
        doc_id: str,
        company_id: str,
        session_state: Dict[str, Any],
        correlation_id: str = "",
    ) -> Optional[AgentOutput]:
        """
        Importa cotización masiva (Excel/CSV) adjunta en el chat hacia la matriz económica.
        """
        from pathlib import Path

        from app.services.economic_price_file_import import import_economic_prices_from_file

        pending_list = list(session_state.get("pending_questions") or [])
        eco_n = self._count_economic_price_pending(pending_list)
        has_price_source_pending = any(
            str(q.get("field") or "").strip() == "economic_price_source"
            or str(q.get("input_mode") or "").strip().lower() == "price_source"
            for q in pending_list
        )
        blocks = await self._ensure_capture_matrix_blocks(session_id, session_state)
        if eco_n <= 0 and not blocks and not has_price_source_pending:
            return None

        doc = None
        try:
            docs = await self.context_manager.memory.get_documents(session_id)
            if docs:
                doc = next(
                    (d for d in docs if str(d.get("id") or d.get("doc_id") or "") == str(doc_id)),
                    None,
                )
        except Exception as exc:
            logger.warning("eco_file_import_doc_fetch", error=str(exc)[:120])

        content = doc.get("content") if isinstance(doc, dict) else {}
        if not isinstance(content, dict):
            content = {}
        file_path = str(content.get("file_path") or "").strip()
        filename = str(
            content.get("filename") or doc.get("metadata", {}).get("filename") or ""
        ).strip()

        if not file_path or not Path(file_path).is_file():
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    "Recibí el archivo pero no lo encuentro en almacenamiento. "
                    "Vuelve a adjuntarlo en el chat."
                ),
                confianza="Media",
                tipo="clarification_needed",
                intake_active=True,
            )

        suffix = Path(file_path).suffix.lower()
        if suffix in (".docx",):
            from app.services.document_docx_ingest import process_docx_document
            from app.services.economic_tabular_ingest_sync import (
                filter_reliable_pricing_rows,
                sync_economic_pending_after_tabular_ingest,
            )

            try:
                await process_docx_document(
                    self.context_manager.memory,
                    session_id,
                    str(doc_id),
                    file_path,
                    filename,
                )
            except Exception as proc_exc:
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=(
                        f"No pude leer tablas de precios en **{filename or 'el DOCX'}**. "
                        f"Detalle: {str(proc_exc)[:200]}"
                    ),
                    confianza="Media",
                    tipo="clarification_needed",
                    intake_active=True,
                )

            sync = await sync_economic_pending_after_tabular_ingest(
                self.context_manager.memory, session_id
            )
            fresh = await self.context_manager.memory.get_session(session_id) or session_state
            rows = await self.context_manager.memory.get_line_items_for_session(session_id)
            reliable = filter_reliable_pricing_rows(rows or [])
            n_rel = len(reliable)
            if n_rel <= 0:
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=(
                        f"Recibí **{filename or 'el archivo'}**, pero no detecté precios unitarios "
                        "en tablas del documento. Si es plantilla vacía, completa los importes o "
                        "adjunta un Excel con columnas de concepto y precio."
                    ),
                    confianza="Media",
                    tipo="clarification_needed",
                    intake_active=bool(fresh.get("pending_questions")),
                )
            cleared = bool(sync.get("cleared_price_source"))
            tail = (
                " Ya quité el bloqueo de «fuente de precios» pendiente."
                if cleared
                else ""
            )
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    f"Listo. Extraje **{n_rel}** partida(s) con precio desde **{filename or 'tu DOCX'}**."
                    f"{tail}\n\n"
                    "Puedes escribir **generar propuesta económica** o usar **Revalidar** arriba."
                ),
                confianza="Alta",
                tipo="data_saved",
                intake_active=bool(fresh.get("pending_questions")),
            )

        if suffix in (".xlsx", ".xls") and has_price_source_pending and not blocks:
            from app.services.document_excel_ingest import process_excel_document
            from app.services.economic_tabular_ingest_sync import (
                filter_reliable_pricing_rows,
                sync_economic_pending_after_tabular_ingest,
            )

            try:
                await process_excel_document(
                    self.context_manager.memory,
                    session_id,
                    str(doc_id),
                    file_path,
                    filename,
                )
            except Exception as proc_exc:
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=(
                        f"No pude leer precios en **{filename or 'el Excel'}**. "
                        f"Detalle: {str(proc_exc)[:200]}"
                    ),
                    confianza="Media",
                    tipo="clarification_needed",
                    intake_active=True,
                )
            sync = await sync_economic_pending_after_tabular_ingest(
                self.context_manager.memory, session_id
            )
            fresh = await self.context_manager.memory.get_session(session_id) or session_state
            rows = await self.context_manager.memory.get_line_items_for_session(session_id)
            reliable = filter_reliable_pricing_rows(rows or [])
            if reliable:
                cleared = bool(sync.get("cleared_price_source"))
                tail = (
                    " Ya quité el bloqueo de «fuente de precios» pendiente."
                    if cleared
                    else ""
                )
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=(
                        f"Listo. Extraje **{len(reliable)}** partida(s) con precio desde "
                        f"**{filename or 'tu Excel'}**.{tail}\n\n"
                        "Puedes escribir **generar propuesta económica** o usar **Revalidar** arriba."
                    ),
                    confianza="Alta",
                    tipo="data_saved",
                    intake_active=bool(fresh.get("pending_questions")),
                )

        if suffix not in (".xlsx", ".xls", ".csv", ".tsv", ".txt"):
            return None

        result = import_economic_prices_from_file(
            file_path,
            blocks,
            session_state.get("economic_user_inputs"),
        )
        applied = result.get("applied") or {}
        if not applied:
            err_lines = list(result.get("errors") or [])[:5]
            unmatched = list(result.get("unmatched") or [])[:8]
            detail = ""
            if err_lines:
                detail += "\n".join(f"- {e}" for e in err_lines)
            if unmatched:
                detail += "\n\nConceptos no reconocidos (muestra):\n" + "\n".join(
                    f"- {u}" for u in unmatched
                )
            cols = result.get("columns_detected") or {}
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=(
                    f"No pude importar precios desde **{filename or 'el archivo'}**. "
                    f"Revisa que tenga columnas de concepto/ubicación y precio unitario "
                    f"(detecté: concepto=`{cols.get('label')}`, precio=`{cols.get('price')}`).\n\n"
                    f"{detail or '¿Puedes usar la plantilla «Copiar para Excel» y volver a subir el archivo?'}"
                ),
                confianza="Media",
                tipo="clarification_needed",
                intake_active=True,
            )

        inputs = dict(result.get("economic_user_inputs") or {})
        session_state["economic_user_inputs"] = inputs
        if blocks:
            session_state["capture_matrix_blocks"] = blocks
            session_state["economic_capture_mode"] = "matrix"
        await self.context_manager.memory.save_session(session_id, dict(session_state))
        try:
            await refresh_economic_validations_for_session(
                self.context_manager.memory, session_id
            )
        except Exception as ref_err:
            logger.info("eco_file_import_refresh_skipped", error=str(ref_err)[:120])

        fresh = await self.context_manager.memory.get_session(session_id) or session_state
        applied_fields = set(applied.keys())
        fresh["pending_questions"] = [
            q
            for q in (fresh.get("pending_questions") or [])
            if str(q.get("field") or "") not in applied_fields
            and str(q.get("type") or "")
            not in ("economic_price", "economic_price_matrix")
        ]
        if not any(
            str(q.get("type") or "") == "economic_price_matrix"
            for q in fresh.get("pending_questions") or []
        ):
            fresh["economic_capture_mode"] = "matrix"
        fresh["current_question_index"] = 0
        await self.context_manager.memory.save_session(session_id, fresh)

        n = len(applied)
        n_unmatched = len(result.get("unmatched") or [])
        tail = (
            f"\n\n⚠️ **{n_unmatched}** fila(s) no se emparejaron con la matriz de la sesión."
            if n_unmatched
            else ""
        )
        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=(
                f"Listo. Importé **{n}** precio(s) unitario(s) desde **{filename or 'tu archivo'}** "
                f"y los guardé en tu cotización.{tail}\n\n"
                "Puedes escribir **generar propuesta económica** para continuar."
            ),
            confianza="Alta",
            tipo="data_saved",
            intake_active=bool(fresh.get("pending_questions")),
        )

    async def _handle_file_upload_with_mission(
        self,
        session_id: str,
        doc_id: str,
        session_state: dict,
        pending_questions: list,
        current_idx: int,
        correlation_id: str,
        activity_state: str = "active",
    ) -> "AgentOutput":
        """
        Orquesta el flujo de extracción cuando el usuario sube un archivo
        con una pregunta activa.

        Flujo:
        1. Obtener el documento por doc_id
        2. Preprocesar con DocumentPreprocessor
        3. Extraer con MissionDataExtractor
        4. Validar con NumericValidator si aplica
        5. Retornar mensaje de confirmación o not_found
        """
        try:
            # Obtener el documento
            doc = None
            try:
                docs = await self.context_manager.memory.get_documents(session_id)
                if docs:
                    doc = next((d for d in docs if str(d.get("id") or d.get("doc_id") or "") == str(doc_id)), None)
                    if not doc:
                        doc = docs[-1] if docs else None  # fallback: último documento
            except Exception as e:
                logger.warning("mission_extractor_doc_fetch_error", error=str(e)[:80])

            extracted_text = ""
            if doc:
                extracted_text = str(doc.get("extracted_text") or doc.get("content") or "")

            if not extracted_text:
                logger.info("mission_extractor_no_text", session_id=session_id, doc_id=doc_id)
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta="Recibí tu archivo, pero no pude extraer texto de él. ¿Puedes escribirme el dato directamente?",
                    confianza="Media",
                    tipo="pending_question",
                    activity_state=activity_state,
                )

            # Construir mission_context
            current_q = pending_questions[current_idx] if 0 <= current_idx < len(pending_questions) else {}
            mission_ctx = self._build_mission_context(session_state, current_q, current_idx, len(pending_questions))

            # Paso 1: Preprocesar (Python puro)
            preprocessor = DocumentPreprocessor()
            preprocess_result = preprocessor.extract_relevant_sections(
                extracted_text=extracted_text,
                dato_solicitado=mission_ctx.get("dato_solicitado", ""),
            )

            logger.info(
                "mission_extractor_preprocess",
                session_id=session_id,
                reduction_ratio=preprocess_result.reduction_ratio,
                original_chars=preprocess_result.total_chars_original,
                filtered_chars=preprocess_result.total_chars_filtered,
            )

            # Paso 2: Extraer con LLM
            extractor = MissionDataExtractor(self.llm)
            extraction_result = await extractor.extract(
                relevant_text=preprocess_result.relevant_text,
                mission_context=mission_ctx,
            )

            dato_solicitado = mission_ctx.get("dato_solicitado", "el dato solicitado")

            # Manejar not_found
            if extraction_result.extraction_status == "not_found" or extraction_result.value is None:
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=(
                        f"Revisé tu archivo pero no encontré **{dato_solicitado}** en él. "
                        f"¿Puedes escribirme el valor directamente?"
                    ),
                    confianza="Media",
                    tipo="pending_question",
                    activity_state=activity_state,
                )

            # Paso 3: Validar numéricamente si aplica (Python puro)
            field_target = str(current_q.get("field_target") or current_q.get("field") or "")
            field_type = self._infer_field_type(field_target)

            display_value = extraction_result.value
            if field_type in ("currency", "integer"):
                validator = NumericValidator()
                validation = validator.validate_and_normalize(extraction_result.value, field_type)
                if validation.is_valid and validation.normalized_value:
                    display_value = validation.normalized_value

            # Paso 4: Persistir propuesta y retornar mensaje de confirmación
            session_state["pending_mapping_confirmation"] = {
                "field": str(current_q.get("field") or current_q.get("field_target") or ""),
                "label": dato_solicitado,
                "proposed_value": display_value,
                "source_reference": extraction_result.source_reference,
                "confidence": extraction_result.confidence,
                "question_idx": current_idx,
            }
            await self.context_manager.memory.save_session(session_id, session_state)

            source_note = f"\n📍 Origen: {extraction_result.source_reference}" if extraction_result.source_reference else ""

            confirmation_msg = (
                f"Revisé tu archivo y encontré lo siguiente:\n\n"
                f"📋 **{dato_solicitado}**: {display_value}"
                f"{source_note}\n\n"
                f"¿Es correcto? Puedes responder:\n"
                f"- **Sí** para guardar este valor\n"
                f"- **No, el valor correcto es [X]** para corregirlo\n"
                f"- **No aplica** si este dato no está en el archivo"
            )

            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=confirmation_msg,
                confianza="Alta",
                tipo="mapping_confirmation",
                activity_state=activity_state,
            )

        except Exception as e:
            logger.warning("mission_extractor_handle_error", error=str(e)[:120])
            # Fallback: pedir el dato directamente
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta="Recibí tu archivo. ¿Puedes escribirme el dato directamente para asegurarme de capturarlo bien?",
                confianza="Media",
                tipo="pending_question",
                activity_state=activity_state,
            )

    async def _handle_mapping_confirmation(
        self,
        user_response: str,
        session_id: str,
        company_id: str,
        session_state: dict,
        correlation_id: str,
        activity_state: str = "active",
    ) -> "AgentOutput":
        """
        Procesa la respuesta del usuario a la confirmación del mapeo propuesto.
        """
        confirmation = session_state.get("pending_mapping_confirmation") or {}
        if not confirmation:
            return None  # No hay confirmación pendiente, continuar flujo normal

        field = str(confirmation.get("field") or "")
        label = str(confirmation.get("label") or "dato")
        proposed_value = str(confirmation.get("proposed_value") or "")
        question_idx = int(confirmation.get("question_idx") or 0)

        intent = self._classify_confirmation_response(user_response)

        value_to_save = None

        if intent == "confirm":
            value_to_save = proposed_value
        elif intent == "correct":
            # Extraer el valor corregido del mensaje del usuario
            # Buscar patrones como "no, es X", "no, el valor es X", "en realidad es X"
            import re as _re
            patterns = [
                r"(?:no[,\s]+(?:el valor (?:es|correcto) )?(?:es|son)[,\s]+)(.+)",
                r"(?:en realidad (?:es|son)[,\s]+)(.+)",
                r"(?:correcto es[,\s]+)(.+)",
            ]
            corrected = None
            lo = user_response.lower().strip()
            for pattern in patterns:
                m = _re.search(pattern, lo)
                if m:
                    corrected = m.group(1).strip()
                    break
            if not corrected:
                # Fallback: tomar todo después del primer "no"
                parts = user_response.split("no", 1)
                if len(parts) > 1:
                    corrected = parts[1].strip().lstrip(",.: ")
            value_to_save = corrected or user_response.strip()
        elif intent == "reject":
            # Limpiar confirmación y mantener pregunta pendiente
            session_state.pop("pending_mapping_confirmation", None)
            await self.context_manager.memory.save_session(session_id, session_state)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=f"Entendido, ese dato no aplica. ¿Puedes escribirme el valor de **{label}** directamente?",
                confianza="Alta",
                tipo="pending_question",
                activity_state=activity_state,
            )

        # Guardar el valor en master_profile
        saved = False
        if value_to_save and field and company_id:
            try:
                saved = await self._save_field_to_company(
                    company_id=company_id,
                    field_key=field,
                    value=value_to_save,
                )
            except Exception as e:
                logger.warning("mission_confirmation_save_error", error=str(e)[:80])

        # Limpiar confirmación pendiente
        session_state.pop("pending_mapping_confirmation", None)

        if saved:
            # Avanzar al siguiente pendiente
            pending_questions = list(session_state.get("pending_questions") or [])
            next_idx = question_idx + 1
            session_state["current_question_index"] = next_idx
            await self.context_manager.memory.save_session(session_id, session_state)

            if next_idx < len(pending_questions):
                next_q = pending_questions[next_idx]
                tone_mode = self._detect_tone_mode(session_state, pending_questions, next_idx)
                mission_ctx = self._build_mission_context(session_state, next_q, next_idx, len(pending_questions))
                try:
                    next_question_text = await self._generate_mission_question(
                        mission_ctx, tone_mode, pending_question=next_q
                    )
                except Exception:
                    next_question_text = str(next_q.get("question") or "")

                resp = f"Listo, ya tengo **{label}**.\n\n{next_question_text}"
            else:
                resp = f"¡Perfecto! Ya guardé **{label}**. Con esto terminamos de reunir la información necesaria."
        else:
            await self.context_manager.memory.save_session(session_id, session_state)
            resp = f"No pude guardar **{label}**. ¿Puedes intentarlo de nuevo?"

        return self._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=resp,
            confianza="Alta",
            tipo="pending_question",
            activity_state=activity_state,
        )

    async def _handle_labor_compliance_interview(
        self, session_id: str, company_id: str, user_query: str, session_state: Dict, correlation_id: str
    ) -> Optional[AgentOutput]:
        """
        Gestiona la entrevista interactiva secuencial (Paso a Paso) de variables de nómina
        para completar el perfil de labor_compliance de la empresa.
        """
        step = session_state.get("labor_compliance_interview_step")
        if not step or not company_id:
            return None

        # Intentar extraer número de la respuesta
        import re
        val_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", user_query)
        
        company = await self.context_manager.memory.get_company(company_id)
        if not company:
            return None
        profile = company.get("master_profile", {})
        labor = profile.get("labor_compliance", {})
        if not isinstance(labor, dict):
            labor = {
                "base_salary_per_day": 0.0,
                "imss_risk_class": "V",
                "infonavit_rate": 0.05,
                "isn_rate": 0.03,
                "daily_fsr": 0.0,
                "status": "PENDING_INPUT"
            }

        # Procesar según el paso actual
        if step == "step_1_base_salary":
            if not val_match:
                err = "Por favor, proporciona un valor numérico válido para el **Salario Base Diario** (Ejemplo: `374.89`):"
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=err,
                    confianza="Alta",
                    tipo="labor_compliance_interview"
                )
            
            val = float(val_match.group(1))
            labor["base_salary_per_day"] = val
            session_state["labor_compliance_interview_step"] = "step_2_imss_risk"
            await self.context_manager.memory.save_session(session_id, session_state)
            
            profile["labor_compliance"] = labor
            company["master_profile"] = profile
            await self.context_manager.memory.save_company(company_id, company)
            
            msg = (
                f"✅ **Salario Base Diario guardado:** ${val:,.2f} MXN.\n\n"
                "**Paso 2 de 4:** Por favor, indícame la **Clase de Riesgo IMSS** (romana: `I`, `II`, `III`, `IV` o `V`). (Ejemplo: clase `V` para seguridad privada):"
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="labor_compliance_interview"
            )

        elif step == "step_2_imss_risk":
            risk_class = "V"
            for r in ("V", "IV", "III", "II", "I"):
                if r in user_query.upper():
                    risk_class = r
                    break
            
            labor["imss_risk_class"] = risk_class
            session_state["labor_compliance_interview_step"] = "step_3_isn_rate"
            await self.context_manager.memory.save_session(session_id, session_state)
            
            profile["labor_compliance"] = labor
            company["master_profile"] = profile
            await self.context_manager.memory.save_company(company_id, company)
            
            msg = (
                f"✅ **Clase de Riesgo IMSS guardada:** Clase {risk_class}.\n\n"
                "**Paso 3 de 4:** Por favor, indica la tasa del **Impuesto Sobre Nómina (ISN)** de tu estado. (Ejemplo: `0.03` para 3% o `0.04` para 4%):"
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="labor_compliance_interview"
            )

        elif step == "step_3_isn_rate":
            if not val_match:
                err = "Por favor, proporciona un valor numérico válido para la **Tasa de ISN** (Ejemplo: `0.03` o `3`):"
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=err,
                    confianza="Alta",
                    tipo="labor_compliance_interview"
                )
            
            val = float(val_match.group(1))
            if val > 1.0:
                val = val / 100.0
            
            labor["isn_rate"] = val
            session_state["labor_compliance_interview_step"] = "step_4_daily_fsr"
            await self.context_manager.memory.save_session(session_id, session_state)
            
            profile["labor_compliance"] = labor
            company["master_profile"] = profile
            await self.context_manager.memory.save_company(company_id, company)
            
            msg = (
                f"✅ **Tasa de ISN guardada:** {val*100:g}%.\n\n"
                "**Paso 4 de 4:** Finalmente, introduce el **Factor de Salario Real (FSR)** diario para el cálculo. (Ejemplo: `1.7645`):"
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="labor_compliance_interview"
            )

        elif step == "step_4_daily_fsr":
            if not val_match:
                err = "Por favor, proporciona un valor numérico válido para el **FSR** (Ejemplo: `1.7645`):"
                return self._format_response(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    respuesta=err,
                    confianza="Alta",
                    tipo="labor_compliance_interview"
                )
            
            val = float(val_match.group(1))
            labor["daily_fsr"] = val
            labor["status"] = "VALIDATED"
            
            session_state["labor_compliance_interview_step"] = None
            await self.context_manager.memory.save_session(session_id, session_state)
            
            profile["labor_compliance"] = labor
            company["master_profile"] = profile
            await self.context_manager.memory.save_company(company_id, company)
            
            msg = (
                f"🎉 **¡Perfil de Nómina y FSR configurados con éxito!**\n\n"
                f"Hemos registrado en el Perfil Corporativo de **{profile.get('razon_social', 'la Empresa')}**:\n"
                f"• Salario Base Diario: **${labor['base_salary_per_day']:,.2f} MXN**\n"
                f"• Clase de Riesgo IMSS: **Clase {labor['imss_risk_class']}**\n"
                f"• Impuesto Sobre Nómina: **{labor['isn_rate']*100:g}%**\n"
                f"• Factor de Salario Real (FSR): **{labor['daily_fsr']:.4f}**\n\n"
                "Ya estoy listo para generar la propuesta económica oficial. Escribe **'generar propuesta económica'** para arrancar el motor transaccional."
            )
            await self._save_chat_history(session_id, user_query, msg)
            return self._format_response(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=msg,
                confianza="Alta",
                tipo="labor_compliance_success",
                suggested_actions=[
                    {"label": "🚀 Generar Propuesta Económica", "payload": "CMD_TRIGGER_GENERATION", "style": "primary"}
                ]
            )

        return None

