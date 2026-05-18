"""
Extracción industrial de partidas/precios desde hojas Excel.
Heurísticas por encabezados (concepto, precio, unidad) sin depender del layout visual del PDF.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from docx import Document

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
    best: Optional[Tuple[int, int, float, str]] = None
    for c in df.columns:
        h = _norm_header(c)
        if "total" in h and "sub" not in h:
            continue
        score = sum(1 for t in _PRICE_TOKENS if t in h)
        if score == 0:
            continue
        
        parsed = df[c].apply(_parse_price)
        valid_count = int(parsed.notna().sum())
        max_val = float(parsed.max()) if valid_count > 0 else 0.0

        current = (score, valid_count, max_val, str(c))
        if best is None or current[:3] > best[:3]:
            best = current
    if best:
        return best[3]
    # Fallback genérico: columna numérica con más valores positivos parseables
    best_num: Optional[Tuple[int, str]] = None
    for c in df.columns:
        parsed = df[c].apply(_parse_price)
        count = int(parsed.notna().sum())
        if count >= 3:
            if best_num is None or count > best_num[0]:
                best_num = (count, str(c))
    return best_num[1] if best_num else None


def _pick_concept_column(df: pd.DataFrame, price_col: Optional[str]) -> Optional[str]:
    best: Optional[Tuple[int, str]] = None
    for c in df.columns:
        if price_col and str(c) == price_col:
            continue
        h = _norm_header(c)
        score = 0
        if "descripcion" in h or "descripción" in h:
            score += 5
        if "concepto" in h:
            score += 4
        if any(t in h for t in _CONCEPT_TOKENS):
            score += 1
        # Evitar priorizar "partida" si hay columnas descriptivas mejores.
        if "partida" in h:
            score -= 1
        if score > 0 and (best is None or score > best[0]):
            best = (score, str(c))
    if best:
        return best[1]
    # Fallback: primera columna de texto con valores no vacíos (layouts de cálculo)
    for c in df.columns:
        if price_col and str(c) == price_col:
            continue
        non_null = df[c].dropna()
        if len(non_null) >= 2 and (df[c].dtype == object or str(df[c].dtype) == "string"):
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
        # Intentar primero con header automático
        df_auto = xl.parse(sheet_name)
        df_auto = df_auto.dropna(how="all", axis=0).dropna(how="all", axis=1)

        rows_found = _extract_from_df(df_auto, sheet_name, filename)

        # Si no encontró nada, intentar sin header (layouts de cálculo tipo desglose de costos)
        if not rows_found:
            df_raw = xl.parse(sheet_name, header=None)
            df_raw = df_raw.dropna(how="all", axis=0).dropna(how="all", axis=1)
            rows_found = _extract_from_raw_layout(df_raw, sheet_name, filename)

        out.extend(rows_found)
    return out


def extract_line_items_from_csv_path(file_path: str, filename: str) -> List[Dict[str, Any]]:
    """
    Extrae partidas desde CSV con autodetección básica de separador/encoding.
    """
    out: List[Dict[str, Any]] = []
    # Intento 1: autodetección engine python
    tried = []
    for kwargs in (
        {"sep": None, "engine": "python", "encoding": "utf-8"},
        {"sep": ";", "engine": "python", "encoding": "utf-8"},
        {"sep": ",", "engine": "python", "encoding": "utf-8"},
        {"sep": "|", "engine": "python", "encoding": "utf-8"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
        {"sep": ";", "engine": "python", "encoding": "latin-1"},
    ):
        try:
            df = pd.read_csv(file_path, **kwargs)
            df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
            if df.empty:
                continue
            rows = _extract_from_df(df, "csv", filename)
            if rows:
                out.extend(rows)
                return out
            # fallback layout raw sobre mismo dataframe
            rows_raw = _extract_from_raw_layout(df, "csv", filename)
            if rows_raw:
                out.extend(rows_raw)
                return out
        except Exception as e:  # pragma: no cover - depende del archivo real
            tried.append(str(e))
            continue
    return out


def extract_line_items_from_docx_path(file_path: str, filename: str) -> List[Dict[str, Any]]:
    """
    Extrae partidas desde tablas DOCX (propuestas económicas en hoja membretada).

    Reutiliza las mismas heurísticas de Excel/CSV para identificar concepto/precio.
    """
    out: List[Dict[str, Any]] = []
    doc = Document(file_path)
    for idx, table in enumerate(doc.tables):
        raw_rows: List[List[str]] = []
        for row in table.rows:
            cells = [str(c.text or "").strip() for c in row.cells]
            if any(cells):
                raw_rows.append(cells)
        if len(raw_rows) < 2:
            continue
        max_cols = max(len(r) for r in raw_rows)
        if max_cols <= 1:
            continue
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in raw_rows]
        header = []
        seen_cols = {}
        for i, c in enumerate(normalized_rows[0]):
            c_base = c if c else f"col_{i}"
            if c_base in seen_cols:
                seen_cols[c_base] += 1
                header.append(f"{c_base}_{seen_cols[c_base]}")
            else:
                seen_cols[c_base] = 0
                header.append(c_base)
        data_rows = normalized_rows[1:]
        try:
            df = pd.DataFrame(data_rows, columns=header)
        except Exception:
            continue
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if df.empty:
            continue

        rows_found = _extract_from_df(df, f"docx_table_{idx+1}", filename)
        if not rows_found:
            df_raw = pd.DataFrame(data_rows)
            df_raw = df_raw.dropna(how="all", axis=0).dropna(how="all", axis=1)
            if not df_raw.empty:
                rows_found = _extract_from_raw_layout(df_raw, f"docx_table_{idx+1}", filename)
        out.extend(rows_found)
    return out


def _extract_from_df(df: pd.DataFrame, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Extracción estándar desde DataFrame con headers detectados."""
    out: List[Dict[str, Any]] = []
    if df.empty or len(df.columns) < 1:
        return out
    price_col = _pick_price_column(df)
    if not price_col:
        return out
    concept_col = _pick_concept_column(df, price_col)
    if not concept_col:
        return out
    
    price_col_idx = -1
    try:
        price_col_idx = list(df.columns).get_loc(price_col)
    except Exception:
        pass

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
        # Filtrar filas de subtotal/total que no son partidas reales
        if re.match(r"(?i)^(sub)?total|^t\s*o\s*t\s*a\s*l", concept_str):
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
        out.append({
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
            "extra": {
                "source_filename": filename[:500],
                "price_column_index": price_col_idx,
                "price_column_name": str(price_col)
            },
        })
    return out


def _extract_from_raw_layout(df: pd.DataFrame, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """
    Extracción para layouts sin headers estándar (celdas merged, desglose de costos,
    catálogos con encabezado en fila 2, etc.).
    Estrategia genérica: columna con más texto no vacío = concepto,
    columna numérica con más valores positivos = precio.
    """
    out: List[Dict[str, Any]] = []
    if df.empty or len(df.columns) < 2:
        return out

    # Columna de concepto: la que tiene más strings con longitud > 2
    concept_col = None
    best_text_count = 0
    for c in df.columns:
        count = df[c].apply(lambda x: isinstance(x, str) and len(x.strip()) > 2).sum()
        if count > best_text_count:
            best_text_count = count
            concept_col = c

    if concept_col is None or best_text_count < 2:
        return out

    # Columna de precio: la numérica con más valores positivos parseables (excluyendo concepto)
    price_col = None
    best_price_count = 0
    for c in df.columns:
        if c == concept_col:
            continue
        parsed = df[c].apply(_parse_price)
        count = int(parsed.notna().sum())
        if count > best_price_count:
            best_price_count = count
            price_col = c

    if price_col is None or best_price_count < 3:
        return out

    # Patrones genéricos de filas a ignorar: agregados contables, encabezados repetidos
    _SKIP_ROW = re.compile(
        r"(?i)^\s*(sub\s*total|total\s*general|gran\s*total|t\s*o\s*t\s*a\s*l"
        r"|suma\s*total|importe\s*total|monto\s*total)\s*$"
    )

    for i, row in df.iterrows():
        price = _parse_price(row.get(price_col))
        if price is None or price <= 0:
            continue
        raw_concept = row.get(concept_col)
        if raw_concept is None or (isinstance(raw_concept, float) and pd.isna(raw_concept)):
            continue
        concept_str = str(raw_concept).strip()
        if len(concept_str) < 3:
            continue
        if _SKIP_ROW.match(concept_str):
            continue

        cn = _norm_concepto(concept_str)
        out.append({
            "id": str(uuid.uuid4()),
            "concepto_raw": concept_str[:4000],
            "concepto_norm": cn,
            "precio_unitario": price,
            "unidad": None,
            "cantidad": None,
            "sheet_name": str(sheet_name)[:255],
            "row_index": float(i) if isinstance(i, (int, float)) else None,
            "source_type": "document_tabular",
            "moneda": "MXN",
            "extra": {"source_filename": filename[:500], "layout": "raw_calculation"},
        })
    return out
