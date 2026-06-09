"""Cálculo de propuesta económica de obra pública (directos + indirectos + utilidad + IVA)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

_MONEY_Q = Decimal("0.01")


def compute_obra_publica_totals(
    costos_directos: Decimal,
    *,
    indirectos_rate: Decimal = Decimal("0.10"),
    utilidad_rate: Decimal = Decimal("0.05"),
    iva_rate: Decimal = Decimal("0.16"),
) -> Dict[str, Any]:
    """
    Aplica la cadena típica de catálogo de obra:
    indirectos sobre directos; utilidad sobre (directos + indirectos); IVA sobre subtotal.
    """
    directos = costos_directos.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    indirectos = (directos * indirectos_rate).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    base_utilidad = directos + indirectos
    utilidad = (base_utilidad * utilidad_rate).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    subtotal_antes_iva = (directos + indirectos + utilidad).quantize(
        _MONEY_Q, rounding=ROUND_HALF_UP
    )
    iva_amount = (subtotal_antes_iva * iva_rate).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    grand_total = (subtotal_antes_iva + iva_amount).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    return {
        "costos_directos": float(directos),
        "costos_indirectos": float(indirectos),
        "utilidad": float(utilidad),
        "indirectos_rate": float(indirectos_rate),
        "utilidad_rate": float(utilidad_rate),
        "subtotal_antes_iva": float(subtotal_antes_iva),
        "iva_amount": float(iva_amount),
        "total_base": float(subtotal_antes_iva),
        "grand_total": float(grand_total),
    }
