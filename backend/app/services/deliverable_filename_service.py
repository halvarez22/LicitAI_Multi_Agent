"""
Nombres de entrega alineados al convocante (universal, sin hardcode por licitación).

Cascada de precedencia para el nombre en ZIP/CompraNet:
  source_filename ingestado > archivo_fuente > nombre en compliance/bases > patrón canónico RFC.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

# Nombres genéricos que produce el pipeline (no son los del pliego).
_GENERIC_NOMBRE_RE = re.compile(
    r"(?i)^("
    r"documento|propuesta|requisito|formato|sin\s+nombre|"
    r"te[-_]?\d+|fo[-_]?\d+|ad[-_]?\d+|ae[-_]?\d+|dd[-_]?\d+"
    r")$"
)

_CONVOCANTE_SIGNAL_RE = re.compile(
    r"(?i)(^(\d{1,2})[\.\)\-\s]+|anexo\s+[a-z0-9]{1,4}|formato\s+de|"
    r"manifiesto|declaraci[oó]n|acreditaci[oó]n|propuesta\s+econ[oó]mica|"
    r"integraci[oó]n\s+del\s+costo|cartilla|constancia)"
)

_AGENT_OUTPUT_STEM_RE = re.compile(
    r"(?i)^[a-z]{2,4}[-_]?\d+[_-]"
)

# Requisitos del inventario compliance (sin plantilla ingestada numerada).
_INVENTARIO_REQUISITO_RE = re.compile(
    r"(?i)^("
    r"escrito de|carta de|declaraci[oó]n de|estratificaci[oó]n de|"
    r"formato de|comprobante de|acreditaci[oó]n de|manifestaci[oó]n de|"
    r"modelo de|integraci[oó]n del costo"
    r")"
)

# Código de requisito + descripción (ej. ``TE-12: Puntuación…``, ``AD-186 - Escrito…``).
_CODIGO_REQUISITO_RE = re.compile(
    r"(?i)^(ad|te|fo|dd|ae)[-_\s]?\d+[\s:\.\-—]+\S.{6,}"
)


def _env_true(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def prefer_convocante_filenames() -> bool:
    """Si True, el empaquetado final usa nombres del pliego cuando existan."""
    return _env_true("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")


def _normalize_stem(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    stem, ext = os.path.splitext(raw)
    if not stem and raw.lower().endswith(ext.lower()):
        stem = raw[: -len(ext)] if ext else raw
    t = unicodedata.normalize("NFC", stem)
    t = re.sub(r"[:：]", " - ", t)
    t = re.sub(r'[<>"/\\|?*\x00-\x1f]', "_", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"_+", " ", t).strip()
    return t[:180] if t else ""


def _looks_like_convocante_label(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return False
    if _GENERIC_NOMBRE_RE.match(t):
        return False
    if _AGENT_OUTPUT_STEM_RE.match(t.replace(" ", "_")):
        return False
    if _INVENTARIO_REQUISITO_RE.search(t):
        return True
    if _CODIGO_REQUISITO_RE.search(t):
        return True
    return bool(_CONVOCANTE_SIGNAL_RE.search(t))


def _basename(path: str) -> str:
    return os.path.basename((path or "").replace("\\", "/"))


def pick_convocante_label(doc: Dict[str, Any]) -> Tuple[str, str]:
    """
    Elige la etiqueta humana del convocante desde metadatos del documento.

    Returns:
        (label, source_key) — source_key para auditoría en manifiesto.
    """
    if not isinstance(doc, dict):
        return "", "none"

    src_fn = str(doc.get("source_filename") or "").strip()
    if src_fn and _looks_like_convocante_label(src_fn):
        return src_fn, "source_filename"

    af = str(doc.get("archivo_fuente") or "").strip()
    if af:
        base = _basename(af)
        if _looks_like_convocante_label(base):
            return base, "archivo_fuente"

    nombre = str(doc.get("nombre") or "").strip()
    if nombre and _looks_like_convocante_label(nombre):
        return nombre, "nombre"

    # Nombre de archivo en disco con prefijo 01_9. Anexo J...
    archivo = str(doc.get("archivo") or "").strip()
    if archivo:
        base = _basename(archivo)
        base = re.sub(r"^\d+_", "", base)
        if _looks_like_convocante_label(base):
            return base, "archivo_staged"

    return "", "none"


def build_canonical_filename(
    rfc_token: str,
    licitacion_token: str,
    sobre_label: str,
    orden: int,
    ext: str,
) -> str:
    """Patrón legado RFC + sesión + sobre + orden (trazabilidad)."""
    ext_l = ext if ext.startswith(".") else f".{ext}"
    return f"{rfc_token}_{licitacion_token}_{sobre_label}_{orden:02d}{ext_l}"


def resolve_deliverable_filename(
    doc: Dict[str, Any],
    *,
    rfc_token: str,
    licitacion_token: str,
    sobre_label: str,
    orden: int,
    ext: str,
    used_names: Optional[set[str]] = None,
) -> Tuple[str, str, str]:
    """
    Resuelve el nombre final del archivo en ``_compranet_validated``.

    Returns:
        (filename, naming_mode, convocante_label)
        naming_mode: ``convocante`` | ``canonical_fallback``
    """
    ext_l = ext.lower()
    if ext_l and not ext_l.startswith("."):
        ext_l = f".{ext_l}"

    label, source_key = pick_convocante_label(doc)
    canonical = build_canonical_filename(
        rfc_token, licitacion_token, sobre_label, orden, ext_l
    )

    if not prefer_convocante_filenames() or not label:
        return canonical, "canonical_fallback", label

    stem = _normalize_stem(label)
    if not stem:
        return canonical, "canonical_fallback", label

    candidate = f"{stem}{ext_l}"
    used = used_names if used_names is not None else set()
    final = candidate
    n = 2
    while final.lower() in used:
        final = f"{stem} ({n}){ext_l}"
        n += 1
    used.add(final.lower())
    return final, f"convocante:{source_key}", label
