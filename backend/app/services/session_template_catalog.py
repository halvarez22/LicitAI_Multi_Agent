"""
Catálogo universal de plantillas y documentos ingestados por sesión.

No referencia licitaciones concretas: clasifica por señales en nombre, extensión y reglas
compartidas con ``document_deliverable_filter``.
"""
from __future__ import annotations

import re
import unicodedata

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.document_deliverable_filter import (
    is_company_credential_present_only,
    is_economic_writer_domain,
    is_pliego_causal_or_prohibition,
    is_procedural_noise_not_deliverable,
)

CATALOG_SCHEMA_VERSION = "1.0.0"

_OFFICE_EXT = frozenset({".doc", ".docx", ".xls", ".xlsx"})
_PDF_EXT = frozenset({".pdf"})

# Pliego / referencia evaluación (no es plantilla a rellenar para la oferta).
# Nota: «Anexo Técnico» en Word/Excel de la propuesta se trata aparte (``is_anexo_tecnico_propuesta_entregable``).
_PLIEGO_REFERENCIA_RE = re.compile(
    r"(?i)\b("
    r"bases[_\s]|convocatoria|aclaracion(?:es)?|anexo\s+admon|"
    r"tecnico\s+final|requerimiento\s*\d|cedula\s+de\s+puntos|matriz\s+p\b|"
    r"bitacora|lista\s+de\s+asistencia|focon\s*\d|puntos\s+y\s+porcentajes|"
    r"bas_\d|guia\s+de\s+entrega|logistica"
    r")\b"
)

_ANEXO_TECNICO_ENTREGABLE_RE = re.compile(r"(?i)\banexo\s+t[eé]cnico\b")

_TECNICO_ANEXO_III_SOBRE_RE = re.compile(
    r"(?i)\b("
    r"anexo\s+iii[\-\s]*(b|c|d)\b|"
    r"anexo\s+iii[\-\s]*d\s+partida|"
    r"descripci[oó]n\s+del\s+servicio|"
    r"actividades\s+del\s+supervisor|"
    r"actividades\s+de\s+los\s+elementos|"
    r"cedula\s+de\s+evaluaci[oó]n|"
    r"entrega\s+de\s+materiales|"
    r"entrega\s+rm"
    r")\b"
)

_ADMINISTRATIVO_SOBRE_RE = re.compile(
    r"(?i)\b("
    r"anexo\s+d[\-\s]*iii\b|"
    r"integracion\s+del\s+costo\s+de\s+limpieza"
    r")\b"
)

_VISITA_EVIDENCIA_RE = re.compile(
    r"(?i)\b(constancia\s+de\s+visita|visita\s+a\s+instalaciones|anexo\s+f\b)\b"
)

# Acreditación de personalidad (formato convocante que el licitante firma con datos propios).
_PERSONALIDAD_PLIEGO_RE = re.compile(
    r"(?i)\b("
    r"acreditaci[oó]n\s+de\s+personalidad|personalidad\s+(f[ií]sica|moral)|"
    r"anexo\s+a[\-\s]?i\b|anexo\s+a[\-\s]?ii\b"
    r")\b"
)

_PLANTILLA_OFERTA_RE = re.compile(
    r"(?i)\b("
    r"anexo\s+[a-z0-9]{1,4}|formato|propuesta|integraci[oó]n\s+del\s+costo|"
    r"carta\s+(de\s+)?(compromiso|declaraci[oó]n|presentaci[oó]n)|"
    r"declaraci[oó]n|manifestaci[oó]n|comprobante\s+de\s+muestras|"
    r"registro|antisoborno|manifiesto|actividades|concent|entrega\s+rm|"
    r"cantidades\s+mensuales|contenido\s+nacional|cedula\s+de\s+evaluaci[oó]n|"
    r"entrega\s+de\s+materiales|modelo\s+de\s+fianza|fianza|facturaci[oó]n|"
    r"intereses|zon[ae]\s+[a-d]\b|partida\s+\d"
    r")\b"
)

_TECNICO_SOBRE_RE = re.compile(
    r"(?i)\b("
    r"propuesta\s+t[eé]cnica|descripci[oó]n\s+del\s+servicio|actividades|"
    r"supervisor|contenido\s+nacional|cedula\s+de\s+evaluaci[oó]n|"
    r"entrega\s+de\s+materiales|visita|acta\s+de\s+inspecci[oó]n|seguridad\s+e\s+higiene"
    r")\b"
)

_ECONOMICO_SOBRE_RE = re.compile(
    r"(?i)\b("
    r"propuesta\s+econ[oó]mica|integraci[oó]n\s+del\s+costo|precios|"
    r"zona\s+[a-d]\b|concent|formato\s+de\s+propuesta|cat[aá]logo|tabla\s+de\s+precios|"
    r"anexo\s+iii[\-\s]*(a|e|f|h|k|p\s*1|p1|iii-a)|"
    r"cantidades\s+mensuales|cart[ao]\s+compromiso.*limpieza|propuesta\s+economica"
    r")\b"
)


def is_anexo_tecnico_propuesta_entregable(filename: str) -> bool:
    """
    True si el nombre corresponde a la plantilla Word/Excel del Anexo Técnico de la oferta
    (no al PDF de bases ni a extractos de pliego).
    """
    fn = (filename or "").strip()
    blob = filename_classification_blob(fn)
    if not blob or not _ANEXO_TECNICO_ENTREGABLE_RE.search(blob):
        return False
    if re.search(
        r"(?i)\b(bases|convocatoria|aclaracion|requerimiento\s*\d|matriz\s+p|tecnico\s+final)\b",
        blob,
    ):
        return False
    # Espejo/resumen pequeño del pliego (no sustituye la plantilla de propuesta).
    if _file_ext(fn) in _OFFICE_EXT and not re.search(
        r"(?i)\b(20\d{2}|abril|diciembre|enero|febrero|marzo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|vigencia|semestre|trimestre)\b",
        blob,
    ):
        return False
    return _file_ext(fn) in _OFFICE_EXT


def infer_plantilla_sobre(filename: str) -> str:
    """
    Infiere sobre CompraNet para una plantilla: administrativo | tecnico | economico.

    Precedencia: dominio económico explícito > anexo técnico entregable > señales III técnico >
    señales técnico genéricas > señales económicas > administrativo.
    """
    fn = (filename or "").strip()
    if not fn:
        return "administrativo"
    blob = filename_classification_blob(fn)
    if _ADMINISTRATIVO_SOBRE_RE.search(blob):
        return "administrativo"
    if is_economic_writer_domain(blob):
        return "economico"
    if is_anexo_tecnico_propuesta_entregable(fn):
        return "tecnico"
    if _TECNICO_ANEXO_III_SOBRE_RE.search(blob) or _TECNICO_SOBRE_RE.search(blob):
        return "tecnico"
    if _ECONOMICO_SOBRE_RE.search(blob):
        return "economico"
    return "administrativo"


def filename_classification_blob(filename: str) -> str:
    """
    Texto normalizado para reglas de clasificación (stems con ``_``, prefijos de pipeline).
    """
    stem = re.sub(r"\.[^.\\/]+$", "", (filename or "").strip())
    stem = re.sub(r"^\d+_", "", stem)
    stem = re.sub(r"^(mirror|cat|econ|te|fo|ad|dd|ae)_\d*_?", "", stem, flags=re.IGNORECASE)
    stem = unicodedata.normalize("NFD", stem)
    stem = "".join(c for c in stem if unicodedata.category(c) != "Mn")
    stem = re.sub(r"[_]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def normalize_filename_key(name: str) -> str:
    """Clave estable para emparejar nombres de archivo (sin acentos ni ruido)."""
    raw = (name or "").strip()
    stem = re.sub(r"\.[^.\\/]+$", "", raw)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+copia\s*$", "", stem, flags=re.IGNORECASE)
    t = unicodedata.normalize("NFD", stem)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower()
    t = re.sub(r"^\d+[\.\)\-\s]*", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _file_ext(filename: str) -> str:
    low = (filename or "").lower()
    for ext in (".docx", ".xlsx", ".doc", ".xls", ".pdf"):
        if low.endswith(ext):
            return ext
    return ""


def classify_ingested_filename(filename: str) -> Tuple[str, str, str]:
    """
    Clasifica un archivo ingestado sin hardcodear licitaciones.

    Returns:
        (document_class, accion_recomendada, sobre_inferido)
        document_class: plantilla_oferta | pliego_referencia | credencial_empresa |
                        evidencia_visita | informativo
        accion_recomendada: generar | presentar_fisico | referencia | informativo
        sobre_inferido: administrativo | tecnico | economico
    """
    fn = (filename or "").strip()
    ext = _file_ext(fn)
    blob = fn
    norm_blob = filename_classification_blob(fn)

    if is_pliego_causal_or_prohibition(fn) or is_procedural_noise_not_deliverable(fn):
        return "informativo", "informativo", "administrativo"

    if is_anexo_tecnico_propuesta_entregable(fn):
        return "plantilla_oferta", "generar", "tecnico"

    if ext in _PDF_EXT and _ANEXO_TECNICO_ENTREGABLE_RE.search(norm_blob):
        return "pliego_referencia", "referencia", "administrativo"

    if _PLIEGO_REFERENCIA_RE.search(blob):
        return "pliego_referencia", "referencia", "administrativo"

    if is_company_credential_present_only(fn) or _PERSONALIDAD_PLIEGO_RE.search(blob):
        return "credencial_empresa", "presentar_fisico", "administrativo"

    if _VISITA_EVIDENCIA_RE.search(blob):
        return "evidencia_visita", "presentar_fisico", "administrativo"

    if ext in _PDF_EXT and not _PLANTILLA_OFERTA_RE.search(blob):
        # PDF sin señal de formato: referencia de pliego salvo patrón explícito.
        if re.search(r"(?i)\b(anexo|formato)\b", blob):
            pass  # puede ser plantilla escaneada; tratar abajo
        else:
            return "pliego_referencia", "referencia", "administrativo"

    if ext not in _OFFICE_EXT and ext not in _PDF_EXT:
        return "informativo", "informativo", "administrativo"

    sobre = infer_plantilla_sobre(fn)

    if ext in _OFFICE_EXT or _PLANTILLA_OFERTA_RE.search(blob):
        if re.search(r"(?i)\b(preguntas|modelo\s+de\s+contrato)\b", blob):
            return "informativo", "informativo", sobre
        return "plantilla_oferta", "generar", sobre

    return "pliego_referencia", "referencia", sobre


def build_session_template_catalog(
    session_id: str,
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Construye el catálogo de plantillas/documentos para una sesión.

    Args:
        session_id: Identificador de sesión.
        documents: Lista de ``memory.get_documents`` (content + metadata).

    Returns:
        Dict serializable con ``items`` y ``stats``.
    """
    items: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {
        "total_ingested": 0,
        "plantilla_oferta": 0,
        "pliego_referencia": 0,
        "credencial_empresa": 0,
        "evidencia_visita": 0,
        "informativo": 0,
        "accion_generar": 0,
        "accion_presentar_fisico": 0,
        "accion_referencia": 0,
    }

    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        content = doc.get("content") if isinstance(doc.get("content"), dict) else {}
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        filename = (
            content.get("filename")
            or meta.get("filename")
            or "sin_nombre"
        )
        stats["total_ingested"] += 1
        doc_class, accion, sobre = classify_ingested_filename(str(filename))
        stats[doc_class] = stats.get(doc_class, 0) + 1
        if accion == "generar":
            stats["accion_generar"] += 1
        elif accion == "presentar_fisico":
            stats["accion_presentar_fisico"] += 1
        elif accion == "referencia":
            stats["accion_referencia"] += 1

        items.append(
            {
                "doc_id": doc.get("id"),
                "source_filename": filename,
                "source_path": content.get("file_path") or meta.get("file_path"),
                "filename_key": normalize_filename_key(str(filename)),
                "document_class": doc_class,
                "accion_recomendada": accion,
                "sobre_inferido": sobre,
                "office_format": _file_ext(str(filename)).lstrip(".") or None,
                "ingest_status": meta.get("status") or content.get("status"),
                "provenance_ui": {
                    "source_key": "ingesta",
                    "source_label": "Archivo subido (convocante)",
                    "detail": f"Clasificación automática por nombre y tipo ({doc_class}).",
                },
            }
        )

    items.sort(key=lambda x: (x.get("document_class", ""), x.get("source_filename", "")))

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "session_id": session_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": (
            "Plantillas Word/Excel mínimas para presentación de propuesta "
            "(sin firmas); clasificación universal por sesión."
        ),
        "items": items,
        "stats": stats,
    }


def build_catalog_mirror_reqs(
    session_state: Dict[str, Any],
    seen_ids: set,
    *,
    exclude_sobre: Optional[Tuple[str, ...]] = ("economico",),
) -> List[Dict[str, Any]]:
    """
    Convierte ítems ``plantilla_oferta`` del catálogo en requisitos para Formats/Technical.

    Args:
        session_state: Estado de sesión con ``session_template_catalog``.
        seen_ids: IDs ya procesados (se muta).
        exclude_sobre: Sobres que otro agente materializa (p. ej. económico).

    Returns:
        Lista de dicts compatibles con FormatsAgent.
    """
    catalog = session_state.get("session_template_catalog") or {}
    out: List[Dict[str, Any]] = []
    excl = set(exclude_sobre or ())

    for item in catalog.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("document_class") != "plantilla_oferta":
            continue
        if item.get("accion_recomendada") != "generar":
            continue
        sobre = str(item.get("sobre_inferido") or "administrativo")
        if sobre in excl:
            continue
        fn = str(item.get("source_filename") or "").strip()
        if not fn:
            continue
        fkey = str(item.get("filename_key") or normalize_filename_key(fn))
        cid = ("cat_" + re.sub(r"[^\w]", "_", fkey))[:56]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        tipo_bucket = "tecnico" if sobre == "tecnico" else "administrativo"
        out.append(
            {
                "id": cid,
                "nombre": fn,
                "descripcion": "Plantilla oficial ingestada (catálogo de sesión).",
                "archivo_fuente": fn,
                "source_doc_id": item.get("doc_id"),
                "source_path": item.get("source_path"),
                "tipo_accion": "generar",
                "tipo": tipo_bucket,
                "from_session_catalog": True,
                "sobre_inferido": sobre,
                "provenance_ui": item.get("provenance_ui") if isinstance(item.get("provenance_ui"), dict) else {},
            }
        )
    return out
