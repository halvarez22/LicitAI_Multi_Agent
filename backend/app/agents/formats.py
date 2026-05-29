import os
import re
import json
import time
import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.contracts.document_inventory import (
    DocumentEnvelope,
    DocumentInventory,
    InventoryItemStatus,
)
from app.services.document_fill_quality_gate import (
    detect_cross_tender_marker,
    validate_generated_documents_fill,
)
from app.services.validation_service import validation_mapping_service
from app.core.formats_pilot_slots import build_formats_pilot_missing_entries
from app.core.observability import get_logger
from app.services.document_traceability import (
    attach_traceability,
    build_materialization_metrics,
    safe_file_sha256,
)
from app.utils.doc_formatting import (
    ANTI_PLACEHOLDER_PROMPT_RULE, 
    strip_markdown_for_docx,
    is_markdown_table_line,
    parse_markdown_table
)
from app.core.template_engine import LegalTemplateEngine, TemplateIntegrityError
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.config.settings import settings as app_settings

logger = get_logger(__name__)


def _formats_inventory_doc_exists(output_dir: str, canonical_id: str) -> bool:
    """Idempotencia: no regenerar si ya existe .docx que incluye el canonical_id."""
    if not canonical_id or not os.path.isdir(output_dir):
        return False
    token = re.sub(r"[^\w\-]+", "_", canonical_id).strip("_").lower()
    if len(token) < 3:
        return False
    try:
        for fn in os.listdir(output_dir):
            if not fn.endswith(".docx") or fn.startswith("~$"):
                continue
            if token in fn.lower():
                return True
    except OSError:
        return False
    return False


def _merge_document_inventory_legal(
    company_data: Dict[str, Any],
    output_dir: str,
    reqs_to_process: List[Dict[str, Any]],
    seen_ids: Set[str],
) -> None:
    """
    Modo fábrica: añade ítems ``legal_administrative`` pendientes del inventario canónico.

    No duplica ``id`` ya visto en compliance ni archivos ya materializados en disco.
    Solo agrega ítems con evidencia real (Tier A) o explícitamente añadidos por el usuario
    (Tier C). Los ítems Tier B (inferidos) sin anchors se descartan para evitar alucinaciones.
    """
    raw = company_data.get("document_inventory")
    if not isinstance(raw, dict) or not raw.get("items"):
        return
    try:
        inv = DocumentInventory.model_validate(raw)
    except Exception as e:
        logger.warning("formats_inventory_parse_failed", error=str(e))
        return

    for it in inv.items:
        if it.category != DocumentEnvelope.LEGAL:
            continue
        if it.status != InventoryItemStatus.PENDING:
            continue
        cid = (it.canonical_id or "").strip().replace(".", "_")
        if not cid:
            continue
        key = cid.lower()
        if key in seen_ids:
            continue
        if _formats_inventory_doc_exists(output_dir, it.canonical_id):
            continue

        # ── FILTRO ANTI-ALUCINACIÓN (document_inventory) ────────────────────
        # Ítems Tier B (inferidos) sin anchors reales son candidatos a alucinación.
        # Solo aceptamos:
        #   - Tier A (anchored): tienen evidencia literal en las bases
        #   - Tier C (user_added): el usuario los agregó explícitamente
        #   - Tier B con al menos un anchor con snippet >= 20 chars
        tier_val = str(getattr(it, "tier", "") or "").lower()
        if tier_val == "inferred":
            anchors = list(getattr(it, "anchors", []) or [])
            has_real_anchor = any(
                len(str(getattr(a, "snippet", "") or "").strip()) >= 20
                for a in anchors
            )
            if not has_real_anchor:
                logger.info(
                    "formats_inventory_inferred_no_anchor_discarded",
                    canonical_id=cid,
                    display_name=str(it.display_name or "")[:80],
                )
                seen_ids.add(key)
                continue

        seen_ids.add(key)
        reqs_to_process.append(
            {
                "id": cid,
                "nombre": it.display_name,
                "descripcion": (it.description or "").strip(),
                "tipo": "formato",
                "from_document_inventory": True,
                "generator_hint": it.generator_hint,
            }
        )


def _sanitize_legal_content(
    content: str,
    *,
    session_id: str,
    metadata: Dict[str, Any],
) -> str:
    """
    Sanea placeholders frecuentes de plantillas legales antes de guardar DOCX.

    Regla: ningún documento final debe contener marcadores entre corchetes ni
    tokens genéricos tipo "N/A" como dato principal.
    """
    text = (content or "").strip()
    if not text:
        return text

    razon_social = str(metadata.get("empresa") or "la empresa").strip()
    representante = str(metadata.get("representante") or "representante legal").strip()
    rfc = str(metadata.get("rfc") or "").strip()
    fecha = str(metadata.get("fecha") or "").strip()
    domicilio = ""
    footer_text = str(metadata.get("footer_text") or "")
    if "Domicilio:" in footer_text:
        domicilio = footer_text.split("Domicilio:", 1)[1].strip()
    ciudad = domicilio.split(",")[0].strip() if domicilio else "México"

    replacements = {
        "[Dirección de la empresa]": domicilio or "Dato pendiente de confirmar por el representante legal.",
        "[Ciudad, Estado, Código Postal]": domicilio or "Dato pendiente de confirmar por el representante legal.",
        "[Fecha actual]": fecha or "Dato pendiente de confirmar por el representante legal.",
        "[Fecha]": fecha or "Dato pendiente de confirmar por el representante legal.",
        "[Nombre del Representante Legal/Apoderado]": representante,
        "[Nombre del Representante Legal o Destinatario]": representante,
        "[Nombre del Destinatario]": "Comité de Adquisiciones y Dirección de Obras Públicas",
        "[Nombre completo del concursante]": razon_social,
        "[Número de Licitación o Nombre del Proceso]": session_id,
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    # Reemplazos semánticos de fallback comunes.
    text = re.sub(r"\bRFC:\s*N/A\b", f"RFC: {rfc or 'Dato pendiente de confirmar por el representante legal.'}", text, flags=re.I)
    text = re.sub(r"\bRepresentante\s+Legal:\s*N/A\b", f"Representante Legal: {representante}", text, flags=re.I)
    text = re.sub(r"\bLugar y fecha:\s*N/A\b", f"Lugar y fecha: {ciudad}, {fecha}", text, flags=re.I)
    if domicilio:
        text = text.replace(
            "domicilio en Dato pendiente de confirmar por el representante legal.",
            f"domicilio en {domicilio}.",
        )
    if representante:
        text = re.sub(
            r"(Firma del Representante Legal:?\s*)Dato pendiente de confirmar por el representante legal\.",
            rf"\1{representante}",
            text,
            flags=re.I,
        )

    # Última barrera: cualquier placeholder restante entre [] o {} se neutraliza.
    text = re.sub(
        r"\[[^\]]+\]|\{[^}]+\}",
        "Dato pendiente de confirmar por el representante legal.",
        text,
    )
    return text


def _normalize_formats_blob(value: Any) -> str:
    return str(value or "").strip().lower()


def _infer_formats_contenido_nacional_pct(
    vector_db: VectorDbServiceClient,
    session_id: str,
) -> str:
    try:
        res = vector_db.query_texts(session_id, "contenido nacional 65% anexo iii-k punto 46", n_results=4)
        for doc in res.get("documents") or []:
            text = str(doc or "")
            if "contenido nacional" not in text.lower():
                continue
            match = re.search(r"(\d{1,3})\s*%", text)
            if match:
                return match.group(1)
    except Exception as exc:
        logger.warning("formats_contenido_nacional_pct_failed", session_id=session_id, error=str(exc))
    return ""


def _build_formats_contenido_nacional_text(
    *,
    razon_social: str,
    rfc: str,
    representante: str,
    session_id: str,
    tender_name: str,
    fecha_es: str,
    zonas: List[str],
    porcentaje: str,
) -> str:
    zonas_txt = ", ".join(zonas) if zonas else "correspondientes a la propuesta presentada"
    if len(zonas) == 1:
        zona_clause = f"la zona {zonas_txt}"
    elif len(zonas) > 1:
        zona_clause = f"las zonas {zonas_txt}"
    else:
        zona_clause = "la zona en que participo"
    porcentaje_txt = porcentaje or "65"
    proc_ref = tender_name.strip() or session_id.replace("_", " ").upper()
    return (
        "MANIFESTACIÓN DE NACIONALIDAD MEXICANA, PRODUCCIÓN EN MÉXICO Y GRADO DE CONTENIDO NACIONAL\n\n"
        f"{fecha_es}\n\n"
        "Comité de Adquisiciones, Arrendamientos y Contratación\n"
        "de Servicios de la Administración Pública Estatal\n"
        "PRESENTE.-\n\n"
        f"Me refiero al procedimiento de contratación identificado como {proc_ref}, "
        f"en el que mi representada, la empresa {razon_social}, RFC {rfc}, participa a través de la propuesta contenida en el presente sobre.\n\n"
        "Sobre el particular y en términos de lo previsto por el Acuerdo por el que se establecen las reglas para la determinación "
        "del grado de contenido nacional, tratándose de procedimientos de contratación de carácter nacional, el suscrito manifiesta "
        "bajo protesta de decir verdad que los bienes ofertados para la partida 2 correspondiente a "
        f"{zona_clause}, serán producidos en México y contendrán un grado de contenido nacional de cuando menos el {porcentaje_txt} por ciento, "
        "en el supuesto de que sea adjudicado el pedido respectivo. Asimismo, manifiesto bajo protesta de decir verdad ser de nacionalidad mexicana.\n\n"
        "De igual forma, manifiesto tener conocimiento de lo previsto en el artículo 57 de la Ley de Adquisiciones, "
        "Arrendamientos y Servicios del Sector Público y me comprometo, en caso de ser requerido, a aceptar una verificación "
        "del cumplimiento de los requisitos sobre el contenido nacional de los bienes ofertados mediante la exhibición de la "
        "información documental correspondiente y/o a través de una inspección física de la planta industrial en la que se producen.\n\n"
        "ATENTAMENTE\n\n"
        f"{razon_social}\n\n"
        f"{representante}\n"
        "Representante Legal"
    )


def _pick_reference_service_price(user_inputs: Dict[str, Any]) -> Optional[float]:
    candidates: List[tuple[str, float]] = []

    def _collect_from_mapping(mapping: Any) -> None:
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            k = str(key or "")
            if not k.startswith("price_struct_service_"):
                continue
            try:
                candidates.append((k, float(value)))
            except (TypeError, ValueError):
                continue

    _collect_from_mapping(user_inputs.get("concept_prices"))
    _collect_from_mapping(user_inputs)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _zones_from_economic_user_inputs(user_inputs: Dict[str, Any]) -> List[str]:
    """Extrae zonas A/B/C… desde claves ``price_struct_service_{zona}_``."""
    zones: List[str] = []
    sources: List[Any] = [user_inputs]
    cp = user_inputs.get("concept_prices")
    if isinstance(cp, dict):
        sources.append(cp)
    for mapping in sources:
        if not isinstance(mapping, dict):
            continue
        for key in mapping:
            m = re.search(r"price_struct_service_([a-z])_", str(key or "").lower())
            if not m:
                continue
            z = m.group(1).upper()
            if z not in zones:
                zones.append(z)
    return zones


def _mirror_source_has_cross_tender_marker(ref: Any, session_hint: str) -> bool:
    text = str(getattr(ref, "extracted_text", "") or "")
    return bool(detect_cross_tender_marker([text], session_hint))


def _should_block_by_quality_gate(
    *,
    total_items: int,
    generar_count: int,
    unknown_count: int,
    evidence_match_ratio: float,
    presentar_fisico_count: int = 0,
    triage_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Gate duro para frenar sobre-generación administrativa por clasificación débil.

    Excepción OBRA: en licitaciones de obra pública (LOPSRM / categoría OBRA),
    los formatos son predefinidos (AT/AE) que el licitante llena y presenta
    físicamente. Si generar_count == 0 pero hay ítems presentar_fisico, no es
    un error de clasificación — es el comportamiento esperado.
    """
    if not bool(app_settings.DOCUMENT_QUALITY_HARD_GATE_ENABLED):
        return {"block": False, "reason": "", "metrics": {}}

    # ── Excepción por categoría de licitación ──────────────────────────────
    tender_category = ""
    if isinstance(triage_context, dict):
        tender_category = str(triage_context.get("tender_category") or "").upper()

    if tender_category == "OBRA":
        if generar_count == 0 and presentar_fisico_count > 0:
            return {
                "block": False,
                "reason": "obra_category_no_generate_items_expected",
                "metrics": {
                    "total_items": total_items,
                    "generar_count": generar_count,
                    "presentar_fisico_count": presentar_fisico_count,
                    "tender_category": tender_category,
                    "evidence_match_ratio": evidence_match_ratio,
                },
            }
        if total_items == 0:
            return {"block": False, "reason": "", "metrics": {"tender_category": tender_category}}

    min_items = max(1, int(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3) or 3))
    max_unknown = float(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO", 0.6) or 0.6)
    min_evidence = float(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO", 0.5) or 0.5)
    if total_items < min_items:
        return {"block": False, "reason": "", "metrics": {}}
    unknown_ratio = (unknown_count / total_items) if total_items else 0.0
    if generar_count == 0:
        return {
            "block": True,
            "reason": "no_actionable_generate_items",
            "metrics": {
                "total_items": total_items,
                "generar_count": generar_count,
                "unknown_ratio": unknown_ratio,
                "evidence_match_ratio": evidence_match_ratio,
                "tender_category": tender_category or None,
            },
        }
    if unknown_ratio > max_unknown:
        return {
            "block": True,
            "reason": "unknown_ratio_above_threshold",
            "metrics": {
                "total_items": total_items,
                "generar_count": generar_count,
                "unknown_ratio": unknown_ratio,
                "threshold_unknown_ratio": max_unknown,
                "evidence_match_ratio": evidence_match_ratio,
                "tender_category": tender_category or None,
            },
        }
    if evidence_match_ratio < min_evidence:
        return {
            "block": True,
            "reason": "evidence_match_ratio_below_threshold",
            "metrics": {
                "total_items": total_items,
                "generar_count": generar_count,
                "unknown_ratio": unknown_ratio,
                "evidence_match_ratio": evidence_match_ratio,
                "threshold_evidence_match_ratio": min_evidence,
                "tender_category": tender_category or None,
            },
        }
    return {"block": False, "reason": "", "metrics": {}}


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
        self.template_engine = LegalTemplateEngine()
        self.vector_db = VectorDbServiceClient()

    @staticmethod
    def _template_id_for_requirement(req: Dict[str, Any]) -> str | None:
        """Mapea un requisito de formato a template legal bloqueado."""
        rid = str(req.get("id", "")).strip().lower()
        name = str(req.get("nombre", "")).strip().lower()
        desc = str(req.get("descripcion", "")).strip().lower()
        label_tax = str(req.get("label_taxonomica", "")).strip().lower()
        text = f"{rid} {name} {desc} {label_tax}"
        if "anexo 7" in text or "personalidad" in text:
            return "anexo_7"
        if "anexo 11" in text or "conformidad" in text:
            return "anexo_11"
        if "anexo 15" in text or "50" in text or "60" in text:
            return "anexo_15"
        if "decl_integridad" in text or "no colusion" in text or "colusión" in text:
            return "decl_integridad_no_colusion"
        if "decl_mipyme" in text or "mipyme" in text or "estratificacion" in text or "estratificación" in text:
            return "decl_mipyme"
        return None

    def _template_data(self, session_id: str, master_profile: Dict[str, Any], metadata: Dict[str, Any], economic_overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """Construye datos dinámicos para render de templates legales."""
        domicilio = master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
        lugar = (
            master_profile.get("ciudad")
            or (str(domicilio).split("|", 1)[0].strip() if domicilio else "")
            or "México"
        )
        actividad_principal = (
            master_profile.get("actividad_principal")
            or master_profile.get("giro")
            or "prestación de servicios"
        )
        data = {
            "razon_social": master_profile.get("razon_social", "N/A"),
            "rfc": master_profile.get("rfc", "N/A"),
            "numero_licitacion": session_id,
            "servicio": master_profile.get("giro", "servicio licitado"),
            "nombre_representante": master_profile.get("representante_legal", "N/A"),
            "domicilio": domicilio,
            "lugar": lugar,
            "fecha": metadata.get("fecha", ""),
            "tipo_licitacion": "Licitacion Publica",
            "autoridad_convocante": "Convocante",
            "actividad_principal": actividad_principal,
        }
        # Hito 3.2: Inyectar overrides económicos en el diccionario de la plantilla
        if economic_overrides:
            for k, v in economic_overrides.items():
                if k != "concept_prices":
                    data[f"econ_{k}"] = v
        return data

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        started_at = time.perf_counter()
        llm = self.llm
        context = await self.context_manager.get_global_context(session_id)

        # 1. RECUPERAR DATOS DE IDENTIDAD (PRODUCCIÓN)
        company_data = agent_input.company_data or {}
        master_profile = company_data.get("master_profile", {})
        
        if not master_profile:
            state = await self.context_manager.memory.get_session(session_id)
            if state and "initial_data" in state:
                master_profile = state["initial_data"].get("company_data", {}).get("master_profile", {})
        if not master_profile and agent_input.company_id:
            try:
                company_db = await self.context_manager.memory.get_company(str(agent_input.company_id))
                if isinstance(company_db, dict):
                    master_profile = company_db.get("master_profile") or company_db.get("catalog") or {}
            except Exception:
                pass

        tipo_persona = master_profile.get("tipo", "moral").lower()
        razon_social = master_profile.get("razon_social", "EMPRESA SIN REGISTRO")
        rfc = master_profile.get("rfc")
        representante = master_profile.get("representante_legal")

        # --- Hito 4: piloto bloqueo por slots (sin escribir bajo /data/outputs) ---
        missing_slots = build_formats_pilot_missing_entries(
            master_profile,
            blocking_job_id=agent_input.job_id,
        )
        if missing_slots:
            field_keys = [m["field"] for m in missing_slots]
            logger.info(
                "formats_pilot_blocked",
                agent_id=self.agent_id,
                session_id=session_id,
                correlation_id=correlation_id,
                blocking_job_id=agent_input.job_id,
                pilot="formats_administrativo",
                missing_fields=field_keys,
                missing_count=len(missing_slots),
            )
            await self._save_pending_questions(session_id, missing_slots)

            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=f"Para generar tus documentos necesito: {', '.join([m['label'] for m in missing_slots])}",
                data={"missing": missing_slots},
                correlation_id=correlation_id,
            )

        # Valores seguros después de validación
        rfc = rfc or "N/A"
        representante = representante or (razon_social if tipo_persona == "fisica" else "N/A")
        
        # Lógica de Redacción Universal (Yo vs Nosotros)
        pronombres = "en primera persona ('Yo', 'mi empresa')" if tipo_persona == "fisica" else "en representación de la empresa ('Nosotros', 'la empresa')"
        system_prompt = (
            f"ERES UN REDACTOR LEGAL EXPERTO EN LICITACIONES MEXICANAS. Escribe {pronombres}. "
            "REGLA DE ORO (ESPEJO ESTRICTO): Si se te proporciona una 'PLANTILLA OFICIAL O FORMATO DE LAS BASES', "
            "tu tarea es realizar una TRANSCRIPCIÓN FIEL. Mantén la estructura, todas las columnas de las tablas, "
            "el orden de los párrafos y el lenguaje legal exacto. "
            "SOLO debes rellenar los datos de la empresa, fechas y placeholders. "
            "ESTÁ PROHIBIDO omitir secciones, simplificar tablas o cambiar el formato original. "
            "Si el contexto muestra una tabla con columnas específicas, genera esa tabla EXACTAMENTE IGUAL. "
            "Nunca escribas 'Dato pendiente de confirmar', nunca dejes blancos reales y nunca cites una institución "
            "o convocante distinta a la del procedimiento actual. Si no tienes un dato variable, omite la cláusula "
            "o devuelve solo el texto sustentado por contexto real. "
            f"{ANTI_PLACEHOLDER_PROMPT_RULE}"
        )

        # Buscar logo real
        logo_path = master_profile.get("logo")
        if not logo_path:
            logo_info = company_data.get("docs", {}).get("LOGOTIPO", {})
            if logo_info and isinstance(logo_info, dict):
                logo_path = logo_info.get("path")

        # Metadata para Word
        _MESES_F = {
            "January": "enero", "February": "febrero", "March": "marzo",
            "April": "abril", "May": "mayo", "June": "junio",
            "July": "julio", "August": "agosto", "September": "septiembre",
            "October": "octubre", "November": "noviembre", "December": "diciembre"
        }
        _fecha_f = datetime.now().strftime("%d de %B de %Y")
        for _en, _es in _MESES_F.items():
            _fecha_f = _fecha_f.replace(_en, _es)

        doc_metadata = {
            "logo_path": logo_path,
            "tender_name": session_id.replace("_", " ").upper(),
            "fecha": _fecha_f,
            "empresa": razon_social,
            "rfc": rfc,
            "representante": representante,
            "footer_text": f"{razon_social} | RFC: {rfc} | Domicilio: {master_profile.get('domicilio_fiscal', 'S/D')}"
        }

        # --- Hito 3.2: Inyectar Overrides Económicos ---
        session_state = context.get("session_state", {})
        user_inputs = session_state.get("economic_user_inputs") or {}
        econ_parts = []
        for k, v in user_inputs.items():
            if k == "concept_prices" and isinstance(v, dict):
                for c, p in v.items():
                    econ_parts.append(f"Precio Unitario de {c.upper()}: {p}")
            elif v is not None:
                lbl = k.replace("_", " ").upper()
                econ_parts.append(f"{lbl}: {v}")
        
        economic_block = ""
        if econ_parts:
            economic_block = "\nDATOS ECONÓMICOS CONFIRMADOS (USAR ESTOS VALORES SI EL DOCUMENTO LO REQUIERE):\n" + "\n".join(econ_parts)

        try:
            from app.services.mini_dictamen_anexos_service import (
                build_and_persist_mini_dictamen,
                build_stage_blocking_questions,
                get_blocking_annex_rows_for_stage,
            )

            await build_and_persist_mini_dictamen(self.context_manager.memory, session_id)
            fresh_state = await self.context_manager.memory.get_session(session_id) or session_state
            blocking_rows = get_blocking_annex_rows_for_stage(fresh_state, "formats")
            if blocking_rows:
                fresh_state["pending_questions"] = build_stage_blocking_questions(
                    "formats", blocking_rows
                ) + list(fresh_state.get("pending_questions") or [])
                fresh_state["current_question_index"] = 0
                await self.context_manager.memory.save_session(session_id, fresh_state)
                return AgentOutput(
                    status=AgentStatus.WAITING_FOR_DATA,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message=(
                        "La generación administrativa quedó bloqueada por anexos obligatorios "
                        "con fuente inválida, referencial o pendiente de aclaración."
                    ),
                    data={"missing": blocking_rows},
                    correlation_id=correlation_id,
                )
        except Exception as exc:
            logger.warning(
                "formats_mini_dictamen_guard_failed",
                session_id=session_id,
                error=str(exc),
            )

        # 2. RECUPERAR LISTA MAESTRA (SINCRONIZACIÓN CORONACIÓN)
        # Orden de prioridad:
        # a) Inyección directa del orquestador via compliance_master_list
        # b) Resultados de Fase 1 via results.compliance.data
        # c) Tarea persistida master_compliance_list en tasks_completed
        session_state = context.get("session_state", {})
        tasks = session_state.get("tasks_completed", [])
        compliance_data: Dict[str, Any] = {}
        injected = company_data.get("compliance_master_list")
        if isinstance(injected, dict) and injected:
            compliance_data = injected
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
        reqs_to_process: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        raw_list = compliance_data.get("administrativo", []) + compliance_data.get("formatos", [])
        action_counts: Dict[str, int] = {"generar": 0, "presentar_fisico": 0, "informativo": 0, "unknown": 0}
        total_candidates = len(raw_list)
        evidence_true = sum(1 for r in raw_list if bool(r.get("evidence_match")))
        evidence_ratio = (evidence_true / total_candidates) if total_candidates else 1.0

        admin_output_dir = os.path.join(
            "/data", "outputs", session_id, "3.documentos administrativos"
        )
        os.makedirs(admin_output_dir, exist_ok=True)

        # Contador de formas numeradas por prefijo para detectar alucinaciones secuenciales
        _numbered_form_counts: Dict[str, int] = {}

        from app.config.settings import settings
        from app.services.document_deliverable_filter import (
            has_admin_format_template_evidence,
            is_company_credential_present_only,
            is_economic_writer_domain,
            is_generable_tipo_accion,
            normalize_deliverable_key,
            should_show_deliverable_in_ui,
        )

        seen_sigs: Set[str] = set()

        for req in raw_list:
            rid = str(req.get("id", "")).strip().replace(".", "_")
            raw_name = req.get("nombre", "Documento")
            if not rid or rid in seen_ids:
                continue

            raw_name_u = str(raw_name or "")
            desc_u = str(req.get("descripcion", "") or "")
            if not should_show_deliverable_in_ui(
                raw_name_u,
                desc_u,
                str(req.get("snippet") or ""),
                str(req.get("tipo_accion") or ""),
            ):
                seen_ids.add(rid)
                logger.info(
                    "formats_causal_item_skipped",
                    session_id=session_id,
                    rid=rid,
                    nombre=raw_name_u[:80],
                )
                continue

            # Si el compliance clasificó tipo_accion, usarlo directamente
            tipo_accion = str(req.get("tipo_accion", "")).lower()
            if tipo_accion not in action_counts:
                tipo_accion = "unknown"
            action_counts[tipo_accion] = action_counts.get(tipo_accion, 0) + 1
            if not is_generable_tipo_accion(tipo_accion):
                seen_ids.add(rid)
                continue
            if is_company_credential_present_only(
                raw_name_u, desc_u, str(req.get("snippet") or "")
            ):
                seen_ids.add(rid)
                logger.info(
                    "formats_company_credential_skipped",
                    session_id=session_id,
                    rid=rid,
                    nombre=raw_name_u[:80],
                )
                continue
            if is_economic_writer_domain(raw_name_u, desc_u, str(req.get("snippet") or "")):
                seen_ids.add(rid)
                continue

            blob_ids = f"{rid} {raw_name_u} {desc_u}".upper()

            # ── FILTRO ANTI-ALUCINACIÓN ──────────────────────────────────────────
            # Ítems con tipo_accion == "unknown" y patrón de forma numerada (DD-NN,
            # AT-NN, AE-NN) sin evidencia real son candidatos a alucinación del LLM.
            # El LLM ve DD-01..DD-10 en las bases y "completa" la secuencia hasta
            # DD-29 con descripciones genéricas. Filtramos estos ítems si:
            #   1. tipo_accion es "unknown" (el LLM no los clasificó como "generar")
            #   2. Tienen patrón de forma numerada (DD-NN, AT-NN, AE-NN)
            #   3. NO tienen evidence_match = True (no hay snippet literal en las bases)
            #   4. El snippet es vacío o muy corto (< 20 chars)
            # Excepción: si tipo_accion == "generar", el LLM lo clasificó explícitamente
            # y lo dejamos pasar aunque no tenga evidencia perfecta.
            if tipo_accion == "unknown":
                _numbered_form_match = re.search(
                    r"\b(DD|AT|AE|FO|DC)[-_]?\d{1,2}\b", blob_ids
                )
                if _numbered_form_match:
                    has_evidence = bool(req.get("evidence_match"))
                    snippet = str(req.get("snippet") or "").strip()
                    has_real_snippet = len(snippet) >= 20
                    if not has_evidence and not has_real_snippet:
                        # Alucinación probable: forma numerada sin evidencia literal
                        logger.info(
                            "formats_hallucinated_form_discarded",
                            session_id=session_id,
                            rid=rid,
                            nombre=raw_name_u[:80],
                            reason="numbered_form_no_evidence",
                        )
                        seen_ids.add(rid)  # Marcar como visto para no re-procesar
                        continue

            if not has_admin_format_template_evidence(req):
                seen_ids.add(rid)
                logger.info(
                    "formats_no_template_evidence_skipped",
                    session_id=session_id,
                    rid=rid,
                    nombre=raw_name_u[:80],
                )
                continue

            sig = normalize_deliverable_key(raw_name_u, "administrativo")
            if sig in seen_sigs:
                seen_ids.add(rid)
                continue
            seen_sigs.add(sig)
            reqs_to_process.append(req)
            seen_ids.add(rid)

        gate = _should_block_by_quality_gate(
            total_items=total_candidates,
            generar_count=action_counts.get("generar", 0),
            unknown_count=action_counts.get("unknown", 0),
            evidence_match_ratio=evidence_ratio,
            presentar_fisico_count=action_counts.get("presentar_fisico", 0),
            triage_context=agent_input.triage_context,
        )
        if gate.get("block"):
            # En lugar de bloquear al usuario con un pendiente técnico,
            # logueamos la situación y continuamos con lo que tenemos.
            # El gate solo interrumpe si no hay absolutamente nada que generar
            # Y no hay documentos para presentar físicamente.
            has_anything_to_do = (
                action_counts.get("generar", 0) > 0
                or action_counts.get("presentar_fisico", 0) > 0
                or len(reqs_to_process) > 0
            )
            logger.warning(
                "formats_quality_gate_triggered",
                session_id=session_id,
                reason=str(gate.get("reason")),
                metrics=gate.get("metrics"),
                continuing=has_anything_to_do,
            )
            if not has_anything_to_do:
                # Solo bloquear si realmente no hay nada que hacer
                missing = [
                    {
                        "field": "document_quality_gate",
                        "label": "Confirmar clasificación documental administrativa",
                        "question": (
                            "La lista administrativa/formatos no es lo suficientemente confiable "
                            "para generar documentos automáticamente. Requiere reclasificación por acción "
                            "o evidencia más sólida."
                        ),
                        "document_hint": f"Motivo gate: {gate.get('reason')}. Métricas: {gate.get('metrics')}",
                        "type": "document_quality_gate_blocking",
                        "blocking_items": [],
                    }
                ]
                await self._save_pending_questions(session_id, missing)
                return AgentOutput(
                    status=AgentStatus.WAITING_FOR_DATA,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message=(
                        "Pausa por calidad documental: la clasificación de formatos/administrativos "
                        "no es suficientemente confiable para generar archivos sin riesgo."
                    ),
                    data={"missing": missing, "document_quality_gate": gate},
                    correlation_id=correlation_id,
                )

        from app.services.ingested_file_resolver import (
            build_ingested_file_index,
            resolve_ingested_file,
        )
        from app.services.session_template_catalog import build_catalog_mirror_reqs
        from app.services.template_mirror_service import mirror_template_to_output

        session_documents: List[Dict[str, Any]] = []
        try:
            session_documents = await self.context_manager.memory.get_documents(session_id)
        except Exception as doc_exc:
            logger.warning("formats_get_documents_failed", session_id=session_id, error=str(doc_exc))

        file_index = build_ingested_file_index(session_documents)
        catalog_reqs = build_catalog_mirror_reqs(
            session_state,
            seen_ids,
            exclude_sobre=("economico",),
        )
        reqs_to_process = catalog_reqs + reqs_to_process

        mirror_enabled = bool(getattr(settings, "TEMPLATE_MIRROR_ENABLED", True))
        mirror_max = int(getattr(settings, "TEMPLATE_MIRROR_MAX_ADMIN", 40) or 40)
        mirror_queue: List[tuple] = []
        llm_queue: List[Dict[str, Any]] = []
        unresolved_catalog_mirrors: List[str] = []
        session_hint = f"{session_id} {session_state.get('name', '')}"
        for req in reqs_to_process:
            q = str(req.get("archivo_fuente") or req.get("nombre") or "")
            ref = resolve_ingested_file(
                q,
                file_index,
                doc_id=req.get("source_doc_id"),
                source_path=req.get("source_path"),
            )
            ext = (ref.file_path.rsplit(".", 1)[-1].lower() if ref and ref.file_path else "")
            if bool(req.get("from_session_catalog")) and not ref:
                unresolved_catalog_mirrors.append(str(req.get("nombre") or q or "sin_nombre"))
                logger.warning(
                    "formats_catalog_source_unresolved_skip_llm",
                    session_id=session_id,
                    requested=q,
                    source_doc_id=str(req.get("source_doc_id") or ""),
                    source_path=str(req.get("source_path") or ""),
                )
                continue
            if mirror_enabled and ref and ext in ("doc", "docx", "xls", "xlsx"):
                if _mirror_source_has_cross_tender_marker(ref, session_hint):
                    if bool(req.get("from_session_catalog")):
                        logger.warning(
                            "formats_catalog_cross_tender_skip_llm",
                            session_id=session_id,
                            requested=q,
                            source_filename=ref.filename,
                        )
                        continue
                    fallback_req = dict(req)
                    fallback_req["archivo_fuente"] = ""
                    fallback_req["cross_tender_mirror_skipped"] = True
                    fallback_req["mirror_conflict_source"] = ref.filename
                    llm_queue.append(fallback_req)
                    continue
                mirror_queue.append((req, ref))
            else:
                llm_queue.append(req)

        if unresolved_catalog_mirrors:
            logger.warning(
                "formats_catalog_mirror_sources_unresolved",
                session_id=session_id,
                count=len(unresolved_catalog_mirrors),
                names=unresolved_catalog_mirrors[:10],
            )

        if mirror_max > 0 and len(mirror_queue) > mirror_max:
            mirror_queue = mirror_queue[:mirror_max]

        max_formats = int(getattr(settings, "FORMATS_MAX_GENERABLE_DOCS", 18) or 18)
        if max_formats > 0 and len(llm_queue) > max_formats:
            llm_queue = llm_queue[:max_formats]

        _merge_document_inventory_legal(company_data, admin_output_dir, llm_queue, seen_ids)

        logger.info(
            "formats_generation_started",
            agent=self.agent_id,
            session_id=session_id,
            mirror_count=len(mirror_queue),
            llm_count=len(llm_queue),
        )

        generated_files = []
        zonas_detectadas: list[str] = []
        zone_sources: List[str] = []
        for req_item in list(mirror_queue) + [(item, None) for item in llm_queue]:
            req_data = req_item[0] if isinstance(req_item, tuple) else req_item
            zone_sources.append(
                " ".join(str(req_data.get(k) or "") for k in ("nombre", "descripcion", "titulo", "label"))
            )
        for doc in session_documents:
            if not isinstance(doc, dict):
                continue
            content = doc.get("content") if isinstance(doc.get("content"), dict) else {}
            metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
            zone_sources.append(
                " ".join(
                    str(v or "")
                    for v in (
                        content.get("filename"),
                        content.get("doc_type"),
                        metadata.get("filename"),
                        metadata.get("doc_type"),
                        metadata.get("title"),
                    )
                )
            )
        for blob in zone_sources:
            for zone in re.findall(r"\bzona\s+([A-Z])\b", blob, flags=re.IGNORECASE):
                z = str(zone).upper()
                if z not in zonas_detectadas:
                    zonas_detectadas.append(z)
        for z in _zones_from_economic_user_inputs(user_inputs):
            if z not in zonas_detectadas:
                zonas_detectadas.append(z)
        zonas_ofertadas = ", ".join(zonas_detectadas[:-1]) + (" y " + zonas_detectadas[-1] if len(zonas_detectadas) > 1 else (zonas_detectadas[0] if zonas_detectadas else ""))
        profile_fill = {
            "rfc": rfc,
            "razon_social": razon_social,
            "representante_legal": representante,
            "domicilio": master_profile.get("domicilio_fiscal") or master_profile.get("domicilio"),
            "fecha": doc_metadata.get("fecha"),
            "licitacion": doc_metadata.get("tender_name") or session_id,
            "zonas_ofertadas": zonas_ofertadas,
            "numero_referencia": doc_metadata.get("tender_name") or session_id,
            "tarifa_mensual_referencia": _pick_reference_service_price(user_inputs),
        }
        contenido_nacional_pct = _infer_formats_contenido_nacional_pct(self.vector_db, session_id)

        def _mirror_output_dir(req_item: Dict[str, Any]) -> str:
            base = os.path.join("/data", "outputs", session_id)
            sobre = str(req_item.get("sobre_inferido") or "")
            tipo = str(req_item.get("tipo") or "").lower()
            if sobre == "tecnico" or tipo == "tecnico":
                sub = "1.propuesta tecnica"
            elif sobre == "economico":
                sub = "2.propuesta_economica"
            else:
                sub = "3.documentos administrativos"
            path = os.path.join(base, sub)
            os.makedirs(path, exist_ok=True)
            return path

        for req, ref in mirror_queue:
            rid = str(req.get("id", "")).strip().replace(".", "_")
            raw_name = req.get("nombre", "Documento")
            safe_name = re.sub(r"[^\w\s-]", "", str(raw_name).replace(" ", "_"))[:60].strip("_")
            filename = f"{rid}_{safe_name}" if rid else safe_name
            filename = re.sub(r"_+", "_", filename).strip("_")
            src_ext = ref.file_path.rsplit(".", 1)[-1].lower()
            out_ext = ".docx" if src_ext == "doc" else f".{src_ext}"
            if out_ext not in (".docx", ".xlsx", ".xls"):
                out_ext = ".docx"
            output_dir = _mirror_output_dir(req)
            filepath = os.path.join(output_dir, f"{filename}{out_ext}")
            if _formats_inventory_doc_exists(output_dir, rid):
                continue
            try:
                normalized_name = _normalize_formats_blob(raw_name or ref.filename)
                if "contenido nacional" in normalized_name:
                    contenido_text = _build_formats_contenido_nacional_text(
                        razon_social=razon_social,
                        rfc=rfc,
                        representante=representante,
                        session_id=session_id,
                        tender_name=doc_metadata.get("tender_name") or session_id,
                        fecha_es=doc_metadata.get("fecha") or "",
                        zonas=zonas_detectadas,
                        porcentaje=contenido_nacional_pct,
                    )
                    _save_docx(raw_name, contenido_text, filepath, doc_metadata)
                    meta = {
                        "ruta": filepath,
                        "mirror_mode": "deterministic_contenido_nacional",
                        "materialization_route": "mirror",
                        "source_filename": ref.filename,
                        "source_path": ref.file_path,
                        "source_hash": safe_file_sha256(ref.file_path),
                        "output_hash": safe_file_sha256(filepath),
                    }
                else:
                    meta = mirror_template_to_output(
                        ref,
                        filepath,
                        profile_fill,
                        fill_profile=True,
                    )
                generated_files.append(
                    attach_traceability(
                        {
                        "nombre": raw_name,
                        "ruta": meta["ruta"],
                        "status": "FINAL",
                        "tipo": str(req.get("tipo") or "administrativo"),
                        "template_id": None,
                        },
                        source_doc_id=str(ref.doc_id or req.get("source_doc_id") or "") or None,
                        source_filename=ref.filename,
                        source_path=meta.get("source_path") or ref.file_path,
                        source_hash=meta.get("source_hash"),
                        template_id=None,
                        mirror_mode=meta.get("mirror_mode"),
                        materialization_route=meta.get("materialization_route") or "mirror",
                        output_hash=meta.get("output_hash") or safe_file_sha256(meta.get("ruta")),
                        provenance_ui=req.get("provenance_ui") if isinstance(req.get("provenance_ui"), dict) else None,
                    )
                )
                logger.info(
                    "formats_mirror_ok",
                    session_id=session_id,
                    source=ref.filename,
                    mode=meta.get("mirror_mode"),
                )
            except Exception as mir_exc:
                logger.warning(
                    "formats_mirror_failed",
                    session_id=session_id,
                    source=ref.filename,
                    error=str(mir_exc),
                )
                llm_queue.append(req)

        for req in llm_queue:
            rid = str(req.get("id", "")).strip().replace(".", "_")
            raw_name = req.get('nombre', 'Documento')
            # Usar nombre completo (hasta 60 chars) para evitar colisiones de nombre de archivo
            safe_name = re.sub(r'[^\w\s-]', '', raw_name.replace(' ', '_'))[:60].strip('_')
            filename = f"{rid}_{safe_name}" if rid else safe_name
            filename = re.sub(r'_+', '_', filename).strip('_')
            
            template_id = self._template_id_for_requirement(req)
            req_nombre = raw_name
            req_desc = str(req.get("descripcion") or "")
            req_snippet = str(req.get("snippet") or "")
            req_source = str(req.get("archivo_fuente") or "").strip()
            req_context = ""
            context_type = "FRAGMENTADO (RAG)"
            try:
                if req_source and req_source.lower().endswith(".pdf"):
                    logger.info(
                        "formats_mirror_protocol_activated",
                        session_id=session_id,
                        source=req_source,
                    )
                    req_context = self.vector_db.get_full_document_text(session_id, req_source)
                    context_type = "ESPEJO COMPLETO (TEMPLATE OFICIAL)"
                if not req_context:
                    rag_query = f"{req_nombre} {req_desc} {req_snippet}".strip()
                    req_context_res = self.vector_db.query_texts(session_id, rag_query, n_results=5)
                    docs = req_context_res.get("documents", []) if req_context_res else []
                    req_context = "\n".join(d for d in docs[:4] if d and d.strip())
            except Exception as _rag_err:
                logger.warning(
                    "formats_context_retrieval_failed",
                    agent=self.agent_id,
                    req_name=req_nombre[:80],
                    error=str(_rag_err),
                )

            hint = req.get("generator_hint")
            hint_line = f"\nGUÍA_DE_PLANTILLA_O_CLAVE: {hint}" if hint else ""
            bases_context_block = (
                f"\n--- INICIO DE {context_type} ---\n{req_context}\n--- FIN DE {context_type} ---\n"
                if req_context
                else ""
            )
            prompt = (
                f"Genera el contenido legal oficial para el requisito {req.get('id')}: {req_nombre}\n"
                f"Descripción: {req_desc}\nEmpresa: {razon_social}\n"
                f"Representante: {representante}\nRFC: {rfc}\n"
                f"Domicilio: {master_profile.get('domicilio_fiscal', '')}\n"
                f"{bases_context_block}\n"
                f"{economic_block}\n{hint_line}"
            )

            content = ""
            materialization_route = "generate_controlled"
            if template_id:
                tpl_data = self._template_data(session_id, master_profile, doc_metadata, user_inputs)
                content = self.template_engine.render(template_id, tpl_data)
                if not self.template_engine.verify_integrity(content, template_id):
                    raise TemplateIntegrityError(f"Integridad inválida para template {template_id}")
                materialization_route = "template_locked"
            else:
                resp = await llm.generate(
                    prompt=prompt, system_prompt=system_prompt, correlation_id=correlation_id
                )
                if not resp.success:
                    logger.error(
                        "llm_generation_failed",
                        agent=self.agent_id,
                        req_name=raw_name,
                        error=resp.error,
                    )
                    continue
                llm_content = (resp.response or "").strip()
                if llm_content:
                    content = llm_content
            if not content.strip():
                logger.warning("llm_empty_response", agent=self.agent_id, req_name=raw_name)
                continue

            content = _sanitize_legal_content(
                content,
                session_id=session_id,
                metadata=doc_metadata,
            )
            
            filepath = os.path.join(_mirror_output_dir(req), f"{filename}.docx")
            try:
                _save_docx(f"{rid} - {raw_name}", content, filepath, doc_metadata)
                _display = raw_name if str(raw_name).lower().endswith(".docx") else f"{raw_name}.docx"
                generated_files.append(
                    attach_traceability(
                        {
                            "nombre": raw_name,
                            "source_filename": str(req.get("archivo_fuente") or _display).strip() or _display,
                            "ruta": filepath,
                            "status": "FINAL",
                            "tipo": str(req.get("tipo") or "administrativo"),
                            "template_id": template_id,
                            "template_static_hash": self.template_engine.static_hash(template_id) if template_id else None,
                        },
                        source_doc_id=str(req.get("source_doc_id") or "") or None,
                        source_filename=str(req.get("archivo_fuente") or _display).strip() or _display,
                        source_path=str(req.get("source_path") or "") or None,
                        source_hash=safe_file_sha256(str(req.get("source_path") or "")),
                        template_id=template_id,
                        mirror_mode=None,
                        materialization_route=materialization_route,
                        output_hash=safe_file_sha256(filepath),
                        provenance_ui=req.get("provenance_ui") if isinstance(req.get("provenance_ui"), dict) else None,
                    )
                )
                logger.info("docx_generated", agent=self.agent_id, filename=filename)
            except Exception as e:
                logger.error("docx_save_failed", agent=self.agent_id, filename=filename, error=str(e))

        result_data = {
            "documentos": generated_files,
            "count": len(generated_files),
            "folder": admin_output_dir,
            "action_type_stats": action_counts,
            "materialization_metrics": build_materialization_metrics(
                stage="formats",
                documents=generated_files,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        }
        fill_gate = validate_generated_documents_fill(
            stage="formats",
            generated_documents=generated_files,
            master_profile=master_profile,
            provenance_context={
                "source": "formats_writer",
                "confidence": 0.9,
                "session_hint": session_hint,
            },
        )
        result_data["document_fill_quality_gate"] = fill_gate
        result_data["validation_events"] = [
            validation_mapping_service.build_event(
                error_type=it.get("error_type"),
                context={
                    "document_id": it.get("document_id"),
                    "field_key": it.get("field_key"),
                    "detected_value": it.get("detected_value"),
                    "expected_rule": it.get("expected_rule"),
                },
                raw_message=f"Validación en {it.get('document_id')}: {it.get('field_key')}"
            )
            for it in (fill_gate.get("issues") or [])
        ]
        if not bool(fill_gate.get("validation_passed", True)):
            missing = [
                {
                    "field": "document_fill_quality_gate",
                    "label": "Corregir llenado documental administrativo",
                    "question": (
                        "Se detectaron inconsistencias o placeholders en documentos administrativos generados. "
                        "Corrige perfil/fuentes y vuelve a generar."
                    ),
                    "document_hint": f"Gate llenado: {fill_gate.get('metrics')}",
                    "type": "document_fill_quality_gate_blocking",
                    "blocking_items": fill_gate.get("issues") or [],
                }
            ]
            await self._save_pending_questions(session_id, missing)
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message="Pausa por calidad de llenado documental administrativo.",
                data={**result_data, "missing": missing},
                correlation_id=correlation_id,
            )
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

    # --- PROCESAMIENTO DE CUERPO CON SOPORTE PARA TABLAS NATIVAS ---
    raw_lines = (content or "").split("\n")
    table_buffer: List[str] = []
    
    def flush_table(buffer: List[str]):
        if not buffer: return
        matrix = parse_markdown_table(buffer)
        if not matrix: return
        
        # Crear tabla real en Word
        rows = len(matrix)
        cols = max(len(row) for row in matrix)
        table = doc.add_table(rows=rows, cols=cols)
        table.style = 'Table Grid' # Borde estándar oficial
        
        for r_idx, row_data in enumerate(matrix):
            row_cells = table.rows[r_idx].cells
            for c_idx, cell_text in enumerate(row_data):
                if c_idx < cols:
                    cell_p = row_cells[c_idx].paragraphs[0]
                    # Limpiar markdown del texto de la celda
                    clean_text = strip_markdown_for_docx(cell_text)
                    run = cell_p.add_run(clean_text)
                    if r_idx == 0: # Negrita para cabeceras
                        run.bold = True
                    cell_p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    for line in raw_lines:
        if is_markdown_table_line(line):
            table_buffer.append(line)
            continue
        
        # Si veníamos procesando una tabla y esta línea no lo es, imprimir tabla acumulada
        if table_buffer:
            flush_table(table_buffer)
            table_buffer = []
            
        if line.strip():
            clean_p = strip_markdown_for_docx(line)
            if clean_p.strip():
                p = doc.add_paragraph(clean_p)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    
    # Imprimir tabla final si quedó en buffer
    if table_buffer:
        flush_table(table_buffer)
            
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
