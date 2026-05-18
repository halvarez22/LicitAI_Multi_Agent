from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List

_Q4 = Decimal("0.0001")

_REQUIRED_KEYS = (
    "imss",
    "sar",
    "infonavit",
    "dias_no_laborados",
    "dias_laborados",
    "prima_vacacional",
    "aguinaldo_dias",
)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if isinstance(value, str):
            return Decimal(value.replace(",", "").strip())
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def validate_required_params(params: Dict[str, Any]) -> List[str]:
    """Devuelve la lista de parámetros faltantes para cálculo FSR."""
    missing: List[str] = []
    for key in _REQUIRED_KEYS:
        if key not in params:
            missing.append(key)
            continue
        val = _to_decimal(params.get(key), default="-1")
        if val < 0:
            missing.append(key)
    return missing


def compute_fsr(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calcula un FSR aproximado de anexos sector salud de forma determinista.

    Fórmula operativa versionada (v1):
    - carga_social = imss + sar + infonavit
    - factor_dias = dias_laborados / (dias_laborados - dias_no_laborados)
    - prestaciones = (prima_vacacional + aguinaldo_dias) / 365
    - fsr = (1 + carga_social) * factor_dias * (1 + prestaciones)
    """
    missing = validate_required_params(params)
    if missing:
        return {
            "ok": False,
            "missing_params": missing,
            "formula_id": "salario_real_v1_fsr",
            "formula_version": "v1",
        }

    imss = _to_decimal(params["imss"])
    sar = _to_decimal(params["sar"])
    infonavit = _to_decimal(params["infonavit"])
    dnl = _to_decimal(params["dias_no_laborados"])
    dl = _to_decimal(params["dias_laborados"], default="365")
    pv = _to_decimal(params["prima_vacacional"])
    ag = _to_decimal(params["aguinaldo_dias"])

    denom = dl - dnl
    if denom <= 0:
        return {
            "ok": False,
            "missing_params": ["dias_laborados>días_no_laborados"],
            "formula_id": "salario_real_v1_fsr",
            "formula_version": "v1",
        }

    carga_social = imss + sar + infonavit
    factor_dias = dl / denom
    prestaciones = (pv + ag) / Decimal("365")
    fsr = ((Decimal("1") + carga_social) * factor_dias * (Decimal("1") + prestaciones)).quantize(
        _Q4, rounding=ROUND_HALF_UP
    )
    return {
        "ok": True,
        "formula_id": "salario_real_v1_fsr",
        "formula_version": "v1",
        "fsr": float(fsr),
        "inputs": {
            "imss": float(imss),
            "sar": float(sar),
            "infonavit": float(infonavit),
            "dias_no_laborados": float(dnl),
            "dias_laborados": float(dl),
            "prima_vacacional": float(pv),
            "aguinaldo_dias": float(ag),
        },
    }
