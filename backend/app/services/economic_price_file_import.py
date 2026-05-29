"""
Importación de cotización económica desde Excel/CSV subido en chat (HITL masivo).

No requiere pegado manual: lee el archivo, detecta columnas, cruza con la matriz
de la sesión y persiste en ``economic_user_inputs``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.conversational_price_normalizer import normalize_conversational_price
from app.services.economic_column_roles import (
    ROLE_AMOUNT,
    ROLE_LOCATION_LABEL,
    ROLE_UNIT_PRICE_EXCL_IVA,
    ROLE_UNIT_PRICE_IVA_INCLUDED,
    detect_column_role,
    normalize_header_text,
)

_SUPPORTED_EXT = frozenset({".xlsx", ".xls", ".csv", ".tsv", ".txt"})

_PRICE_ROLES = frozenset(
    {
        ROLE_UNIT_PRICE_EXCL_IVA,
        ROLE_UNIT_PRICE_IVA_INCLUDED,
        ROLE_AMOUNT,
    }
)


def _read_tabular_file(file_path: Path) -> pd.DataFrame:
    """Carga la primera hoja útil de Excel o un CSV/TSV."""
    suffix = file_path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        raw = pd.read_excel(file_path, sheet_name=None, header=None, dtype=object)
        if isinstance(raw, dict):
            for _name, frame in raw.items():
                df = _coerce_dataframe(frame)
                if df is not None and not df.empty:
                    return df
        df = pd.read_excel(file_path, header=0, dtype=object)
        return _coerce_dataframe(df) or pd.DataFrame()
    if suffix in (".csv", ".tsv", ".txt"):
        sample = file_path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
        first_line = sample.splitlines()[0] if sample else ""
        tab_n = first_line.count("\t")
        comma_n = first_line.count(",")
        semicolon_n = first_line.count(";")
        if suffix == ".tsv" or tab_n >= max(comma_n, semicolon_n, 1):
            seps = ("\t", ",", ";")
        else:
            seps = (",", ";", "\t")
        for sep in seps:
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    df = pd.read_csv(file_path, sep=sep, dtype=object, encoding=encoding)
                    if df is not None and len(df.columns) >= 2:
                        coerced = _coerce_dataframe(df)
                        if coerced is not None and not coerced.empty:
                            return coerced
                except Exception:
                    continue
        return pd.read_csv(file_path, sep=None, engine="python", dtype=object)
    raise ValueError(f"Extensión no soportada: {suffix}")


def _coerce_dataframe(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Detecta fila de encabezados si la primera fila parece títulos."""
    if frame is None or frame.empty:
        return None
    if all(isinstance(c, (int, float)) for c in frame.columns):
        header_row = 0
        for i in range(min(5, len(frame))):
            row_vals = [str(v or "") for v in frame.iloc[i].tolist()]
            joined = " ".join(row_vals).lower()
            if any(
                k in joined
                for k in ("precio", "concepto", "ubicacion", "anexo", "archivo", "zona")
            ):
                header_row = i
                break
        hdr = [str(v or f"col_{j}").strip() for j, v in enumerate(frame.iloc[header_row].tolist())]
        body = frame.iloc[header_row + 1 :].copy()
        body.columns = hdr
        return body.reset_index(drop=True)
    frame.columns = [str(c or "").strip() for c in frame.columns]
    return frame


def _detect_import_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Devuelve (columna_anexo, columna_concepto, columna_precio)."""
    annex_col: Optional[str] = None
    label_col: Optional[str] = None
    price_col: Optional[str] = None

    for col in df.columns:
        role = detect_column_role(col)
        cs = str(col)
        if role in _PRICE_ROLES and price_col is None:
            price_col = cs
        elif role == ROLE_LOCATION_LABEL and label_col is None:
            label_col = cs
        nh = normalize_header_text(col)
        if annex_col is None and any(k in nh for k in ("anexo", "archivo", "file", "fuente")):
            annex_col = cs
        if label_col is None and any(
            k in nh for k in ("concepto", "ubicacion", "localidad", "zona", "concept", "horario")
        ):
            label_col = cs
        if price_col is None and any(
            k in nh for k in ("precio", "costo", "importe", "mxn", "unitario")
        ):
            price_col = cs

    cols = list(df.columns)
    if price_col is None and len(cols) >= 2:
        for col in reversed(cols):
            sample = df[col].dropna().head(12)
            numeric_hits = sum(1 for v in sample if _looks_numeric_cell(v))
            if numeric_hits >= max(2, len(sample) // 2):
                price_col = str(col)
                break

    if label_col is None and len(cols) >= 2:
        for col in cols:
            if str(col) == price_col:
                continue
            if annex_col and str(col) == annex_col:
                continue
            label_col = str(col)
            break

    if annex_col is None and len(cols) >= 3 and label_col and price_col:
        for col in cols:
            if str(col) not in (label_col, price_col):
                annex_col = str(col)
                break

    # Plantilla exportada: Anexo | Concepto | Precio
    if len(cols) >= 3 and price_col:
        if label_col is None or label_col == annex_col:
            mid = [c for c in cols if str(c) not in (annex_col, price_col)]
            if mid:
                label_col = str(mid[0])
        if annex_col is None and len(cols) >= 3:
            first = str(cols[0])
            if first != label_col and first != price_col:
                annex_col = first

    return annex_col, label_col, price_col


def _looks_numeric_cell(value: Any) -> bool:
    s = re.sub(r"[^\d.\-]", "", str(value or "").replace(",", ""))
    if not s or s in (".", "-"):
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_price_cell(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    text = str(raw or "").strip()
    if not text:
        return None, None
    text = text.replace("$", "").replace("MXN", "").replace("mxn", "").strip()
    text = text.replace(",", "")
    val, err, _conf = normalize_conversational_price(text)
    if err or not val:
        return None, err or "inválido"
    try:
        return float(val), None
    except ValueError:
        return None, "inválido"


def _build_field_maps(
    blocks: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    ``label_lower -> field`` y ``(anexo_norm|label_lower) -> field`` para desambiguar.
    """
    by_label: Dict[str, str] = {}
    by_annex_label: Dict[str, str] = {}
    for block in blocks or []:
        annex = normalize_header_text(block.get("source_file") or "")
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            field = str(row.get("field") or "").strip()
            if not label or not field:
                continue
            key = label.lower()
            by_label[key] = field
            if annex:
                by_annex_label[f"{annex}|{key}"] = field
    return by_label, by_annex_label


def _resolve_field(
    label: str,
    annex: str,
    by_label: Dict[str, str],
    by_annex_label: Dict[str, str],
) -> Optional[str]:
    lk = label.strip().lower()
    if not lk:
        return None
    an = normalize_header_text(annex)
    if an:
        hit = by_annex_label.get(f"{an}|{lk}")
        if hit:
            return hit
        for k, field in by_annex_label.items():
            if k.endswith(f"|{lk}") and (an in k or k.split("|", 1)[0] in an):
                return field
    return by_label.get(lk)


def import_economic_prices_from_file(
    file_path: str | Path,
    blocks: List[Dict[str, Any]],
    economic_user_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Importa precios desde Excel/CSV hacia ``economic_user_inputs``.

    Returns:
        dict con applied, errors, unmatched, rows_read, columns_detected
    """
    path = Path(file_path)
    if path.suffix.lower() not in _SUPPORTED_EXT:
        return {
            "applied": {},
            "errors": [f"Extensión no soportada: {path.suffix}"],
            "unmatched": [],
            "rows_read": 0,
            "columns_detected": {},
        }

    df = _read_tabular_file(path)
    if df.empty:
        return {
            "applied": {},
            "errors": ["El archivo no contiene filas de datos."],
            "unmatched": [],
            "rows_read": 0,
            "columns_detected": {},
        }

    annex_col, label_col, price_col = _detect_import_columns(df)
    if not label_col or not price_col:
        return {
            "applied": {},
            "errors": [
                "No detecté columnas de concepto/ubicación y precio. "
                "Usa encabezados como «Concepto / ubicación» y «Precio unitario»."
            ],
            "unmatched": [],
            "rows_read": int(len(df)),
            "columns_detected": {
                "annex": annex_col,
                "label": label_col,
                "price": price_col,
            },
        }

    by_label, by_annex_label = _build_field_maps(blocks)
    inputs = dict(economic_user_inputs or {})
    applied: Dict[str, float] = {}
    errors: List[str] = []
    unmatched: List[str] = []

    for idx, row in df.iterrows():
        label = str(row.get(label_col) or "").strip()
        if not label or label.lower().startswith("concepto"):
            continue
        annex = str(row.get(annex_col) or "").strip() if annex_col else ""
        price_raw = row.get(price_col)
        if price_raw is None or (isinstance(price_raw, float) and pd.isna(price_raw)):
            continue
        field = _resolve_field(label, annex, by_label, by_annex_label)
        if not field:
            unmatched.append(label[:80])
            continue
        amount, perr = _parse_price_cell(price_raw)
        if perr or amount is None:
            errors.append(f"{label[:40]}: {perr or 'sin precio'}")
            continue
        inputs[field] = amount
        applied[field] = amount

    return {
        "applied": applied,
        "errors": errors[:25],
        "unmatched": unmatched[:25],
        "rows_read": int(len(df)),
        "columns_detected": {
            "annex": annex_col,
            "label": label_col,
            "price": price_col,
        },
        "economic_user_inputs": inputs,
    }
