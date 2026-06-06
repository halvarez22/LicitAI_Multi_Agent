import json
import logging
from app.core.logging_config import get_logger
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from hashlib import sha1

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover - entornos sin rapidfuzz aún
    _rf_fuzz = None
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.services.analyst_output_normalize import (
    normalize_alcance_operativo_list,
    normalize_reglas_economicas_dict,
)
from app.economic_validation.engine import validate_economic_proposal
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.services.economic_cotization_filters import (
    build_upstream_doc_ids,
    is_required_price_source_artifact,
    is_contaminated_economic_pending_question,
    should_exclude_technical_for_cotization,
)
from app.services.validation_service import validation_mapping_service
from app.services.validation_policy_service import resolve_validation_policy
from app.services.economic_calculator_engine import EconomicCalculatorEngine
from app.services.structured_economic_price_mapper import (
    apply_structured_price_inputs,
    build_structured_price_slots,
)
from app.services.economic_tabular_ingest_sync import tech_requirements_from_tabular_pricing
from app.services.tabular_line_item_extract import dedupe_tabular_line_items
from app.config.settings import settings as app_settings

logger = get_logger(__name__)


def _tech_requirement_by_id(
    tech_requirements: List[Dict[str, Any]], concepto_id: Any
) -> Optional[Dict[str, Any]]:
    """Localiza el requisito técnico original por id (para enriquecer mensajes al usuario)."""
    if concepto_id is None:
        return None
    sid = str(concepto_id).strip()
    if not sid:
        return None
    for r in tech_requirements or []:
        if isinstance(r, dict) and str(r.get("id", "")).strip() == sid:
            return r
    return None


def _blob_for_guard_detection(concepto: str, req: Optional[Dict[str, Any]], ref: str) -> str:
    """Texto agregado para heurística de servicios por guardia / vigilancia."""
    parts: List[str] = [str(concepto or ""), str(ref or "")]
    if isinstance(req, dict):
        for k in (
            "nombre",
            "label",
            "titulo",
            "descripcion",
            "texto_literal",
            "texto",
            "snippet",
            "norma_o_fragmento",
        ):
            v = req.get(k)
            if v is not None:
                parts.append(str(v))
    return " ".join(p.lower() for p in parts if p)


def _is_guard_like_context(concepto: str, req: Optional[Dict[str, Any]], ref: str) -> bool:
    """
    Heurística conservadora: vigilancia, guardias, turnos operativos en bases/dictamen.
    Sirve para redactar preguntas en lenguaje natural y, si aplica, pedir esquema de horas.
    """
    blob = _blob_for_guard_detection(concepto, req, ref)
    if not blob.strip():
        return False
    keys = (
        "vigilanc",
        "guardia",
        "rond",
        "custodia",
        "custodio",
        "elemento de vigilancia",
        "personal de seguridad",
        "seguridad f",
        "seguridad física",
        "vigilante",
        "24x24",
        "12x12",
        "12 x 12",
        "24 x 24",
        "turno de",
        "horario de servicio",
        "periodo de horas",
        "período de horas",
        "por guardia",
    )
    return any(k in blob for k in keys)


def _economic_gap_reference_snippet(req: Optional[Dict[str, Any]], concepto: str) -> str:
    """Fragmento de texto de bases/dictamen más informativo que el solo título corto."""
    if not isinstance(req, dict):
        return ""
    c0 = str(concepto or "").strip()
    for key in ("snippet", "texto_literal", "texto", "descripcion", "norma_o_fragmento"):
        val = req.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if len(s) >= 24 and s.lower() != c0.lower():
            return s[:420] + ("…" if len(s) > 420 else "")
    blob = " ".join(
        str(req.get(k) or "")
        for k in ("descripcion", "nombre", "label", "titulo", "texto")
    ).strip()
    if len(blob) >= len(c0) + 20:
        return blob[:420] + ("…" if len(blob) > 420 else "")
    return ""


def _strict_anchor_from_requirement(req: Optional[Dict[str, Any]], fallback_snippet: str) -> Dict[str, Any]:
    """Construye ancla verificable estricta (documento + página + fragmento)."""
    if not isinstance(req, dict):
        return {}
    source = (
        req.get("source")
        or req.get("documento")
        or req.get("archivo")
        or req.get("fuente")
        or req.get("doc_id")
    )
    page = req.get("page") or req.get("pagina")
    snippet = req.get("snippet") or req.get("texto_literal") or req.get("texto") or fallback_snippet
    out: Dict[str, Any] = {}
    if source is not None:
        out["source"] = str(source).strip()
    if page is not None:
        try:
            out["page"] = int(page)
        except (TypeError, ValueError):
            pass
    if snippet is not None:
        out["snippet"] = str(snippet).strip()
    return out


def _build_price_source_blocking_items(requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convierte anexos económicos documentales en evidencia accionable para HITL."""
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for req in requirements or []:
        if not isinstance(req, dict) or not is_required_price_source_artifact(req):
            continue
        label = str(
            req.get("nombre")
            or req.get("label")
            or req.get("titulo")
            or req.get("descripcion")
            or "Fuente económica requerida"
        ).strip()
        key = re.sub(r"\s+", " ", label.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        snippet = _economic_gap_reference_snippet(req, label) or label
        anchor = _strict_anchor_from_requirement(req, snippet)
        out.append(
            {
                "concepto_label": label,
                "page_number": anchor.get("page"),
                "context_snippet": anchor.get("snippet") or snippet,
                "source_name": anchor.get("source") or "Bases de la licitación",
                "requested_input": "price_source",
            }
        )
    return out


def _summarize_structured_template_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resume anexos tabulares de la convocante que ya fijan cantidades/elementos."""
    zones: Dict[str, Dict[str, Any]] = {}
    service_rows = 0
    material_rows = 0
    seen_service: set[tuple[str, str, str, str]] = set()
    seen_material: set[tuple[str, str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if str(extra.get("layout") or "").strip().lower() != "structured_template":
            continue
        template_kind = str(extra.get("template_kind") or "").strip().lower()
        try:
            qty = float(row.get("cantidad") or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        if template_kind == "service_zone_elements":
            zone = str(extra.get("zone") or "").strip().upper() or "?"
            service_key = (
                zone,
                str(extra.get("site_code") or "").strip().upper(),
                str(row.get("concepto_norm") or row.get("concepto_raw") or "").strip().lower(),
                str(extra.get("schedule") or "").strip().lower(),
            )
            if service_key in seen_service:
                continue
            seen_service.add(service_key)
            bucket = zones.setdefault(zone, {"sites": 0, "elements": 0.0})
            bucket["sites"] += 1
            bucket["elements"] += max(0.0, qty)
            service_rows += 1
        elif template_kind == "monthly_material_requirement":
            material_key = (
                str(extra.get("zone") or "").strip().upper(),
                str(extra.get("item_no") or "").strip(),
                str(row.get("concepto_norm") or row.get("concepto_raw") or "").strip().lower(),
            )
            if material_key in seen_material:
                continue
            seen_material.add(material_key)
            material_rows += 1
    if not zones and material_rows <= 0:
        return {}
    return {
        "zones": {
            z: {
                "sites": int(v.get("sites") or 0),
                "elements": int(round(float(v.get("elements") or 0.0))),
            }
            for z, v in zones.items()
        },
        "service_rows": service_rows,
        "material_rows": material_rows,
    }


def _format_structured_template_summary(summary: Dict[str, Any]) -> str:
    """Texto humano a partir de la estructura económica ya detectada en anexos."""
    if not isinstance(summary, dict) or not summary:
        return ""
    parts: List[str] = []
    zones = summary.get("zones") if isinstance(summary.get("zones"), dict) else {}
    if zones:
        zone_bits = []
        for zone in sorted(zones.keys()):
            info = zones.get(zone) or {}
            zone_bits.append(
                f"Zona {zone}: {int(info.get('elements') or 0)} elementos en {int(info.get('sites') or 0)} unidades"
            )
        preview = "; ".join(zone_bits[:4])
        if len(zone_bits) > 4:
            preview += "; ..."
        parts.append(f"Ya identifiqué en tus anexos la estructura operativa ({preview}).")
    material_rows = int(summary.get("material_rows") or 0)
    if material_rows > 0:
        parts.append(f"También detecté {material_rows} renglones de materiales/consumos por cotizar.")
    return " ".join(parts).strip()


def _build_structured_price_question_for_user(slot: Dict[str, Any]) -> str:
    """Pregunta humana para capturar precios faltantes desde anexos estructurados."""
    concept_label = str(slot.get("concept_label") or "este concepto").strip()
    source_name = str(slot.get("source_name") or "anexo económico").strip()
    sheet_name = str(slot.get("sheet_name") or "").strip()
    row_index = slot.get("row_index")
    quantity_total = int(round(float(slot.get("quantity_total") or 0.0)))
    rows_count = int(slot.get("rows_count") or 0)
    slot_type = str(slot.get("slot_type") or "").strip()

    where = source_name
    if sheet_name:
        where += f", hoja {sheet_name}"
    if row_index:
        where += f", fila {row_index}"

    if slot_type == "service_zone_elements":
        zone = str(slot.get("zone") or "").strip().upper() or "N/D"
        schedule = str(slot.get("schedule") or "").strip() or "horario indicado"
        return (
            f"Necesito el **costo por elemento sin IVA** para **Zona {zone} | {schedule}**.\n\n"
            f"Ya detecté **{quantity_total} elementos** distribuidos en **{rows_count} unidades** dentro de {where}.\n\n"
            "Responde solo con el importe unitario por elemento. Si deseas continuar después, escribe `siguiente`."
        )

    unit = str(slot.get("unit") or "").strip()
    unit_txt = f" por {unit}" if unit else ""
    qty_support_name = str(slot.get("quantity_support_source_name") or "").strip()
    qty_support_sheet = str(slot.get("quantity_support_sheet_name") or "").strip()
    qty_support_row = slot.get("quantity_support_row_index")
    qty_support_where = qty_support_name
    if qty_support_sheet:
        qty_support_where += f", hoja {qty_support_sheet}"
    if qty_support_row:
        qty_support_where += f", fila {qty_support_row}"
    support_msg = ""
    if qty_support_where:
        support_msg = (
            f"Ya ubiqué este material en **{qty_support_where}** y también en el formato económico "
            "donde capturaremos el precio."
        )
    return (
        f"Necesito el **costo unitario sin IVA**{unit_txt} para **{concept_label}**.\n\n"
        f"{support_msg or 'Ya identifiqué este material en los anexos económicos de la convocante.'}\n\n"
        f"La cantidad total a cotizar para esta propuesta es **{quantity_total}**, consolidada en {where}.\n\n"
        "Responde solo con el precio unitario. Si deseas continuar después, escribe `siguiente`."
    )


def _build_structured_price_intro(missing_slots: List[Dict[str, Any]]) -> str:
    """Mensaje resumido cuando ya existe estructura económica pero faltan precios concretos."""
    if not missing_slots:
        return (
            "Ya identifiqué la estructura económica de la convocante, pero todavía faltan precios "
            "unitarios para continuar."
        )
    first = missing_slots[0]
    concept = str(first.get("concept_label") or "el primer concepto pendiente").strip()
    total = len(missing_slots)
    support_name = next(
        (
            str(slot.get("quantity_support_source_name") or "").strip()
            for slot in (missing_slots or [])
            if str(slot.get("quantity_support_source_name") or "").strip()
        ),
        "",
    )
    if support_name:
        return (
            f"Ya leí los anexos económicos y también un anexo soporte de materiales **{support_name}**. "
            f"Ahora solo necesito capturar **{total} precio(s) unitarios** para continuar.\n\n"
            f"Empezamos con: **{concept}**."
        )
    return (
        "Ya leí los anexos económicos y detecté la estructura de cantidades/elementos. "
        f"Ahora necesito capturar **{total} precio(s)** para continuar.\n\n"
        f"Empezamos con: **{concept}**."
    )


def _build_structured_price_pending_questions(
    missing_slots: List[Dict[str, Any]],
    *,
    block_group_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convierte slots estructurados en preguntas `economic_price` consumibles por el chat."""
    pending: List[Dict[str, Any]] = []
    for seq, slot in enumerate(missing_slots):
        source_name = str(slot.get("source_name") or "anexo_economico.xlsx").strip()
        row_index = slot.get("row_index")
        original_item = {
            "source": source_name,
            "row_index": row_index,
            "sheet_name": slot.get("sheet_name"),
            "snippet": str(slot.get("context_snippet") or slot.get("concept_label") or "")[:420],
            "concepto": str(slot.get("concept_label") or ""),
            "structured_price_slot": True,
            "structured_price_field": str(slot.get("field") or ""),
            "structured_slot_type": str(slot.get("slot_type") or ""),
            "quantity_support_source_name": str(slot.get("quantity_support_source_name") or ""),
        }
        row = {
            "field": str(slot.get("field") or ""),
            "label": str(slot.get("label") or ""),
            "question": _build_structured_price_question_for_user(slot),
            "document_hint": source_name,
            "type": "economic_price",
            "original_item": original_item,
            "capture_guard_schedule": False,
        }
        if block_group_key:
            row["block_group_key"] = block_group_key
            row["block_item_seq"] = seq
        pending.append(row)
    return pending


def _build_economic_price_source_question(
    blocking_items: List[Dict[str, Any]],
    structured_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pregunta humana para pedir la fuente económica real cuando aún no hay precios auditables."""
    first = str((blocking_items or [{}])[0].get("concepto_label") or "la fuente económica real").strip()
    structured_text = _format_structured_template_summary(structured_summary)
    question = (
        "Para cerrar la propuesta económica necesito la fuente real de precios o costos "
        f"que usarás en esta licitación. En las bases aparece, por ejemplo, **{first}**."
    )
    if structured_text:
        question = f"{question} {structured_text} Lo que sigue faltando son los costos o precios."
    return {
        "field": "economic_price_source",
        "label": "Fuente económica real",
        "question": question,
        "type": "economic_validation_blocking",
        "input_mode": "price_source",
        "blocking_items": blocking_items,
        "detected_structure_summary": structured_summary if structured_summary else None,
    }


def _build_economic_price_source_intro(
    blocking_items: List[Dict[str, Any]],
    structured_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Mensaje de pausa humana cuando faltan anexos/catálogos económicos base."""
    if not blocking_items:
        return (
            "Para continuar necesito una fuente económica real (catálogo, análisis o cotización) "
            "que me permita capturar precios válidos."
        )
    first = blocking_items[0]
    label = str(first.get("concepto_label") or "la fuente económica real").strip()
    page = first.get("page_number")
    source = str(first.get("source_name") or "bases").strip()
    page_txt = f", página {page}" if page else ""
    base = (
        "Antes de generar la propuesta económica necesito la fuente real de precios o costos. "
        f"Ya detecté esta referencia en **{source}**{page_txt}: **{label}**. "
        "Compárteme ese catálogo/análisis o los importes reales que deban capturarse."
    )
    structured_text = _format_structured_template_summary(structured_summary)
    return f"{base} {structured_text}".strip() if structured_text else base


def _has_strict_anchor_for_user(item: Dict[str, Any]) -> bool:
    """Fail-closed: exige documento + fragmento + página o fila verificable."""
    if not isinstance(item, dict):
        return False
    oi = item.get("original_item")
    if not isinstance(oi, dict):
        return False
    src = str(oi.get("source") or "").strip()
    sn = str(oi.get("snippet") or "").strip()
    pg = oi.get("page")
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


def _ensure_chat_anchor(original_item: Dict[str, Any], concepto: str) -> Dict[str, Any]:
    """
    Ancla mínima para captura de precios en chat cuando el pliego no trae snippet/página.
    """
    oi = dict(original_item or {})
    if not str(oi.get("source") or "").strip():
        oi["source"] = "bases_licitacion"
    try:
        if int(oi.get("page") or 0) < 1:
            oi["page"] = 1
    except (TypeError, ValueError):
        oi["page"] = 1
    sn = str(oi.get("snippet") or "").strip()
    if len(sn) < 12:
        label = str(concepto or "Partida").strip() or "Partida"
        oi["snippet"] = f"Cotización en chat — {label}"[:220]
    return oi


def _slug_block_item_id(error_type: str, label: str) -> str:
    base = f"{error_type}|{label}".encode("utf-8", errors="ignore")
    return f"blk_{sha1(base).hexdigest()[:12]}"

def _looks_documental_non_cotizable(label: str) -> bool:
    """
    Cortafuego inmediato: requisitos documentales/legales no deben entrar
    al flujo de cotización económica.
    """
    s = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if not s:
        return True
    documental_terms = (
        "repse",
        "registro",
        "acta",
        "carta",
        "constancia",
        "anexo",
        "identificacion",
        "identificación",
        "certificado",
        "escrito",
        "declaracion",
        "declaración",
        "manifestacion",
        "manifiesto",
        "curp",
        "identificacion oficial",
        "identificación oficial",
        "propuesta tecnica",
        "propuesta técnica",
        "propuesta economica",
        "propuesta económica",
        "programa calendarizado",
    )
    if any(t in s for t in documental_terms):
        return True
    # Regla positiva mínima: para cotización en bloqueo masivo pedimos indicios
    # de servicio/suministro/mantenimiento/unidad operativa.
    service_terms = (
        "servicio",
        "suministro",
        "mantenimiento",
        "vigilancia",
        "guardia",
        "pieza",
        "lote",
        "puesto",
        "turno",
        "equipo",
        "instalacion",
        "instalación",
    )
    return not any(t in s for t in service_terms)


def _human_economic_blocking_summary(
    validation_events: List[Dict[str, Any]],
    validation_result: Any,
) -> str:
    """Resume el bloqueo en lenguaje de negocio (UX / primer issue), sin jerga de motor."""
    for ev in validation_events or []:
        if not isinstance(ev, dict):
            continue
        ux = ev.get("ux") if isinstance(ev.get("ux"), dict) else {}
        title = str(ux.get("title") or "").strip()
        um = str(ux.get("user_message") or "").strip()
        if len(um) >= 12:
            lead = f"{title}: {um}" if title else um
            return (lead[:320] + "…") if len(lead) > 320 else lead
    if isinstance(validation_result, dict):
        issues = list(validation_result.get("blocking_issues") or [])
    else:
        issues = getattr(validation_result, "blocking_issues", None) or []
    if issues:
        first = str(issues[0]).strip()
        if len(first) >= 8:
            return (first[:320] + "…") if len(first) > 320 else first
    return ""


def _calcular_multiplicador_plantilla_lft(turno_horario: str, dias_semana: str) -> float:
    """
    Ingeniería de Turnos (Capa Operativa):
    Determina cuántos guardias reales en nómina se requieren para cubrir 
    un (1) elemento físico en el área, según el horario exigido por las bases.
    """
    turno = str(turno_horario).strip().upper()
    dias = str(dias_semana).strip().upper()
    
    # FLAG DE RIESGO 1: Puesto 24/7 (168 horas semanales)
    # Según LFT (48h/semana por guardia), cubrir 1 punto 24/7 exige matemáticamente
    # 3.5 guardias (168/48). Pero en el esquema común 24x24 (descanso 24h),
    # necesitas un multiplicador mínimo de 2 (Dos guardias turnándose 1 plaza).
    if "24 HORAS" in turno and any(d in dias for d in ["LUN-DOM", "L-D", "LUNES A DOMINGO"]):
        return 2.0  # El factor de doble plantilla (Relevo)
    
    # FLAG DE RIESGO 2: Puesto 12/7 Diurno/Nocturno (84 horas semanales)
    elif "12 HORAS" in turno and any(d in dias for d in ["LUN-DOM", "L-D"]):
        return 1.5  # Plantilla de relevo fraccionado
    
    return 1.0  # Turno normal de 8 horas L-V

def _validar_viabilidad_operativa_fila(fila: dict) -> dict:
    """
    Intercepta la fila extraída antes de enviarla a cotización.
    """
    try:
        elementos_fisicos = float(fila.get("numero_elementos", 1))
    except (TypeError, ValueError):
        elementos_fisicos = 1.0

    multiplicador = _calcular_multiplicador_plantilla_lft(
        fila.get("turno", ""), 
        fila.get("dias", "")
    )
    
    elementos_nomina = elementos_fisicos * multiplicador
    
    riesgo_operativo = None
    if multiplicador > 1.0:
        riesgo_operativo = {
            "flag": "FLAG_RIESGO_OPERATIVO",
            "mensaje": (
                f"ALERTA LFT: Las bases solicitan {elementos_fisicos} elementos para un "
                f"turno '{fila.get('turno')} / {fila.get('dias')}'. "
                f"El motor ajustará la cotización a {elementos_nomina} elementos en nómina "
                f"para cubrir la operación sin pérdidas financieras."
            )
        }
        
    return {
        "elementos_cotizables": elementos_nomina,
        "riesgo": riesgo_operativo
    }


class EconomicAgent(BaseAgent):
    """
    Agente 5: Estratega Económico.
    Analiza los conceptos de la licitación y genera la propuesta financiera.
    Utiliza el catálogo de la empresa para calcular costos y márgenes.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="economic_001",
            name="Estratega de Propuesta Económica",
            description="Motor de cálculo y cotización para licitaciones.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()
        self.calculator = EconomicCalculatorEngine()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        company_id = agent_input.company_id
        correlation_id = agent_input.correlation_id or "no-id"
        
        print(f"💰 [Económico] Iniciando Análisis Financiero para: {session_id} - correlation_id: {correlation_id}")

        company_data = agent_input.company_data if isinstance(agent_input.company_data, dict) else {}
        skip_economic_silence = bool(company_data.get("skip_economic_silence"))
        relax_price_anchors = bool(company_data.get("relax_price_anchors"))

        # 1. Recuperar Hallazgos de Compliance (La Lista Maestra)
        context = await self.context_manager.get_global_context(session_id)
        session_state = context.get("session_state", {})
        
        master_list = agent_input.company_data.get("compliance_master_list")

        if not master_list:
            tasks = session_state.get("tasks_completed", [])
            for task in reversed(tasks):
                tname = task.get("task", "")
                if tname == "master_compliance_list":
                    master_list = task.get("result")
                    break
                if tname == "stage_completed:compliance":
                    res = task.get("result") or {}
                    master_list = res.get("data") if isinstance(res, dict) else None
                    if master_list:
                        break
        
        if not master_list:
            master_list = session_state.get("master_compliance_list", {})

        # 2. Recuperar Catálogo de Precios de la Empresa y partidas tabulares de la sesión (Excel)
        company_catalog = await self._get_company_catalog(company_id)
        session_line_items: List[Dict] = []
        try:
            session_line_items = await self.context_manager.memory.get_line_items_for_session(
                session_id
            )
        except Exception as e:
            logger.warning("[EconomicAgent] No se pudieron leer session_line_items: %s", e)
        concept_prices = {}
        econ_inputs = session_state.get("economic_user_inputs")
        if isinstance(econ_inputs, dict):
            cp = econ_inputs.get("concept_prices")
            if isinstance(cp, dict):
                concept_prices = cp
        structured_price_slots = build_structured_price_slots(session_line_items, concept_prices)
        missing_structured_price_slots = [
            slot for slot in structured_price_slots if slot.get("captured_price") is None
        ]
        session_line_items_effective = apply_structured_price_inputs(session_line_items, concept_prices)
        structured_template_summary = _summarize_structured_template_rows(session_line_items)
        pricing_line_items = dedupe_tabular_line_items(
            self._filter_reliable_pricing_rows(session_line_items_effective)
        )
        tabular_catalog = self._tabular_rows_to_catalog_entries(pricing_line_items)

        analisis_bases = self._extract_analisis_bases_from_session(session_state)
        reglas_bases = normalize_reglas_economicas_dict(
            analisis_bases.get("reglas_economicas") if isinstance(analisis_bases, dict) else None
        )

        # --- ARQUITECTURA UNIVERSAL (Fase 2): Inyección de Overrides de Chat ---
        # Priorizamos datos dictados por el usuario sobre extracciones automáticas del Analyst.
        user_overrides = session_state.get("economic_user_inputs", {})
        if user_overrides:
            fsr_keys = [
                "imss", "sar", "infonavit", "dias_no_laborados", "dias_laborados",
                "prima_vacacional", "aguinaldo_dias"
            ]
            # Construir blob de overrides con separadores fuertes y limpieza de nulos
            override_blob = ", ".join([
                f"{k}={v}" for k, v in user_overrides.items()
                if k in fsr_keys and v is not None
            ])
            if override_blob:
                # Inyectar al inicio para que el motor determinista de FSR (regex-based)
                # encuentre el override antes que el dato original del documento.
                current_rules = reglas_bases.get("otras_reglas_oferta_precio") or ""
                reglas_bases["otras_reglas_oferta_precio"] = f"{override_blob}. {current_rules}"
                logger.info(
                    "economic_agent_fsr_overrides_injected",
                    session_id=session_id,
                    overrides=override_blob,
                )
        alcance_bases = normalize_alcance_operativo_list(
            analisis_bases.get("alcance_operativo") if isinstance(analisis_bases, dict) else None
        )
        datos_tab = (
            analisis_bases.get("datos_tabulares")
            if isinstance(analisis_bases, dict) and isinstance(analisis_bases.get("datos_tabulares"), dict)
            else {}
        )
        if datos_tab.get("alerta_faltante"):
            print(f"    [!] {str(datos_tab['alerta_faltante'])[:280]}", flush=True)

        bases_economic_context = self._format_bases_economic_context(
            reglas_bases, alcance_bases, datos_tab
        )
        alertas_contexto_bases = self._build_bases_economic_alertas(reglas_bases, datos_tab)
        contexto_bases_analista = {
            "reglas_economicas": reglas_bases,
            "alcance_operativo_filas": len(alcance_bases or []),
            "datos_tabulares": datos_tab,
        }
        # Contexto canónico (Sprint 1/2): ayuda a explicar bloqueos por plantillas o agregados.
        econ_norm_root = session_state.get("economic_normalized_data")
        if isinstance(econ_norm_root, dict):
            summ = econ_norm_root.get("summary") or {}
            if isinstance(summ, dict):
                total_docs = int(summ.get("documents_count") or 0)
                items_cnt = int(summ.get("items_count") or 0)
                if total_docs > 0:
                    alertas_contexto_bases.append(
                        f"[Canónico] Fuentes económicas normalizadas: {total_docs} documento(s), {items_cnt} partida(s)."
                    )
                ph = summ.get("placeholder_signals") or {}
                if isinstance(ph, dict) and (
                    ph.get("raw_text_contains_total_0")
                    or ph.get("raw_text_contains_pending_markers")
                    or ph.get("high_zero_ratio")
                ):
                    alertas_contexto_bases.append(
                        "[Canónico] Señales de plantilla detectadas (totales en 0 o marcadores pendientes); validar cantidad de elementos y total final."
                    )
        alcance_catalog = self._alcance_rows_to_catalog_entries(alcance_bases)

        # 3. Identificar requerimientos que necesitan COTIZACIÓN
        # Filtrar ítems técnicos que son documentos generados por la app (no cotizables)
        # Estrategia dual (Cursor): señales negativas + señales positivas + categoría upstream
        tech_requirements_raw = master_list.get("tecnico") or master_list.get("técnico") or []

        doc_ids_upstream = build_upstream_doc_ids(master_list)

        tech_requirements = []
        excluded_as_docs = []
        for req in tech_requirements_raw:
            if should_exclude_technical_for_cotization(req, doc_ids_upstream):
                excluded_as_docs.append(req)
                continue
            tech_requirements.append(req)

        if excluded_as_docs:
            logger.info(
                "economic_excluded_doc_items",
                session_id=session_id,
                excluded_count=len(excluded_as_docs),
                remaining_count=len(tech_requirements),
            )
            print(f"    [Económico] Excluidos {len(excluded_as_docs)} ítems documentales (no cotizables). Cotizables: {len(tech_requirements)}", flush=True)

        print(f"    [DEBUG] Técnico items count: {len(tech_requirements)} (de {len(tech_requirements_raw)} totales)", flush=True)

        if not tech_requirements and pricing_line_items:
            tech_requirements = tech_requirements_from_tabular_pricing(pricing_line_items)
            logger.info(
                "economic_tabular_only_mode",
                session_id=session_id,
                tabular_count=len(tech_requirements),
            )
            print(
                f"    [Económico] Sin ítems técnicos cotizables; uso {len(tech_requirements)} partida(s) "
                "desde cotización/importe tabular.",
                flush=True,
            )

        if not tech_requirements:
            price_source_blocking = _build_price_source_blocking_items(excluded_as_docs)
            if price_source_blocking:
                print("    [-] No hay ítems cotizables, pero sí referencias a fuente económica real.", flush=True)
                if missing_structured_price_slots:
                    from app.services.structured_price_capture import (
                        prepare_structured_price_capture,
                    )

                    fresh_s = await self.context_manager.memory.get_session(session_id) or {}
                    missing_fields, intro_msg, cap_updates = prepare_structured_price_capture(
                        fresh_s,
                        missing_structured_price_slots,
                        session_id=session_id,
                    )
                    await self._save_pending_questions(session_id, missing_fields)
                    if cap_updates:
                        fresh_s.update(cap_updates)
                        await self.context_manager.memory.save_session(
                            session_id, cap_updates
                        )
                    return AgentOutput(
                        status=AgentStatus.WAITING_FOR_DATA,
                        agent_id=self.agent_id,
                        session_id=session_id,
                        message=intro_msg,
                        data={
                            "missing": missing_fields,
                            "missing_price_count": len(missing_fields),
                            "validation_result": {
                                "blocking_issues": [
                                    "structured_price_capture_pending"
                                ]
                            },
                        },
                        correlation_id=correlation_id,
                    )
                missing_fields = [_build_economic_price_source_question(price_source_blocking, structured_template_summary)]
                await self._save_pending_questions(session_id, missing_fields)
                return AgentOutput(
                    status=AgentStatus.WAITING_FOR_DATA,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message=_build_economic_price_source_intro(price_source_blocking, structured_template_summary),
                    data={
                        "missing": missing_fields,
                        "missing_price_count": len(price_source_blocking),
                        "alertas_contexto_bases": alertas_contexto_bases,
                        "contexto_bases_analista": contexto_bases_analista,
                    },
                    correlation_id=correlation_id,
                )
            print("    [-] No se detectaron ítems cotizables en la auditoría previa.", flush=True)
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id=self.agent_id,
                session_id=session_id,
                message="No hay requerimientos económicos detectables.",
                correlation_id=correlation_id
            )

        # HITO: Catálogo empresa + partidas Excel + filas de alcance operativo (bases) + RAG.
        print(f"    [*] Realizando búsqueda semántica de precios para {len(tech_requirements)} ítems...")
        enriched_catalog = list(company_catalog) + tabular_catalog + alcance_catalog
        for req in tech_requirements:
            label = (
                req.get("label")
                or req.get("descripcion")
                or req.get("titulo")
                or req.get("texto")
                or ""
            )
            label = str(label).strip()
            if not label:
                continue
            
            # Consultamos la base vectorial por este concepto
            # Aumentado a 6 para asegurar captura de precios unitarios en tablas de anexos económicos
            rag_results = self.vector_db.query_texts(session_id, f"precio unitario de {label}", n_results=6)
            docs = (
                rag_results.get("documents", [])
                if isinstance(rag_results, dict)
                else []
            )
            if docs:
                # Añadimos un ítem "virtual" al catálogo basado en lo hallado en RAG
                context_str = " ".join(docs)
                # Este ítem virtual permitirá al LLM en _calculate_proposal tomar decisiones informadas
                enriched_catalog.append({
                    "name": f"REFERENCIA_RAG_{label}",
                    "description": f"Encontrado en documentos de la sesión: {context_str}",
                    "price": 0.0, # El LLM lo extraerá del texto de la descripción
                    "is_rag_reference": True
                })

        # --- SILENCIO ECONÓMICO (solo si no es disparo explícito desde chat) ---
        if not skip_economic_silence and await self._check_economic_silence(
            session_id, correlation_id
        ):
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=(
                    "La cotización económica está en pausa mientras el inventario legal "
                    "documental siga pendiente en el panel. Puedes completarlo allí o, si ya "
                    "tienes los precios, escríbelos aquí (ej. precio unitario por concepto)."
                ),
                correlation_id=correlation_id,
            )

        # 4. Cálculo de Propuesta (mapeo semántico con marco de bases del Analista)
        calculation_result = await self._calculate_proposal(
            tech_requirements,
            enriched_catalog,
            correlation_id,
            bases_economic_context=bases_economic_context,
        )
        
        if isinstance(calculation_result, dict) and calculation_result.get("status") == "error":
             return AgentOutput(
                status=AgentStatus.ERROR,
                agent_id=self.agent_id,
                session_id=session_id,
                error=calculation_result.get("message", "Error desconocido en cálculo"),
                correlation_id=correlation_id
             )
        
        if isinstance(calculation_result, list):
             proposal_draft = calculation_result
             alertas: List[Any] = []
        else:
             proposal_draft = calculation_result.get("items", []) or []
             alertas = calculation_result.get("alertas") or []

        proposal_draft = self._apply_tabular_prices_to_proposal(
            proposal_draft, tech_requirements, pricing_line_items
        )
        proposal_draft = self._bootstrap_proposal_from_tabular_rows(
            proposal_draft, pricing_line_items
        )
        from app.services.economic_refresher import EconomicRefresherService
        refresher = EconomicRefresherService()
        proposal_draft = refresher.apply_overrides(
            proposal_draft,
            session_state.get("economic_user_inputs") or {},
            tech_requirements,
            session_state # Argumento faltante que causaba TypeError
        )
        proposal_draft = self._attach_guard_schedules_from_session(
            proposal_draft,
            session_state.get("economic_user_inputs") or {},
        )
        proposal_draft = self._attach_provenance_ui_defaults(proposal_draft)
        chat_override_alerts = self._build_chat_override_alerts(proposal_draft)
        proposal_draft = self._ensure_supervisor_no_cost_item(
            proposal_draft, alcance_bases, tech_requirements
        )

        # 5. Detección de Gaps Económicos
        # El LLM a menudo devuelve "matched" con precio 0 o sin precio: eso NO es cotizable.
        economic_gaps: List[Dict] = []
        for item in proposal_draft:
            st = (item.get("status") or "").lower()
            pu = item.get("precio_unitario")
            try:
                # If explicitly missing, set to -1 to trigger gap
                pu_f = float(pu) if pu is not None and str(pu).strip() != "" else -1.0
            except (TypeError, ValueError):
                pu_f = -1.0 # Set to -1 so we can distinguish from a user typing 0
            if st == "price_missing" or pu_f < 0:
                economic_gaps.append(item)
        
        if economic_gaps:
            logger.info("economic_gaps_detected", session_id=session_id, count=len(economic_gaps))
            
            # --- Hito 6: Generar pending_questions econonómicas ---
            missing_fields = []
            unverified_suggestions: List[Dict[str, Any]] = []
            non_cotizable_fields = {
                str(it.get("field"))
                for it in (session_state.get("economic_non_cotizable_overrides") or [])
                if str(it.get("field") or "").strip()
            }
            min_block = max(1, int(getattr(app_settings, "BLOCK_RESOLUTION_MIN_ITEMS", 3) or 3))
            block_group_key: Optional[str] = None
            if len(economic_gaps) >= min_block:
                # Misma clave para todos los gaps de esta corrida → RequirementGrouper puede armar un bloque.
                block_group_key = f"economic_proposal:{session_id}"
            seq_real = 0
            for _, gap in enumerate(economic_gaps):
                concepto = gap.get("concepto", "Concepto técnico")
                req_g = _tech_requirement_by_id(tech_requirements, gap.get("concepto_id"))
                ref_g = _economic_gap_reference_snippet(req_g, str(concepto))
                guard_ctx = _is_guard_like_context(str(concepto), req_g, ref_g)
                anchor = _strict_anchor_from_requirement(req_g, ref_g)
                oi_enriched = dict(gap or {})
                oi_enriched.update({k: v for k, v in anchor.items() if v is not None})
                row: Dict[str, Any] = {
                    "field": f"price_{gap.get('concepto_id', concepto)}", # ID virtual o nombre
                    "label": f"Precio (sin IVA): {concepto}",
                    "question": self._build_economic_price_question_for_user(
                        str(concepto), tech_requirements, gap
                    ),
                    "document_hint": str(anchor.get("source") or ""),
                    "type": "economic_price",
                    "original_item": oi_enriched,
                    "capture_guard_schedule": guard_ctx,
                }
                if str(row.get("field") or "") in non_cotizable_fields:
                    logger.info(
                        "economic_gap_skipped_non_cotizable_override",
                        session_id=session_id,
                        field=str(row.get("field")),
                    )
                    continue
                if is_contaminated_economic_pending_question(row):
                    logger.warning(
                        "economic_gap_skipped_documental",
                        session_id=session_id,
                        concepto_preview=str(concepto)[:120],
                    )
                    continue
                if not _has_strict_anchor_for_user(row):
                    if relax_price_anchors:
                        row["original_item"] = _ensure_chat_anchor(oi_enriched, str(concepto))
                    else:
                        unverified_suggestions.append(
                            {
                                "field": str(row.get("field") or ""),
                                "label": str(row.get("label") or "")[:280],
                                "reason": "missing_strict_anchor",
                                "source": "economic_fail_closed",
                                "concepto": str(concepto)[:220],
                                "anchor_preview": {
                                    "source": row["original_item"].get("source"),
                                    "page": row["original_item"].get("page"),
                                    "snippet": str(row["original_item"].get("snippet") or "")[:180],
                                },
                            }
                        )
                        logger.warning(
                            "economic_gap_skipped_unanchored",
                            session_id=session_id,
                            field=str(row.get("field") or ""),
                        )
                        continue
                if block_group_key:
                    row["block_group_key"] = block_group_key
                    row["block_item_seq"] = seq_real
                    seq_real += 1
                missing_fields.append(row)

            if unverified_suggestions:
                s2 = await self.context_manager.memory.get_session(session_id) or {}
                bucket = list(s2.get("economic_unverified_suggestions") or [])
                bucket.extend(unverified_suggestions)
                s2["economic_unverified_suggestions"] = bucket[-400:]
                await self.context_manager.memory.save_session(session_id, s2)

            if not missing_fields and economic_gaps and relax_price_anchors:
                for gap in economic_gaps:
                    concepto = gap.get("concepto", "Concepto técnico")
                    if str(f"price_{gap.get('concepto_id', concepto)}") in non_cotizable_fields:
                        continue
                    row_fb: Dict[str, Any] = {
                        "field": f"price_{gap.get('concepto_id', concepto)}",
                        "label": f"Precio (sin IVA): {concepto}",
                        "question": self._build_economic_price_question_for_user(
                            str(concepto), tech_requirements, gap
                        ),
                        "document_hint": "bases_licitacion",
                        "type": "economic_price",
                        "original_item": _ensure_chat_anchor(dict(gap or {}), str(concepto)),
                    }
                    if is_contaminated_economic_pending_question(row_fb):
                        continue
                    missing_fields.append(row_fb)
                if missing_fields:
                    logger.info(
                        "economic_gaps_relaxed_anchor_fallback",
                        session_id=session_id,
                        count=len(missing_fields),
                    )

            if not missing_fields and economic_gaps:
                if missing_structured_price_slots:
                    from app.services.structured_price_capture import (
                        prepare_structured_price_capture,
                    )

                    fresh_s = await self.context_manager.memory.get_session(session_id) or {}
                    missing_fields, intro_msg, cap_updates = prepare_structured_price_capture(
                        fresh_s,
                        missing_structured_price_slots,
                        session_id=session_id,
                    )
                    await self._save_pending_questions(session_id, missing_fields)
                    if cap_updates:
                        await self.context_manager.memory.save_session(
                            session_id, cap_updates
                        )
                    return AgentOutput(
                        status=AgentStatus.WAITING_FOR_DATA,
                        agent_id=self.agent_id,
                        session_id=session_id,
                        message=intro_msg,
                        data={
                            "missing": missing_fields,
                            "missing_price_count": len(missing_fields),
                            "validation_result": {
                                "blocking_issues": [
                                    "structured_price_capture_pending"
                                ]
                            },
                        },
                        correlation_id=correlation_id,
                    )
                price_source_blocking = _build_price_source_blocking_items(excluded_as_docs)
                if price_source_blocking and not pricing_line_items:
                    missing_fields = [_build_economic_price_source_question(price_source_blocking, structured_template_summary)]
                    await self._save_pending_questions(session_id, missing_fields)
                    return AgentOutput(
                        status=AgentStatus.WAITING_FOR_DATA,
                        agent_id=self.agent_id,
                        session_id=session_id,
                        message=_build_economic_price_source_intro(price_source_blocking, structured_template_summary),
                        data={
                            "missing": missing_fields,
                            "missing_price_count": len(price_source_blocking),
                            "alertas_contexto_bases": list(alertas_contexto_bases) + list(chat_override_alerts),
                            "contexto_bases_analista": contexto_bases_analista,
                        },
                        correlation_id=correlation_id,
                    )
            if not missing_fields:
                logger.warning(
                    "economic_gaps_all_filtered_documental",
                    session_id=session_id,
                    raw_gaps=len(economic_gaps),
                )
            else:
                if not skip_economic_silence:
                    inv = session_state.get("document_inventory", {})
                    inv_items = inv.get("items", [])
                    has_pending_legal = any(
                        self._inventory_item_blocks_economic_progress(it)
                        for it in inv_items
                    )
                    if has_pending_legal:
                        logger.info(
                            "economic_silence_active",
                            session_id=session_id,
                            reason="pending_legal_docs",
                        )
                        return AgentOutput(
                            status=AgentStatus.WAITING_FOR_DATA,
                            agent_id=self.agent_id,
                            session_id=session_id,
                            message=(
                                "Hay documentos legales pendientes en el inventario. "
                                "Puedes resolverlos en el panel o capturar precios aquí en el chat."
                            ),
                            correlation_id=correlation_id,
                        )

                await self._save_pending_questions(session_id, missing_fields)
                n = len(missing_fields)
                first_gap = missing_fields[0].get("original_item") or economic_gaps[0]
                msg_intro = self._build_economic_msg_intro(n, first_gap, tech_requirements)
                return AgentOutput(
                    status=AgentStatus.WAITING_FOR_DATA,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    message=msg_intro,
                    data={
                        "missing": missing_fields,
                        "alertas_contexto_bases": list(alertas_contexto_bases) + list(chat_override_alerts),
                        "contexto_bases_analista": {
                            "reglas_economicas": reglas_bases,
                            "alcance_operativo_filas": len(alcance_bases),
                            "datos_tabulares": dict(datos_tab),
                        },
                    },
                    correlation_id=correlation_id,
                )

        # 6. Consolidación Final (motor determinista + cuadratura)
        user_inputs = session_state.get("economic_user_inputs") or {}
        proposal_draft = self.calculator.normalize_items(proposal_draft)
        session_name_for_profile = str(session_state.get("name") or session_id)
        
        # Inyectar overrides del chat (FSR) en las reglas en formato texto para el Regex del Engine
        # Hito 4.3: Inyectar también valores de ley por defecto si faltan, para evitar bloqueos innecesarios
        defaults = {
            "sar": "0.02",
            "infonavit": "0.05",
            "prima_vacacional": "0.25",
            "dias_laborados": "365",
            "dias_no_laborados": "0"
        }
        
        # Primero inyectamos defaults (si no están ya en reglas_bases)
        for k, v in defaults.items():
            if k not in reglas_bases:
                reglas_bases[f"default_{k}"] = f"{k}: {v}"

        # Luego inyectamos los del usuario (tienen prioridad absoluta)
        for k, v in user_inputs.items():
            if k != "concept_prices" and v is not None:
                reglas_bases[f"chat_override_{k}"] = f"{k}: {v}"

        def _recompute_from_current_draft(
            items: List[Dict[str, Any]],
        ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], float, float, Dict[str, Any]]:
            norm_items = self.calculator.normalize_items(items)
            calc_totals = self.calculator.compute_totals(
                norm_items, reglas_bases, session_name_for_profile
            )
            calc_total_base = float(calc_totals.get("total_base") or 0.0)
            calc_grand_total = float(calc_totals.get("grand_total") or 0.0)
            quad = self.calculator.build_quadrature_report(norm_items, pricing_line_items)
            return norm_items, calc_totals, calc_total_base, calc_grand_total, quad

        proposal_draft, totals, total_base, grand_total, quadrature_report = (
            _recompute_from_current_draft(proposal_draft)
        )
        if total_base <= 0 and pricing_line_items:
            # Fallback duro P0: si el LLM no produjo renglones cotizables, usar directamente
            # session_line_items para evitar engine_total=0 con Excel sí presente.
            proposal_draft, totals, total_base, grand_total, quadrature_report = (
                _recompute_from_current_draft(
                    self._proposal_from_session_line_items(pricing_line_items)
                )
            )

        excel_total_q = float(quadrature_report.get("excel_total") or 0.0)
        engine_total_q = float(quadrature_report.get("engine_total") or 0.0)
        severe_quadrature_gap = (
            bool(quadrature_report.get("blocking"))
            and excel_total_q > 0
            and abs(engine_total_q - excel_total_q) / max(excel_total_q, 1.0) > 0.95
            and len(pricing_line_items) > len(proposal_draft or [])
        )
        if severe_quadrature_gap:
            # Verdad canónica: si la sesión ya trae renglones tabulares abundantes y el
            # resumen del LLM queda desfasado por >95 %, confiamos en la base normalizada.
            proposal_draft, totals, total_base, grand_total, quadrature_report = (
                _recompute_from_current_draft(
                    self._proposal_from_session_line_items(pricing_line_items)
                )
            )

        if bool(quadrature_report.get("blocking")) and pricing_line_items:
            # Cotización tabular: usar partidas de sesión solo si cierra la cuadratura.
            _, _, _, _, quadrature_canonical = _recompute_from_current_draft(
                self._proposal_from_session_line_items(pricing_line_items)
            )
            if not quadrature_canonical.get("blocking"):
                proposal_draft, totals, total_base, grand_total, quadrature_report = (
                    _recompute_from_current_draft(
                        self._proposal_from_session_line_items(pricing_line_items)
                    )
                )

        calc_blocking_issues = list(totals.get("blocking_issues") or [])
        alertas_merged = (
            list(alertas if isinstance(alertas, list) else [])
            + alertas_contexto_bases
            + chat_override_alerts
        )
        if quadrature_report.get("available"):
            alertas_merged.append(
                (
                    "[Cuadratura] Excel vs motor: "
                    f"{quadrature_report.get('excel_total', 0.0):.2f} vs "
                    f"{quadrature_report.get('engine_total', 0.0):.2f} "
                    f"(delta {quadrature_report.get('delta_total', 0.0):.2f})."
                )
            )
        if calc_blocking_issues:
            fsr_msg = (
                "No cierres la app. Faltan parámetros obligatorios para calcular el Factor de Salario Real "
                "(Anexos 8/9/9A/13). Captura los datos requeridos y vuelve a generar."
            )
            calc_missing = [
                {
                    "field": "validation_rule_fsr_required",
                    "label": "Completar parámetros FSR",
                    "question": str(calc_blocking_issues[0]),
                    "document_hint": "Captura IMSS, SAR, Infonavit, días laborados/no laborados y prestaciones.",
                    "type": "economic_validation_blocking",
                    "blocking_items": [],
                }
            ]
            await self._save_pending_questions(session_id, calc_missing)
            blocked_payload: Dict[str, Any] = {
                "status": "waiting_for_data",
                "currency": "MXN",
                "items": proposal_draft,
                "total_base": float(total_base),
                "grand_total": float(grand_total),
                "analisis_precios": {"alertas": alertas_merged},
                "missing": calc_missing,
                "calculator_result": {
                    "profile_name": totals.get("profile_name"),
                    "formula_set": totals.get("formula_set"),
                    "fsr": totals.get("fsr"),
                    "blocking_issues": calc_blocking_issues,
                },
                "quadrature_report": quadrature_report,
                "contexto_bases_analista": {
                    "reglas_economicas": reglas_bases,
                    "alcance_operativo_filas": len(alcance_bases),
                    "datos_tabulares": dict(datos_tab),
                },
            }
            await self.context_manager.record_task_completion(
                session_id, "economic_proposal", blocked_payload
            )
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=fsr_msg,
                data={
                    "missing": calc_missing,
                    "alertas_contexto_bases": list(alertas_contexto_bases) + list(chat_override_alerts),
                    "calculator_result": {
                        "profile_name": totals.get("profile_name"),
                        "formula_set": totals.get("formula_set"),
                        "fsr": totals.get("fsr"),
                        "blocking_issues": calc_blocking_issues,
                    },
                    "quadrature_report": quadrature_report,
                    "contexto_bases_analista": {
                        "reglas_economicas": reglas_bases,
                        "alcance_operativo_filas": len(alcance_bases),
                        "datos_tabulares": dict(datos_tab),
                    },
                },
                correlation_id=correlation_id,
            )
        if bool(quadrature_report.get("blocking")):
            cuadratura_msg = (
                "No cierres la app. Detecté una diferencia de cuadratura entre tu Excel y el cálculo del motor "
                "económico mayor a $0.01. Revisa partidas y vuelve a generar."
            )
            quadrature_missing = [
                {
                    "field": "validation_rule_quadrature",
                    "label": "Corregir cuadratura económica",
                    "question": (
                        "El total del Excel no cuadra con el total calculado por el motor. "
                        "Ajusta precios o cantidades en tu Excel y vuelve a intentar."
                    ),
                    "document_hint": "Revisa subtotal por partida en tu Excel/cotización.",
                    "type": "economic_validation_blocking",
                    "blocking_items": [],
                }
            ]
            await self._save_pending_questions(session_id, quadrature_missing)
            blocked_payload: Dict[str, Any] = {
                "status": "waiting_for_data",
                "currency": "MXN",
                "items": proposal_draft,
                "total_base": float(total_base),
                "grand_total": float(grand_total),
                "analisis_precios": {"alertas": alertas_merged},
                "missing": quadrature_missing,
                "calculator_result": {
                    "profile_name": totals.get("profile_name"),
                    "formula_set": totals.get("formula_set"),
                    "fsr": totals.get("fsr"),
                    "blocking_issues": calc_blocking_issues,
                },
                "quadrature_report": quadrature_report,
                "contexto_bases_analista": {
                    "reglas_economicas": reglas_bases,
                    "alcance_operativo_filas": len(alcance_bases),
                    "datos_tabulares": dict(datos_tab),
                },
            }
            await self.context_manager.record_task_completion(
                session_id, "economic_proposal", blocked_payload
            )
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=cuadratura_msg,
                data={
                    "missing": quadrature_missing,
                    "alertas_contexto_bases": list(alertas_contexto_bases) + list(chat_override_alerts),
                    "calculator_result": {
                        "profile_name": totals.get("profile_name"),
                        "formula_set": totals.get("formula_set"),
                        "fsr": totals.get("fsr"),
                        "blocking_issues": calc_blocking_issues,
                    },
                    "quadrature_report": quadrature_report,
                    "contexto_bases_analista": {
                        "reglas_economicas": reglas_bases,
                        "alcance_operativo_filas": len(alcance_bases),
                        "datos_tabulares": dict(datos_tab),
                    },
                },
                correlation_id=correlation_id,
            )
        allow_zero_total_base = bool(
            (session_state.get("economic_user_inputs") or {}).get("allow_zero_total_base_ack")
        )
        validation_result = validate_economic_proposal(
            proposal_items=proposal_draft,
            currency="MXN",
            total_base=float(total_base),
            grand_total=float(grand_total),
            reglas_economicas=reglas_bases,
            session_name=session_name_for_profile,
            allow_zero_total_base=allow_zero_total_base,
        )
        if validation_result.blocking_issues:
            validation_events: List[Dict[str, Any]] = []
            for issue in validation_result.blocking_issues:
                error_type = str(issue).split(":", 1)[0].strip().lower()
                if not error_type:
                    error_type = "economic_validation_blocking"
                raw_context: Dict[str, Any] = {"session_id": session_id}
                traz = validation_result.trazabilidad.get(error_type)
                if isinstance(traz, dict):
                    valor = traz.get("valor_calculado")
                    if isinstance(valor, dict):
                        raw_context.update(valor)
                    elif isinstance(valor, list) and valor:
                        names = [str(x).strip() for x in valor if str(x).strip()]
                        # La traza puede truncar nombres (p. ej. [:8]); el texto del issue lleva el total real.
                        total_from_issue: Optional[int] = None
                        if isinstance(issue, str):
                            _mct = re.search(r"(\d+)\s*ítems", issue, re.I)
                            if _mct:
                                total_from_issue = int(_mct.group(1))
                        raw_context["item_count"] = (
                            total_from_issue if total_from_issue is not None else max(len(names), 1)
                        )
                        raw_context["lista_breve"] = (
                            ", ".join(names[:4]) + (f" (y {len(names) - 4} más)" if len(names) > 4 else "")
                            if names
                            else "partidas sin nombre legible"
                        )
                        # Mantener lista explícita para que el chatbot pida concepto por concepto
                        # (evita degradar a placeholders tipo "3 partidas").
                        raw_context["valor_calculado"] = names
                        raw_context["item_name"] = names[0] if names else ""
                        raw_context["raw_value"] = "0"
                policy = resolve_validation_policy(
                    session_state,
                    error_type=error_type,
                )
                event = validation_mapping_service.build_event(
                    error_type=error_type,
                    context=raw_context,
                    raw_message=issue,
                    policy=policy,
                )
                validation_events.append(event)

            missing_fields = []
            def _locator_from_requirement_or_item(label: str, proposal_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                """Ubica evidencia mínima (página o fila) + snippet para un concepto bloqueado."""
                norm_lbl = self._normalize_econ_label(label)
                req_hit: Optional[Dict[str, Any]] = None
                if isinstance(proposal_item, dict):
                    req_hit = _tech_requirement_by_id(tech_requirements, proposal_item.get("concepto_id"))
                if req_hit is None:
                    for req in tech_requirements or []:
                        if not isinstance(req, dict):
                            continue
                        cand = str(
                            req.get("label")
                            or req.get("descripcion")
                            or req.get("titulo")
                            or req.get("texto")
                            or ""
                        ).strip()
                        if not cand:
                            continue
                        n_cand = self._normalize_econ_label(cand)
                        if norm_lbl == n_cand or (len(norm_lbl) >= 6 and (norm_lbl in n_cand or n_cand in norm_lbl)):
                            req_hit = req
                            break
                anchor = _strict_anchor_from_requirement(req_hit, label)
                page_number = anchor.get("page")
                row_index = None
                if isinstance(proposal_item, dict):
                    for rk in ("row_index", "tabular_row_index", "excel_row_index"):
                        rv = proposal_item.get(rk)
                        if rv is not None:
                            try:
                                row_index = int(float(rv))
                                break
                            except (TypeError, ValueError):
                                row_index = None
                snippet = str(anchor.get("snippet") or "").strip()
                if not snippet and isinstance(proposal_item, dict):
                    snippet = str(
                        proposal_item.get("descripcion")
                        or proposal_item.get("concepto")
                        or label
                    ).strip()
                return {
                    "source_name": str(anchor.get("source") or "propuesta_economica").strip(),
                    "page_number": int(page_number) if isinstance(page_number, int) else None,
                    "row_index": row_index,
                    "context_snippet": snippet[:420],
                }

            def _build_blocking_item(label: str, error_type: str, valor_detectado: float = 0.0, proposal_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                loc = _locator_from_requirement_or_item(label, proposal_item=proposal_item)
                return {
                    "concepto_id": _slug_block_item_id(error_type, label),
                    "concepto_label": label[:280],
                    "motivo": error_type,
                    "valor_detectado": valor_detectado,
                    "trace_ref": {"source": "validation_result.trazabilidad"},
                    "source_name": loc.get("source_name"),
                    "page_number": loc.get("page_number"),
                    "row_index": loc.get("row_index"),
                    "context_snippet": loc.get("context_snippet"),
                    "evidence_quality": "strict" if (loc.get("page_number") is not None or loc.get("row_index") is not None) else "weak",
                }

            def _filter_actionable_blocking_items(items: List[Dict[str, Any]], field_id: str) -> List[Dict[str, Any]]:
                """Contrato canónico: sin page_number ni row_index, el ítem no se expone al usuario."""
                ok: List[Dict[str, Any]] = []
                for it in items or []:
                    has_locator = it.get("page_number") is not None or it.get("row_index") is not None
                    if has_locator:
                        ok.append(it)
                        continue
                    bucket = list(session_state.get("economic_unverified_suggestions") or [])
                    bucket.append(
                        {
                            "field": field_id,
                            "label": str(it.get("concepto_label") or "")[:280],
                            "reason": "missing_evidence_locator",
                            "source": "economic_evidence_contract",
                            "error_type": str(it.get("motivo") or "economic_validation_blocking"),
                        }
                    )
                    session_state["economic_unverified_suggestions"] = bucket[-400:]
                return ok

            def _fallback_blocking_items_from_proposal(
                issue_text: str,
                error_type: str,
            ) -> List[Dict[str, Any]]:
                """
                Deriva items accionables desde `proposal_draft` cuando la trazabilidad
                no trae nombres legibles (caso real en producción para precios_positivos).
                """
                if error_type == "total_base_cotizable":
                    return [
                        {
                            "concepto_id": _slug_block_item_id(error_type, "subtotal_base"),
                            "concepto_label": "Subtotal cotizable antes de IVA",
                            "motivo": error_type,
                            "valor_detectado": float(total_base),
                            "trace_ref": {"source": "total_base_cotizable"},
                            "source_name": "propuesta_economica",
                            "page_number": None,
                            "row_index": 1,
                            "context_snippet": (
                                "El importe base es cero o inferior al mínimo operativo. "
                                "Captura precios en tu cotización o solicita confirmación HITL de oferta sin importe base."
                            )[:420],
                            "evidence_quality": "strict",
                        }
                    ]
                if error_type != "precios_positivos":
                    return []
                out_items: List[Dict[str, Any]] = []
                for pos, it in enumerate(proposal_draft or [], start=1):
                    if not isinstance(it, dict):
                        continue
                    if it.get("supervisor_sin_costo") is True:
                        continue
                    try:
                        pu = float(it.get("precio_unitario") or 0)
                    except (TypeError, ValueError):
                        pu = 0.0
                    if pu > 0:
                        continue
                    raw_label = str(it.get("concepto") or it.get("descripcion") or "").strip()
                    label = raw_label if raw_label else f"Ítem #{pos} de tu lista de precios"
                    if _looks_documental_non_cotizable(label):
                        continue
                    cid_raw = str(it.get("concepto_id") or "").strip()
                    cid = cid_raw or _slug_block_item_id(error_type, label)
                    bi = _build_blocking_item(label=label, error_type=error_type, valor_detectado=pu, proposal_item=it)
                    bi["concepto_id"] = cid[:120]
                    bi["trace_ref"] = {"source": "proposal_items", "index": pos}
                    out_items.append(bi)
                if out_items:
                    return out_items
                mcnt = re.search(r"(\d+)\s*ítems", str(issue_text or ""), re.I)
                if mcnt and int(mcnt.group(1)) > 0:
                    n = min(int(mcnt.group(1)), 50)
                    return [
                        {
                            "concepto_id": _slug_block_item_id(error_type, f"item_{i}"),
                            "concepto_label": f"Ítem #{i} de tu lista de precios",
                            "motivo": error_type,
                            "valor_detectado": 0,
                            "trace_ref": {"source": "blocking_issue_count_fallback", "index": i},
                            "source_name": "propuesta_economica",
                            "page_number": None,
                            "row_index": i,
                            "context_snippet": f"Ítem #{i} detectado sin etiqueta legible en la propuesta económica.",
                            "evidence_quality": "strict",
                        }
                        for i in range(1, n + 1)
                    ]
                return []
            for i, (issue, ev) in enumerate(
                zip(validation_result.blocking_issues, validation_events), start=1
            ):
                ux = ev.get("ux") or {}
                friendly_q = (ux.get("user_message") or issue or "").strip()
                ctx = ev.get("context") if isinstance(ev.get("context"), dict) else {}
                items_raw = ctx.get("valor_calculado") if isinstance(ctx, dict) else None
                blocking_items: List[Dict[str, Any]] = []
                if isinstance(items_raw, list):
                    for nm in items_raw:
                        s = str(nm).strip()
                        if not s:
                            continue
                        if _looks_documental_non_cotizable(s):
                            continue
                        blocking_items.append(
                            _build_blocking_item(
                                label=s,
                                error_type=str(ev.get("error_type") or "economic_validation_blocking"),
                                valor_detectado=0,
                            )
                        )
                elif isinstance(ctx.get("item_name"), str) and ctx.get("item_name").strip():
                    s = str(ctx.get("item_name")).strip()
                    # Descartar placeholders agregados ("N partidas"/"N conceptos"), no son accionables.
                    if (not re.match(r"^\d+\s+(partidas?|conceptos?)$", s, re.I)) and (not _looks_documental_non_cotizable(s)):
                        blocking_items.append(
                            _build_blocking_item(
                                label=s,
                                error_type=str(ev.get("error_type") or "economic_validation_blocking"),
                                valor_detectado=0,
                            )
                        )
                if not blocking_items:
                    blocking_items = _fallback_blocking_items_from_proposal(
                        issue_text=str(issue),
                        error_type=str(ev.get("error_type") or "").strip().lower(),
                    )
                blocking_items = _filter_actionable_blocking_items(
                    blocking_items,
                    field_id=f"validation_rule_{i}",
                )
                if not blocking_items:
                    # Fail-closed para bloqueos no accionables por chat.
                    bucket = list(session_state.get("economic_unverified_suggestions") or [])
                    bucket.append(
                        {
                            "field": f"validation_rule_{i}",
                            "label": str(ux.get("title") or "Corregir propuesta económica").strip()[:280],
                            "reason": "blocking_without_actionable_items",
                            "source": "economic_validation_fail_closed",
                            "error_type": str(ev.get("error_type") or "economic_validation_blocking"),
                        }
                    )
                    session_state["economic_unverified_suggestions"] = bucket[-400:]
                    continue
                missing_fields.append(
                    {
                        "field": f"validation_rule_{i}",
                        "label": str(ux.get("title") or "Corregir propuesta económica").strip(),
                        "question": friendly_q,
                        "document_hint": "Responde en el chat del asistente o ajusta precios en tu Excel/cotización.",
                        "type": "economic_validation_blocking",
                        "blocking_items": blocking_items,
                    }
                )
            if missing_fields:
                await self._save_pending_questions(session_id, missing_fields)
            else:
                await self.context_manager.memory.save_session(session_id, session_state)
            # Persistir igual que en el camino de éxito: el chatbot lee tasks_completed → economic_proposal → validation_result.
            blocked_payload: Dict[str, Any] = {
                "status": "waiting_for_data",
                "currency": "MXN",
                "items": proposal_draft,
                "total_base": float(total_base),
                "grand_total": float(grand_total),
                "allow_zero_total_base_ack": allow_zero_total_base,
                "analisis_precios": {"alertas": alertas_merged},
                "validation_result": validation_result.model_dump(mode="json"),
                "missing": missing_fields,
                "validation_events": validation_events,
                "calculator_result": {
                    "profile_name": totals.get("profile_name"),
                    "formula_set": totals.get("formula_set"),
                    "fsr": totals.get("fsr"),
                    "blocking_issues": calc_blocking_issues,
                },
                "quadrature_report": quadrature_report,
                "contexto_bases_analista": {
                    "reglas_economicas": reglas_bases,
                    "alcance_operativo_filas": len(alcance_bases),
                    "datos_tabulares": dict(datos_tab),
                },
            }
            validation_dump = blocked_payload["validation_result"]
            datos_tabular_payload = blocked_payload.get("contexto_bases_analista", {}).get("datos_tabulares") or {}
            datos_tabulares_metric = (
                len(datos_tabular_payload)
                if isinstance(datos_tabular_payload, dict)
                else 0
            )
            logger.info(
                "economic_proposal_blocking_persisted",
                session_id=session_id,
                blocking_issues_count=len(validation_dump.get("blocking_issues") or []),
                validations_count=len(validation_dump.get("validations") or []),
                alerts_count=len(validation_dump.get("alerts") or []),
                validation_events_count=len(blocked_payload.get("validation_events") or []),
                missing_pending_count=len(blocked_payload.get("missing") or []),
                datos_tabulares_top_keys=datos_tabulares_metric,
                perfil_usado=str(validation_dump.get("perfil_usado") or "unknown"),
            )
            await self.context_manager.record_task_completion(
                session_id, "economic_proposal", blocked_payload
            )
            actionable_count = sum(
                len((mf.get("blocking_items") if isinstance(mf.get("blocking_items"), list) else []))
                for mf in (missing_fields or [])
                if str(mf.get("type") or "") == "economic_validation_blocking"
            )
            if actionable_count > 0:
                blocking_user_msg = (
                    "Para finalizar el análisis de tu propuesta, necesito que me ayudes con el valor de las partidas faltantes.\n\n"
                    f"Todavía me faltan **{actionable_count}** precio(s) por capturar para poder completar la validación económica."
                )
            else:
                blocking_user_msg = (
                    "Necesito tu ayuda para completar algunos precios que no pude localizar automáticamente en los documentos.\n\n"
                    "Por favor, revisa tus partidas en el chat o en tu cotización y proporciónanos los valores para poder avanzar."
                )
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=blocking_user_msg,
                data={
                    "missing": missing_fields,
                    "validation_events": validation_events,
                    "alertas_contexto_bases": list(alertas_contexto_bases) + list(chat_override_alerts),
                    "validation_result": validation_result.model_dump(mode="json"),
                    "actionable_missing_count": actionable_count,
                    "contexto_bases_analista": {
                        "reglas_economicas": reglas_bases,
                        "alcance_operativo_filas": len(alcance_bases),
                        "datos_tabulares": dict(datos_tab),
                    },
                },
                correlation_id=correlation_id,
            )
        final_result = {
            "status": "complete",
            "currency": "MXN",
            "items": proposal_draft,
            "total_base": total_base,
            "grand_total": grand_total,
            "allow_zero_total_base_ack": allow_zero_total_base,
            "analisis_precios": {
                "alertas": alertas_merged,
            },
            "validation_result": validation_result.model_dump(mode="json"),
            "calculator_result": {
                "profile_name": totals.get("profile_name"),
                "formula_set": totals.get("formula_set"),
                "fsr": totals.get("fsr"),
                "blocking_issues": calc_blocking_issues,
            },
            "quadrature_report": quadrature_report,
            "contexto_bases_analista": {
                "reglas_economicas": reglas_bases,
                "alcance_operativo_filas": len(alcance_bases),
                "datos_tabulares": dict(datos_tab),
            },
        }

        await self.context_manager.record_task_completion(session_id, "economic_proposal", final_result)
        print(f"💰 [Económico] Propuesta Calculada: ${final_result['grand_total']:.2f}")
        
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=final_result,
            correlation_id=correlation_id
        )

    def _extract_analisis_bases_from_session(self, session_state: Dict[str, Any]) -> Dict[str, Any]:
        """Último resultado de `analisis_bases` en tasks_completed, o {}."""
        for task in reversed(session_state.get("tasks_completed") or []):
            if task.get("task") == "analisis_bases":
                res = task.get("result")
                return res if isinstance(res, dict) else {}
        return {}

    def _ensure_supervisor_no_cost_item(
        self,
        proposal_items: List[Dict[str, Any]],
        alcance: List[Dict[str, str]],
        tech_requirements: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Inyecta un renglón de supervisión sin costo cuando el alcance lo exige."""
        joined = " ".join(
            str(r.get("texto_literal_fila") or r.get("puesto_funcion_o_servicio") or "")
            for r in (alcance or [])
        )
        req_joined = " ".join(
            str(r.get("label") or r.get("descripcion") or r.get("texto") or "")
            for r in (tech_requirements or [])
            if isinstance(r, dict)
        )
        source = f"{joined} {req_joined}".strip()
        needs_supervisor = re.search(r"(?i)(supervisor|coordinador|jefe\s*de\s*turno)", source)
        no_cost_signal = re.search(r"(?i)(sin\s*costo|0\.00|sin\s*cargo|costos?\s+indirectos?)", source)
        if not needs_supervisor:
            return proposal_items
        has_item = False
        for it in proposal_items:
            text = f"{it.get('concepto','')} {it.get('descripcion','')}"
            if re.search(r"(?i)(supervisor|coordinador|jefe\s*de\s*turno)", text):
                has_item = True
                if no_cost_signal or re.search(r"(?i)(sin\s*costo|0\.00|sin\s*cargo|costos?\s+indirectos?)", text):
                    it["precio_unitario"] = 0.0
                    it["subtotal"] = 0.0
                    it["supervisor_sin_costo"] = True
        if has_item:
            return proposal_items
        return proposal_items + [{
            "concepto": "Supervisor General (Sin costo)",
            "descripcion": "Supervisor General (Sin costo, incluido en costos indirectos)",
            "concepto_id": "AUTO-SUP-NC",
            "cantidad": 1,
            "precio_unitario": 0.0,
            "subtotal": 0.0,
            "status": "matched",
            "incluir_en_indirectos": True,
            "supervisor_sin_costo": True,
        }]

    def _format_bases_economic_context(
        self,
        reglas: Dict[str, str],
        alcance: List[Dict[str, str]],
        datos_tab: Dict[str, Any],
    ) -> str:
        """Texto para el LLM: reglas citadas, alcance tabular y estado de partidas en sesión."""
        lines: List[str] = ["=== REGLAS ECONÓMICAS (literal bases) ==="]
        _def = "No especificado"
        any_rule = False
        for k, v in reglas.items():
            if v and v != _def:
                lines.append(f"- {k}: {v}")
                any_rule = True
        if not any_rule:
            lines.append("(Sin reglas económicas explícitas distintas de 'No especificado'.)")

        lines.append("\n=== ALCANCE OPERATIVO (filas resumidas) ===")
        if not alcance:
            lines.append("(Sin filas de alcance operativo en el análisis de bases.)")
        else:
            for i, row in enumerate(alcance[:30]):
                frag = row.get("texto_literal_fila") or row.get("puesto_funcion_o_servicio") or ""
                lines.append(
                    f"Fila {i + 1}: área={row.get('ubicacion_o_area', '')!s} | "
                    f"puesto/servicio={row.get('puesto_funcion_o_servicio', '')!s} | "
                    f"cant={row.get('cantidad_o_elementos', '')!s} | turno={row.get('turno', '')!s} | "
                    f"literal={str(frag)[:220]}"
                )
            if len(alcance) > 30:
                lines.append(f"(... {len(alcance) - 30} filas más omitidas en el resumen.)")

        lines.append("\n=== DATOS TABULARES (sesión vs bases) ===")
        lines.append(f"line_items_count: {datos_tab.get('line_items_count', 'N/D')}")
        lines.append(
            f"texto_sugiere_partidas_o_anexo_tabular: "
            f"{datos_tab.get('texto_sugiere_partidas_o_anexo_tabular', False)}"
        )
        af = datos_tab.get("alerta_faltante")
        if isinstance(af, str) and af.strip():
            lines.append(f"ALERTA_TABULAR: {af.strip()}")
        return "\n".join(lines)

    def _build_bases_economic_alertas(
        self,
        reglas: Dict[str, str],
        datos_tab: Dict[str, Any],
    ) -> List[str]:
        """Alertas determinísticas para anexar a analisis_precios (y en WAITING_FOR_DATA)."""
        out: List[str] = []
        _def = "No especificado"
        af = datos_tab.get("alerta_faltante")
        if isinstance(af, str) and af.strip():
            out.append(f"[Partidas/sesión] {af.strip()}")
        for key in (
            "criterio_importe_minimo_o_plazo_inferior",
            "criterio_importe_maximo_o_plazo_superior",
            "meses_o_periodo_minimo_citado",
            "meses_o_periodo_maximo_citado",
            "vinculacion_presupuesto_partida",
            "referencia_partidas_anexos_citados",
            "modalidad_contratacion_observada",
            "otras_reglas_oferta_precio",
        ):
            val = reglas.get(key, _def)
            if val != _def:
                out.append(f"[Bases] {key}: {val} — revisar coherencia con totales y plazos.")
        return out

    def _alcance_rows_to_catalog_entries(self, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Convierte filas de alcance_operativo en ítems guía (sin precio) para el mapeo del LLM."""
        out: List[Dict[str, Any]] = []
        for row in rows[:50]:
            name = (row.get("puesto_funcion_o_servicio") or row.get("texto_literal_fila") or "").strip()
            if len(name) < 3:
                continue
            qty = row.get("cantidad_o_elementos") or ""
            desc_parts = [
                row.get("ubicacion_o_area"),
                row.get("turno"),
                row.get("horario"),
                row.get("dias_aplicables"),
                row.get("texto_literal_fila"),
            ]
            desc = " | ".join(p for p in desc_parts if p)
            out.append(
                {
                    "name": name[:512],
                    "description": (
                        f"(Alcance operativo en bases) {desc[:1500]} "
                        f"Cantidad referida en bases: {qty}"
                    ).strip(),
                    "price": 0.0,
                    "is_alcance_operativo": True,
                }
            )
        return out

    @staticmethod
    def _is_reliable_pricing_row(row: Dict[str, Any]) -> bool:
        """Filtra filas tabulares que sí pueden usarse como evidencia económica."""
        from app.services.economic_tabular_ingest_sync import is_reliable_pricing_row

        return is_reliable_pricing_row(row)

    def _filter_reliable_pricing_rows(self, rows: List[Dict]) -> List[Dict]:
        """Conserva solo evidencia tabular que trae ancla de precio utilizable."""
        return [row for row in (rows or []) if self._is_reliable_pricing_row(row)]

    def _tabular_rows_to_catalog_entries(self, rows: List[Dict]) -> List[Dict]:
        """Convierte filas de session_line_items en ítems de catálogo consumibles por el LLM."""
        out: List[Dict] = []
        for row in rows:
            out.append(
                {
                    "name": (row.get("concepto_norm") or "")[:512],
                    "description": (row.get("concepto_raw") or "")[:2000],
                    "price": float(row.get("precio_unitario") or 0),
                    "unidad": row.get("unidad"),
                    "is_session_tabular": True,
                }
            )
        return out

    def _proposal_from_session_line_items(
        self,
        session_line_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Construye propuesta mínima directamente desde partidas tabulares de sesión."""
        out: List[Dict[str, Any]] = []
        for idx, row in enumerate(session_line_items or [], start=1):
            try:
                qty = float(row.get("cantidad") or 1.0)
            except (TypeError, ValueError):
                qty = 1.0
            if qty <= 0:
                qty = 1.0
            try:
                pu = float(row.get("precio_unitario") or 0.0)
            except (TypeError, ValueError):
                pu = 0.0
            concepto = str(
                row.get("concepto_raw")
                or row.get("concepto_norm")
                or f"Partida tabular {idx}"
            ).strip()
            out.append(
                {
                    "concepto_id": str(row.get("id") or f"line_{idx}"),
                    "concepto": concepto,
                    "descripcion": str(row.get("concepto_raw") or concepto),
                    "unidad": row.get("unidad") or "SERVICIO",
                    "cantidad": qty,
                    "precio_unitario": pu,
                    "status": "matched",
                    "price_source": "session_line_items_engine_fallback",
                }
            )
        return out

    def _bootstrap_proposal_from_tabular_rows(
        self,
        proposal_draft: List[Dict[str, Any]],
        tabular_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Fallback determinista cuando el LLM no aterriza partidas cotizables.

        Si hay filas tabulares en sesión pero la propuesta queda vacía o en ceros,
        construye ítems mínimos desde `session_line_items` para que el motor económico
        pueda cuadrar contra Excel y no se quede en `engine_total=0`.
        """
        if not tabular_rows:
            return proposal_draft

        has_positive = False
        for item in proposal_draft or []:
            try:
                if float(item.get("subtotal") or 0.0) > 0:
                    has_positive = True
                    break
            except (TypeError, ValueError):
                continue
        if proposal_draft and has_positive:
            return proposal_draft

        boot_items: List[Dict[str, Any]] = []
        for idx, row in enumerate(tabular_rows, start=1):
            try:
                qty = float(row.get("cantidad") or 1.0)
            except (TypeError, ValueError):
                qty = 1.0
            if qty <= 0:
                qty = 1.0
            try:
                pu = float(row.get("precio_unitario") or 0.0)
            except (TypeError, ValueError):
                pu = 0.0
            if row.get("subtotal") is not None:
                try:
                    subtotal = float(row.get("subtotal") or 0.0)
                except (TypeError, ValueError):
                    subtotal = qty * pu
            elif row.get("importe") is not None:
                try:
                    subtotal = float(row.get("importe") or 0.0)
                except (TypeError, ValueError):
                    subtotal = qty * pu
            else:
                subtotal = qty * pu

            concepto = str(
                row.get("concepto_raw")
                or row.get("concepto_norm")
                or f"Partida tabular {idx}"
            ).strip()
            boot_items.append(
                {
                    "concepto_id": str(row.get("id") or f"tabular_{idx}"),
                    "concepto": concepto,
                    "unidad": row.get("unidad") or "SERVICIO",
                    "cantidad": qty,
                    "precio_unitario": pu,
                    "subtotal": subtotal,
                    "status": "matched",
                    "price_source": "session_line_items_bootstrap",
                    "provenance_ui": {
                        "source_key": "excel",
                        "source_label": "Excel",
                        "source_icon": "🟡",
                        "detail": "Partida construída automáticamente desde session_line_items.",
                    },
                }
            )
        return boot_items

    def _build_economic_price_question_for_user(
        self,
        concepto: str,
        tech_requirements: List[Dict[str, Any]],
        gap: Dict[str, Any],
    ) -> str:
        """
        Pregunta HITL en lenguaje natural: precio unitario sin IVA y, si el contexto es de
        vigilancia por guardia, también el esquema de horas (consumible vía ``economic_user_inputs``).
        """
        req = _tech_requirement_by_id(tech_requirements, gap.get("concepto_id"))
        ref = _economic_gap_reference_snippet(req, concepto)
        guard = _is_guard_like_context(str(concepto), req, ref)

        if guard:
            lines = [
                "Necesito el precio unitario sin IVA del servicio de vigilancia por guardia "
                f"(o unidad operativa equivalente) para: {concepto}.",
                "También dime qué periodos de horas por guardia van a ejecutar "
                "(por ejemplo 12x12 o 24x24).",
            ]
            if ref:
                lines.insert(1, f"Referencia en bases/dictamen: {ref}.")
            lines.append(
                "Cómo responder: escribe el importe (solo número, sin IVA) y, si ya tienes el esquema, "
                "ponlo en la misma línea separado por punto y coma (ejemplo: 5800; 24x24) "
                "o en el siguiente mensaje. Si no aplica costo: 0. Si aún no defines turnos: pendiente. "
                "Para aplazar: siguiente."
            )
            return "\n\n".join(lines)

        lines = [
            f"Necesito el precio unitario sin IVA que ofertas para el servicio o entregable "
            f"relacionado con: {concepto}.",
            "Si en bases la unidad es distinta (mes, evento, global, licencia, etc.), usa la misma unidad "
            "con la que cotizas en tu Excel o tabla de precios.",
        ]
        if ref:
            lines.insert(1, f"Referencia en bases/dictamen: {ref}.")
        lines.append(
            "Responde con el número (sin IVA). Si no lleva dinero: 0 o sin costo. Para aplazar: siguiente."
        )
        return "\n\n".join(lines)

    def _build_economic_msg_intro(
        self,
        n: int,
        first_gap: Dict[str, Any],
        tech_requirements: List[Dict[str, Any]],
    ) -> str:
        """Mensaje resumido al usuario: alineado con el primer pendiente y tono humano."""
        concepto = str(first_gap.get("concepto") or "este concepto").strip()
        req = _tech_requirement_by_id(tech_requirements, first_gap.get("concepto_id"))
        ref = _economic_gap_reference_snippet(req, concepto)
        if _is_guard_like_context(concepto, req, ref):
            return (
                f"Para completar la propuesta, necesito que definamos {n} datos de cotización que no logré extraer de los documentos.\n\n"
                f"¿Cuál es el **precio unitario (sin IVA)** para **{concepto}**? "
                "Si ya tienes definido el esquema de horas (ej. 12x12 o 24x24), puedes incluirlo también."
            )
        return (
            f"He identificado {n} conceptos que requieren tu validación de precio para cerrar el cálculo económico.\n\n"
            f"¿Qué **precio unitario (sin IVA)** debemos asignar a **{concepto}**?\n"
            "Si prefieres dejarlo para después, solo escribe 'siguiente'."
        )

    def _normalize_econ_label(self, value: Any) -> str:
        t = re.sub(r"\s+", " ", str(value).strip().lower())
        return t[:2000] if len(t) > 2000 else t

    def _tabular_similarity(self, a: str, b: str) -> float:
        """
        Similitud en [0, 1] entre dos etiquetas ya normalizadas.
        Usa rapidfuzz (partial + token_sort) si está instalado; si no, difflib + orden de tokens.
        """
        if not a or not b:
            return 0.0
        if _rf_fuzz is not None:
            return max(
                _rf_fuzz.partial_ratio(a, b) / 100.0,
                _rf_fuzz.token_sort_ratio(a, b) / 100.0,
                _rf_fuzz.token_set_ratio(a, b) / 100.0,
            )
        ta = " ".join(sorted(a.split()))
        tb = " ".join(sorted(b.split()))
        return max(
            SequenceMatcher(None, a, b).ratio(),
            SequenceMatcher(None, ta, tb).ratio(),
        )

    def _fuzzy_best_tabular_row(
        self,
        candidates: List[str],
        by_norm: Dict[str, Dict],
    ) -> Tuple[Optional[Dict], float]:
        """
        Elige la fila tabular cuya concepto_norm maximiza similitud frente a los candidatos.
        Umbral por defecto 0.68 (ECON_TABULAR_FUZZY_THRESHOLD).
        """
        if not candidates or not by_norm:
            return None, 0.0
        try:
            thr = float(os.getenv("ECON_TABULAR_FUZZY_THRESHOLD", "0.68"))
        except ValueError:
            thr = 0.68
        thr = max(0.5, min(0.95, thr))

        best_row: Optional[Dict] = None
        best_sc = 0.0
        for c in candidates:
            if not c or len(c) < 6:
                continue
            for tnorm, row in by_norm.items():
                if len(tnorm) < 3:
                    continue
                sc = self._tabular_similarity(c, tnorm)
                if sc > best_sc:
                    best_sc = sc
                    best_row = row
        if best_row is not None and best_sc >= thr:
            return best_row, best_sc
        return None, best_sc

    def _apply_tabular_prices_to_proposal(
        self,
        proposal_draft: List[Dict],
        tech_requirements: List[Dict],
        tabular_rows: List[Dict],
    ) -> List[Dict]:
        """
        Post-proceso: asigna precio_unitario desde partidas Excel si el LLM dejó gap.
        Orden: coincidencia exacta → subcadena (textos largos) → matching difuso (rapidfuzz/difflib).
        """
        if not tabular_rows or not proposal_draft:
            return proposal_draft
        by_norm = {r["concepto_norm"]: r for r in tabular_rows if r.get("concepto_norm")}
        req_by_id: Dict[str, Dict] = {}
        for r in tech_requirements:
            rid = r.get("id")
            if rid is not None:
                req_by_id[str(rid)] = r

        for item in proposal_draft:
            st = (item.get("status") or "").lower()
            pu = item.get("precio_unitario")
            try:
                pu_f = float(pu) if pu is not None and pu != "" else 0.0
            except (TypeError, ValueError):
                pu_f = 0.0
            need_fill = pu_f <= 0 or st == "price_missing"
            if not need_fill:
                continue

            candidates: List[str] = []
            if item.get("concepto"):
                candidates.append(self._normalize_econ_label(item["concepto"]))
            cid = item.get("concepto_id")
            if cid is not None and str(cid) in req_by_id:
                r0 = req_by_id[str(cid)]
                lbl = r0.get("label") or r0.get("descripcion") or r0.get("titulo") or r0.get("texto")
                if lbl:
                    candidates.append(self._normalize_econ_label(lbl))

            hit: Optional[Dict] = None
            for c in candidates:
                if c and c in by_norm:
                    hit = by_norm[c]
                    break
            if hit is None and candidates:
                n0 = candidates[0]
                if len(n0) >= 10:
                    for tnorm, row in by_norm.items():
                        if len(tnorm) >= 10 and (n0 in tnorm or tnorm in n0):
                            hit = row
                            break
            fuzzy_sc = 0.0
            if hit is None and candidates:
                hit, fuzzy_sc = self._fuzzy_best_tabular_row(candidates, by_norm)
            if not hit:
                continue

            qty = item.get("cantidad")
            try:
                qty_f = float(qty) if qty is not None and qty != "" else 1.0
            except (TypeError, ValueError):
                qty_f = 1.0
            price = float(hit["precio_unitario"])
            item["precio_unitario"] = price
            item["subtotal"] = qty_f * price
            item["status"] = "matched"
            if fuzzy_sc > 0:
                item["price_source"] = "session_line_items_fuzzy"
                item["tabular_match_score"] = round(fuzzy_sc, 3)
                item["provenance_ui"] = {
                    "source_key": "excel",
                    "source_label": "Excel",
                    "source_icon": "🟡",
                    "detail": (
                        f"Precio tomado de partidas tabulares de sesión "
                        f"(matching difuso, score={round(fuzzy_sc, 3)})."
                    ),
                }
            else:
                item["price_source"] = "session_line_items"
                row_idx = hit.get("row_index")
                item["provenance_ui"] = {
                    "source_key": "excel",
                    "source_label": "Excel",
                    "source_icon": "🟡",
                    "detail": (
                        f"Precio tomado de archivo tabular de sesión"
                        + (f", fila {row_idx}." if row_idx is not None else ".")
                    ),
                }
        return proposal_draft

    def _build_chat_override_alerts(self, proposal_draft: List[Dict[str, Any]]) -> List[str]:
        """
        Construye alertas explicables para los precios sobreescritos por chat.
        """
        out: List[str] = []
        for item in proposal_draft or []:
            if str(item.get("price_source") or "").strip() != "chat_user_override":
                continue
            concepto = str(item.get("concepto") or item.get("descripcion") or "concepto").strip()
            try:
                precio = float(item.get("precio_unitario") or 0.0)
            except (TypeError, ValueError):
                precio = 0.0
            out.append(
                f"[Conversación] Se aplicó precio manual para: {concepto} (${precio:,.2f}) vía Chat."
            )
        return out

    def _apply_chat_overrides_to_proposal(
        self,
        proposal_draft: List[Dict[str, Any]],
        tech_requirements: List[Dict[str, Any]],
        economic_user_inputs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Aplica overrides transaccionales del chat al borrador de propuesta.

        Cascada de verdad:
        1) economic_user_inputs (chat)
        2) session_line_items / económico canónico (ya aplicados antes)
        3) inferencia LLM.
        """
        if not proposal_draft or not isinstance(economic_user_inputs, dict):
            return proposal_draft

        concept_prices = economic_user_inputs.get("concept_prices")
        if not isinstance(concept_prices, dict) or not concept_prices:
            return proposal_draft

        req_by_id: Dict[str, Dict[str, Any]] = {}
        for req in tech_requirements or []:
            rid = req.get("id")
            if rid is not None:
                req_by_id[str(rid)] = req

        # Depuración: Ver qué conceptos tenemos en la propuesta
        available_concepts = [str(it.get("concepto") or it.get("descripcion") or "S/N") for it in proposal_draft]
        logger.info(
            "economic_agent_override_debug",
            session_id=self.agent_id,
            user_input_concepts=list(concept_prices.keys()),
            proposal_concepts_count=len(available_concepts),
            proposal_concepts_preview=available_concepts[:10]
        )

        for k, v in concept_prices.items():
            try:
                normalized_prices[self._normalize_econ_label(k)] = float(v)
            except (TypeError, ValueError):
                continue

        for item in proposal_draft:
            candidates: List[str] = []
            concepto = item.get("concepto")
            if concepto:
                candidates.append(self._normalize_econ_label(concepto))

            cid = item.get("concepto_id")
            if cid is not None and str(cid) in req_by_id:
                req = req_by_id[str(cid)]
                lbl = req.get("label") or req.get("descripcion") or req.get("titulo") or req.get("texto")
                if lbl:
                    candidates.append(self._normalize_econ_label(lbl))

            if not candidates:
                continue

            hit_key: Optional[str] = None
            # 1) exacto
            for c in candidates:
                if c in normalized_prices:
                    hit_key = c
                    break
            # 2) subcadena
            if hit_key is None:
                for c in candidates:
                    for k in normalized_prices.keys():
                        if (len(c) >= 8 and c in k) or (len(k) >= 8 and k in c):
                            hit_key = k
                            break
                    if hit_key is not None:
                        break
            # 3) fuzzy (Matching Inteligente con RapidFuzz)
            if hit_key is None:
                best_score = 0.0
                best_key = None
                # Umbral de confianza ajustado para balancear Wow vs Seguridad
                # 0.70 permite variaciones descriptivas pero bloquea cargos distintos.
                CONFIDENCE_THRESHOLD = 0.70 
                
                for c in candidates:
                    for k in normalized_prices.keys():
                        sc = self._tabular_similarity(c, k)
                        if sc > best_score:
                            best_score = sc
                            best_key = k
                
                if best_key is not None:
                    logger.info(
                        "economic_agent_fuzzy_match_attempt",
                        input_concept=c,
                        best_match=best_key,
                        score=round(best_score, 3),
                        threshold=CONFIDENCE_THRESHOLD,
                        passed=best_score >= CONFIDENCE_THRESHOLD
                    )

                if best_key is not None and best_score >= CONFIDENCE_THRESHOLD:
                    hit_key = best_key
                    logger.info(
                        "economic_agent_fuzzy_chat_match_found",
                        candidate=candidates[0] if candidates else "N/A",
                        matched_key=hit_key,
                        score=round(best_score, 3)
                    )

            if hit_key is None:
                continue

            try:
                qty = float(item.get("cantidad") or 1.0)
            except (TypeError, ValueError):
                qty = 1.0
            price = float(normalized_prices[hit_key])
            item["precio_unitario"] = price
            item["subtotal"] = qty * price
            item["status"] = "matched"
            item["price_source"] = "chat_user_override"
            item["provenance_ui"] = {
                "source_key": "chat",
                "source_label": "Chat",
                "source_icon": "🟢",
                "detail": f"Instrucción directa del usuario para '{hit_key}': ${price:,.2f}.",
            }

        return proposal_draft

    def _attach_guard_schedules_from_session(
        self,
        proposal_draft: List[Dict[str, Any]],
        economic_user_inputs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Copia a cada ítem el texto de esquema de horas por guardia capturado en chat
        (``economic_user_inputs["concept_guard_schedules"]``), para consumo en UI/export.
        """
        schedules = economic_user_inputs.get("concept_guard_schedules")
        if not isinstance(schedules, dict) or not schedules:
            return proposal_draft
        for item in proposal_draft:
            cid = item.get("concepto_id")
            keys = []
            if cid is not None and str(cid).strip():
                keys.append(str(cid).strip())
                keys.append(f"price_{str(cid).strip()}")
            concepto = item.get("concepto")
            if concepto is not None and str(concepto).strip():
                keys.append(f"price_{str(concepto).strip()}")
            note = None
            for k in keys:
                if k in schedules and str(schedules.get(k) or "").strip():
                    note = str(schedules[k]).strip()[:2000]
                    break
            if note:
                item["horario_ofertado_por_guardia"] = note
        return proposal_draft

    def _attach_provenance_ui_defaults(self, proposal_draft: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Asegura `provenance_ui` en cada ítem para renderizado frontend.
        """
        for item in proposal_draft or []:
            if isinstance(item.get("provenance_ui"), dict):
                continue
            src = str(item.get("price_source") or "").strip()
            if src in {"chat_user_override"}:
                item["provenance_ui"] = {
                    "source_key": "chat",
                    "source_label": "Chat",
                    "source_icon": "🟢",
                    "detail": "Precio aplicado por conversación (override manual).",
                }
            elif src in {"session_line_items", "session_line_items_fuzzy"}:
                item["provenance_ui"] = {
                    "source_key": "excel",
                    "source_label": "Excel",
                    "source_icon": "🟡",
                    "detail": "Precio obtenido de partidas tabulares normalizadas.",
                }
            else:
                item["provenance_ui"] = {
                    "source_key": "catalog_or_llm",
                    "source_label": "Catálogo/Inferencia",
                    "source_icon": "⚪",
                    "detail": "Precio estimado desde catálogo y/o inferencia del agente económico.",
                }
        return proposal_draft

    async def _calculate_proposal(
        self,
        requirements: List[Dict],
        catalog: List[Dict],
        correlation_id: str = "",
        *,
        bases_economic_context: str = "",
    ) -> Dict:
        """Usa el LLM para mapear requerimientos; el cálculo monetario es determinista en Python."""
        ctx_block = (bases_economic_context or "").strip()
        if not ctx_block:
            ctx_block = "(Sin contexto adicional del analista de bases.)"
        prompt = f"""
REQUERIMIENTOS: {json.dumps(requirements)}
CATALOGO: {json.dumps(catalog)}

CONTEXTO DEL ANALISTA DE BASES (usar para coherencia de cantidades, plazos y alertas; no inventar precios aquí):
{ctx_block}

REGLA CRÍTICA MONETARIA (NO RELAJABLE):
- NO calcules importes ni subtotales.
- Si no hay precio verificable en el material, usa status="price_missing".

REGLA CRÍTICA (NO RELAJABLE):
- NO cotices entregables documentales/legales. Si el concepto parece "carta", "escrito", "declaración",
  "bajo protesta", "acta", "constancia", "anexo", "formato", "manifiesto", etc., NO lo marques como
  "matched" ni "price_missing": simplemente omítelo de "items".

Prioriza precios así: 1) ítems con "is_session_tabular": true (Excel de sesión), 2) catálogo de empresa sin flags,
3) "is_alcance_operativo": true como guía de descripción y cantidad si aplica al requerimiento,
4) "is_rag_reference" solo como apoyo textual.

Si el contexto cita importes/meses/plazos o alerta tabular, refleja advertencias en "alertas".
Genera un JSON ESTRICTO con la siguiente estructura:
{{
    "items": [
        {{
            "concepto": "nombre del requerimiento",
            "concepto_id": "id del requerimiento original",
            "cantidad": 1,
            "status": "matched" // (usa price_missing si no hallas precio exacto)
        }}
    ],
    "alertas": ["alerta 1"] // (opcional: alertas sobre monedas o condiciones deducidas)
}}
"""
        resp = await self.llm.generate(
            prompt=prompt, 
            system_prompt="Analista Financiero estricto. Responde única y exclusivamente con un JSON válido.", 
            format="json",
            correlation_id=correlation_id
        )
        if not resp.success:
            return {"status": "error", "message": resp.error}
        return self._robust_json_parse(resp.response or "{}")

    async def _get_company_catalog(self, company_id: str) -> List[Dict]:
        if not company_id: return []
        try:
            company = await self.context_manager.memory.get_company(company_id)
            return company.get("catalog", []) if company else []
        except Exception as e:
            logger.error(f"[EconomicAgent] Error obteniendo catalogo: {e}")
            return []

    def _robust_json_parse(self, text: str) -> Any:
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            # El prompt estricto pide un objeto JSON {...}
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
            return {}
        except Exception as e:
            logger.error(f"[EconomicAgent] Parser error: {e}")
            return {}

    async def _save_pending_questions(self, session_id: str, missing_fields: List[Dict]):
        """Persiste preguntas para el chatbot de forma segura (Hito 6)."""
        try:
            # Leer el estado más fresco posible
            fresh = await self.context_manager.memory.get_session(session_id)
            if fresh is None:
                fresh = {}
            
            existing = fresh.get("pending_questions", []) or []
            incoming_types = {str(q.get("type") or "") for q in missing_fields}
            
            # Limpiar la cola económica previa del mismo tipo para evitar preguntas stale
            # y permitir que mejoras de wording/procedencia reemplacen versiones antiguas.
            replaceable_types = {"economic_validation_blocking", "economic_price"}
            types_to_replace = incoming_types & replaceable_types
            if types_to_replace:
                existing = [
                    q for q in existing if str(q.get("type") or "") not in types_to_replace
                ]
            
            def _get_q_key(q):
                return str(q.get("question_id") or q.get("field") or q.get("field_target") or "")

            existing_keys = {_get_q_key(q) for q in existing if _get_q_key(q)}
            new_questions = [q for q in missing_fields if _get_q_key(q) not in existing_keys]

            from app.services.hitl_queue_service import normalize_pending_queue

            final_list = normalize_pending_queue(existing + new_questions)

            # Log de seguridad (para trazabilidad con Orchestrator)
            logger.info("economic_save_pending_questions", 
                        session_id=session_id, 
                        count=len(final_list),
                        added=len(new_questions))

            updates: Dict[str, Any] = {
                "pending_questions": final_list
            }
            try:
                from app.services.economic_capture_matrix_service import (
                    build_capture_matrix_blocks,
                )

                line_items = fresh.get("session_line_items") or []
                matrices = build_capture_matrix_blocks(
                    line_items, fresh.get("economic_user_inputs")
                )
                if matrices:
                    updates["capture_matrix_blocks"] = matrices
            except Exception:
                pass

            # Forzar foco si hay nuevas económicas
            if new_questions and any(str(q.get("type")) == "economic_price" for q in new_questions):
                updates["current_question_index"] = 0
            elif "current_question_index" not in fresh:
                updates["current_question_index"] = 0

            # Aplicar cambios al estado fresco
            fresh.update(updates)
            await self.context_manager.memory.save_session(session_id, fresh)
            
        except Exception as e:
            logger.error(f"[EconomicAgent] ⚠️ Error guardando preguntas econ: {e}")

    async def _check_economic_silence(self, session_id: str, correlation_id: str) -> bool:
        """Determina si debemos callar las brechas económicas en favor del inventario legal."""
        try:
            fresh = await self.context_manager.memory.get_session(session_id)
            if not fresh: 
                logger.info("silence_check_no_session", session_id=session_id)
                return False
            
            inv = fresh.get("document_inventory", {})
            inv_items = inv.get("items", [])
            logger.info("silence_check_inventory", session_id=session_id, items_count=len(inv_items))
            
            # Solo silenciamos si el pendiente legal es realmente bloqueante para la oferta.
            has_pending_legal = False
            for it in inv_items:
                if self._inventory_item_blocks_economic_progress(it):
                    has_pending_legal = True
                    logger.info("silence_check_hit", session_id=session_id, item=it.get("name"))
                    break
            
            if has_pending_legal:
                logger.info("economic_silence_active", session_id=session_id, reason="pending_legal_docs")
                return True
        except Exception as e:
            logger.warning("economic_silence_check_failed", session_id=session_id, error=str(e))
        return False

    @staticmethod
    def _inventory_item_blocks_economic_progress(item: Dict[str, Any]) -> bool:
        """Solo ciertos pendientes legales deben silenciar el frente económico."""
        if not isinstance(item, dict):
            return False
        category = str(item.get("category") or item.get("requirement_type") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        if category != "legal_administrative" or status != "pending":
            return False
        if bool(item.get("is_blocking")):
            return True
        tier = str(item.get("tier") or "").strip().lower()
        if tier in {"inferred", "post_award", "postaward"}:
            return False
        return False
