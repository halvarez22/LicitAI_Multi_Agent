from __future__ import annotations

import re
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from app.economic_validation.models import EconomicValidationItem, EconomicValidationResult
from app.economic_validation.profiles import detect_profile, get_profile


_MONEY_RE = re.compile(r"(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)")


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v)
    except Exception:
        return default


def _extract_first_amount(text: str) -> Optional[float]:
    if not isinstance(text, str):
        return None
    m = _MONEY_RE.search(text.replace("$", "").replace("MXN", ""))
    if not m:
        return None
    return _to_float(m.group(1), default=None)  # type: ignore[arg-type]


def _extract_first_int(text: str) -> Optional[int]:
    if not isinstance(text, str):
        return None
    m = re.search(r"\b(\d{1,3})\b", text)
    if not m:
        return None
    return int(m.group(1))


def _add(
    out: EconomicValidationResult,
    *,
    regla: str,
    estado: str,
    evidencia: str,
    severidad: int = 1,
    fuente: str = "",
    formula: str = "",
    valor: Any = None,
) -> None:
    out.validations.append(
        EconomicValidationItem(
            regla=regla, estado=estado, evidencia=evidencia, severidad=severidad
        )
    )
    out.trazabilidad[regla] = {
        "fuente": fuente,
        "formula": formula,
        "valor_calculado": valor,
    }
    if estado == "blocking":
        out.blocking_issues.append(f"{regla}: {evidencia}")
    elif estado == "warn":
        out.alerts.append(f"{regla}: {evidencia}")


def validate_economic_proposal(
    *,
    proposal_items: List[Dict[str, Any]],
    currency: str,
    total_base: float,
    grand_total: float,
    reglas_economicas: Dict[str, str],
    session_name: str = "",
) -> EconomicValidationResult:
    profile_name = detect_profile(reglas_economicas or {}, session_name=session_name)
    profile = get_profile(profile_name)
    out = EconomicValidationResult(perfil_usado=profile_name)

    # 1) Precios nulos/negativos
    bad_prices = []
    for it in proposal_items or []:
        pu = _to_float(it.get("precio_unitario"), default=-1.0)
        if pu <= 0:
            bad_prices.append(str(it.get("concepto") or it.get("descripcion") or "ítem"))
    if bad_prices:
        _add(
            out,
            regla="precios_positivos",
            estado="blocking",
            evidencia=f"{len(bad_prices)} ítems con precio <= 0",
            severidad=3,
            fuente="proposal_items",
            formula="precio_unitario > 0",
            valor=bad_prices[:8],
        )
    else:
        _add(
            out,
            regla="precios_positivos",
            estado="ok",
            evidencia="Todos los ítems tienen precio unitario positivo.",
            fuente="proposal_items",
            formula="precio_unitario > 0",
            valor=True,
        )

    # 2) Consistencia subtotal por ítem
    mismatches = 0
    for it in proposal_items or []:
        qty = _to_float(it.get("cantidad"), 1.0)
        pu = _to_float(it.get("precio_unitario"), 0.0)
        st = _to_float(it.get("subtotal"), qty * pu)
        if abs((qty * pu) - st) > 0.01:
            mismatches += 1
    if mismatches:
        _add(
            out,
            regla="consistencia_subtotales",
            estado="warn",
            evidencia=f"{mismatches} ítems con subtotal inconsistente.",
            severidad=2,
            fuente="proposal_items",
            formula="subtotal ≈ cantidad * precio_unitario",
            valor={"mismatches": mismatches},
        )
    else:
        _add(
            out,
            regla="consistencia_subtotales",
            estado="ok",
            evidencia="Subtotales consistentes.",
            fuente="proposal_items",
            formula="subtotal ≈ cantidad * precio_unitario",
            valor=True,
        )

    # 3) IVA / total esperado (sobre total_base)
    iva_rate = _to_float(profile.get("iva_rate"), 0.16)
    expected_grand = round(total_base * (1.0 + iva_rate), 2)
    if abs(expected_grand - grand_total) > 0.05:
        _add(
            out,
            regla="consistencia_total_iva",
            estado="warn",
            evidencia=(
                f"Total esperado con IVA {iva_rate:.2f}: {expected_grand:.2f} "
                f"vs grand_total={grand_total:.2f}"
            ),
            severidad=2,
            fuente="proposal_totals",
            formula="grand_total ≈ total_base * (1 + iva_rate)",
            valor={"expected": expected_grand, "actual": grand_total, "currency": currency},
        )
    else:
        _add(
            out,
            regla="consistencia_total_iva",
            estado="ok",
            evidencia="Total coherente con IVA configurado.",
            fuente="proposal_totals",
            formula="grand_total ≈ total_base * (1 + iva_rate)",
            valor=True,
        )

    # 4) Reglas de importes min/max desde bases (si vienen en texto)
    min_text = (reglas_economicas or {}).get("criterio_importe_minimo_o_plazo_inferior", "")
    max_text = (reglas_economicas or {}).get("criterio_importe_maximo_o_plazo_superior", "")
    min_amt = _extract_first_amount(min_text)
    max_amt = _extract_first_amount(max_text)
    if min_amt is not None and total_base < min_amt:
        _add(
            out,
            regla="importe_minimo",
            estado="warn",
            evidencia=f"total_base {total_base:.2f} menor al mínimo {min_amt:.2f}",
            severidad=2,
            fuente="reglas_economicas.criterio_importe_minimo_o_plazo_inferior",
            formula="total_base >= importe_minimo",
            valor={"minimo": min_amt, "total_base": total_base},
        )
    elif min_amt is not None:
        _add(
            out,
            regla="importe_minimo",
            estado="ok",
            evidencia="Total base cumple importe mínimo detectado.",
            fuente="reglas_economicas.criterio_importe_minimo_o_plazo_inferior",
            formula="total_base >= importe_minimo",
            valor={"minimo": min_amt, "total_base": total_base},
        )

    if max_amt is not None and total_base > max_amt:
        _add(
            out,
            regla="importe_maximo",
            estado="warn",
            evidencia=f"total_base {total_base:.2f} excede máximo {max_amt:.2f}",
            severidad=2,
            fuente="reglas_economicas.criterio_importe_maximo_o_plazo_superior",
            formula="total_base <= importe_maximo",
            valor={"maximo": max_amt, "total_base": total_base},
        )
    elif max_amt is not None:
        _add(
            out,
            regla="importe_maximo",
            estado="ok",
            evidencia="Total base no excede importe máximo detectado.",
            fuente="reglas_economicas.criterio_importe_maximo_o_plazo_superior",
            formula="total_base <= importe_maximo",
            valor={"maximo": max_amt, "total_base": total_base},
        )

    # 5) Meses mínimo/máximo (coherencia)
    min_m_text = (reglas_economicas or {}).get("meses_o_periodo_minimo_citado", "")
    max_m_text = (reglas_economicas or {}).get("meses_o_periodo_maximo_citado", "")
    min_m = _extract_first_int(min_m_text) or profile.get("min_months")
    max_m = _extract_first_int(max_m_text) or profile.get("max_months")
    if min_m and max_m and int(min_m) > int(max_m):
        _add(
            out,
            regla="coherencia_meses_min_max",
            estado="blocking",
            evidencia=f"Meses mínimos ({min_m}) mayor que máximos ({max_m}).",
            severidad=3,
            fuente="reglas_economicas.meses",
            formula="meses_min <= meses_max",
            valor={"meses_min": min_m, "meses_max": max_m},
        )
    elif min_m or max_m:
        _add(
            out,
            regla="coherencia_meses_min_max",
            estado="ok",
            evidencia="Rango de meses sin conflicto detectado.",
            fuente="reglas_economicas.meses",
            formula="meses_min <= meses_max",
            valor={"meses_min": min_m, "meses_max": max_m},
        )

    # 6) Precio desproporcionado
    thr = _to_float(profile.get("desproporcion_threshold"), 0.35)
    prices = [
        _to_float(it.get("precio_unitario"), 0.0)
        for it in (proposal_items or [])
        if _to_float(it.get("precio_unitario"), 0.0) > 0
    ]
    if len(prices) >= 3:
        m = mean(prices)
        outliers = [p for p in prices if abs(p - m) / m > thr] if m > 0 else []
        if outliers:
            _add(
                out,
                regla="precio_desproporcionado",
                estado="warn",
                evidencia=f"{len(outliers)} precios podrían ser desproporcionados (> {thr:.2f} de desviación).",
                severidad=2,
                fuente="proposal_items",
                formula="abs(p-mean)/mean <= threshold",
                valor={"mean": m, "threshold": thr, "outliers": outliers[:8]},
            )
        else:
            _add(
                out,
                regla="precio_desproporcionado",
                estado="ok",
                evidencia="No se detectaron outliers de precio con el umbral del perfil.",
                fuente="proposal_items",
                formula="abs(p-mean)/mean <= threshold",
                valor={"mean": m, "threshold": thr},
            )
    else:
        _add(
            out,
            regla="precio_desproporcionado",
            estado="warn",
            evidencia="Muestra insuficiente para evaluar desproporción (mínimo 3 precios).",
            severidad=1,
            fuente="proposal_items",
            formula="n_pricios >= 3",
            valor={"count": len(prices)},
        )

    # 7) PPE (si perfil lo habilita y hay datos)
    if bool(profile.get("ppe_formula")):
        ot = (reglas_economicas or {}).get("otras_reglas_oferta_precio", "") or ""
        m_mpemb = re.search(r"mpemb\s*[:=]\s*([0-9.,]+)", ot, flags=re.I)
        m_mpi = re.search(r"mpi\s*[:=]\s*([0-9.,]+)", ot, flags=re.I)
        mpemb = _to_float(m_mpemb.group(1), 0.0) if m_mpemb else 0.0
        mpi = _to_float(m_mpi.group(1), 0.0) if m_mpi else 0.0
        if mpemb > 0 and mpi > 0:
            ppe = round((mpemb * 40.0) / mpi, 4)
            _add(
                out,
                regla="ppe_formula",
                estado="ok",
                evidencia=f"PPE calculado={ppe:.4f}",
                fuente="reglas_economicas.otras_reglas_oferta_precio",
                formula="PPE = MPemb * 40 / MPi",
                valor={"mpemb": mpemb, "mpi": mpi, "ppe": ppe},
            )
        else:
            _add(
                out,
                regla="ppe_formula",
                estado="warn",
                evidencia="No hay datos suficientes para PPE (MPemb/MPi).",
                severidad=1,
                fuente="reglas_economicas.otras_reglas_oferta_precio",
                formula="PPE = MPemb * 40 / MPi",
                valor={"mpemb": mpemb, "mpi": mpi},
            )

    return out
