"""
Normalización de bloques estructurados del Analista de bases y heurísticas de apoyo
(económico / tablas / partidas). Sin datos fijos de expedientes concretos.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Final, List, Set, Tuple

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


def _coerce_str(val: Any, default: str = _DEFAULT_REGLAS) -> str:
    if val is None:
        return default
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
