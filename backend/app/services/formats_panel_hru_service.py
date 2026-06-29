"""
Normalización HRU del panel «Formatos/Anexos detectados».

Universal (sin mapas por licitación): limpieza OCR, títulos por dedupe_key obra|T/E,
 reclasificación de sobres y deduplicación.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.compliance_consolidation_service import classify_deliverable_sobre
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

_OCR_PRESUPUESTO_RE = re.compile(r"(?i)(?:presupuesto[\s_.-]*52[\s_.-]*)+")
_SEQ_NUM_SPAM_RE = re.compile(r"(?:\b\d{1,2}\b[\s,.-]+){6,}\d{1,2}\b")
_MULTI_SPACE_RE = re.compile(r"\s+")

# Títulos canónicos por clave dedupe (obra pública T/E — LOPSRM genérico, no por convocante).
_OBRA_DEDUPE_DISPLAY: Dict[str, str] = {
    "obra|T1": "Anexo T-1 — Propuesta técnica (maquinaria y equipo)",
    "obra|T1_ACRED": "Acreditación de propiedad de maquinaria y equipo",
    "obra|T2": "Anexo T-2 — Relación de contratos de obras vigentes",
    "obra|T3": "Anexo T-3 — Modelo de contrato firmado de conformidad",
    "obra|T4": "Anexo T-4 — Bases y requisitos firmados de conformidad",
    "obra|T5": "Anexo T-5 — Acta de visita / junta de aclaraciones",
    "obra|T6": "Anexo T-6 — Manifestación de cumplimiento de obligaciones contractuales",
    "obra|T7": "Anexo T-7 — Manifestación de subcontratación",
    "obra|T8_PRIVACIDAD": "Anexo T-8 — Aviso de privacidad (firmado)",
    "obra|T-B-2": "Anexo T-B-2 — Documentación de experiencia y capacidad técnica",
    "obra|T_B_SOLVENCIA": "Capital contable / solvencia comprometida",
    "obra|E1": "Anexo E-1 — Carta-compromiso de la proposición",
    "obra|E2": "Anexo E-2 — Catálogo de conceptos (propuesta económica)",
    "obra|E3": "Anexo E-3 — Análisis de precios unitarios",
    "obra|E4": "Anexo E-4 — Programas de obra (Gantt)",
    "obra|E5": "Anexo E-5 — Cotizaciones de materiales",
}


def is_panel_label_ocr_corrupted(label: str) -> bool:
    """True si la etiqueta muestra ruido OCR típico (52…, secuencias numéricas)."""
    text = str(label or "")
    if not text.strip():
        return False
    if _OCR_PRESUPUESTO_RE.search(text):
        return True
    if _SEQ_NUM_SPAM_RE.search(text):
        return True
    if len(text) > 160 and re.search(r"\b\d{1,2}\b", text):
        return True
    return False


def clean_panel_display_label(label: str) -> str:
    """Limpia ruido OCR universal sin perder el código de anexo."""
    text = _MULTI_SPACE_RE.sub(" ", str(label or "").strip())
    text = _OCR_PRESUPUESTO_RE.sub(" ", text)
    text = _SEQ_NUM_SPAM_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip(" ,;.-")
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0] + "…"
    return text or str(label or "").strip()


def resolve_panel_display_name(label: str, snippet: str = "") -> str:
    """
    Nombre legible para UI: dedupe_key → título canónico; si no, limpieza OCR.
    """
    raw = str(label or "").strip()
    key = pliego_format_dedupe_key(raw)
    if key and key in _OBRA_DEDUPE_DISPLAY:
        if is_panel_label_ocr_corrupted(raw) or len(raw) > 100:
            return _OBRA_DEDUPE_DISPLAY[key]
    if key and key.startswith("obra|") and is_panel_label_ocr_corrupted(raw):
        return _OBRA_DEDUPE_DISPLAY.get(key) or clean_panel_display_label(raw)

    cleaned = clean_panel_display_label(raw)
    if key and cleaned and len(cleaned) < 12 and key in _OBRA_DEDUPE_DISPLAY:
        return _OBRA_DEDUPE_DISPLAY[key]

    # Snippet corto como subtítulo si el título sigue siendo pobre
    if key in _OBRA_DEDUPE_DISPLAY and (
        is_panel_label_ocr_corrupted(raw) or re.match(r"(?i)^anexo\s+[te][\s.-]*\d", cleaned)
    ):
        return _OBRA_DEDUPE_DISPLAY[key]

    return cleaned or raw or "Formato del pliego"


def resolve_panel_sobre_bucket(label: str, snippet: str = "") -> str:
    """
    Sobre del panel: E-* → económico; T-* → técnico; solvencia → legal.
    """
    key = pliego_format_dedupe_key(label)
    norm = f"{label} {snippet}".lower()

    if key:
        if key.startswith("obra|E") or key in (
            "pliego|propuesta_economica",
            "pliego|catalogo_conceptos",
            "pliego|analisis_costos",
        ):
            return "sobre_2_economico"
        if key in ("obra|T_B_SOLVENCIA",) or re.search(
            r"(?i)\bcapital\s+contable|solvencia\s+comprometida|liquidez\s+comprometida",
            norm,
        ):
            return "requisitos_legales"
        if key.startswith("obra|T") or key.startswith("obra|T-B"):
            return "sobre_1_tecnico"

    if is_economic_keyword(norm):
        return "sobre_2_economico"

    return classify_deliverable_sobre(label, snippet)


def is_economic_keyword(text: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(anexo\s+e[\s.-]*[1-5]|propuesta\s+econ|cat[aá]logo\s+de\s+conceptos|"
            r"precios\s+unitarios|programas\s+de\s+obra\s+55)\b",
            text,
        )
    )


def normalize_formats_panel_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica nombre legible y sobre coherente a una fila del panel."""
    if not isinstance(row, dict):
        return {}
    out = dict(row)
    raw_name = str(out.get("nombre_canonico") or out.get("nombre") or "")
    snippet = str(out.get("snippet_representativo") or out.get("snippet") or "")
    display = resolve_panel_display_name(raw_name, snippet)
    bucket = resolve_panel_sobre_bucket(display, snippet)
    out["nombre_canonico"] = display
    out["nombre"] = display
    out["sobre_clasificado"] = bucket
    out["hru_normalized"] = True
    return out


def normalize_formats_panel_payload(panel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reagrupa el panel consolidado con nombres HRU y sobres corregidos.
    """
    if not isinstance(panel, dict):
        return panel

    bucket_keys = (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    )
    meta = panel.get("_meta") if isinstance(panel.get("_meta"), dict) else {}
    seen: set[str] = set()
    buckets: Dict[str, List[Dict[str, Any]]] = {k: [] for k in bucket_keys}

    for bk in bucket_keys:
        for raw in panel.get(bk) or []:
            if not isinstance(raw, dict):
                continue
            row = normalize_formats_panel_row(raw)
            name = str(row.get("nombre_canonico") or "")
            key = pliego_format_dedupe_key(name) or name.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            target = str(row.get("sobre_clasificado") or bk)
            if target not in buckets:
                target = "otros_requisitos_criticos"
            buckets[target].append(row)

    total = sum(len(buckets[k]) for k in bucket_keys)
    generar = sum(
        1
        for k in bucket_keys
        for r in buckets[k]
        if str(r.get("tipo_accion_final") or r.get("tipo") or "") == "generar"
    )
    meta = {**meta, "hru_panel_normalized": True, "total": total, "generar_count": generar}
    return {**buckets, "_meta": meta}
