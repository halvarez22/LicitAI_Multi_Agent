"""
Extracción industrial de partidas/precios desde hojas Excel.
Heurísticas por encabezados (concepto, precio, unidad) sin depender del layout visual del PDF.
"""

from __future__ import annotations

import re
import unicodedata
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


def _line_item_dedupe_key(row: Dict[str, Any]) -> Tuple[str, float, float, str]:
    """Clave estable para fusionar la misma partida en tablas/hojas repetidas (p. ej. DOCX)."""
    try:
        pu = round(float(row.get("precio_unitario") or 0.0), 4)
    except (TypeError, ValueError):
        pu = 0.0
    try:
        qty = round(float(row.get("cantidad") or 1.0), 4)
    except (TypeError, ValueError):
        qty = 1.0
    concept = _norm_concepto(str(row.get("concepto_norm") or row.get("concepto_raw") or ""))
    unit = re.sub(r"\s+", " ", str(row.get("unidad") or "").strip().lower())
    return concept, pu, qty, unit


def dedupe_tabular_line_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Elimina partidas duplicadas (mismo concepto, precio, cantidad y unidad).

    Evita inflar ``excel_total`` en cuadratura cuando el DOCX repite la misma tabla.
    """
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, float, float, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = _line_item_dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _norm_match_text(value: Any) -> str:
    """Normaliza texto para matching semántico de headers/celdas."""
    t = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")


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


def _extract_zone_hint(sheet_name: str) -> Optional[str]:
    match = re.search(r"\bzona\s+([a-z])\b", _norm_match_text(sheet_name), re.I)
    return match.group(1).upper() if match else None


def _find_first_col(headers: List[str], needles: Tuple[str, ...]) -> Optional[int]:
    for idx, header in enumerate(headers):
        if any(needle in header for needle in needles):
            return idx
    return None


def _classify_support_matrix_role(
    df: pd.DataFrame,
    *,
    concept_col: Optional[str],
    price_col: Optional[str],
    unit_col: Optional[str],
) -> Optional[str]:
    """
    Clasifica matrices/listas tabulares de soporte por forma estructural.

    Busca documentos que no son grids de captura de precio, pero sí una relación amplia
    de materiales con múltiples columnas numéricas auxiliares. Se usa para persistir
    un rol canónico consumible después por el flujo económico.
    """
    if df.empty or not concept_col or not price_col:
        return None

    try:
        cols = list(df.columns)
    except Exception:
        return None

    concept_idx = None
    price_idx = None
    unit_idx = None
    try:
        concept_idx = int(df.columns.get_loc(concept_col))
        price_idx = int(df.columns.get_loc(price_col))
        if unit_col:
            unit_idx = int(df.columns.get_loc(unit_col))
    except Exception:
        return None

    text_rows = 0
    positive_price_rows = 0
    numeric_aux_cols = 0
    meaningful_aux_headers = 0
    for c in cols:
        if c in (concept_col, price_col, unit_col):
            continue
        header = _norm_header(c)
        if any(token in header for token in ("cantidad", "total", "mensual", "entrega", "unidad", "zona", "mes", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")):
            meaningful_aux_headers += 1
        parsed = df[c].apply(_parse_price)
        if int(parsed.notna().sum()) >= 3:
            numeric_aux_cols += 1

    for _, row in df.iterrows():
        raw_concept = row.get(concept_col)
        if raw_concept is None or (isinstance(raw_concept, float) and pd.isna(raw_concept)):
            continue
        concept_str = str(raw_concept).strip()
        if len(concept_str) < 2:
            continue
        text_rows += 1
        if _parse_price(row.get(price_col)) is not None:
            positive_price_rows += 1

    if text_rows < 8:
        return None
    if positive_price_rows < 8:
        return None
    if numeric_aux_cols < 4:
        return None
    if meaningful_aux_headers < 2:
        return None
    if price_idx <= concept_idx:
        return None
    if unit_idx is not None:
        return None
    return "material_support_matrix"


def _find_structured_template_header(df: pd.DataFrame) -> Tuple[Optional[int], Optional[str]]:
    """Localiza headers de formatos económicos con cantidades pero costos vacíos."""
    if df.empty:
        return None, None
    max_scan = min(len(df.index), 25)
    for row_idx in range(max_scan):
        row_vals = [_norm_match_text(v) for v in df.iloc[row_idx].tolist()]
        joined = " | ".join(v for v in row_vals if v)
        if not joined:
            continue
        if (
            "elementos" in joined
            and "horario" in joined
            and "unidad" in joined
        ):
            return row_idx, "service_zone_elements"
        if (
            "cantidad mensual" in joined
            and ("descripcion del material" in joined or "descripcion" in joined)
        ):
            return row_idx, "monthly_material_requirement"
        if (
            ("localidad" in joined or "ubicacion" in joined or "municipio" in joined)
            and (
                "costo" in joined
                or "elemento" in joined
                or "iva" in joined
                or "precio" in joined
            )
        ):
            return row_idx, "location_price_grid"
    return None, None


def _looks_like_structured_template_df(df: pd.DataFrame) -> bool:
    row_idx, kind = _find_structured_template_header(df)
    return row_idx is not None and bool(kind)


_STRUCTURED_SKIP_ROW = re.compile(
    r"(?i)^\s*(totales?|nombre y firma|representante|apoderado legal|servicio de limpieza|anexo iii)\b"
)


def _find_material_support_list_header(df: pd.DataFrame) -> tuple[Optional[int], Dict[str, int]]:
    """Detecta listas de soporte de materiales con columnas tipo descripción/presentación/cantidad."""
    max_scan = min(len(df.index), 25)
    for row_idx in range(max_scan):
        headers = [_norm_match_text(v) for v in df.iloc[row_idx].tolist()]
        concept_col = _find_first_col(headers, ("descripcion del material", "descripcion"))
        if concept_col is None:
            continue
        unit_col = _find_first_col(headers, ("presentacion", "unidad"))
        qty_col = _find_first_col(headers, ("cantidad mensual", "cantidad"))
        obs_col = _find_first_col(headers, ("observaciones",))
        if unit_col is not None and (qty_col is not None or obs_col is not None):
            return row_idx, {
                "concept_col": concept_col,
                "unit_col": unit_col,
                "qty_col": qty_col if qty_col is not None else -1,
            }
    return None, {}


def _extract_from_material_support_list(
    df: pd.DataFrame, sheet_name: str, filename: str
) -> List[Dict[str, Any]]:
    """Extrae listas soporte de materiales sin costos ofertados."""
    out: List[Dict[str, Any]] = []
    header_row_idx, cols = _find_material_support_list_header(df)
    if header_row_idx is None or not cols:
        return out

    concept_col = cols["concept_col"]
    unit_col = cols["unit_col"]
    qty_col = cols.get("qty_col", -1)
    for row_pos in range(header_row_idx + 1, len(df.index)):
        row = df.iloc[row_pos]
        raw_concept = row.iloc[concept_col] if concept_col is not None else None
        if raw_concept is None or (isinstance(raw_concept, float) and pd.isna(raw_concept)):
            continue
        concept_str = str(raw_concept).strip()
        if len(concept_str) < 2 or _STRUCTURED_SKIP_ROW.match(_norm_match_text(concept_str)):
            continue

        unit_val = None
        if unit_col is not None:
            raw_unit = row.iloc[unit_col]
            if raw_unit is not None and not (isinstance(raw_unit, float) and pd.isna(raw_unit)):
                unit_val = str(raw_unit).strip()[:64] or None

        qty = None
        if qty_col is not None and qty_col >= 0:
            qty = _parse_price(row.iloc[qty_col])

        out.append(
            {
                "id": str(uuid.uuid4()),
                "concepto_raw": concept_str[:4000],
                "concepto_norm": _norm_concepto(concept_str),
                "precio_unitario": 0.0,
                "unidad": unit_val,
                "cantidad": qty,
                "sheet_name": str(sheet_name)[:255],
                "row_index": float(row_pos + 1),
                "source_type": "document_tabular",
                "moneda": "MXN",
                "extra": {
                    "source_filename": filename[:500],
                    "layout": "material_support_list",
                    "document_role": "material_support_list",
                    "header_row_index": int(header_row_idx + 1),
                    "quantity_column_index": qty_col if qty_col >= 0 else None,
                    "price_values_suppressed": True,
                },
            }
        )
    return out


def _extract_from_transposed_material_support_matrix(
    df: pd.DataFrame, sheet_name: str, filename: str
) -> List[Dict[str, Any]]:
    """Extrae matrices transpuestas donde cada columna representa un material."""
    out: List[Dict[str, Any]] = []
    max_scan = min(len(df.index), 12)
    concept_row_idx = unit_row_idx = qty_row_idx = None
    for row_idx in range(max_scan):
        vals = [_norm_match_text(v) for v in df.iloc[row_idx].tolist()]
        joined = " | ".join(v for v in vals if v)
        if "descripcion del material" in joined:
            concept_row_idx = row_idx
        elif "presentacion" in joined or "presentación" in joined:
            unit_row_idx = row_idx
        elif "unidad medica" in joined or "unidad médica" in joined:
            qty_row_idx = row_idx
    if concept_row_idx is None or unit_row_idx is None or qty_row_idx is None:
        return out
    if not (concept_row_idx < unit_row_idx < qty_row_idx):
        return out

    concept_row = df.iloc[concept_row_idx]
    unit_row = df.iloc[unit_row_idx]
    qty_header_row = df.iloc[qty_row_idx]
    data_start = qty_row_idx + 1
    for col_idx in range(len(df.columns)):
        concept_str = str(concept_row.iloc[col_idx] or "").strip()
        unit_str = str(unit_row.iloc[col_idx] or "").strip()
        qty_header = _norm_match_text(qty_header_row.iloc[col_idx])
        if len(concept_str) < 2:
            continue
        if _STRUCTURED_SKIP_ROW.match(_norm_match_text(concept_str)):
            continue
        if not unit_str:
            continue
        if "cantidad" not in qty_header:
            continue

        qty_total = 0.0
        qty_found = False
        for row_pos in range(data_start, len(df.index)):
            val = df.iloc[row_pos, col_idx]
            parsed = _parse_price(val)
            if parsed is None:
                continue
            qty_total += float(parsed)
            qty_found = True

        out.append(
            {
                "id": str(uuid.uuid4()),
                "concepto_raw": concept_str[:4000],
                "concepto_norm": _norm_concepto(concept_str),
                "precio_unitario": 0.0,
                "unidad": unit_str[:64],
                "cantidad": round(qty_total, 4) if qty_found else None,
                "sheet_name": str(sheet_name)[:255],
                "row_index": float(concept_row_idx + 1),
                "source_type": "document_tabular",
                "moneda": "MXN",
                "extra": {
                    "source_filename": filename[:500],
                    "layout": "transposed_material_support_matrix",
                    "document_role": "material_support_matrix",
                    "concept_row_index": int(concept_row_idx + 1),
                    "unit_row_index": int(unit_row_idx + 1),
                    "quantity_header_row_index": int(qty_row_idx + 1),
                    "matrix_column_index": col_idx,
                    "price_values_suppressed": True,
                },
            }
        )
    return out


def _extract_from_structured_template(
    df: pd.DataFrame, sheet_name: str, filename: str
) -> List[Dict[str, Any]]:
    """
    Extrae formatos donde la convocante fija cantidades/elementos y deja vacías
    las columnas de costos para que el licitante las complete.
    """
    out: List[Dict[str, Any]] = []
    header_row_idx, template_kind = _find_structured_template_header(df)
    if header_row_idx is None or template_kind is None:
        return out

    headers = [_norm_match_text(v) for v in df.iloc[header_row_idx].tolist()]
    zone_hint = _extract_zone_hint(sheet_name)

    if template_kind == "location_price_grid":
        location_col = _find_first_col(
            headers, ("localidad", "ubicacion", "municipio", "ciudad")
        )
        price_col = _find_first_col(
            headers,
            (
                "costo por elemento",
                "costo unitario",
                "precio unitario",
                "iva incl",
                "i.v.a",
            ),
        )
        amount_col = _find_first_col(headers, ("importe", "monto", "subtotal"))
        total_col = _find_first_col(headers, ("total", "costo total"))
        if location_col is None or price_col is None:
            return out
        price_header_raw = df.iloc[header_row_idx, price_col] if price_col is not None else None
        for row_pos in range(header_row_idx + 1, len(df.index)):
            row = df.iloc[row_pos]
            raw_loc = row.iloc[location_col] if location_col is not None else None
            if raw_loc is None or (isinstance(raw_loc, float) and pd.isna(raw_loc)):
                continue
            loc_str = str(raw_loc).strip()
            if len(loc_str) < 2 or _STRUCTURED_SKIP_ROW.match(_norm_match_text(loc_str)):
                continue
            price = _parse_price(row.iloc[price_col]) if price_col is not None else None
            extra = {
                "source_filename": filename[:500],
                "layout": "structured_template",
                "template_kind": template_kind,
                "header_row_index": int(header_row_idx + 1),
                "price_column_index": price_col,
                "price_column_header": str(price_header_raw or "").strip()[:200],
                "subtotal_column_index": amount_col,
                "total_column_index": total_col,
                "location_label": loc_str[:128],
                "price_input_pending": price is None,
                "template_source": "convocante_blank_price_grid",
            }
            out.append(
                {
                    "concepto_raw": loc_str,
                    "concepto_norm": _norm_concepto(loc_str),
                    "cantidad": 1.0,
                    "precio_unitario": price,
                    "unidad": "SERVICIO",
                    "sheet_name": sheet_name,
                    "row_index": float(row_pos),
                    "source_type": "document_tabular",
                    "moneda": "MXN",
                    "extra": extra,
                }
            )
        return out

    if template_kind == "service_zone_elements":
        zone_col = _find_first_col(headers, ("zona",))
        code_col = _find_first_col(headers, ("num.", "num ", "num", "numero"))
        concept_col = _find_first_col(headers, ("unidad",))
        city_col = _find_first_col(headers, ("ciudad",))
        qty_col = _find_first_col(headers, ("elementos",))
        schedule_col = _find_first_col(headers, ("horario",))
        price_col = _find_first_col(headers, ("costo por elemento", "costo unitario"))
        subtotal_col = _find_first_col(headers, ("tarifa mensual", "costo mensual"))
        total_col = _find_first_col(headers, ("costo total",))
        if concept_col is None or qty_col is None:
            return out
    else:
        item_no_col = _find_first_col(headers, ("no.", "no ", "numero"))
        concept_col = _find_first_col(headers, ("descripcion del material", "descripcion"))
        unit_col = _find_first_col(headers, ("presentacion", "unidad"))
        qty_col = _find_first_col(headers, ("cantidad mensual", "cantidad"))
        price_col = _find_first_col(headers, ("costo unitario", "precio unitario"))
        subtotal_col = _find_first_col(headers, ("costo mensual",))
        total_col = _find_first_col(headers, ("costo total",))
        if concept_col is None or qty_col is None:
            return out

    for row_pos in range(header_row_idx + 1, len(df.index)):
        row = df.iloc[row_pos]
        raw_concept = row.iloc[concept_col] if concept_col is not None else None
        if raw_concept is None or (isinstance(raw_concept, float) and pd.isna(raw_concept)):
            continue
        concept_str = str(raw_concept).strip()
        if len(concept_str) < 2 or _STRUCTURED_SKIP_ROW.match(_norm_match_text(concept_str)):
            continue

        qty_val = row.iloc[qty_col] if qty_col is not None else None
        qty = _parse_price(qty_val)
        if qty is None or qty <= 0:
            continue

        price = _parse_price(row.iloc[price_col]) if price_col is not None else None
        subtotal = _parse_price(row.iloc[subtotal_col]) if subtotal_col is not None else None
        total = _parse_price(row.iloc[total_col]) if total_col is not None else None

        extra: Dict[str, Any] = {
            "source_filename": filename[:500],
            "layout": "structured_template",
            "template_kind": template_kind,
            "header_row_index": int(header_row_idx + 1),
            "quantity_column_index": qty_col,
            "price_column_index": price_col,
            "subtotal_column_index": subtotal_col,
            "total_column_index": total_col,
            "price_input_pending": price is None,
        }

        if template_kind == "service_zone_elements":
            zone = (
                str(row.iloc[zone_col]).strip()
                if zone_col is not None and row.iloc[zone_col] is not None
                else (zone_hint or "")
            )
            site_code = (
                str(row.iloc[code_col]).strip()
                if code_col is not None and row.iloc[code_col] is not None
                else ""
            )
            city = (
                str(row.iloc[city_col]).strip()
                if city_col is not None and row.iloc[city_col] is not None
                else ""
            )
            schedule = (
                str(row.iloc[schedule_col]).strip()
                if schedule_col is not None and row.iloc[schedule_col] is not None
                else ""
            )
            extra.update(
                {
                    "zone": zone[:32] or zone_hint,
                    "site_code": site_code[:128] or None,
                    "city": city[:128] or None,
                    "schedule": schedule[:255] or None,
                    "quantity_kind": "num_elementos",
                    "price_input_kind": "cost_per_element",
                    "template_source": "convocante_blank_price_grid",
                }
            )
            unidad_val = "ELEMENTO"
        else:
            item_no = (
                str(row.iloc[item_no_col]).strip()
                if item_no_col is not None and row.iloc[item_no_col] is not None
                else ""
            )
            unit_text = (
                str(row.iloc[unit_col]).strip()
                if unit_col is not None and row.iloc[unit_col] is not None
                else None
            )
            extra.update(
                {
                    "item_no": item_no[:64] or None,
                    "zone": zone_hint,
                    "quantity_kind": "cantidad_mensual",
                    "price_input_kind": "unit_cost",
                    "template_source": "convocante_blank_price_grid",
                }
            )
            unidad_val = unit_text[:64] if unit_text else None

        if subtotal is not None:
            extra["subtotal_detected"] = subtotal
        if total is not None:
            extra["total_detected"] = total

        out.append(
            {
                "id": str(uuid.uuid4()),
                "concepto_raw": concept_str[:4000],
                "concepto_norm": _norm_concepto(concept_str),
                "precio_unitario": float(price or 0.0),
                "unidad": unidad_val,
                "cantidad": qty,
                "sheet_name": str(sheet_name)[:255],
                "row_index": float(row_pos + 1),
                "source_type": "document_tabular",
                "moneda": "MXN",
                "extra": extra,
            }
        )
    return out


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
        df_raw = xl.parse(sheet_name, header=None)
        df_raw = df_raw.dropna(how="all", axis=0).dropna(how="all", axis=1)

        support_rows = _extract_from_structured_template(df_raw, sheet_name, filename)
        if not support_rows:
            support_rows = _extract_from_transposed_material_support_matrix(
                df_raw, sheet_name, filename
            )
        if not support_rows:
            support_rows = _extract_from_material_support_list(df_raw, sheet_name, filename)
        if support_rows:
            rows_found = support_rows

        # Si no encontró nada, intentar sin header (layouts de cálculo tipo desglose de costos)
        if not rows_found:
            rows_found = _extract_from_raw_layout(df_raw, sheet_name, filename)

        out.extend(rows_found)
    return dedupe_tabular_line_items(out)


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
                return dedupe_tabular_line_items(out)
        except Exception as e:  # pragma: no cover - depende del archivo real
            tried.append(str(e))
            continue
    return dedupe_tabular_line_items(out)


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
    return dedupe_tabular_line_items(out)


def _extract_from_df(df: pd.DataFrame, sheet_name: str, filename: str) -> List[Dict[str, Any]]:
    """Extracción estándar desde DataFrame con headers detectados."""
    out: List[Dict[str, Any]] = []
    if df.empty or len(df.columns) < 1:
        return out
    # Si el "header" automático dejó los verdaderos encabezados como filas de datos,
    # devolvemos vacío para que la ruta raw capture cantidades/zonas sin degradarlas a precio.
    if _looks_like_structured_template_df(df):
        return out
    price_col = _pick_price_column(df)
    if not price_col:
        return out
    concept_col = _pick_concept_column(df, price_col)
    if not concept_col:
        return out
    
    price_col_idx = -1
    try:
        price_col_idx = int(df.columns.get_loc(price_col))
    except Exception:
        pass

    skip = {price_col, concept_col}
    unit_col = _pick_unit_column(df, skip)
    document_role = _classify_support_matrix_role(
        df,
        concept_col=concept_col,
        price_col=price_col,
        unit_col=unit_col,
    )

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
        effective_price = 0.0 if document_role == "material_support_matrix" else price
        out.append({
            "id": str(uuid.uuid4()),
            "concepto_raw": concept_str[:4000],
            "concepto_norm": cn,
            "precio_unitario": effective_price,
            "unidad": unit_val,
            "cantidad": qty,
            "sheet_name": str(sheet_name)[:255],
            "row_index": float(i) if isinstance(i, (int, float)) else None,
            "source_type": "document_tabular",
            "moneda": "MXN",
            "extra": {
                "source_filename": filename[:500],
                "price_column_index": price_col_idx,
                "price_column_name": str(price_col),
                "document_role": document_role,
                "price_values_suppressed": document_role == "material_support_matrix",
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


# --- Texto plano (TXT / PDF nativo-OCR) → partidas de catálogo obra/servicios ---

_UNITS_CANONICAL = frozenset(
    {
        "m3",
        "m2",
        "m²",
        "m³",
        "pza",
        "kg",
        "lote",
        "servicio",
        "hora",
        "dia",
        "día",
        "ml",
        "l",
        "ton",
        "tonelada",
        "global",
        "mes",
    }
)

_SKIP_TEXT_ROW = re.compile(
    r"(?i)^\s*(no\.?|clave|descripci[oó]n|concepto|unidad|cantidad|precio|importe|subtotal|"
    r"total|iva|utilidad|indirecto|gran\s*total|costos?\s+directos?|representante|fecha|"
    r"licitaci[oó]n|cat[aá]logo|propuesta|mxn|unitario)\b"
)

_INLINE_ROW_RE = re.compile(
    r"^(?P<partida>\d{1,3})\s+"
    r"(?P<clave>\d{3,6})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<unidad>m[²2³3]|pza|kg|lote|servicio|hora|d[ií]a|ml|l|ton|tonelada|global|mes)\s+"
    r"(?P<cantidad>[\d.,]+)\s+"
    r"(?P<pu>[\d.,]+)\s+"
    r"(?P<importe>[\d.,]+)\s*$",
    re.I,
)


def _is_unit_token(token: str) -> bool:
    raw = str(token or "").strip().lower()
    if not raw:
        return False
    if raw in _UNITS_CANONICAL:
        return True
    return bool(re.fullmatch(r"m[²2³3]", raw))


def _parse_qty(val: Any) -> Optional[float]:
    p = _parse_price(val)
    if p is not None:
        return p
    s = str(val or "").strip().replace(",", "")
    if not s:
        return None
    try:
        x = float(s)
        return x if x >= 0 else None
    except ValueError:
        return None


def _append_text_row(
    out: List[Dict[str, Any]],
    *,
    filename: str,
    partida: int,
    clave: str,
    descripcion: str,
    unidad: str,
    cantidad: float,
    precio_unitario: float,
    row_index: int,
    layout: str,
) -> None:
    concept = f"{clave} {descripcion}".strip()
    if len(concept) < 4 or precio_unitario <= 0:
        return
    if _SKIP_TEXT_ROW.match(concept):
        return
    out.append(
        {
            "id": str(uuid.uuid4()),
            "concepto_raw": concept[:4000],
            "concepto_norm": _norm_concepto(concept),
            "precio_unitario": float(precio_unitario),
            "unidad": (unidad or None)[:64] if unidad else None,
            "cantidad": float(cantidad) if cantidad and cantidad > 0 else 1.0,
            "sheet_name": "text_catalog",
            "row_index": float(row_index),
            "source_type": "text_catalog",
            "moneda": "MXN",
            "extra": {
                "source_filename": filename[:500],
                "layout": layout,
                "partida": partida,
                "clave": clave,
            },
        }
    )


def _extract_catalog_from_structured_lines(
    lines: List[str], filename: str
) -> List[Dict[str, Any]]:
    """Filas en una línea (TSV, espacios múltiples o copy-paste tabular)."""
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(lines):
        line = re.sub(r"\s+", " ", str(raw or "").strip())
        if not line or _SKIP_TEXT_ROW.match(line):
            continue
        m = _INLINE_ROW_RE.match(line)
        if not m:
            continue
        _append_text_row(
            out,
            filename=filename,
            partida=int(m.group("partida")),
            clave=m.group("clave"),
            descripcion=m.group("desc").strip(),
            unidad=m.group("unidad"),
            cantidad=float(_parse_qty(m.group("cantidad")) or 1),
            precio_unitario=float(_parse_price(m.group("pu")) or 0),
            row_index=idx,
            layout="inline_row",
        )
    return out


def _append_numeric_tokens_from_line(line: str, nums: List[float], *, limit: int = 3) -> int:
    """Añade números de una línea (p. ej. ``18,500.00 37,000.00``). Devuelve cuántos se añadieron."""
    added = 0
    for part in str(line or "").split():
        if len(nums) >= limit:
            break
        val = _parse_qty(part)
        if val is not None:
            nums.append(val)
            added += 1
    return added


def _extract_catalog_from_ocr_lines(lines: List[str], filename: str) -> List[Dict[str, Any]]:
    """
    Catálogo obra con celdas en líneas separadas (típico de PDF nativo vía PyMuPDF).
    """
    out: List[Dict[str, Any]] = []
    n = len(lines)
    i = 0
    while i < n - 4:
        partida_s = lines[i].strip()
        if not re.fullmatch(r"\d{1,3}", partida_s):
            i += 1
            continue
        clave_line = lines[i + 1].strip() if i + 1 < n else ""
        m_clave = re.match(r"^(\d{3,6})\b", clave_line)
        if not m_clave:
            i += 1
            continue
        clave_s = m_clave.group(1)
        clave_tail = clave_line[m_clave.end() :].strip()
        j = i + 2
        desc_parts: List[str] = []
        if clave_tail:
            desc_parts.append(clave_tail)
        unidad: Optional[str] = None
        while j < n:
            tok = lines[j].strip()
            if not tok:
                j += 1
                continue
            if _SKIP_TEXT_ROW.match(tok):
                j += 1
                continue
            if _is_unit_token(tok):
                unidad = tok
                j += 1
                break
            # Unidad al final de la línea (p. ej. «colocación de puerta pza»)
            tail_parts = tok.rsplit(None, 1)
            if len(tail_parts) == 2 and _is_unit_token(tail_parts[1]):
                if tail_parts[0]:
                    desc_parts.append(tail_parts[0])
                unidad = tail_parts[1]
                j += 1
                break
            if re.fullmatch(r"[\d.,]+", tok.replace(",", "")):
                break
            desc_parts.append(tok)
            j += 1
        if j >= n or not desc_parts or not unidad:
            i += 1
            continue
        nums: List[float] = []
        while j < n and len(nums) < 3:
            tok = lines[j].strip()
            if not tok:
                j += 1
                continue
            if _SKIP_TEXT_ROW.match(tok):
                j += 1
                continue
            added = _append_numeric_tokens_from_line(tok, nums)
            if added:
                j += 1
            else:
                break
        if len(nums) < 2:
            i += 1
            continue
        cantidad, pu = nums[0], nums[1]
        _append_text_row(
            out,
            filename=filename,
            partida=int(partida_s),
            clave=clave_s,
            descripcion=" ".join(desc_parts),
            unidad=unidad,
            cantidad=cantidad,
            precio_unitario=pu,
            row_index=i,
            layout="ocr_multiline",
        )
        i = j
    return out


def _extract_catalog_from_tsv_blocks(text: str, filename: str) -> List[Dict[str, Any]]:
    """Bloques con tabuladores (exportación Excel → TXT)."""
    out: List[Dict[str, Any]] = []
    for block in re.split(r"\n{2,}", text):
        if "\t" not in block:
            continue
        rows = [ln for ln in block.splitlines() if ln.strip()]
        if len(rows) < 2:
            continue
        header = [c.strip().lower() for c in rows[0].split("\t")]
        if not any("precio" in h or "concepto" in h or "descrip" in h for h in header):
            continue
        try:
            import io

            df = pd.read_csv(io.StringIO("\n".join(rows)), sep="\t")
            df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
            out.extend(_extract_from_df(df, "text_tsv", filename))
        except Exception:
            continue
    return out


def extract_line_items_from_text_blob(text: str, filename: str) -> List[Dict[str, Any]]:
    """
    Extrae partidas cotizables desde texto plano (TXT o ``extracted_text`` de PDF).

    Estrategias (en orden): TSV → filas inline → layout OCR multilínea.
    """
    if not str(text or "").strip():
        return []

    raw = str(text)
    # Quitar encabezados de página del pipeline híbrido PDF
    raw = re.sub(r"---\s*PÁGINA\s+\d+\s*---", "\n", raw, flags=re.I)
    raw = re.sub(r"###\s*ARCHIVO:.*", "\n", raw, flags=re.I)

    lines = [ln.strip() for ln in raw.splitlines() if str(ln or "").strip()]
    if not lines:
        return []

    merged: List[Dict[str, Any]] = []
    for chunk in (
        _extract_catalog_from_tsv_blocks(raw, filename),
        _extract_catalog_from_structured_lines(lines, filename),
        _extract_catalog_from_ocr_lines(lines, filename),
    ):
        merged.extend(chunk)

    # Mínimo 2 partidas con precio para evitar falsos positivos de una celda suelta
    priced = [r for r in merged if float(r.get("precio_unitario") or 0) > 0]
    if len(priced) < 2:
        return []
    return dedupe_tabular_line_items(priced)
