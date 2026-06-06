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

_WS_FLEX = r"[\s_]+"

_CONVOCANTE_SIGNAL_RE = re.compile(
    r"(?i)(^(\d{1,2})[\.\)\-\s]+|"
    rf"anexo{_WS_FLEX}[a-z0-9]{{1,4}}|formato{_WS_FLEX}de|"
    r"manifiesto|declaraci[oó]n|acreditaci[oó]n|propuesta\s+econ[oó]mica|"
    rf"integraci[oó]n{_WS_FLEX}del{_WS_FLEX}costo|cartilla|constancia|"
    rf"carta{_WS_FLEX}compromiso|garant[ií]a|aseguramiento|"
    rf"precios{_WS_FLEX}unitarios|an[aá]lisis{_WS_FLEX}de{_WS_FLEX}precios|"
    rf"tabla{_WS_FLEX}de{_WS_FLEX}precios|propuesta{_WS_FLEX}t[eé]cnica|"
    rf"carta{_WS_FLEX}presentaci[oó]n|modelo{_WS_FLEX}de)"
)

_BARE_AGENT_CODE_RE = re.compile(
    r"(?i)^(?:\d+_)*(ad|te|fo|dd|ae)[-_]?\d+$"
)

_INVENTARIO_REQUISITO_RE = re.compile(
    r"(?i)(?:^|"
    rf"escrito{_WS_FLEX}de|carta{_WS_FLEX}de|declaraci[oó]n{_WS_FLEX}de|"
    rf"estratificaci[oó]n{_WS_FLEX}de|formato{_WS_FLEX}de|"
    rf"comprobante{_WS_FLEX}de|acreditaci[oó]n{_WS_FLEX}de|"
    rf"manifestaci[oó]n{_WS_FLEX}de|modelo{_WS_FLEX}de|"
    rf"integraci[oó]n{_WS_FLEX}del{_WS_FLEX}costo"
    r")"
)

_CODIGO_REQUISITO_RE = re.compile(
    r"(?i)^(?:\d+_)*(ad|te|fo|dd|ae)[-_\s]?\d+[\s:\.\-—_]+\S.{6,}"
)

_PACKAGER_ORDINAL_PREFIX_RE = re.compile(r"^(?:\d+_)+(?!anexo)", re.I)

# Prefijos internos del pipeline (catálogo, espejo, panel, económico).
_PIPELINE_ROUTE_PREFIX_RE = re.compile(
    r"(?i)^(?:"
    r"cat(?:alog)?|mirror|panel(?:[_\s-]*pliego)?|econ"
    r")[\s_.-]*"
)

_ANEXO_KEY_RE = (
    r"(?:III[-\s][A-Z]|XIII|XIV|XV|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I|[A-Z]{1,2}|\d{1,2})"
)

# Fragmento oficial «N. Anexo …» embebido en nombres largos del pipeline.
_NUMBERED_ANEXO_FRAGMENT_RE = re.compile(
    r"(?<![\d\.])"
    r"(\d{1,2})"
    r"[\.\)\-\s_]+"
    r"(Anexo[\s_.-]+"
    + _ANEXO_KEY_RE +
    r"(?:[\s_.-].*)?)",
    re.I,
)

# Anexo sin numeración explícita del convocante.
_ANEXO_FRAGMENT_RE = re.compile(
    r"(Anexo[\s_.-]+" + _ANEXO_KEY_RE + r"(?:[\s_.-].*)?)",
    re.I,
)

# Código de agente + descripción (AD-71, FO-35, TE-03…).
_AGENT_CODE_DESC_RE = re.compile(
    r"((?:AD|TE|FO|DD|AE)[-_]?\d+[\s:\.\-—_]+.+)"
)

_KNOWN_FILE_EXT_RE = re.compile(
    r"\.(docx|doc|xlsx|xls|pdf|jpg|jpeg|png)$",
    re.I,
)


def _strip_known_extension(text: str) -> str:
    """Quita extensión solo si parece archivo real (no el punto de ``9. Anexo …``)."""
    base = (text or "").strip()
    if _KNOWN_FILE_EXT_RE.search(base):
        return _KNOWN_FILE_EXT_RE.sub("", base).strip()
    return base


_GLUE_EXT_TAIL_RE = re.compile(r"(?i)(docx|doc|xlsx|xls|pdf)$")

_STEM_MAX_LEN = 240


def _env_true(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def prefer_convocante_filenames() -> bool:
    """Si True, el empaquetado final usa nombres del pliego cuando existan."""
    return _env_true("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")


def _strip_packager_prefix(name: str) -> str:
    """Quita prefijos ``01_`` / ``01 01 `` del empaquetador sin perder el anexo."""
    raw = (name or "").strip()
    if not raw:
        return ""
    base = _basename(raw) if ("/" in raw or "\\" in raw) else raw
    stem = _strip_known_extension(base)
    changed = True
    while changed:
        changed = False
        nxt = _PACKAGER_ORDINAL_PREFIX_RE.sub("", stem)
        if nxt != stem:
            stem = nxt
            changed = True
        if re.match(r"^\d{1,2}[\.\)]", stem):
            break
        if re.match(r"^\d{1,2}_anexo", stem.replace(" ", "_"), re.I):
            break
        m_sp = re.match(r"^(?:\d{1,2}[\s_.-]+){1,4}", stem)
        if m_sp:
            stem = stem[m_sp.end() :].lstrip("_.- ")
            changed = True
    return stem


def _label_match_blob(text: str) -> str:
    """Texto normalizado para reglas universales (sin acentos ni guiones bajos)."""
    t = unicodedata.normalize("NFD", _strip_packager_prefix(text))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower().replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


def _has_pliego_anexo_marker(text: str) -> bool:
    from app.services.pliego_formats_enrichment_service import _anexo_key_from_label

    return bool(_anexo_key_from_label(_strip_packager_prefix(text)))


def _has_deliverable_domain_marker(text: str) -> bool:
    """Señales de dominio técnico/económico compartidas con writers y packager."""
    from app.services.document_deliverable_filter import is_economic_writer_domain
    from app.services.session_template_catalog import (
        is_anexo_tecnico_propuesta_entregable,
    )

    raw = _strip_packager_prefix(text)
    blob = _label_match_blob(text)
    if is_anexo_tecnico_propuesta_entregable(raw):
        return True
    if is_economic_writer_domain(raw, "", blob):
        return True
    return bool(
        re.search(
            rf"(?i)(propuesta{_WS_FLEX}t[eé]cnica|carta{_WS_FLEX}presentaci[oó]n|"
            rf"modelo{_WS_FLEX}.*presentaci[oó]n)",
            blob,
        )
    )


def _repair_glued_extension_stem(stem: str) -> str:
    """Quita extensiones pegadas al final del stem (p. ej. ``Manifiestosdocx``)."""
    return _GLUE_EXT_TAIL_RE.sub("", (stem or "").rstrip()).strip()


def _has_pipeline_route_prefix(text: str) -> bool:
    blob = _label_match_blob(text)
    return bool(re.match(r"^(cat(?:alog)?|mirror|panel|econ)\b", blob))


def _strip_pipeline_route_prefix(text: str) -> str:
    """Elimina prefijos cat/mirror/panel/econ y ordinales de empaquetado posteriores."""
    t = _strip_packager_prefix(text)
    t = re.sub(r"\.[^.\\/]+$", "", t)
    changed = True
    while changed:
        changed = False
        m = _PIPELINE_ROUTE_PREFIX_RE.match(t)
        if m:
            t = t[m.end() :].lstrip("_.- ")
            changed = True
        m_ord = re.match(r"^\d{1,2}[\s_.-]+", t)
        if m_ord and not re.match(r"^\d{1,2}[\.\)]", t):
            t = t[m_ord.end() :]
            changed = True
    return t.strip()


def _format_convocante_delivery_label(text: str) -> str:
    """Normaliza espacios y el patrón ``N. Anexo …``."""
    t = _repair_glued_extension_stem(_strip_known_extension((text or "").strip()))
    t = re.sub(r"_+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"^(\d{1,2})[\.\)\-\s_]+(Anexo\s+.+)$", t, re.I)
    if m:
        return f"{int(m.group(1))}. {m.group(2).strip()}"
    return t


def _score_pliego_fragment(frag: str) -> float:
    sc = 0.0
    if re.match(r"^\d{1,2}\.", frag):
        sc += 20.0
    if _has_pliego_anexo_marker(frag):
        sc += 15.0
    if _looks_like_convocante_label(frag):
        sc += 10.0
    sc += min(len(frag), 120) / 120.0
    if _has_pipeline_route_prefix(frag):
        sc -= 30.0
    return sc


def _collect_pliego_fragments(text: str) -> list[str]:
    """Extrae candidatos legibles del convocante desde un nombre pipeline."""
    blob = _strip_packager_prefix(text).replace("_", " ")
    blob = re.sub(r"\s+", " ", blob).strip()
    if not blob:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        frag = _format_convocante_delivery_label(raw)
        key = frag.lower()
        if frag and key not in seen:
            seen.add(key)
            candidates.append(frag)

    for m in _NUMBERED_ANEXO_FRAGMENT_RE.finditer(blob):
        num = int(m.group(1))
        anexo = _repair_glued_extension_stem(m.group(2).strip())
        anexo = re.sub(r"[\s_]+", " ", anexo)
        _add(f"{num}. {anexo}")

    for m in _ANEXO_FRAGMENT_RE.finditer(blob):
        anexo = _repair_glued_extension_stem(m.group(1).strip())
        anexo = re.sub(r"[\s_]+", " ", anexo)
        _add(anexo)

    for m in _AGENT_CODE_DESC_RE.finditer(blob):
        desc = re.sub(r"[\s_]+", " ", m.group(1).strip())
        _add(desc)

    if not candidates:
        tail = _strip_pipeline_route_prefix(text).replace("_", " ")
        tail = _repair_glued_extension_stem(re.sub(r"\s+", " ", tail).strip())
        if tail:
            _add(tail)

    return candidates


def refine_convocante_label(text: str) -> str:
    """
    Convierte nombres internos del pipeline en etiqueta legible del convocante.

    Prioriza fragmentos embebidos tipo ``10. Anexo K …`` sobre el prefijo ``cat_``/``mirror_``.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    base = _basename(raw) if ("/" in raw or "\\" in raw) else raw
    stem = _strip_packager_prefix(_strip_known_extension(base))

    if _looks_like_convocante_label(stem) and not _has_pipeline_route_prefix(stem):
        return _format_convocante_delivery_label(stem)

    fragments = _collect_pliego_fragments(stem)
    if fragments:
        best = max(fragments, key=_score_pliego_fragment)
        if _looks_like_convocante_label(best):
            return best

    cleaned = _format_convocante_delivery_label(_strip_pipeline_route_prefix(stem))
    return cleaned


def _normalize_stem(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    stem = _strip_known_extension(raw)
    stem = _PACKAGER_ORDINAL_PREFIX_RE.sub("", stem)
    stem = _repair_glued_extension_stem(stem)
    t = unicodedata.normalize("NFC", stem)
    t = re.sub(r"[:：]", " - ", t)
    t = re.sub(r'[<>"/\\|?*\x00-\x1f]', "_", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"_+", " ", t).strip()
    if not t:
        return ""
    if len(t) > _STEM_MAX_LEN:
        cut = t[:_STEM_MAX_LEN]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        t = cut.strip()
    return t


def _looks_like_convocante_label(text: str) -> bool:
    raw = _strip_packager_prefix(text)
    t = (raw or "").strip()
    if len(t) < 4:
        return False
    stem = re.sub(r"\.[^.\\/]+$", "", t)
    if _GENERIC_NOMBRE_RE.match(stem):
        return False
    if _BARE_AGENT_CODE_RE.match(stem):
        return False
    if _has_pliego_anexo_marker(t):
        return True
    if _has_deliverable_domain_marker(t):
        return True
    blob = _label_match_blob(t)
    if _INVENTARIO_REQUISITO_RE.search(blob):
        return True
    if _CODIGO_REQUISITO_RE.search(t.replace(" ", "_")):
        return True
    if _CODIGO_REQUISITO_RE.search(stem):
        return True
    return bool(_CONVOCANTE_SIGNAL_RE.search(blob))


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

    fields: list[tuple[str, str]] = [
        ("source_filename", str(doc.get("source_filename") or "").strip()),
        ("archivo_fuente", _basename(str(doc.get("archivo_fuente") or "").strip())),
        ("nombre", str(doc.get("nombre") or "").strip()),
        (
            "archivo_staged",
            _strip_packager_prefix(_basename(str(doc.get("archivo") or "").strip())),
        ),
    ]

    best_label = ""
    best_source = "none"
    best_score = -1.0

    source_bonus = {
        "source_filename": 3.0,
        "archivo_fuente": 2.0,
        "nombre": 1.0,
        "archivo_staged": 0.5,
    }

    for source_key, raw in fields:
        if not raw:
            continue
        refined = refine_convocante_label(raw)
        if not refined or not _looks_like_convocante_label(refined):
            continue
        stem_probe = re.sub(r"\.[^.\\/]+$", "", refined)
        if _GENERIC_NOMBRE_RE.match(stem_probe):
            continue
        score = _score_pliego_fragment(refined) + source_bonus.get(source_key, 0.0)
        if _has_pipeline_route_prefix(raw) and not _has_pipeline_route_prefix(refined):
            score += 5.0
        if score > best_score:
            best_score = score
            best_label = refined
            best_source = source_key

    return best_label, best_source


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
