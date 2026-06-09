from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List

from app.economic_validation.formulas.obra_publica_v1 import compute_obra_publica_totals
from app.economic_validation.profiles import detect_profile, get_profile
from app.economic_validation.formulas.salario_real_v1 import compute_fsr

_MONEY_Q = Decimal("0.01")


class EconomicCalculatorEngine:
    """
    Motor determinista para cálculo económico y cuadratura contra Excel.

    Entradas:
    - `proposal_items`: ítems de propuesta (mapeados por LLM + overrides aplicados).
    - `reglas_economicas`: reglas extraídas de bases.
    - `session_line_items`: renglones tabulares capturados en sesión.

    Salidas:
    - Ítems normalizados monetariamente.
    - Totales fiscales por perfil (IVA).
    - Reporte de cuadratura (engine vs Excel).
    """

    def _to_decimal_money(self, value: Any, default: str = "0.00") -> Decimal:
        try:
            if isinstance(value, Decimal):
                dec = value
            elif isinstance(value, str):
                dec = Decimal(value.replace(",", "").strip())
            else:
                dec = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            dec = Decimal(default)
        return dec.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

    def _to_decimal_qty(self, value: Any, default: str = "1") -> Decimal:
        try:
            if value in (None, ""):
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(default)

    def _norm_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _extract_obra_rates(
        self, reglas_economicas: Dict[str, str], profile: Dict[str, Any]
    ) -> tuple[Decimal, Decimal]:
        """Lee % de indirectos/utilidad del catálogo o bases; perfil como fallback."""
        blob = " ".join(str(v or "") for v in (reglas_economicas or {}).values()).lower()
        ind_rate = Decimal(str(profile.get("indirectos_rate", 0.10)))
        util_rate = Decimal(str(profile.get("utilidad_rate", 0.05)))
        m_ind = re.search(r"indirectos?\s*[\(\[]?\s*(\d{1,2}(?:\.\d+)?)\s*%", blob)
        m_util = re.search(r"utilidad\s*[\(\[]?\s*(\d{1,2}(?:\.\d+)?)\s*%", blob)
        if m_ind:
            try:
                ind_rate = Decimal(m_ind.group(1)) / Decimal("100")
            except (InvalidOperation, ValueError):
                pass
        if m_util:
            try:
                util_rate = Decimal(m_util.group(1)) / Decimal("100")
            except (InvalidOperation, ValueError):
                pass
        return ind_rate, util_rate

    def _extract_fsr_params(self, reglas_economicas: Dict[str, str]) -> Dict[str, Any]:
        """
        Extrae parámetros FSR desde texto de reglas.
        Formato esperado (flexible): "imss=0.245, sar=0.02, ...".
        """
        blob = " ".join(str(v or "") for v in (reglas_economicas or {}).values())
        out: Dict[str, Any] = {}
        for key in (
            "imss",
            "sar",
            "infonavit",
            "dias_no_laborados",
            "dias_laborados",
            "prima_vacacional",
            "aguinaldo_dias",
        ):
            m = re.search(rf"{key}\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", blob, flags=re.I)
            if m:
                out[key] = m.group(1)
            else:
                # Fallback de Ley Mexicana para evitar bloqueos en parámetros secundarios
                law_defaults = {
                    "sar": "0.02",
                    "infonavit": "0.05",
                    "prima_vacacional": "0.25",
                    "dias_laborados": "365",
                    "dias_no_laborados": "0"
                }
                if key in law_defaults:
                    out[key] = law_defaults[key]
        return out

    def normalize_items(self, proposal_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Recalcula `subtotal` por línea usando Decimal; no confía en subtotales previos."""
        out: List[Dict[str, Any]] = []
        for item in proposal_items or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            qty = self._to_decimal_qty(row.get("cantidad", 1), default="1")
            if qty < 0:
                qty = Decimal("0")
            price = self._to_decimal_money(row.get("precio_unitario", 0.0))
            subtotal = (qty * price).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
            row["cantidad"] = float(qty)
            row["precio_unitario"] = float(price)
            row["subtotal"] = float(subtotal)
            out.append(row)
        return out

    def compute_totals(
        self,
        proposal_items: List[Dict[str, Any]],
        reglas_economicas: Dict[str, str],
        session_name: str,
    ) -> Dict[str, Any]:
        """Calcula total base y total con IVA del perfil detectado."""
        total_base = Decimal("0.00")
        for item in proposal_items or []:
            if not isinstance(item, dict):
                continue
            total_base += self._to_decimal_money(item.get("subtotal", 0.0))
        
        # --- HITO: Respeto a la Autoridad del Usuario ---
        # Si existe un override explícito del subtotal en las reglas (vía chat), lo usamos.
        for k, v in (reglas_economicas or {}).items():
            if "chat_override_subtotal_propuesta" in k:
                val_override = str(v).split(":", 1)[-1].strip()
                total_base = self._to_decimal_money(val_override)
                break

        costos_directos = total_base.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

        profile_name = detect_profile(reglas_economicas or {}, session_name=session_name)
        profile = get_profile(profile_name)
        iva_rate = self._to_decimal_money(profile.get("iva_rate", 0.16), default="0.16")
        formula_set = str(profile.get("formula_set") or "")
        obra_breakdown: Dict[str, Any] = {}
        if formula_set == "obra_publica_v1" and costos_directos > 0:
            ind_rate, util_rate = self._extract_obra_rates(reglas_economicas or {}, profile)
            obra_breakdown = compute_obra_publica_totals(
                costos_directos,
                indirectos_rate=ind_rate,
                utilidad_rate=util_rate,
                iva_rate=iva_rate,
            )
            total_base = self._to_decimal_money(obra_breakdown.get("subtotal_antes_iva", 0.0))
            grand_total = self._to_decimal_money(obra_breakdown.get("grand_total", 0.0))
        else:
            total_base = costos_directos
            grand_total = (total_base * (Decimal("1.00") + iva_rate)).quantize(
                _MONEY_Q, rounding=ROUND_HALF_UP
            )
        fsr_payload: Dict[str, Any] = {}
        blocking_issues: List[str] = []
        if formula_set == "salario_real_v1" and bool(profile.get("fsr_required")):
            fsr_params = self._extract_fsr_params(reglas_economicas or {})
            fsr_result = compute_fsr(fsr_params)
            fsr_payload = fsr_result
            if not bool(fsr_result.get("ok")):
                missing = ", ".join(fsr_result.get("missing_params") or [])
                blocking_issues.append(
                    f"fsr_required_params_missing: Faltan parámetros FSR ({missing})."
                )
        out: Dict[str, Any] = {
            "profile_name": profile_name,
            "iva_rate": float(iva_rate),
            "costos_directos": float(costos_directos),
            "total_base": float(total_base),
            "grand_total": float(grand_total),
            "formula_set": formula_set or "generic_v1",
            "fsr": fsr_payload,
            "blocking_issues": blocking_issues,
        }
        if obra_breakdown:
            out.update(obra_breakdown)
        return out

    def build_quadrature_report(
        self,
        proposal_items: List[Dict[str, Any]],
        session_line_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Compara total de motor vs total de Excel/sesión.

        Regla:
        - `blocking=True` si `abs(delta_total) > 0.01`.
        """
        if not session_line_items:
            return {
                "available": False,
                "engine_total": 0.0,
                "excel_total": 0.0,
                "delta_total": 0.0,
                "blocking": False,
                "line_deltas": [],
            }

        engine_total = Decimal("0.00")
        engine_by_concept: Dict[str, Decimal] = {}
        for item in proposal_items or []:
            if not isinstance(item, dict):
                continue
            st = self._to_decimal_money(item.get("subtotal", 0.0))
            engine_total += st
            key = self._norm_text(item.get("concepto") or item.get("descripcion") or "")
            if key:
                engine_by_concept[key] = engine_by_concept.get(key, Decimal("0.00")) + st
        engine_total = engine_total.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

        excel_total = Decimal("0.00")
        line_deltas: List[Dict[str, Any]] = []
        for row in session_line_items or []:
            if not isinstance(row, dict):
                continue
            if row.get("subtotal") is not None:
                row_total = self._to_decimal_money(row.get("subtotal"))
            elif row.get("importe") is not None:
                row_total = self._to_decimal_money(row.get("importe"))
            else:
                qty = self._to_decimal_qty(row.get("cantidad", 1), default="1")
                pu = self._to_decimal_money(row.get("precio_unitario", 0.0))
                row_total = (qty * pu).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
            excel_total += row_total

            norm_key = self._norm_text(row.get("concepto_norm") or row.get("concepto_raw") or "")
            if not norm_key:
                continue
            engine_line = engine_by_concept.get(norm_key, Decimal("0.00"))
            delta_line = (engine_line - row_total).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
            if abs(delta_line) > Decimal("0.01"):
                line_deltas.append(
                    {
                        "concepto": str(row.get("concepto_raw") or row.get("concepto_norm") or "")[:220],
                        "excel_subtotal": float(row_total),
                        "engine_subtotal": float(engine_line),
                        "delta": float(delta_line),
                    }
                )
        excel_total = excel_total.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        delta_total = (engine_total - excel_total).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        return {
            "available": True,
            "engine_total": float(engine_total),
            "excel_total": float(excel_total),
            "delta_total": float(delta_total),
            "blocking": abs(delta_total) > Decimal("0.01"),
            "line_deltas": line_deltas[:50],
        }
