"""
Normalización de bloques estructurados del Analista de bases y heurísticas de apoyo
(económico / tablas / partidas). Sin datos fijos de expedientes concretos.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Final, List, Optional, Set, Tuple

# Claves canónicas para reglas de oferta / marco económico citado en convocatoria.
_REGLAS_ECONOMICAS_KEYS: Final[Tuple[str, ...]] = (
    "referencia_partidas_anexos_citados",
    "criterio_importe_minimo_o_plazo_inferior",
    "criterio_importe_maximo_o_plazo_superior",
    "meses_o_periodo_minimo_citado",
    "meses_o_periodo_maximo_citado",
    "modalidad_contratacion_observada",
    "vinculacion_presupuesto_partida",
    "otras_reglas_oferta_precio",
)

_REGLAS_ALIASES: Final[Dict[str, str]] = {
    "referencia_partidas_anexos_citados": "referencia_partidas_anexos_citados",
    "referencia_partidas": "referencia_partidas_anexos_citados",
    "partidas_y_anexos": "referencia_partidas_anexos_citados",
    "importe_minimo": "criterio_importe_minimo_o_plazo_inferior",
    "criterio_importe_minimo_o_plazo_inferior": "criterio_importe_minimo_o_plazo_inferior",
    "importe_maximo": "criterio_importe_maximo_o_plazo_superior",
    "criterio_importe_maximo_o_plazo_superior": "criterio_importe_maximo_o_plazo_superior",
    "meses_minimo": "meses_o_periodo_minimo_citado",
    "meses_o_periodo_minimo_citado": "meses_o_periodo_minimo_citado",
    "meses_maximo": "meses_o_periodo_maximo_citado",
    "meses_o_periodo_maximo_citado": "meses_o_periodo_maximo_citado",
    "modalidad_contrato": "modalidad_contratacion_observada",
    "modalidad_contratacion_observada": "modalidad_contratacion_observada",
    "presupuesto_partida": "vinculacion_presupuesto_partida",
    "vinculacion_presupuesto_partida": "vinculacion_presupuesto_partida",
    "otras_reglas": "otras_reglas_oferta_precio",
    "otras_reglas_oferta_precio": "otras_reglas_oferta_precio",
}

# Filas de alcance operativo (tablas tipo descripción, dotación, turnos).
_ALCANCE_ROW_KEYS: Final[Tuple[str, ...]] = (
    "ubicacion_o_area",
    "puesto_funcion_o_servicio",
    "turno",
    "horario",
    "cantidad_o_elementos",
    "dias_aplicables",
    "texto_literal_fila",
)

_ALCANCE_ALIASES: Final[Dict[str, str]] = {
    "area": "ubicacion_o_area",
    "ubicacion": "ubicacion_o_area",
    "ubicacion_o_area": "ubicacion_o_area",
    "puesto": "puesto_funcion_o_servicio",
    "servicio": "puesto_funcion_o_servicio",
    "funcion": "puesto_funcion_o_servicio",
    "puesto_funcion_o_servicio": "puesto_funcion_o_servicio",
    "turno": "turno",
    "horario": "horario",
    "cantidad": "cantidad_o_elementos",
    "elementos": "cantidad_o_elementos",
    "numero_elementos": "cantidad_o_elementos",
    "cantidad_o_elementos": "cantidad_o_elementos",
    "dias": "dias_aplicables",
    "dias_aplicables": "dias_aplicables",
    "texto_literal": "texto_literal_fila",
    "fragmento_literal": "texto_literal_fila",
    "texto_literal_fila": "texto_literal_fila",
}

_DEFAULT_REGLAS = "No especificado"

# Patrones genéricos: bases que remiten a anexos/partidas/tablas sin ligar a un rubro.
_TABULAR_HINT_PATTERN = re.compile(
    r"(?is)"
    r"(\banexo\s*n[o°º.]?\s*\d+)"
    r"|(\banexo\s+n[uú]mero\s+\d+)"
    r"|(\bcantidades?\b.{0,60}\banexo\b)"
    r"|(\basignar[áa]n?\s+por\s+partida\b)"
    r"|(\bpartidas?\s+de\s+(?:la\s+)?(?:convocatoria|licitaci[oó]n)\b)"
    r"|(\bprecios?\s+por\s+partida\b)"
    r"|(\bimporte\s+m[ií]nimo\b.{0,80}\bmeses?\b)"
    r"|(\bimporte\s+m[aá]ximo\b.{0,80}\bmeses?\b)",
)


def detect_tabular_reference_signals(text: str) -> Dict[str, Any]:
    """
    Indica si el texto (bases + contexto) sugiere dependencia de tablas/anexos/partidas.

    Returns:
        texto_sugiere_partidas_o_anexo_tabular: bool
        coincidencias_aproximadas: int
    """
    if not text or not isinstance(text, str):
        return {"texto_sugiere_partidas_o_anexo_tabular": False, "coincidencias_aproximadas": 0}
    matches = list(_TABULAR_HINT_PATTERN.finditer(text))
    return {
        "texto_sugiere_partidas_o_anexo_tabular": len(matches) > 0,
        "coincidencias_aproximadas": len(matches),
    }


def _norm_key(s: str) -> str:
    nk = unicodedata.normalize("NFD", (s or "").strip())
    nk = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    return nk.lower().replace("-", "_").replace(" ", "_")


def _coerce_page(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    s = str(val).strip()
    if not s:
        return None
    m = re.search(r"\d+", s)
    if not m:
        return None
    try:
        n = int(m.group(0))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _coerce_str(val: Any, default: str = _DEFAULT_REGLAS) -> str:
    if val is None:
        return default
    if isinstance(val, dict):
        inner = val.get("value") or val.get("texto") or val.get("text")
        return _coerce_str(inner, default)
    if isinstance(val, str):
        t = val.strip()
        return t if t else default
    if isinstance(val, (int, float, bool)):
        return str(val)
    try:
        t = str(val).strip()
        return t if t else default
    except Exception:
        return default


def normalize_regla_economica_anchor(raw: Any) -> Dict[str, Any]:
    """
    Normaliza un ítem de regla económica con ancla HRU {value, page, snippet, source}.
    Devuelve dict vacío si el valor es «No especificado» o falta.
    """
    if raw is None:
        return {}
    if isinstance(raw, str):
        value = _coerce_str(raw, _DEFAULT_REGLAS)
        if value == _DEFAULT_REGLAS:
            return {}
        return {"value": value, "page": None, "snippet": None, "source": None}

    if not isinstance(raw, dict):
        return {}

    value = _coerce_str(
        raw.get("value") or raw.get("texto") or raw.get("text"),
        _DEFAULT_REGLAS,
    )
    if value == _DEFAULT_REGLAS:
        return {}

    snippet_raw = (
        raw.get("snippet")
        or raw.get("evidence_snippet")
        or raw.get("texto_literal")
        or raw.get("fragmento")
    )
    snippet = _coerce_str(snippet_raw, "").strip() or None
    source_raw = raw.get("source") or raw.get("archivo_fuente") or raw.get("file_name")
    source = _coerce_str(source_raw, "").strip() or None
    page = _coerce_page(raw.get("page") or raw.get("pagina"))

    return {
        "value": value,
        "page": page,
        "snippet": snippet,
        "source": source,
    }


def normalize_reglas_economicas_anchored(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Mapa canónico de reglas económicas con anclas del analista (solo claves con valor real)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for rk, val in raw.items():
        if not isinstance(rk, str):
            continue
        nk = _norm_key(rk)
        canon = _REGLAS_ALIASES.get(nk)
        if canon is None and nk in _REGLAS_ECONOMICAS_KEYS:
            canon = nk
        if canon is None or canon not in _REGLAS_ECONOMICAS_KEYS:
            continue
        anchor = normalize_regla_economica_anchor(val)
        if not anchor:
            continue
        out[canon] = anchor
    return out


def normalize_reglas_economicas_dict(raw: Any) -> Dict[str, str]:
    """Unifica reglas económicas citadas en bases; valores ausentes → 'No especificado'."""
    out: Dict[str, str] = {k: _DEFAULT_REGLAS for k in _REGLAS_ECONOMICAS_KEYS}
    if not isinstance(raw, dict):
        return out
    for rk, val in raw.items():
        if not isinstance(rk, str):
            continue
        nk = _norm_key(rk)
        canon = _REGLAS_ALIASES.get(nk)
        if canon is None and nk in _REGLAS_ECONOMICAS_KEYS:
            canon = nk
        if canon is None or canon not in out:
            continue
        coerced = _coerce_str(val, _DEFAULT_REGLAS)
        if coerced != _DEFAULT_REGLAS or out[canon] == _DEFAULT_REGLAS:
            out[canon] = coerced
    return out


def normalize_alcance_operativo_list(raw: Any) -> List[Dict[str, str]]:
    """
    Normaliza filas de alcance/dotación (tablas). Dicts parciales se rellenan con cadenas vacías
    en claves canónicas; deduplica por texto_literal_fila / concatenación estable.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        row: Dict[str, str] = {k: "" for k in _ALCANCE_ROW_KEYS}
        for rk, val in item.items():
            if not isinstance(rk, str):
                continue
            nk = _norm_key(rk)
            canon = _ALCANCE_ALIASES.get(nk, nk if nk in _ALCANCE_ROW_KEYS else None)
            if not canon or canon not in row:
                continue
            s = val if isinstance(val, str) else str(val) if val is not None else ""
            row[canon] = s.strip()
        sig = "|".join(row[k] for k in _ALCANCE_ROW_KEYS).lower()[:1200]
        if not sig.strip("|"):
            continue
        if sig in seen:
            continue
        seen.add(sig)
        out.append(row)
    return out
