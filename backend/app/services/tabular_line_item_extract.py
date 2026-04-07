"""
Extracción industrial de partidas/precios desde hojas Excel.
Heurísticas por encabezados (concepto, precio, unidad) sin depender del layout visual del PDF.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_PRICE_TOKENS = (
    "precio",
    "costo",
    "unitario",
    "p.u",
    "pu ",
    " importe",
    "monto",
    "tarifa",
    "cost ",
    "cu",
)
_CONCEPT_TOKENS = (
    "concepto",
    "descripcion",
    "descripción",
    "partida",
    "servicio",
    "producto",
    "insumo",
    "rubro",
    "item",
    "clave",
    "descriptivo",
)


def _norm_header(h: Any) -> str:
    return re.sub(r"\s+", " ", str(h).strip().lower())


def _norm_concepto(s: str) -> str:
    t = re.sub(r"\s+", " ", str(s).strip().lower())
    return t[:2000] if len(t) > 2000 else t


def _parse_price(val: Any) -> Optional[float]:
    """Convierte celdas mixtas (número, texto con $, MXN) a float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        x = float(val)
        return x if x > 0 else None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", "—"):
        return None
    s = re.sub(r"[\$€]", "", s, flags=re.I)
    s = re.sub(r"\bmxn\b", "", s, flags=re.I).strip()
    s = s.replace(",", "")
    try:
        x = float(s)
        return x if x > 0 else None
    except ValueError:
        return None


def _pick_price_column(df: pd.DataFrame) -> Optional[str]:
    best: Optional[Tuple[int, str]] = None
    for c in df.columns:
        h = _norm_header(c)
        if "total" in h and "sub" not in h:
            continue
        score = sum(1 for t in _PRICE_TOKENS if t in h)
        if score == 0:
            continue
        if best is None or score > best[0]:
            best = (score, str(c))
    if best:
        return best[1]
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            return str(c)
    return None


def _pick_concept_column(df: pd.DataFrame, price_col: Optional[str]) -> Optional[str]:
    for c in df.columns:
        if price_col and str(c) == price_col:
            continue
        h = _norm_header(c)
        if any(t in h for t in _CONCEPT_TOKENS):
            return str(c)
    for c in df.columns:
        if price_col and str(c) == price_col:
            continue
        if df[c].dtype == object or str(df[c].dtype) == "string":
            return str(c)
    for c in df.columns:
        if price_col and str(c) == price_col:
            continue
        return str(c)
    return None


def _pick_unit_column(df: pd.DataFrame, skip: set) -> Optional[str]:
    for c in df.columns:
        if c in skip:
            continue
        h = _norm_header(c)
        if "unidad" in h or h in ("u.m.", "um", "u.m"):
            return str(c)
    return None


def extract_line_items_from_excel_path(file_path: str, filename: str) -> List[Dict[str, Any]]:
    """
    Lee todas las hojas y devuelve filas con precio > 0 listas para persistir.

    Returns:
        Lista de dicts con keys: concepto_raw, concepto_norm, precio_unitario, unidad,
        cantidad, sheet_name, row_index, source_type, moneda, extra.
    """
    out: List[Dict[str, Any]] = []
    xl = pd.ExcelFile(file_path)
    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if df.empty or len(df.columns) < 1:
            continue
        price_col = _pick_price_column(df)
        if not price_col:
            continue
        concept_col = _pick_concept_column(df, price_col)
        if not concept_col:
            continue
        skip = {price_col, concept_col}
        unit_col = _pick_unit_column(df, skip)

        for i, row in df.iterrows():
            price = _parse_price(row.get(price_col))
            if price is None:
                continue
            raw_concept = row.get(concept_col)
            if raw_concept is None or (isinstance(raw_concept, float) and pd.isna(raw_concept)):
                continue
            concept_str = str(raw_concept).strip()
            if len(concept_str) < 2:
                continue
            unit_val = None
            if unit_col:
                u = row.get(unit_col)
                if u is not None and not (isinstance(u, float) and pd.isna(u)):
                    unit_val = str(u).strip()[:64] or None
            qty = None
            for c in df.columns:
                if c in (price_col, concept_col, unit_col):
                    continue
                h = _norm_header(c)
                if "cantidad" in h or h in ("cant", "qty"):
                    qv = row.get(c)
                    if qv is not None and not (isinstance(qv, float) and pd.isna(qv)):
                        try:
                            qty = float(qv)
                        except (TypeError, ValueError):
                            qty = None
                    break

            cn = _norm_concepto(concept_str)
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "concepto_raw": concept_str[:4000],
                    "concepto_norm": cn,
                    "precio_unitario": price,
                    "unidad": unit_val,
                    "cantidad": qty,
                    "sheet_name": str(sheet_name)[:255],
                    "row_index": float(i) if isinstance(i, (int, float)) else None,
                    "source_type": "document_tabular",
                    "moneda": "MXN",
                    "extra": {"source_filename": filename[:500]},
                }
            )
    return out
