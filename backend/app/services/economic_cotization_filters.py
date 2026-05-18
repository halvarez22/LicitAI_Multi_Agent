"""
Filtros compartidos: qué requisitos técnicos son cotizables vs documentales (entregables sin PU).

Usado por EconomicAgent y scripts de mantenimiento (limpieza de pending_questions / catálogo).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

# Alineado con la lógica de exclusión del EconomicAgent (documento sin señal operativa/precio).
_DOC_PATTERNS = re.compile(
    r"(?i)(carta\s|protesta|declaraci[oó]n|manifiesto|resumen\s|anexo\s|formato\s"
    r"|constancia\s|escrito\s|acreditaci[oó]n|certificaci[oó]n\s|curriculum|cv\s"
    r"|organigrama|relaci[oó]n\s+de\s+personal|poder\s+notarial|acta\s)"
)
_PRICE_PATTERNS = re.compile(
    r"(?i)(precio|costo|tarifa|importe|monto|unitario|elemento|vigilante|guardia"
    r"|turno|jornada|hora\s|mes\s|mensual|personal\s+operativo|equipo\s|material"
    r"|suministro|servicio\s+de\s|prestaci[oó]n)"
)

# Señales documentales duras: deben excluirse de cotización incluso si conviven
# con palabras generales de operación (p. ej. "prestación del servicio").
_HARD_DOC_PATTERNS = re.compile(
    r"(?i)(escrito|carta|declaraci[oó]n|bajo\s+protesta|manifiesto|anexo|formato"
    r"|constancia|folio|acreditaci[oó]n|certificaci[oó]n|presentaci[oó]n|copia"
    r"|registro|original|acuse|folio|comprobante)"
)

# Documentos técnicos de obra pública: entregables que se presentan como documentos,
# no como partidas con precio unitario. Típicos de licitaciones de construcción/obra.
_OBRA_PUBLICA_DOC_PATTERNS = re.compile(
    r"(?i)(conocimiento\s+de\s+las\s+bases|modificaciones\s+realizadas|junta\s+de\s+aclaraciones"
    r"|relaci[oó]n\s+de\s+contratos|contratos\s+de\s+obras|contratos\s+en\s+vigor"
    r"|relaci[oó]n\s+de\s+maquinaria|equipo\s+de\s+construcci[oó]n|programa\s+de\s+utilizaci[oó]n"
    r"|programa\s+de\s+ejecuci[oó]n|programa\s+de\s+obra|calendario\s+de\s+obra"
    r"|memoria\s+descriptiva|especificaciones\s+t[eé]cnicas|cat[aá]logo\s+de\s+conceptos"
    r"|explosivo\s+de\s+insumos|an[aá]lisis\s+de\s+precios\s+unitarios|tabulador"
    r"|curriculum\s+vitae|experiencia\s+del\s+licitante|capacidad\s+financiera"
    r"|estados\s+financieros|declaraci[oó]n\s+fiscal|situaci[oó]n\s+fiscal"
    r"|identificaci[oó]n\s+oficial|acta\s+constitutiva|poder\s+notarial"
    r"|registro\s+de\s+contratistas|padr[oó]n\s+de\s+contratistas)"
)
# Entregables económico-documentales (no partida operativa), aunque digan "mensual" o "anual".
_DELIVERABLE_ECONOMIC_SUMMARY = re.compile(
    r"(?i)resumen\s+(de\s+)?(la\s+)?cotiz|estado\s+de\s+cuenta.*cotiz|propuesta\s+econ[oó]mica\s+resumen"
)


def merge_technical_item_text(req: Dict[str, Any]) -> str:
    """Texto unificado para clasificar un ítem del master_list técnico."""
    parts = [
        str(req.get("descripcion") or ""),
        str(req.get("nombre") or ""),
        str(req.get("snippet") or ""),
        str(req.get("label") or ""),
        str(req.get("texto") or ""),
        str(req.get("titulo") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def build_upstream_doc_ids(master_list: Dict[str, Any]) -> Set[str]:
    """IDs presentes en formatos o administrativo (evitar cotizar duplicados)."""
    out: Set[str] = set()
    for cat in ("formatos", "administrativo"):
        for item in master_list.get(cat) or []:
            rid = str(item.get("id", "")).strip()
            if rid:
                out.add(rid)
    return out


def should_exclude_technical_for_cotization(
    req: Dict[str, Any],
    doc_ids_upstream: Set[str],
) -> bool:
    """
    True si el ítem técnico no debe entrar al motor de cotización (documento / duplicado upstream).
    """
    rid = str(req.get("id", "")).strip()
    if rid and rid in doc_ids_upstream:
        return True
    text = merge_technical_item_text(req)
    if not text:
        return False
    if _DELIVERABLE_ECONOMIC_SUMMARY.search(text):
        return True
    # Documentos técnicos de obra pública
    if _OBRA_PUBLICA_DOC_PATTERNS.search(text):
        return True
    # Regla prioritaria de sentido común: entregables documentales no son
    # partidas cotizables, aunque mencionen "servicio", "prestación", etc.
    if _HARD_DOC_PATTERNS.search(text):
        return True
    is_doc = bool(_DOC_PATTERNS.search(text))
    is_price = bool(_PRICE_PATTERNS.search(text))
    return bool(is_doc and not is_price)


def _pending_economic_core_concept_text(q: Dict[str, Any]) -> str:
    """
    Texto del concepto a cotizar, sin plantillas que contienen la palabra «precio»
    (si no, todo pending económico parecería «señal de precio»).
    """
    lbl = str(q.get("label") or "")
    core = re.sub(r"(?i)^\s*precio\s+de\s*:\s*", "", lbl).strip()
    core = re.sub(r"(?i)^\s*precio\s*\(sin\s+iva\)\s*:\s*", "", core).strip()
    oi = q.get("original_item")
    if isinstance(oi, dict):
        oc = str(oi.get("concepto") or oi.get("descripcion") or "").strip()
        if len(oc) > len(core):
            core = oc
    return core


def is_contaminated_economic_pending_question(q: Dict[str, Any]) -> bool:
    """
    True si pending_questions tiene un economic_price que el filtro actual ya no pediría
    (documento sin señal de partida/precio).
    """
    if q.get("type") != "economic_price":
        return False
    text = _pending_economic_core_concept_text(q).strip()
    if not text:
        return False
    if _DELIVERABLE_ECONOMIC_SUMMARY.search(text):
        return True
    if _HARD_DOC_PATTERNS.search(text):
        return True
    # Documentos técnicos de obra pública (no tienen precio unitario)
    if _OBRA_PUBLICA_DOC_PATTERNS.search(text):
        return True
    is_doc = bool(_DOC_PATTERNS.search(text))
    is_price = bool(_PRICE_PATTERNS.search(text))
    return bool(is_doc and not is_price)


def should_remove_chatbot_intake_catalog_entry(item: Dict[str, Any]) -> bool:
    """
    True si una fila del catálogo de empresa viene del chatbot y describe un documento, no una partida.
    """
    if item.get("source") != "chatbot_intake":
        return False
    desc = str(item.get("description") or "")
    if not desc.strip():
        return False
    if _HARD_DOC_PATTERNS.search(desc):
        return True
    is_doc = bool(_DOC_PATTERNS.search(desc))
    is_price = bool(_PRICE_PATTERNS.search(desc))
    return bool(is_doc and not is_price)


def filter_pending_questions_economic_contamination(
    pending: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Devuelve (mantener, eliminadas)."""
    keep: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    for q in pending:
        if is_contaminated_economic_pending_question(q):
            removed.append(q)
        else:
            keep.append(q)
    return keep, removed


def filter_company_catalog_contamination(catalog: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Devuelve (catálogo_limpio, entradas_eliminadas)."""
    keep: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    for it in catalog:
        if should_remove_chatbot_intake_catalog_entry(it):
            removed.append(it)
        else:
            keep.append(it)
    return keep, removed
