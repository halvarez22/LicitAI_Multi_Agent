"""
Detección universal de roles de columna en hojas Excel (Ítem D).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

ROLE_UNIT_PRICE_IVA_INCLUDED = "unit_price_iva_included"
ROLE_UNIT_PRICE_EXCL_IVA = "unit_price_excl_iva"
ROLE_AMOUNT = "amount"
ROLE_QUANTITY = "quantity"
ROLE_LOCATION_LABEL = "location_label"
ROLE_SUBTOTAL = "subtotal"
ROLE_TOTAL = "total"

_ROLE_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    (
        ROLE_UNIT_PRICE_IVA_INCLUDED,
        re.compile(
            r"(?i)(iva\s*incl|i\.v\.a\.?\s*incl|con\s*iva|costo\s*por\s*elemento|precio\s*unitario\s*iva)"
        ),
    ),
    (ROLE_UNIT_PRICE_EXCL_IVA, re.compile(r"(?i)(precio\s*unit|p\.?\s*u\.?|costo\s*unit|sin\s*iva)")),
    (ROLE_AMOUNT, re.compile(r"(?i)(importe|monto|subtotal\s*linea)")),
    (ROLE_QUANTITY, re.compile(r"(?i)(cantidad|elementos|num\.?\s*elementos)")),
    (ROLE_LOCATION_LABEL, re.compile(r"(?i)(localidad|ubicaci[oó]n|municipio|ciudad|zona)")),
    (ROLE_SUBTOTAL, re.compile(r"(?i)(tarifa\s*mensual|costo\s*mensual|subtotal)")),
    (ROLE_TOTAL, re.compile(r"(?i)(costo\s*total|total\s*general)")),
]


def normalize_header_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def detect_column_role(header: Any) -> Optional[str]:
    """Mapea texto de encabezado a rol canónico."""
    norm = normalize_header_text(header)
    if not norm:
        return None
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(norm):
            return role
    if "costo" in norm or "precio" in norm:
        return ROLE_UNIT_PRICE_EXCL_IVA
    return None


def map_header_row_to_roles(headers: List[Any]) -> Dict[int, str]:
    """``col_index -> role`` para una fila de encabezados."""
    out: Dict[int, str] = {}
    for idx, h in enumerate(headers):
        role = detect_column_role(h)
        if role:
            out[idx] = role
    return out


def human_role_label(role: str) -> str:
    labels = {
        ROLE_UNIT_PRICE_IVA_INCLUDED: "costo por elemento (IVA incluido)",
        ROLE_UNIT_PRICE_EXCL_IVA: "precio unitario (sin IVA)",
        ROLE_AMOUNT: "importe",
        ROLE_QUANTITY: "cantidad",
        ROLE_LOCATION_LABEL: "ubicación",
        ROLE_SUBTOTAL: "subtotal",
        ROLE_TOTAL: "total",
    }
    return labels.get(role, role.replace("_", " "))
