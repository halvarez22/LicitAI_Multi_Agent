import os
import re
import unicodedata
import json
import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.vector_service import VectorDbServiceClient
from app.services.resilient_llm import ResilientLLMClient
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.contracts.document_inventory import (
    DocumentEnvelope,
    DocumentInventory,
    InventoryItemStatus,
)
from app.core.formats_pilot_slots import build_formats_pilot_missing_entries
from app.core.observability import get_logger
from app.utils.doc_formatting import ANTI_PLACEHOLDER_PROMPT_RULE, strip_markdown_for_docx
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.services.document_fill_quality_gate import validate_generated_documents_fill
from app.services.validation_service import validation_mapping_service
from app.config.settings import settings as app_settings

logger = get_logger(__name__)

# Prefijos de ID que identifican un requisito como redactable técnicamente.
# Provienen del esquema de IDs que asigna ComplianceAgent (zona "tecnico").
TECH_ID_PREFIXES = ("2.",)


def _is_technical_writable(req: Dict[str, Any]) -> bool:
    """Incluye requisitos técnicos aunque el id no sea 2.x (p. ej. Forma AT- en cap. 7)."""
    r_id = str(req.get("id", ""))
    nombre = str(req.get("nombre", "")).upper()
    descripcion = str(req.get("descripcion", "")).upper()
    blob = f"{r_id} {nombre} {descripcion}".upper()

    # Si el compliance ya clasificó el tipo_accion, usarlo directamente
    tipo_accion = str(req.get("tipo_accion", "")).lower()
    if tipo_accion == "generar":
        return True
    if tipo_accion in ("informativo", "presentar_fisico", "requiere_datos_licitante"):
        return False

    # Excluir requisitos informativos de las bases que NO son documentos a redactar
    _INFORMATIVE_BASES_PATTERNS = (
        "FECHA Y HORA DE LOS EVENTOS",
        "FECHA Y HORA DEL ACTO",
        "VISITA AL SITIO",
        "JUNTA DE ACLARACIONES",
        "LUGAR DE ENTREGA",
        "FORMATO DE PRESENTACION",
        "FORMATO DE PROPUESTA ECONOMICA",
        "APERTURA DE PROPUESTAS",
        "ACTO DE PRESENTACION",
        "PRESENTACION DE LAS PROPUESTAS",
        "LECTURA DEL DICTAMEN",
        "EL COMITE ANALIZARA",
        "LA PROPUESTA TECNICA DEBERA DESCRIBIR",
    )
    if any(p in blob for p in _INFORMATIVE_BASES_PATTERNS):
        return False

    if req.get("tipo") == "tecnico":
        return True
    if req.get("inventory_synthetic") is True:
        return True
    if any(r_id.startswith(p) for p in TECH_ID_PREFIXES):
        return True
    if re.search(r"\bAT[-_]?\d", blob):
        return True
    keys = (
        "PROGRAMA",
        "RELACIÓN",
        "RELACION",
        "MAQUINARIA",
        "EXPERIENCIA",
        "SUPERINTENDENTE",
        "SUPERVISOR",
        "CURRÍCULUM",
        "CURRICULUM",
        "CAPACIDAD FINANCIERA",
        "CONTRATOS EN VIGOR",
        "MODELO DE CONTRATO",
        "PROPUESTA TÉCNICA",
        "PROPUESTA TECNICA",
        "INSTALACIÓN",
        "INSTALACION",
        "CALENDARIZ",
    )
    return any(k in blob for k in keys)


def _inventory_doc_already_on_disk(tech_dir: str, canonical_id: str) -> bool:
    """Evita regenerar si ya existe un .docx cuyo nombre incluye el canonical_id."""
    if not canonical_id or not os.path.isdir(tech_dir):
        return False
    token = re.sub(r"[^\w\-]+", "_", canonical_id).strip("_").lower()
    if len(token) < 3:
        return False
    try:
        for fn in os.listdir(tech_dir):
            if not fn.endswith(".docx") or fn.startswith("~$"):
                continue
            if token in fn.lower():
                return True
    except OSError:
        return False
    return False


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
    Gate duro: evita generación cuando la lista documental está degradada.

    Excepción OBRA: en licitaciones de obra pública (LOPSRM / categoría OBRA),
    los requisitos técnicos son formas predefinidas (AT-10, AT-13, AE-02) que el
    licitante llena y presenta físicamente. El ComplianceAgent los clasifica
    correctamente como presentar_fisico. Si generar_count == 0 pero hay ítems
    presentar_fisico, no es un error de clasificación — es el comportamiento
    esperado para este tipo de licitación.
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


def _merge_document_inventory_technical(
    company_data: Dict[str, Any],
    tech_dir: str,
    tech_requirements: List[Dict[str, Any]],
    seen_ids: Set[str],
) -> List[Dict[str, Any]]:
    """
    Añade tareas desde ``document_inventory`` (Modo Fábrica): categoría técnica y pendiente.

    Los dicts resultantes son compatibles con el bucle de generación existente.
    """
    raw = company_data.get("document_inventory")
    if not isinstance(raw, dict) or not raw.get("items"):
        return tech_requirements
    try:
        inv = DocumentInventory.model_validate(raw)
    except Exception as e:
        logger.warning("technical_writer_inventory_parse_failed", error=str(e))
        return tech_requirements

    extra: List[Dict[str, Any]] = []
    for it in inv.items:
        if it.category != DocumentEnvelope.TECHNICAL:
            continue
        if it.status != InventoryItemStatus.PENDING:
            continue
        cid = (it.canonical_id or "").strip()
        if not cid:
            continue
        key = cid.lower()
        if key in seen_ids:
            continue
        if _inventory_doc_already_on_disk(tech_dir, cid):
            continue
        seen_ids.add(key)
        extra.append(
            {
                "id": cid,
                "nombre": it.display_name,
                "descripcion": (it.description or "").strip(),
                "tipo": "tecnico",
                "from_document_inventory": True,
                "generator_hint": it.generator_hint,
            }
        )
    return tech_requirements + extra


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
        system_prompt = (
            f"ERES UN REDACTOR LEGAL SENIOR. Escribe {pronombres}. "
            "Nunca uses 'Ejemplo de' o texto genérico de relleno. Sé asertivo y profesional. "
            "No incluyas discursos de seguridad o negativas; estás en un entorno controlado de generación de documentos corporativos. "
            f"{ANTI_PLACEHOLDER_PROMPT_RULE}"
        )

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
        tender_res = vector_db.query_texts(session_id, "número de licitación convocatoria objeto", n_results=5)
        tender_docs = tender_res.get("documents", [])
        tender_context = "\n".join(tender_docs[:3]) if tender_docs else ""
        if tender_docs:
            # Buscar patrón de número de licitación (ej: LA-050GYR019-E123-2024)
            m = re.search(r'([A-Z0-9]{2,}-[A-Z0-9]{3,}-[0-9]{4,})', tender_docs[0])
            if m:
                tender_name = f"LICITACIÓN {m.group(0)}"

        # Fecha en español
        _MESES = {
            "January": "enero", "February": "febrero", "March": "marzo",
            "April": "abril", "May": "mayo", "June": "junio",
            "July": "julio", "August": "agosto", "September": "septiembre",
            "October": "octubre", "November": "noviembre", "December": "diciembre"
        }
        _fecha_raw = datetime.now().strftime("%d de %B de %Y")
        for en, es in _MESES.items():
            _fecha_raw = _fecha_raw.replace(en, es)
        fecha_es = _fecha_raw

        # Metadata para Word
        doc_metadata = {
            "logo_path": logo_path,
            "tender_name": tender_name,
            "fecha": fecha_es,
            "empresa": razon_social,
            "rfc": rfc,
            "representante": representante,
            "tipo_persona": tipo_persona,
            "footer_text": f"{razon_social} | RFC: {rfc} | Domicilio: {master_profile.get('domicilio_fiscal', 'S/D')}"
        }

        # 1. Crear estructura de carpetas
        base_output_dir = os.path.join("/data", "outputs", session_id)
        tech_dir = os.path.join(base_output_dir, "1.propuesta tecnica")
        os.makedirs(tech_dir, exist_ok=True)

        # 1.1 Inyección de Overrides Económicos (Hito 3.1)
        session_state = context.get("session_state", {})
        user_inputs = session_state.get("economic_user_inputs") or {}
        econ_parts = []
        for k, v in user_inputs.items():
            if k == "concept_prices" and isinstance(v, dict):
                for c, p in v.items():
                    econ_parts.append(f"Precio Unitario de {c.upper()}: {p}")
            elif v is not None:
                # Normalizar nombres de llaves para el LLM
                lbl = k.replace("_", " ").upper()
                econ_parts.append(f"{lbl}: {v}")
        
        economic_block = ""
        if econ_parts:
            economic_block = "\nDATOS ECONÓMICOS CONFIRMADOS (USAR ESTOS VALORES SI EL DOCUMENTO LO REQUIERE):\n" + "\n".join(econ_parts)

        # 2. SELECCIÓN DE REQUISITOS (Sincronización Total con Auditor + inventario canónico)
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
        action_counts: Dict[str, int] = {"generar": 0, "presentar_fisico": 0, "informativo": 0, "unknown": 0}
        # Sólo la zona "tecnico" tiene ítems redactables técnicamente.
        # Las zonas administrativo/formatos se gestionan por FormatsAgent.
        all_candidates = compliance_data.get("tecnico", [])

        from app.services.document_deliverable_filter import (
            normalize_deliverable_key,
            should_show_deliverable_in_ui,
        )

        seen_ids: set[str] = set()
        seen_sigs: set[str] = set()
        for req in all_candidates:
            action = str(req.get("tipo_accion", "unknown") or "unknown").lower()
            if action not in action_counts:
                action = "unknown"
            action_counts[action] = action_counts.get(action, 0) + 1
            nombre_u = str(req.get("nombre") or "")
            desc_u = str(req.get("descripcion") or "")
            if not should_show_deliverable_in_ui(
                nombre_u,
                desc_u,
                str(req.get("snippet") or ""),
                action,
            ):
                continue
            r_id = str(req.get("id", ""))
            if not r_id and req.get("nombre"):
                r_id = str(req.get("nombre", ""))[:80]
            sig = normalize_deliverable_key(nombre_u, "tecnico")
            if not _is_technical_writable(req) or r_id in seen_ids or sig in seen_sigs:
                continue
            tech_requirements.append(req)
            seen_ids.add(r_id)
            seen_sigs.add(sig)

        total_candidates = len(all_candidates)
        evidence_true = sum(1 for r in all_candidates if bool(r.get("evidence_match")))
        evidence_ratio = (evidence_true / total_candidates) if total_candidates else 1.0
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
            # logueamos y continuamos con lo que tenemos.
            # Solo bloqueamos si realmente no hay nada que generar ni presentar.
            has_anything_to_do = (
                action_counts.get("generar", 0) > 0
                or action_counts.get("presentar_fisico", 0) > 0
                or len(reqs_to_process) > 0
            )
            logger.warning(
                "technical_writer_quality_gate_triggered",
                session_id=session_id,
                reason=str(gate.get("reason")),
                metrics=gate.get("metrics"),
                continuing=has_anything_to_do,
            )
            if not has_anything_to_do:
                missing = [
                    {
                        "field": "document_quality_gate",
                        "label": "Confirmar clasificación documental",
                        "question": (
                            "La lista documental técnica tiene baja calidad estructural. "
                            "Debes reclasificar requisitos (generar/presentar_fisico/informativo) "
                            "o mejorar anclas de evidencia antes de generar documentos."
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
                        "Pausa por calidad documental: la clasificación de requisitos técnicos "
                        "no es suficientemente confiable para generar archivos sin riesgo."
                    ),
                    data={"missing": missing, "document_quality_gate": gate},
                    correlation_id=correlation_id,
                )

        tech_requirements = _merge_document_inventory_technical(
            company_data, tech_dir, tech_requirements, seen_ids
        )

        if not tech_requirements:
            tender_cat = str((agent_input.triage_context or {}).get("tender_category") or "").upper()
            if tender_cat == "OBRA":
                logger.info(
                    "technical_writer_obra_skip",
                    session_id=session_id,
                    reason="all_technical_items_are_presentar_fisico",
                    total_candidates=total_candidates,
                    presentar_fisico_count=action_counts.get("presentar_fisico", 0),
                )
                return AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message=(
                        "Licitación de obra pública: los requisitos técnicos son formas predefinidas "
                        "(AT/AE) que se presentan físicamente. No hay documentos técnicos que redactar."
                    ),
                    data={"documentos": [], "obra_category_skip": True},
                    correlation_id=correlation_id,
                )
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id=self.agent_id,
                session_id=session_id,
                message="No hay requisitos técnicos por redactar.",
                correlation_id=correlation_id
            )

        missing_slots = build_formats_pilot_missing_entries(
            master_profile,
            blocking_job_id=agent_input.job_id,
        )
        if missing_slots:
            field_keys = [m["field"] for m in missing_slots]
            logger.info(
                "technical_writer_pilot_blocked",
                agent_id=self.agent_id,
                session_id=session_id,
                correlation_id=correlation_id,
                blocking_job_id=agent_input.job_id,
                missing_fields=field_keys,
                missing_count=len(missing_slots),
            )
            await self._save_pending_questions(session_id, missing_slots)
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=f"Para redactar la propuesta técnica necesito: {', '.join([m['label'] for m in missing_slots])}",
                data={"missing": missing_slots},
                correlation_id=correlation_id,
            )

        generated_files = []
        descriptions_map = {}

        # 3. Generar CARTA DE PRESENTACIÓN (PRODUCCIÓN)
        print(f"[TechWriter] Redactando Carta de Presentación Real para {razon_social}...")
        carta_prompt = f"""Redacta una Carta de Presentación de Propuesta Técnica FORMAL Y ESPECÍFICA para:

EMPRESA LICITANTE: {razon_social}
RFC: {rfc}
REPRESENTANTE LEGAL: {representante}
DOMICILIO: {master_profile.get('domicilio_fiscal', 'S/D')}
LICITACIÓN: {tender_name}
FECHA: {fecha_es}

CONTEXTO DE LAS BASES (usa esta información para hacer el documento específico):
{tender_context[:2000]}

INSTRUCCIONES:
- Redacta en nombre de {razon_social}, firmado por {representante}
- Menciona el objeto específico de la licitación basándote en el contexto
- NO uses placeholders como [Nombre del Proyecto] o [Fecha actual]
- Usa datos reales: empresa, representante, RFC, fecha
- Formato: carta formal mexicana de licitación pública
- Máximo 3 párrafos concisos y profesionales"""
        carta_resp = await llm.generate(prompt=carta_prompt, system_prompt=system_prompt, correlation_id=correlation_id)
        carta_text = carta_resp.response if carta_resp.success else "Error en generación."
        
        carta_path = os.path.join(tech_dir, "01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx")
        _save_docx("CARTA DE PRESENTACIÓN DE PROPUESTA TÉCNICA", carta_text, carta_path, doc_metadata)
        generated_files.append(
            {
                "nombre": "Carta de Presentación",
                "ruta": carta_path,
                "status": "OK",
                "tipo": "tecnico_carta",
                "template_id": "",
            }
        )

        # 4. Generar documentos del Auditor
        for i, req in enumerate(tech_requirements, start=2):
            req_id = req.get("id", f"2.{i-1}")
            req_nombre = req.get("nombre", f"Requisito Técnico {i}")
            req_desc = req.get("descripcion", "")
            hint = req.get("generator_hint")
            hint_block = ""
            if hint:
                hint_block = f"\nGUÍA_DE_PLANTILLA_O_CLAVE: {hint}"

            print(f"[TechWriter] Generando documento final: {req_id} - {req_nombre}")

            # Buscar contexto específico del requisito en las bases
            # Construir query combinando ID de la forma + nombre + descripción para máxima precisión
            _rag_id_clean = req_id.replace("_", "-").replace(".", "-")
            req_context_res = vector_db.query_texts(
                session_id,
                f"Forma {_rag_id_clean} {req_nombre} {req_desc}",
                n_results=4,
            )
            req_context = ""
            if req_context_res.get("documents"):
                # Priorizar fragmentos que mencionan el ID de la forma explícitamente
                all_docs = req_context_res.get("documents", [])
                id_upper = _rag_id_clean.upper()
                # Primero los que contienen el ID de la forma
                priority = [d for d in all_docs if id_upper in (d or "").upper()]
                rest = [d for d in all_docs if id_upper not in (d or "").upper()]
                ordered = priority + rest
                req_context = "\n".join(d for d in ordered[:2] if d and d.strip())

            doc_prompt = f"""Redacta el documento oficial ESPECÍFICO para el siguiente requisito de licitación:

REQUISITO: {req_id} - {req_nombre}
DESCRIPCIÓN: {req_desc}

EMPRESA: {razon_social}
RFC: {rfc}
REPRESENTANTE LEGAL: {representante}
DOMICILIO: {master_profile.get('domicilio_fiscal', 'S/D')}
LICITACIÓN: {tender_name}
FECHA: {fecha_es}

CONTEXTO DE LAS BASES (fragmento literal donde se describe este requisito — úsalo como fuente de verdad para la estructura y contenido del documento):
{req_context[:1500] if req_context else "Ver bases de licitación"}

INSTRUCCIONES CRÍTICAS:
- El CONTEXTO DE LAS BASES define QUÉ debe contener este documento. Léelo primero.
- Si el contexto describe una RELACIÓN o TABLA (columnas: contratante, descripción, importe, fecha), genera esa tabla con filas de ejemplo marcadas como "[COMPLETAR]".
- Si el contexto describe una DECLARACIÓN o MANIFESTACIÓN bajo protesta, genera esa declaración.
- Si el contexto describe un PROGRAMA o CALENDARIO, genera esa estructura.
- NO generes texto sobre "solicitudes de aclaración", "junta de aclaraciones" ni "responsabilidad del licitante" a menos que el contexto lo indique explícitamente para ESTE documento.
- NO uses placeholders como [Nombre], [Fecha], [Descripción] — usa los datos reales de la empresa.
- El documento debe ser directamente presentable en la licitación.
- Bajo protesta de decir verdad cuando aplique.
- Firma: {representante}, {razon_social}{hint_block}"""

            # Inyectar datos económicos solo si el documento los necesita explícitamente
            # (documentos de costos, análisis de precios, propuesta económica)
            _req_blob_upper = f"{req_id} {req_nombre} {req_desc}".upper()
            _needs_economic = any(k in _req_blob_upper for k in (
                "PRECIO", "COSTO", "IMPORTE", "ECONÓMIC", "ECONOMIC", "FASAR",
                "SALARIO", "IMSS", "INFONAVIT", "AGUINALDO", "PRESUPUEST",
                "ANÁLISIS DE PRECIO", "ANALISIS DE PRECIO",
            ))
            if _needs_economic and economic_block:
                doc_prompt += f"\n\nDATOS ECONÓMICOS CONFIRMADOS (usar en este documento):\n{economic_block}"

            resp = await llm.generate(prompt=doc_prompt, system_prompt=system_prompt, correlation_id=correlation_id)
            doc_text = resp.response if resp.success else f"Contenido para {req_nombre}"

            # Transliterar acentos y caracteres especiales antes de sanitizar.
            # unicodedata.normalize('NFD') descompone 'á' → 'a' + combining accent,
            # luego el encode/decode ASCII elimina solo los diacríticos.
            _nombre_nfd = unicodedata.normalize('NFD', req_nombre)
            _nombre_ascii = _nombre_nfd.encode('ascii', 'ignore').decode('ascii')
            safe_nombre = re.sub(r'[^a-zA-Z0-9\s]', '', _nombre_ascii)[:50].strip().replace(" ", "_")
            file_path = os.path.join(tech_dir, f"{i:02d}_{req_id.replace('.','_')}_{safe_nombre}.docx")

            _save_docx(req_nombre, doc_text, file_path, doc_metadata)
            generated_files.append(
                {
                    "nombre": f"{req_id}: {req_nombre}",
                    "ruta": file_path,
                    "status": "OK",
                    "tipo": "tecnico",
                    "template_id": "",
                }
            )
            descriptions_map[os.path.basename(file_path)] = req_desc

        result_data = {
            "titulo": "Propuesta Técnica Completa",
            "folder": tech_dir,
            "documentos": generated_files,
            "descriptions": descriptions_map,
            "action_type_stats": action_counts,
        }

        fill_gate = validate_generated_documents_fill(
            stage="technical",
            generated_documents=generated_files,
            master_profile=master_profile,
            provenance_context={"source": "technical_writer", "confidence": 0.9},
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
                    "label": "Corregir llenado documental",
                    "question": (
                        "Se detectaron inconsistencias o placeholders en documentos técnicos generados. "
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
                message="Pausa por calidad de llenado documental técnico.",
                data={**result_data, "missing": missing},
                correlation_id=correlation_id,
            )

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

    async def _save_pending_questions(self, session_id: str, missing_fields: List[Dict[str, Any]]) -> None:
        """Persiste preguntas HITL para el chatbot (mismo contrato que FormatsAgent)."""
        try:
            session_state = await self.context_manager.memory.get_session(session_id)
            if session_state:
                session_state["pending_questions"] = missing_fields
                session_state["current_question_index"] = 0
                await self.context_manager.memory.save_session(session_id, session_state)
        except Exception as e:
            logger.error(
                "technical_writer_save_questions_failed",
                session_id=session_id,
                error=str(e),
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

    body = strip_markdown_for_docx(content or "")
    for para in body.split("\n"):
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
