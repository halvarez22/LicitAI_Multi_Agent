import json
import logging
import os
import re
import unicodedata
from typing import Any, Dict, Final, List, Set, Tuple
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.core.observability import get_logger, agent_span
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.services.confidence_scorer import ConfidenceScorer
from app.services.experience_store import ExperienceStore
from app.services.analyst_output_normalize import (
    detect_tabular_reference_signals,
    normalize_alcance_operativo_list,
    normalize_reglas_economicas_dict,
)
from app.config.settings import settings

# Logger estructurado
logger = get_logger(__name__)

# Feature flag para contratos estrictos
STRICT_CONTRACTS = os.getenv("LICITAI_STRICT_CONTRACTS", "false").lower() == "true"

# Claves canónicas del cronograma (orden típico de procedimiento; sin datos de licitaciones concretas).
_CRONOGRAMA_KEYS: Final[Tuple[str, ...]] = (
    "publicacion_convocatoria",
    "visita_instalaciones",
    "junta_aclaraciones",
    "presentacion_proposiciones",
    "fallo",
    "firma_contrato",
)

# Sinónimos frecuentes que devuelve el LLM → clave canónica (genéricos, no expediente-específicos).
_CRONOGRAMA_ALIASES: Final[Dict[str, str]] = {
    "publicacion": "publicacion_convocatoria",
    "publicacion_de_la_convocatoria": "publicacion_convocatoria",
    "publicacion_convocatoria": "publicacion_convocatoria",
    "visita": "visita_instalaciones",
    "visita_a_instalaciones": "visita_instalaciones",
    "visita_instalaciones": "visita_instalaciones",
    "firma": "firma_contrato",
    "firma_del_contrato": "firma_contrato",
    "firma_contrato": "firma_contrato",
}


def _normalize_cronograma_key(key: str) -> str:
    """Pasa una clave JSON a forma comparable (minúsculas, sin acentos, guiones→underscore)."""
    nk = unicodedata.normalize("NFD", key.strip())
    nk = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    return nk.lower().replace("-", "_").replace(" ", "_")


def _coerce_cronograma_value(val: Any, default: str) -> str:
    """Convierte el valor del LLM a cadena legible o default si viene vacío."""
    if val is None:
        return default
    if isinstance(val, str):
        s = val.strip()
        return s if s else default
    if isinstance(val, (int, float, bool)):
        return str(val)
    try:
        s = json.dumps(val, ensure_ascii=False)
        return s if s and s != "null" else default
    except (TypeError, ValueError):
        return default


def normalize_cronograma_dict(raw: Any) -> Dict[str, str]:
    """
    Unifica el objeto cronograma del analista: mismas claves en todo expediente,
    relleno con 'No especificado' si el texto no lo menciona. Acepta alias comunes del modelo.
    """
    default = "No especificado"
    out: Dict[str, str] = {k: default for k in _CRONOGRAMA_KEYS}
    if not isinstance(raw, dict):
        return out
    for raw_key, val in raw.items():
        if not isinstance(raw_key, str):
            continue
        nk = _normalize_cronograma_key(raw_key)
        canon = _CRONOGRAMA_ALIASES.get(nk)
        if canon is None and nk in _CRONOGRAMA_KEYS:
            canon = nk
        if canon is None or canon not in out:
            continue
        coerced = _coerce_cronograma_value(val, default)
        if coerced != default or out[canon] == default:
            out[canon] = coerced
    return out


def normalize_requisitos_participacion_list(raw: Any) -> List[Dict[str, str]]:
    """
    Normaliza la lista de requisitos para participar: objetos con inciso opcional y texto literal.
    Acepta strings sueltos o dicts con alias frecuentes del LLM. Sin contenido de expedientes fijos.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [{"inciso": "", "texto_literal": s}] if s else []
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for item in raw:
        if isinstance(item, str):
            s = item.strip()
            if not s:
                continue
            key = s.lower()[:800]
            if key in seen:
                continue
            seen.add(key)
            out.append({"inciso": "", "texto_literal": s})
            continue
        if not isinstance(item, dict):
            continue
        inc = item.get("inciso") or item.get("letra") or item.get("item") or ""
        if not isinstance(inc, str):
            inc = str(inc).strip() if inc is not None else ""
        else:
            inc = inc.strip()
        txt = (
            item.get("texto_literal")
            or item.get("texto")
            or item.get("snippet")
            or item.get("descripcion")
            or item.get("requirement")
        )
        if txt is None:
            continue
        if not isinstance(txt, str):
            txt = str(txt).strip()
        else:
            txt = txt.strip()
        if not txt:
            continue
        key = txt.lower()[:800]
        if key in seen:
            continue
        seen.add(key)
        out.append({"inciso": inc, "texto_literal": txt})
    return out


class AnalystAgent(BaseAgent):
    """
    Agente 1: Analista de Bases
    Experto en extracción y análisis de requisitos de licitación a partir del OCR.
    Realiza un descubrimiento multidimensional (Fechas, Requisitos, Evaluación).
    
    Fase 0 Hardening: Resiliencia LLM y Observabilidad.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="analyst_001",
            name="Analista de Bases",
            description="Extrae cronograma, participación, reglas económicas, alcance operativo, garantías y datos tabulares.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()
        self.confidence_scorer = ConfidenceScorer(
            threshold_default=settings.CONFIDENCE_THRESHOLD_DEFAULT,
            threshold_critical=settings.CONFIDENCE_THRESHOLD_CRITICAL
        )
        self.experience_store = ExperienceStore()

    async def _build_datos_tabulares(self, session_id: str, context_str: str) -> Dict[str, Any]:
        """
        Contrasta señales en texto (bases + extractos) con filas persistidas en session_line_items.
        No usa datos de un expediente fijo: solo heurísticas y lectura de BD.
        """
        parts: List[str] = [context_str or ""]
        try:
            docs = await self.context_manager.memory.get_documents(session_id)
            for d in docs or []:
                if not isinstance(d, dict):
                    continue
                c = d.get("content")
                if isinstance(c, dict):
                    et = c.get("extracted_text")
                    if isinstance(et, str) and et.strip():
                        parts.append(et[:150000])
        except Exception as e:
            logger.debug("datos_tabulares_docs_skip", session_id=session_id, error=str(e))
        fused = "\n".join(parts)
        sig = detect_tabular_reference_signals(fused)
        n_li = 0
        try:
            rows = await self.context_manager.memory.get_line_items_for_session(session_id)
            n_li = len(rows or [])
        except Exception as e:
            logger.warning("get_line_items_failed", session_id=session_id, error=str(e))
            n_li = -1
        alerta = None
        if sig["texto_sugiere_partidas_o_anexo_tabular"] and n_li == 0:
            alerta = (
                "Las bases parecen remitir a partidas o anexos tabulares; no hay filas en "
                "session_line_items. Ingerir y reprocesar el Excel u hoja de partidas asociada."
            )
        elif n_li < 0:
            alerta = "No se pudo consultar session_line_items en la base de datos."
        return {
            "line_items_count": n_li,
            "texto_sugiere_partidas_o_anexo_tabular": sig["texto_sugiere_partidas_o_anexo_tabular"],
            "senal_tabular_coincidencias": sig.get("coincidencias_aproximadas", 0),
            "alerta_faltante": alerta,
        }

    def _infer_periodo_minimo_from_context(self, context_str: str) -> str:
        """Fallback determinista para meses mínimos cuando no quedan explícitos en el JSON del LLM."""
        txt = context_str or ""
        for pat in (
            r"(?i)(?:periodo base|mínimo cotizable|plazo mínimo|periodo mínimo).*?(\d{1,2})\s*mes(?:es)?",
            r"(?i)importe mínimo.*?(?:para|de)\s*(\d{1,2})\s*mes(?:es)?",
        ):
            m = re.search(pat, txt)
            if m:
                return f"{m.group(1)} meses"
        return "No especificado"

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        """
        Extrae la información clave de los textos procesados usando el LLM.
        """
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        
        async with agent_span(logger, self.agent_id, session_id, correlation_id):
            # 1. Recuperar contexto Multidimensional
            print(f"  🔍 Analista: Iniciando Descubrimiento Multinivel...")
            
            # Búsqueda 1: Estructura y Fechas (incluye hitos frecuentes en bases mexicanas y otras convocatorias).
            search_dates = await self.smart_search(
                session_id,
                "plazos del procedimiento calendario cronograma publicación convocatoria visita instalaciones "
                "junta aclaraciones presentación apertura proposiciones fallo firma contrato acto",
                n_results=10,
                vector_db=self.vector_db,
            )
            
            # Búsqueda 2: Participación / elegibilidad (apartados tipo “requisitos para participar”, incisos a) b)…)
            search_participacion = await self.smart_search(
                session_id,
                "requisitos para participar en la licitación elegibilidad licitantes obligaciones "
                "declaración integridad nacionalidad mexicana personalidad jurídica capacidad jurídica "
                "certificado digital firma electrónica CompraNet acuse recibo propuesta técnica económica "
                "conocer las bases convocatoria anexos",
                n_results=12,
                vector_db=self.vector_db,
            )
            # Búsqueda 3: Exclusión, descalificación y documentación formal (no duplicar el checklist de participación)
            search_reqs = await self.smart_search(
                session_id,
                "causas exclusión descalificación inhabilitación impedimento rechazo de propuestas "
                "documentación administrativa técnica formalidades entrega incumplimiento sanciones",
                n_results=10,
                vector_db=self.vector_db,
            )
            # Búsqueda 4: Marco económico de oferta (importes, meses, partidas, anexos, contrato)
            search_economico = await self.smart_search(
                session_id,
                "importe mínimo máximo meses contrato abierto cerrado partidas anexo presupuesto "
                "propuesta económica suma licitación adjudicación precios cantidades asignación por partida",
                n_results=12,
                vector_db=self.vector_db,
            )
            # Búsqueda 5: Alcance operativo / dotación (tablas descripción unidad cantidad turnos áreas)
            search_alcance = await self.smart_search(
                session_id,
                "descripción unidad cantidad turno horario dotación personal elementos área asignada "
                "días laborables jornada servicio a contratar vigilancia unidades requeridas",
                n_results=12,
                vector_db=self.vector_db,
            )
            # Búsqueda 6: Evaluación y Garantías
            search_eval = await self.smart_search(session_id, "criterios de evaluacion puntos y porcentajes binario garantias cumplimiento seriedad", n_results=10, vector_db=self.vector_db)
            
            context_str = "\n\n=== SECCIÓN FECHAS ===\n" + search_dates
            context_str += "\n\n=== SECCIÓN PARTICIPACIÓN (elegibilidad y obligaciones para licitar) ===\n" + search_participacion
            context_str += "\n\n=== SECCIÓN FILTROS EXCLUSIÓN Y DOCUMENTACIÓN ===\n" + search_reqs
            context_str += "\n\n=== SECCIÓN ECONÓMICA Y PARTIDAS ===\n" + search_economico
            context_str += "\n\n=== SECCIÓN ALCANCE OPERATIVO (TABLAS / DOTACIÓN) ===\n" + search_alcance
            context_str += "\n\n=== SECCIÓN EVALUACIÓN ===\n" + search_eval

            # --- FASE 5: Capa de Experiencia ---
            exp_context = ""
            if settings.EXPERIENCE_LAYER_ENABLED:
                # Búsqueda semántica de casos similares basada en requisitos extraídos de la búsqueda
                similar_cases = await self.experience_store.find_similar(
                    query_text=(search_participacion + "\n" + search_reqs + "\n" + search_economico)[:8000],
                    top_k=settings.EXPERIENCE_TOP_K,
                )
                
                if similar_cases and not similar_cases[0].session_id == "none":
                    exp_lines = []
                    for c in similar_cases:
                        exp_lines.append(f"- Caso {c.session_id} ({c.outcome}): {c.summary[:200]}...")
                    
                    exp_context = "\n\n=== CONTEXTO EXPERIENCIA (Casos Similares) ===\n"
                    exp_context += "Los siguientes casos pasados podrían ser relevantes para alertas de riesgo:\n"
                    exp_context += "\n".join(exp_lines)
                    
                    logger.info("experience_retrieved", agent=self.agent_id, session_id=session_id, count=len(similar_cases))
                
                if settings.EXPERIENCE_SHADOW_MODE:
                    # En modo shadow solo logueamos, no inyectamos
                    logger.info("experience_shadow_mode", session_id=session_id, context_len=len(exp_context))
                    exp_context = ""
                elif not settings.EXPERIENCE_PROMPT_INJECTION:
                    exp_context = ""
            
            context_str += exp_context

            # Truncamiento de seguridad operativa para 8GB VRAM
            context_str = self._truncate_context_for_llm(context_str, max_tokens=16000)
            
            if len(context_str.strip()) < 500:
                logger.warning("context_insufficient", session_id=session_id, chars=len(context_str))
                return {
                    "status": "error", 
                    "message": "Contexto insuficiente para un análisis serio. Verifica que los documentos hayan sido ingeridos correctamente."
                }

            # 2. Construir Prompt Forense
            system_prompt = (
                "Eres un experto ANALISTA FORENSE de licitaciones. Tu misión es extraer la VERDAD literal del documento.\n"
                "REGLAS DE ORO:\n"
                "1. SI NO ESTÁ, NO EXISTE: Si un dato no aparece en el texto, responde 'No especificado'. JAMÁS inventes.\n"
                "2. CERO ALUCINACIONES: No uses conocimientos previos. Solo lo que dice este texto.\n"
                "3. LITERALIDAD TÉCNICA: Extrae requisitos como acciones completas y directas.\n"
                "4. Responde ÚNICAMENTE en JSON válido."
            )
            
            prompt = f"""Analiza estos extractos de bases de licitación y genera el dictamen estructurado.

EXTRACTOS TÉCNICOS:
{context_str}

TAREA:
1. cronograma: Del texto, extrae fecha y hora (y lugar/medio si vienen en la misma fila o párrafo) para cada hito
   que aparezca. Usa EXACTAMENTE estas claves en snake_case (string cada una; si no consta en el texto, "No especificado"):
   - publicacion_convocatoria (publicación de convocatoria / aviso en DOF, CompraNet, etc.)
   - visita_instalaciones (visita al sitio, recorrido, reunión en instalaciones, cuando aplique)
   - junta_aclaraciones
   - presentacion_proposiciones (presentación y apertura de proposiciones si van unidos; si el texto los separa, resume en un solo string fiel al documento)
   - fallo
   - firma_contrato (o celebración del contrato si así se denomina el evento)
2. requisitos_participacion: Lista de OBJETOS, uno por cada obligación de participación o elegibilidad que aparezca
   en SECCIÓN PARTICIPACIÓN (o equivalente en el texto), fiel al documento. Cada objeto:
   {{"inciso": "a" o "b" o "" si no hay letra, "texto_literal": "cita o resumen fiel del requisito" }}.
   Incluye incisos a), b), c)… cuando existan. NO listes aquí causas genéricas de descalificación: eso va en requisitos_filtro.
   Si no hay texto sobre participación en los extractos, usa [].
3. requisitos_filtro: Lista de strings: solo causas EXPLÍCITAS de exclusión, descalificación, rechazo o impedimento
   para participar que el documento enuncie como tal (no repitas el mismo contenido de requisitos_participacion).
   Si no hay ninguna enunciación clara, [].
4. garantias: Montos o porcentajes de Seriedad y Cumplimiento.
5. criterios_evaluacion: Determina si es Puntos y Porcentajes, Binario, o Costo Menor.
6. reglas_economicas: Objeto con EXACTAMENTE estas claves (string cada una; si no consta en extractos, "No especificado"):
   - referencia_partidas_anexos_citados (p. ej. asignación por partida, cantidades en anexo N)
   - criterio_importe_minimo_o_plazo_inferior (p. ej. importe mínimo de propuesta, suma para N meses)
   - criterio_importe_maximo_o_plazo_superior (p. ej. importe máximo, otro horizonte de meses)
   - meses_o_periodo_minimo_citado
   - meses_o_periodo_maximo_citado
   - modalidad_contratacion_observada (p. ej. contrato abierto, cerrado, si el texto lo dice)
   - vinculacion_presupuesto_partida (concordancia con presupuesto disponible por partida, si aplica)
   - otras_reglas_oferta_precio (cualquier otra regla literal sobre oferta económica)
7. alcance_operativo: Lista de OBJETOS, una fila por cada renglón sustantivo de tablas tipo descripción/unidad/cantidad,
   turnos, áreas, dotación (SECCIÓN ALCANCE). Cada objeto con claves (vacío "" si no aplica en esa fila):
   ubicacion_o_area, puesto_funcion_o_servicio, turno, horario, cantidad_o_elementos, dias_aplicables, texto_literal_fila.
   Si no hay tabla en los extractos, [].

Responde con este JSON:
{{
  "cronograma": {{
    "publicacion_convocatoria": "...",
    "visita_instalaciones": "...",
    "junta_aclaraciones": "...",
    "presentacion_proposiciones": "...",
    "fallo": "...",
    "firma_contrato": "..."
  }},
  "requisitos_participacion": [{{"inciso": "a", "texto_literal": "..."}}, {{"inciso": "", "texto_literal": "..."}}],
  "requisitos_filtro": ["causa de exclusión 1"],
  "garantias": {{"seriedad_oferta": "...", "cumplimiento": "..."}},
  "criterios_evaluacion": "...",
  "reglas_economicas": {{
    "referencia_partidas_anexos_citados": "...",
    "criterio_importe_minimo_o_plazo_inferior": "...",
    "criterio_importe_maximo_o_plazo_superior": "...",
    "meses_o_periodo_minimo_citado": "...",
    "meses_o_periodo_maximo_citado": "...",
    "modalidad_contratacion_observada": "...",
    "vinculacion_presupuesto_partida": "...",
    "otras_reglas_oferta_precio": "..."
  }},
  "alcance_operativo": [
    {{
      "ubicacion_o_area": "",
      "puesto_funcion_o_servicio": "",
      "turno": "",
      "horario": "",
      "cantidad_o_elementos": "",
      "dias_aplicables": "",
      "texto_literal_fila": "..."
    }}
  ]
}}
"""

            # 3. Llamada al LLM con Resiliencia
            llm_res = await self.llm.generate(
                prompt=prompt, 
                system_prompt=system_prompt, 
                format="json",
                correlation_id=correlation_id
            )
            
            if not llm_res.success:
                logger.error("llm_generation_failed", agent=self.agent_id, error=llm_res.error)
                return {"status": "error", "message": llm_res.error}

            raw_content = llm_res.response
            
            # Limpieza de Fences Markdown
            if "```json" in raw_content:
                raw_content = raw_content.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_content:
                raw_content = raw_content.split("```")[1].split("```")[0].strip()

            # 4. Parsing y Gestión de Estados
            status = AgentStatus.SUCCESS
            try:
                extracted_data = json.loads(raw_content)
                if "cronograma" in extracted_data:
                    extracted_data["cronograma"] = normalize_cronograma_dict(extracted_data.get("cronograma"))
                if "requisitos_participacion" in extracted_data:
                    extracted_data["requisitos_participacion"] = normalize_requisitos_participacion_list(
                        extracted_data.get("requisitos_participacion")
                    )
                if "reglas_economicas" in extracted_data:
                    extracted_data["reglas_economicas"] = normalize_reglas_economicas_dict(
                        extracted_data.get("reglas_economicas")
                    )
                    reglas = extracted_data.get("reglas_economicas") or {}
                    if isinstance(reglas, dict) and reglas.get("meses_o_periodo_minimo_citado") == "No especificado":
                        reglas["meses_o_periodo_minimo_citado"] = self._infer_periodo_minimo_from_context(context_str)
                if "alcance_operativo" in extracted_data:
                    extracted_data["alcance_operativo"] = normalize_alcance_operativo_list(
                        extracted_data.get("alcance_operativo")
                    )
                # Validación de esquema mínimo
                _req_keys = (
                    "cronograma",
                    "requisitos_participacion",
                    "requisitos_filtro",
                    "garantias",
                    "criterios_evaluacion",
                    "reglas_economicas",
                    "alcance_operativo",
                )
                if not all(k in extracted_data for k in _req_keys):
                    logger.warning("json_incomplete", agent=self.agent_id, session_id=session_id)
                    status = AgentStatus.PARTIAL
            except Exception as e:
                logger.error("json_parse_error", agent=self.agent_id, error=str(e))
                extracted_data = {"error": "Error al parsear respuesta del LLM", "raw": raw_content}
                status = AgentStatus.PARTIAL

            try:
                tabular_info = await self._build_datos_tabulares(session_id, context_str)
            except Exception as e:
                logger.warning("build_datos_tabulares_failed", session_id=session_id, error=str(e))
                tabular_info = {
                    "line_items_count": -1,
                    "texto_sugiere_partidas_o_anexo_tabular": False,
                    "senal_tabular_coincidencias": 0,
                    "alerta_faltante": "No se pudo evaluar datos tabulares.",
                }
            if isinstance(extracted_data, dict):
                extracted_data["datos_tabulares"] = tabular_info

            # --- FASE 1: Cálculo de Confianza ---
            confidence_obj = None
            if settings.CONFIDENCE_ENABLED or settings.CONFIDENCE_SHADOW_MODE:
                # Bloques críticos para scoring: participación, filtros, reglas económicas y alcance
                reqs_text = (
                    str(extracted_data.get("requisitos_participacion", ""))
                    + "\n"
                    + str(extracted_data.get("requisitos_filtro", ""))
                    + "\n"
                    + str(extracted_data.get("reglas_economicas", ""))
                    + "\n"
                    + str(extracted_data.get("alcance_operativo", ""))
                )
                confidence_obj = self.confidence_scorer.calculate_extraction_confidence(
                    extracted_text=reqs_text,
                    source_context=context_str,
                    llm_raw_output=llm_res.response,
                    is_critical=True
                )
                
                # Enriquecer data con metadatos de confianza (Requisito de Fase 1)
                extracted_data["confidence"] = confidence_obj.model_dump()
                extracted_data["unknowns"] = confidence_obj.unknowns
                extracted_data["ambiguities"] = confidence_obj.ambiguities
                
                # Log estructurado (Observabilidad Fase 1)
                logger.info(
                    "confidence_score_calculated",
                    agent_id=self.agent_id,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    overall=confidence_obj.overall,
                    recommendation=confidence_obj.recommendation.value,
                    is_critical=True
                )

                # Si NO estamos en shadow mode y el score es REJECT, podríamos degradar status
                if settings.CONFIDENCE_ENABLED and not settings.CONFIDENCE_SHADOW_MODE:
                    if confidence_obj.recommendation == "reject":
                        status = AgentStatus.PARTIAL # O FAIL según política

            # 5. Persistencia MCP
            await self.save_state(session_id, {"last_analysis": extracted_data, "status": status.value})
            await self.context_manager.record_task_completion(
                session_id=session_id,
                task_name="analisis_bases",
                result=extracted_data
            )

            # Preparar salida (Contract-ready)
            output = AgentOutput(
                status=status,
                agent_id=self.agent_id,
                session_id=session_id,
                data=extracted_data,
                correlation_id=correlation_id,
                processing_time_sec=0.0 # Placeholder
            )

            return output
