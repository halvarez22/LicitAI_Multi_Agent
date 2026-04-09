import os
import re
import json
import hashlib
import time
import unicodedata
import asyncio
from typing import Any, Dict, List, Tuple, Optional
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.core.observability import get_logger, agent_span
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.services.confidence_scorer import ConfidenceScorer
from app.services.experience_store import ExperienceStore
from app.services.job_service import update_job_status
from app.config.settings import settings

# Logger estructurado
logger = get_logger(__name__)
_C01_SEMANTIC_PATTERN = re.compile(
    r"(?i)(motivo de descalif|causa de desech|se desech|exclusi[oó]n|causa de rechazo|12\.1\.|inhabilit|descalif)"
)

# --- DOCUMENTACIÓN DE VARIABLES DE OPERACIÓN (PRODUCCIÓN) ---
# COMPLIANCE_CHUNK_CHARS (default 8000): Tamaño de ventana RAG por bloque Map.
# COMPLIANCE_CHUNK_OVERLAP (default 800): Solapamiento para evitar cortes en requisitos.
# COMPLIANCE_ZONE_N_RESULTS (default 5): Hits de vectores iniciales por zona.
# COMPLIANCE_MAX_BLOCK_SECONDS (default 150): Aviso de latencia alta en consola.
# COMPLIANCE_BLOCK_EMPTY_TIMEOUT_SEC (default 590): Límite sospecha timeout silencioso.
# COMPLIANCE_MIN_SNIPPET_MATCH_PCT (default 40): Umbral mínimo para no fallar zona.
# COMPLIANCE_PASS_SNIPPET_MATCH_PCT (default 75): Umbral para marcar zona como 'pass'.
# -----------------------------------------------------------

class ComplianceAgent(BaseAgent):
    """
    Agente 3: Auditor de Cumplimiento (Compliance).
    ARQUITECTURA MAP-REDUCE V5.0 - Rendimiento Industrial.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="compliance_001",
            name="Auditor de Cumplimiento (Map-Reduce 5.0)",
            description="Auditoría Forense de Requisitos y Formatos con Pipeline de Reducción.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()
        self.confidence_scorer = ConfidenceScorer(
            threshold_default=settings.CONFIDENCE_THRESHOLD_DEFAULT,
            threshold_critical=settings.CONFIDENCE_THRESHOLD_CRITICAL
        )
        self.experience_store = ExperienceStore()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        
        async with agent_span(logger, self.agent_id, session_id, correlation_id):
            print(f"🛡️ [Compliance] Iniciando Auditoría Map-Reduce: {session_id}")
            start_global = time.time()
            
            # --- ESTRATEGIA DE BARRIDO MACRO-ZONAS ---
            search_zones = [
                {"name": "ADMINISTRATIVO/LEGAL", "query": "requisitos legales documentacion administrativa rfc acta constitutiva representacion legal"},
                {
                    "name": "TÉCNICO/OPERATIVO",
                    "query": (
                        "especificaciones tecnicas suministro materiales experiencia equipo personal capacidad técnica "
                        "propuesta técnica descripcion servicios anexos técnicos manuales procedimientos "
                        "maquinaria herramientas infraestructura vigilancia calidad del servicio "
                        "competencia habilidad constancias capacitación STPS"
                    ),
                },
                {
                    "name": "FORMATOS/ANEXOS",
                    "query": (
                        "anexos formatos obligatorios lista de anexos anexo 1 anexo 2 anexo 3 "
                        "manifestación declaración carta bajo protesta escritos membretado firmado "
                        "carátula propuesta sobre cerrado checklist documentos a presentar "
                        "propuesta técnica curriculum vitae organigrama relación personal "
                        "DC-03 DC-04 DC-05 FO-CON-14 mipymes estratificación RUPC "
                        "contratos similares experiencia comprobante declaración anual isr iva"
                    ),
                },
                {"name": "GARANTÍAS/SEGUROS", "query": "fianzas polizas cheques certificado garantia cumplimiento anticipo responsabilidad civil"}
            ]
            
            full_master_list = {"administrativo": [], "tecnico": [], "formatos": []}
            zone_reports = []
            all_source_contexts = []
            
            # --- CONFIGURACIÓN INDUSTRIAL ---
            chunk_size = int(os.getenv("COMPLIANCE_CHUNK_CHARS", 8000))
            overlap = int(os.getenv("COMPLIANCE_CHUNK_OVERLAP", 800))
            n_results = int(os.getenv("COMPLIANCE_ZONE_N_RESULTS", 5))
            n_results_formatos = int(os.getenv("COMPLIANCE_FORMATOS_N_RESULTS", max(n_results, 12)))
            n_results_tecnico = int(os.getenv("COMPLIANCE_TECNICO_N_RESULTS", max(n_results, 12)))
            max_block_time = int(os.getenv("COMPLIANCE_MAX_BLOCK_SECONDS", 150))

            # --- CAPA DE EXPERIENCIA ---
            experience_prompt_context = ""
            if settings.EXPERIENCE_LAYER_ENABLED:
                similar_cases = await self.experience_store.find_similar(
                    query_text=" ".join(z["query"] for z in search_zones),
                    top_k=settings.EXPERIENCE_TOP_K,
                )
                if similar_cases and not similar_cases[0].session_id == "none":
                    exp_lines = [
                        f"- Caso {c.session_id} ({c.outcome}): {c.summary[:180]}"
                        for c in similar_cases
                    ]
                    experience_prompt_context = "\n=== CONTEXTO EXPERIENCIA (Casos Similares) ===\n"
                    experience_prompt_context += "Referencia histórica para alertas de riesgo:\n"
                    experience_prompt_context += "\n".join(exp_lines)
                    logger.info("compliance_experience_context_ready", session_id=session_id, count=len(similar_cases))

            for zone in search_zones:
                print(f"    [*] Procesando Zona: {zone['name']}")
                zone_start = time.time()
                
                # --- RAG: Recuperación de Contexto ---
                zname = zone["name"]
                zone_n = n_results_formatos if "FORMATOS" in zname else (n_results_tecnico if "OPERATIVO" in zname else n_results)
                context_zone = await self.smart_search(session_id, zone['query'], n_results=zone_n, vector_db=self.vector_db)
                if not context_zone:
                    zone_reports.append({"zone": zone['name'], "status": "fail", "reason": "RAG vacío", "metrics": {}})
                    continue
                
                all_source_contexts.append(context_zone)

                # --- FASE A: MAP (Mapeo paralelo por bloques) ---
                zone_chunk_size = self._adaptive_chunk_size(len(context_zone), chunk_size)
                chunks = self._split_context(context_zone, zone_chunk_size, overlap)
                print(f"        [-] Bloques a procesar: {len(chunks)} (Contexto: {len(context_zone)} chars)")
                
                raw_zone_items, block_events = await self._map_zone_chunks(
                    zone["name"],
                    chunks,
                    max_block_time,
                    correlation_id,
                    experience_prompt_context,
                    session_id=session_id,
                    job_id=(agent_input.job_id or ""),
                    completed_zones=len(zone_reports),
                )

                # --- FASE B: REDUCE ---
                reduced_items, zone_metrics = self._reduce_zone_items(zone['name'], raw_zone_items, context_zone)
                
                # --- RESOLUCIÓN DE ESTADO (Prioridad: Métricas -> Timeouts -> Errores LLM) ---
                total_raw = sum(b.get("items_count", 0) for b in block_events)
                status, reason = self._apply_zone_gate(reduced_items, zone_metrics, total_raw)
                status, reason = self._resolve_zone_status_for_block_timeouts(status, reason, block_events)
                status, reason = self._resolve_zone_status_for_llm_issues(status, reason, block_events)
                
                zone_duration = round(time.time() - zone_start, 2)
                suspect_n = sum(1 for b in block_events if b.get("suspect_llm_timeout"))
                err_n = sum(1 for b in block_events if b.get("llm_error"))
                empty_n = sum(1 for b in block_events if b.get("empty_llm_response"))

                # Trazabilidad Forense en Redis
                if agent_input.job_id:
                    # pct monótono por zona; tope <100 hasta el cierre del job en agents.py
                    _zone_pct = min(94, 30 + (len(zone_reports) * 15))
                    update_job_status(
                        agent_input.job_id,
                        "RUNNING",
                        progress={
                            "stage": "compliance",
                            "zone": zone['name'],
                            "pct": _zone_pct,
                            "message": f"Zona completada: {zone['name']} ({status})",
                        },
                    )

                zone_reports.append({
                    "zone": zone['name'],
                    "status": status,
                    "reason": reason,
                    "metrics": {
                        **zone_metrics,
                        "duration_sec": zone_duration,
                        "context_chars": len(context_zone),
                        "blocks_count": len(chunks),
                        "block_events": block_events,
                        "blocks_suspect_timeout_count": suspect_n,
                        "blocks_llm_error_count": err_n,
                        "blocks_empty_response_count": empty_n,
                    }
                })

                if status != "fail":
                    for cat in ["administrativo", "tecnico", "formatos"]:
                        full_master_list[cat].extend([it for it in reduced_items if it.get("categoria") == cat])

            # --- DEDUP GLOBAL + IDs SECUENCIALES ---
            full_master_list = self._dedupe_master_list_categories(full_master_list)

            # Histograma de Tiers (Auditoría Forense)
            all_audit_items = [it for k in ("administrativo", "tecnico", "formatos") for it in (full_master_list.get(k) or [])]
            total_final = len(all_audit_items)
            tier_stats = {"literal": 0, "normalized": 0, "weak": 0, "none": 0, "unknown": 0}
            for it in all_audit_items: tier_stats[it.get("match_tier", "unknown")] = tier_stats.get(it.get("match_tier", "unknown"), 0) + 1
            
            ev_ok = sum(1 for it in all_audit_items if it.get("evidence_match"))
            audit_summary = {
                "zones": zone_reports,
                "tier_stats": tier_stats,
                "global_match_pct": round((ev_ok / max(total_final, 1)) * 100, 1) if total_final > 0 else 0.0,
                "total_items": total_final,
                "causas_desechamiento": [
                    (it.get("snippet") or it.get("descripcion") or "")[:300]
                    for it in all_audit_items
                    if _C01_SEMANTIC_PATTERN.search(f"{it.get('descripcion','')} {it.get('snippet','')}")
                ],
            }
            full_master_list["audit_summary"] = audit_summary

            duration_total = time.time() - start_global
            failed_list = [str(z["zone"]) for z in zone_reports if z["status"] == "fail"]
            partial_list = [str(z["zone"]) for z in zone_reports if z["status"] == "partial"]
            
            final_status = AgentStatus.SUCCESS
            err_msg = None
            if failed_list or partial_list:
                final_status = AgentStatus.PARTIAL if total_final > 0 else AgentStatus.FAIL
                msg_parts = []
                if failed_list: msg_parts.append(f"Fallos en: {', '.join(failed_list)}")
                if partial_list: msg_parts.append(f"Parciales en: {', '.join(partial_list)}")
                err_msg = "Auditoría con incidencias. " + ". ".join(msg_parts)
            
            report_data = {
                "status": final_status.value,
                "error": err_msg,
                "data": full_master_list,
                "metrics": {
                    "zones": zone_reports,
                    "total_count": total_final,
                    "total_duration_sec": int(duration_total)
                }
            }
            
            # --- FASE 1: Cálculo de Confianza Agregada ---
            confidence_obj = None
            if settings.CONFIDENCE_ENABLED or settings.CONFIDENCE_SHADOW_MODE:
                # Combinamos todos los contextos para verificación literal (Fase 1)
                full_context_str = "\n".join(all_source_contexts)
                
                # Fase 5 mantiene trazabilidad de experiencia en el contexto de scoring.
                if experience_prompt_context:
                    full_context_str += "\n" + experience_prompt_context
                
                confidence_obj = self.confidence_scorer.calculate_extraction_confidence(
                    extracted_text=str(full_master_list),
                    source_context=full_context_str,
                    is_critical=True
                )
                
                # Enriquecer data (Requisito Fase 1)
                full_master_list["confidence"] = confidence_obj.model_dump()
                full_master_list["unknowns"] = confidence_obj.unknowns
                full_master_list["ambiguities"] = confidence_obj.ambiguities

                # Log estructurado
                logger.info(
                    "confidence_score_calculated",
                    agent_id=self.agent_id,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    overall=confidence_obj.overall,
                    recommendation=confidence_obj.recommendation.value,
                    is_critical=True
                )

                if settings.CONFIDENCE_ENABLED and not settings.CONFIDENCE_SHADOW_MODE:
                    if confidence_obj.recommendation == "reject":
                        final_status = AgentStatus.PARTIAL

            print(f"🛡️ [Compliance] Fin: {final_status.value.upper()} | {total_final} ítems | {duration_total:.1f}s")
            await self.context_manager.record_task_completion(session_id, "master_compliance_list", report_data)
            
            output = AgentOutput(
                status=final_status,
                agent_id=self.agent_id,
                session_id=session_id,
                data=full_master_list,
                message=err_msg,
                correlation_id=correlation_id,
                processing_time_sec=round(duration_total, 2)
            )

            return output

    def _split_context(self, context: str, chunk_size: int, overlap: int) -> List[str]:
        """
        Parte el contexto RAG en ventanas solapadas para el map del compliance.

        Importante: debe recorrer **todo** el texto. Un bug histórico limitaba a 2 bloques
        (`len(chunks) < 2`), descartando el resto y provocando “ceguera” en secciones largas
        (p. ej. listas de documentación a…bb al final del contexto).
        """
        chunks: List[str] = []
        if chunk_size <= 0:
            return [context] if context else []
        if len(context) <= chunk_size:
            return [context]
        step = max(1, chunk_size - max(0, overlap))
        start = 0
        while start < len(context):
            end = min(start + chunk_size, len(context))
            chunks.append(context[start:end])
            if end >= len(context):
                break
            start += step
        return chunks

    async def _map_zone_chunks(
        self,
        zone_name: str,
        chunks: List[str],
        max_block_time: int,
        correlation_id: str = "",
        experience_prompt_context: str = "",
        session_id: str = "no-id",
        job_id: str = "",
        completed_zones: int = 0,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Mapea cada chunk de una zona vía LLM.

        Si ``job_id`` está presente, actualiza Redis tras cada bloque (heartbeat)
        para que ``updated_at`` avance durante corridas largas y el monitoreo externo
        no marque falsamente un job activo como zombie.
        """
        raw_zone_items: List[Dict[str, Any]] = []
        block_events: List[Dict[str, Any]] = []
        empty_timeout_sec = float(os.getenv("COMPLIANCE_BLOCK_EMPTY_TIMEOUT_SEC", "590"))
        max_retries = int(os.getenv("COMPLIANCE_BLOCK_EXTRA_RETRIES", "2"))
        retry_delay = int(os.getenv("COMPLIANCE_BLOCK_RETRY_DELAY_SEC", "5"))
        total_chunks = max(len(chunks), 1)
        done_count = 0

        for i, chunk in enumerate(chunks):
            b_start = time.time()
            print(f"        [>] Mapeando Bloque {i+1}/{len(chunks)}...", end="", flush=True)
            attempts = 0
            recovered = False
            chunk_items: List[Dict[str, Any]] = []
            llm_err: Optional[str] = None
            empty_resp = False
            while attempts <= max_retries:
                chunk_items, llm_err, empty_resp = await self._extract_zone_chunk(
                    zone_name, chunk, correlation_id, experience_prompt_context
                )
                if not llm_err and not empty_resp:
                    if attempts > 0:
                        recovered = True
                    break
                attempts += 1
                if attempts <= max_retries:
                    print(f" [Fallo. Reintento {attempts}/{max_retries} en {retry_delay}s]...", end="", flush=True)
                    await asyncio.sleep(retry_delay)

            b_duration = time.time() - b_start
            print(f" OK ({b_duration:.1f}s, {len(chunk_items)} ítems)")
            suspect = len(chunk_items) == 0 and b_duration >= empty_timeout_sec and not llm_err
            ev: Dict[str, Any] = {
                "block_index": i + 1,
                "duration_sec": round(b_duration, 2),
                "items_count": len(chunk_items),
                "suspect_llm_timeout": suspect,
                "llm_error": llm_err,
                "empty_llm_response": empty_resp,
                "llm_attempts": attempts if not recovered else attempts + 1,
                "recovered_after_retry": recovered,
            }
            if not recovered and (llm_err or empty_resp):
                ev["llm_attempts"] = attempts
            if llm_err and not recovered:
                logger.warning("compliance_block_error", session_id=session_id, zone=zone_name, block=i+1, error=str(llm_err)[:500])
            elif empty_resp and not recovered:
                logger.warning("compliance_block_empty", session_id=session_id, zone=zone_name, block=i+1)
            if b_duration > max_block_time:
                print(f"        ⚠️ [AVISO] Latencia alta en bloque {i+1} ({b_duration:.1f}s)")
            if job_id:
                done_count += 1
                intra = int(14 * done_count / total_chunks)
                _hb_pct = min(94, 30 + completed_zones * 15 + intra)
                update_job_status(
                    job_id,
                    "RUNNING",
                    progress={
                        "stage": "compliance",
                        "zone": zone_name,
                        "pct": _hb_pct,
                        "message": f"{zone_name}: bloque {i + 1}/{len(chunks)}",
                    },
                )
            raw_zone_items.extend(chunk_items)
            block_events.append(ev)
        return raw_zone_items, block_events

    def _adaptive_chunk_size(self, context_len: int, base_chunk: int) -> int:
        """Ajusta chunk_size según longitud del contexto y flag de optimización."""
        enabled = os.getenv("COMPLIANCE_ADAPTIVE_CHUNKING", "true").lower() in ("1", "true", "yes")
        if not enabled:
            return base_chunk
        min_chunk = int(os.getenv("COMPLIANCE_CHUNK_MIN", "2200"))
        max_chunk = int(os.getenv("COMPLIANCE_CHUNK_MAX", str(base_chunk)))
        if context_len > 220_000:
            return max(min_chunk, min(max_chunk, int(base_chunk * 0.45)))
        if context_len > 120_000:
            return max(min_chunk, min(max_chunk, int(base_chunk * 0.65)))
        if context_len > 60_000:
            return max(min_chunk, min(max_chunk, int(base_chunk * 0.8)))
        return max(min_chunk, min(max_chunk, base_chunk))

    def _resolve_zone_status_for_block_timeouts(self, status: str, reason: str, block_events: List[Dict[str, Any]]) -> Tuple[str, str]:
        bad = [b for b in block_events if b.get("suspect_llm_timeout")]
        if not bad: return status, reason
        idxs = ", ".join(str(b["block_index"]) for b in bad)
        detail = f"Bloque(s) {idxs} sin ítems tras espera prolongada (posible timeout LLM)."
        if status == "pass": return "partial", detail
        if status == "partial": return "partial", f"{reason} | {detail}"
        return status, reason

    def _resolve_zone_status_for_llm_issues(self, status: str, reason: str, block_events: List[Dict[str, Any]]) -> Tuple[str, str]:
        err_blocks = [b for b in block_events if b.get("llm_error")]
        empty_blocks = [b for b in block_events if b.get("empty_llm_response")]
        if not err_blocks and not empty_blocks: return status, reason
        parts = []
        if err_blocks:
            idxs = ", ".join(str(b["block_index"]) for b in err_blocks)
            parts.append(f"Error de llamada LLM en bloque(s) {idxs}")
        if empty_blocks:
            idxs = ", ".join(str(b["block_index"]) for b in empty_blocks)
            parts.append(f"Respuesta vacía del LLM en bloque(s) {idxs}")
        detail = "; ".join(parts) + "."
        if status == "pass": return "partial", detail
        if status == "partial": return "partial", f"{reason} | {detail}"
        return status, reason

    async def _extract_zone_chunk(
        self,
        zone_name: str,
        chunk_text: str,
        correlation_id: str = "",
        experience_prompt_context: str = "",
    ) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        system_prompt = (
            "Eres un Auditor Forense Senior de Licitaciones especializado en Despiece Quirúrgico.\n"
            "Tu misión es extraer requisitos con EVIDENCIA LITERAL. \n\n"
            "REGLAS DE ORO PARA SNIPPETS:\n"
            "1. Cita literal: El campo 'snippet' DEBE ser un fragmento contiguo copiado directamente del TEXTO FUENTE.\n"
            "2. Sin Parafraseo: No resumas ni limpies el texto en 'snippet' (mantén errores de OCR si existen).\n"
            "3. Si no hay match literal: Si el requisito existe pero no puedes citar un fragmento claro, deja 'snippet' vacío y marca 'quality_flags': ['non_literal_evidence'].\n"
            "4. Desglose Obligatorio: NUNCA agrupues requerimientos múltiples en el mismo objeto. Cada viñeta, entrega o formato va en un elemento independiente.\n"
            "5. Cobertura total del fragmento: Extrae el 100% de los requisitos explícitos que aparezcan en este TEXTO FUENTE (listas a, b, c… o numéricas). "
            "No impongas un máximo artificial de ítems. No resumas ni condenses listas: un requisito por elemento JSON.\n\n"
            "REGLAS ANTI-DUPLICACIÓN (OBLIGATORIAS):\n"
            "6. No repitas el mismo requisito ni la misma cláusula legal en más de un objeto JSON dentro del mismo bloque.\n"
            "7. Si un párrafo ya fue extraído en otra categoría del mismo JSON, genera UNA SOLA entrada en la categoría más adecuada.\n"
            "8. No generes variaciones casi idénticas del mismo párrafo (p.ej. desechamiento, penalizaciones) como ítems distintos; unifica en un solo ítem con el snippet literal más representativo."
        )
        # Adaptación de Prompt por Zona (P1 Few-Shots)
        few_shot = ""
        if "FORMATOS" in zone_name.upper():
            few_shot = (
                "\nEJEMPLO PARA FORMATOS:\n"
                "TEXTO: '...deberá presentar el Anexo 3 debidamente firmado en papel membretado...'\n"
                "JSON: {\"nombre\": \"Anexo 3\", \"snippet\": \"Anexo 3 debidamente firmado en papel membretado\", \"categoria\": \"formatos\"}\n"
                "LISTAS DE ENTREGA (Bases cap. 6, 'documentación a presentar', incisos a) b) c)… aa) bb)): "
                "un objeto JSON por inciso; siempre \"categoria\": \"formatos\"; snippet = texto literal del inciso.\n"
            )
        elif "TÉCNICO" in zone_name.upper():
            few_shot = (
                "\nEJEMPLO PARA TÉCNICO:\n"
                "TEXTO: '...el equipo debe tener capacidad de 500kW con protección IP65...'\n"
                "JSON: {\"nombre\": \"Capacidad del equipo\", \"snippet\": \"capacidad de 500kW con protección IP65\", \"categoria\": \"tecnico\"}\n"
            )

        prompt = f"""AUDITORÍA DE BLOQUE [{zone_name}]
TEXTO FUENTE: {chunk_text}
{few_shot}
TAREA: Extrae los requisitos requeridos en este fragmento.
FORMATO JSON OBLIGATORIO:
{{
    "administrativo": [{{ "nombre": "...", "page": 5, "descripcion": "...", "snippet": "...", "quality_flags": [] }}],
    "tecnico": [{{ "nombre": "...", "page": 5, "descripcion": "...", "snippet": "...", "quality_flags": [] }}],
    "formatos": [{{ "nombre": "...", "page": 5, "descripcion": "...", "snippet": "...", "quality_flags": [] }}]
}}
"""
        if experience_prompt_context:
            prompt += f"\n{experience_prompt_context}\n"
        llm_res = await self.llm.generate(prompt=prompt, system_prompt=system_prompt, format="json", correlation_id=correlation_id)
        if not llm_res.success:
            return [], llm_res.error, False

        raw_str = llm_res.response
        if raw_str is None or (isinstance(raw_str, str) and not raw_str.strip()):
            return [], None, True

        raw_data = self._robust_json_parse(raw_str)
        if not isinstance(raw_data, dict) or not any(raw_data.get(k) for k in ["administrativo", "tecnico", "formatos"]):
            # No marcar como "respuesta vacía": suele ser JSON truncado o esquema incorrecto.
            logger.warning(
                "compliance_json_parse_or_schema_fail",
                zone=zone_name,
                response_chars=len(raw_str) if isinstance(raw_str, str) else 0,
                preview=(raw_str[:400] + "…") if isinstance(raw_str, str) and len(raw_str) > 400 else raw_str,
            )
            return (
                [],
                "JSON inválido, truncado o sin claves administrativo/tecnico/formatos",
                False,
            )

        flat_items = []
        for cat in ["administrativo", "tecnico", "formatos"]:
            entries = raw_data.get(cat, [])
            if isinstance(entries, dict): entries = [entries]
            if not isinstance(entries, list): continue
            for item in entries:
                if not isinstance(item, dict): continue
                item["categoria_orig"] = cat
                # ✅ TRAZABILIDAD: conservar la zona de map-reduce que originó este ítem
                item["zona_origen"] = zone_name
                flat_items.append(item)
        return flat_items, None, False

    def _reduce_zone_items(self, zone_name: str, items: List[Dict[str, Any]], full_context: str) -> Tuple[List[Dict], Dict]:
        seen_snippets = set()
        final_items = []
        valid_snippets = 0
        valid_pages = 0
        forensic_mismatches: List[Dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict): continue
            item = self._normalize_item(raw)
            dedup_key = self._canonical_item_fingerprint(item)
            
            content_len = max(len(item["descripcion"]), len(item["snippet"]))
            if dedup_key in seen_snippets or content_len < 25: continue
            match_tier, match_info = self._verify_evidence(item["snippet"], full_context)
            item["evidence_match"] = (match_tier != "none")
            item["match_tier"] = match_tier
            
            if match_tier == "none":
                # Instrumentación Forense: Registrar fallo para análisis
                mismatch_case = {
                    "id": item.get("id", "N/A"),
                    "categoria": raw.get("categoria_orig", "N/A"),
                    "snippet": item["snippet"][:150],
                    "context_len": len(full_context),
                    "reason": match_info
                }
                # Solo guardamos los primeros 10 fallos por zona para no inflar el JSON
                if len(forensic_mismatches) < 10:
                    forensic_mismatches.append(mismatch_case)
                
                logger.warning(
                    "compliance_evidence_mismatch",
                    zone=zone_name,
                    category=mismatch_case["categoria"],
                    snippet_preview=mismatch_case["snippet"]
                )
            
            if item["evidence_match"]: valid_snippets += 1
            if item["page"] > 0: valid_pages += 1
            cat_raw = raw.get("categoria_orig", self._infer_category(item, zone_name))
            item["categoria"] = cat_raw.strip() if isinstance(cat_raw, str) else self._infer_category(item, zone_name)
            # ✅ TRAZABILIDAD: estampar zona_origen (propagada desde _extract_zone_chunk)
            item["zona_origen"] = raw.get("zona_origen", zone_name)
            final_items.append(item)
            seen_snippets.add(dedup_key)
        final_items = [x for x in final_items if isinstance(x, dict)]
        for i, it in enumerate(final_items):
            cat = it.get("categoria", self._infer_category(it, zone_name))
            prefix = (cat[:2] if len(cat) >= 2 else (cat + "XX")[:2]).upper()
            it["id"] = f"{prefix}-{i+1:02d}"
        metrics = {
            "total": len(final_items),
            "snip_match_pct": round((valid_snippets/len(final_items)*100), 1) if final_items else 0,
            "page_match_pct": round((valid_pages/len(final_items)*100), 1) if final_items else 0,
            "forensic_mismatches": forensic_mismatches,
        }
        return final_items, metrics

    def _normalize_item(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        desc = raw.get("descripcion") or raw.get("requisito") or raw.get("texto") or raw.get("detalle") or ""
        snip = raw.get("snippet") or raw.get("extracto") or raw.get("evidencia") or raw.get("literal") or ""
        if not desc and snip: desc = snip
        if not snip and desc: snip = desc
        if _C01_SEMANTIC_PATTERN.search(f"{desc} {snip}") and "causa de desechamiento" not in desc.lower():
            desc = f"Causa de desechamiento: {desc}"
        try:
            pg = int(raw.get("page") or raw.get("pagina") or 0)
        except: pg = 0
        name = raw.get("nombre") or raw.get("titulo") or (desc[:50] + "...")
        sec = str(raw.get("seccion") or "N/A")
        qf = raw.get("quality_flags")
        if not isinstance(qf, list):
            qf = []
        else:
            qf = list(qf)
        if pg <= 0 and "missing_page" not in qf:
            qf.append("missing_page")
        return {"id": "", "nombre": name, "seccion": sec, "descripcion": desc, "page": pg, "snippet": snip, "quality_flags": qf}

    def _normalize_text(self, text: str, remove_accents: bool = False) -> str:
        """Normalización profunda de texto para matching industrial."""
        if not text: return ""
        # 1. Normalización Unicode (NFKC para compatibilidad de caracteres)
        text = unicodedata.normalize('NFKC', text)
        # 2. Lowercase y limpieza de espacios
        text = re.sub(r'\s+', ' ', text).strip().lower()
        if remove_accents:
            # 3. Eliminar acentos (con precaución)
            text = "".join(
                c for c in unicodedata.normalize('NFD', text)
                if unicodedata.category(c) != 'Mn'
            )
        return text

    def _verify_evidence(self, snippet: str, context: str) -> Tuple[str, str]:
        """
        Verificación de Evidencia por Capas (match_tier).
        Retorna: (tier, diagnosis)
        Tiers: 'literal', 'normalized', 'weak', 'none'
        """
        if not snippet or len(snippet) < 12: 
            return "none", "Snippet demasiado corto o vacío"

        # --- NIVEL 1: MATCH LITERAL SIMPLE ---
        # (Sin normalización profunda todavía)
        if snippet.strip() in context:
            return "literal", "Exact match found"

        # --- NIVEL 2: NORMALIZACIÓN ESTÁNDAR ---
        norm_snip = self._normalize_text(snippet)
        norm_ctx = self._normalize_text(context)
        
        if norm_snip in norm_ctx:
            return "normalized", "Match found after basic normalization"

        # Prefijo de seguridad (50 chars)
        prefix_len = min(len(norm_snip), 50)
        if norm_snip[:prefix_len] in norm_ctx:
            return "normalized", f"Prefix match ({prefix_len} chars) found"

        # --- NIVEL 3: NORMALIZACIÓN AGRESIVA (SIN ACENTOS) ---
        agg_snip = self._normalize_text(snippet, remove_accents=True)
        agg_ctx = self._normalize_text(context, remove_accents=True)
        
        if agg_snip in agg_ctx:
            return "weak", "Match found after removing accents"

        # Diagnóstico de fallo
        diagnosis = "Snippet no encontrado en el contexto de la zona."
        if len(context) < 100:
            diagnosis = "Contexto de zona extremadamente pobre (RAG issue?)"
            
        return "none", diagnosis

    def _infer_category(self, item: Dict, zone_name: str) -> str:
        zn = zone_name.lower()
        if "administrativo" in zn: return "administrativo"
        if "técnico" in zn or "tecnico" in zn: return "tecnico"
        if "formatos" in zn: return "formatos"
        return "administrativo"

    # ─── P0: Fingerprint canónico + Dedup global cross-zona ───────────────

    def _canonical_item_fingerprint(self, item: Dict[str, Any]) -> str:
        """
        Genera un fingerprint canónico SHA-256 para deduplicación robusta.
        Usa el texto principal (snippet o descripcion) normalizado.
        Devuelve los primeros 32 hex chars del hash.
        """
        text = (item.get("snippet") or "").strip()
        if not text or len(text) < 15:
            text = (item.get("descripcion") or "").strip()
        if not text:
            text = (item.get("nombre") or "").strip()
        normalized = self._normalize_text(text, remove_accents=True)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    # Orden de calidad de match_tier para selección de ganador en dedup
    _MATCH_TIER_RANK: Dict[str, int] = {
        "literal": 4, "normalized": 3, "weak": 2, "none": 1
    }

    def _dedupe_master_list_categories(
        self, master: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        P0: Deduplicación global cross-zona + reasignación de IDs secuenciales.
        Recorre cada categoría, identifica duplicados por fingerprint canónico,
        selecciona el mejor ítem (evidence > tier > longitud) y reasigna IDs.
        """
        cat_keys = ("administrativo", "tecnico", "formatos")
        for cat in cat_keys:
            items = master.get(cat) or []
            if not items:
                continue

            seen: Dict[str, Dict[str, Any]] = {}  # fingerprint → winning item
            for item in items:
                if not isinstance(item, dict):
                    continue
                fp = self._canonical_item_fingerprint(item)

                if fp in seen:
                    existing = seen[fp]
                    if self._is_better_item(item, existing):
                        # Trazar zona del descartado para observabilidad
                        zones_discarded = existing.get(
                            "zonas_duplicadas_descartadas", []
                        )
                        zones_discarded.append(
                            existing.get("zona_origen", "?")
                        )
                        item["zonas_duplicadas_descartadas"] = zones_discarded
                        seen[fp] = item
                    else:
                        # El existente gana; trazar zona del descartado
                        existing.setdefault(
                            "zonas_duplicadas_descartadas", []
                        ).append(item.get("zona_origen", "?"))
                else:
                    seen[fp] = item

            # Reasignar IDs secuenciales por categoría
            deduped = list(seen.values())
            prefix = (cat[:2]).upper() if len(cat) >= 2 else (cat + "XX")[:2].upper()
            for i, it in enumerate(deduped):
                it["id"] = f"{prefix}-{i + 1:02d}"

            master[cat] = deduped

        return master

    def _is_better_item(
        self, candidate: Dict[str, Any], existing: Dict[str, Any]
    ) -> bool:
        """
        Determina si `candidate` es mejor que `existing` para la dedup global.
        Criterio (en orden): evidence_match, match_tier, longitud de snippet.
        """
        # 1. evidence_match True gana
        c_ev = candidate.get("evidence_match", False)
        e_ev = existing.get("evidence_match", False)
        if c_ev and not e_ev:
            return True
        if e_ev and not c_ev:
            return False

        # 2. Mejor match_tier
        c_tier = self._MATCH_TIER_RANK.get(
            candidate.get("match_tier", "none"), 0
        )
        e_tier = self._MATCH_TIER_RANK.get(
            existing.get("match_tier", "none"), 0
        )
        if c_tier > e_tier:
            return True
        if e_tier > c_tier:
            return False

        # 3. Snippet más largo
        c_len = len((candidate.get("snippet") or "").strip())
        e_len = len((existing.get("snippet") or "").strip())
        return c_len > e_len

    def _apply_zone_gate(self, items: List[Dict], metrics: Dict, total_raw: int = 0) -> Tuple[str, str]:
        min_match = int(os.getenv("COMPLIANCE_MIN_SNIPPET_MATCH_PCT", 40))
        pass_match = int(os.getenv("COMPLIANCE_PASS_SNIPPET_MATCH_PCT", 75))
        if not items: return ("fail", f"Se extrajeron {total_raw} ítems, pero todos descartados.") if total_raw > 0 else ("fail", "No items.")
        snip_pct = float(metrics.get("snip_match_pct", 0))
        page_pct = float(metrics.get("page_match_pct", 0))
        if snip_pct <= 0 or page_pct <= 0: return "fail", "Zero evidence coverage."
        if snip_pct < max(min_match, 1): return "fail", f"Baja calidad ({snip_pct}% matched)."
        return ("partial", "Evidencia con inconsistencias.") if snip_pct < pass_match else ("pass", "OK")

    def _robust_json_parse(self, text: str) -> Dict[str, Any]:
        try:
            if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end+1]) if (start != -1 and end != -1) else {}
        except: return {}
