"""ComplianceGate determinista para reglas 12.1."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from app.core.disqualification_rules import DisqualificationRule, get_disqualification_rules


@dataclass
class ComplianceGateResult:
    """Resultado del gate de cumplimiento determinista."""

    is_blocking: bool
    failed_rules: List[str]
    warnings: List[Dict[str, Any]]
    evidence: Dict[str, Any]
    timestamp: str


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _string_blob(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_string_blob(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_string_blob(v) for v in value)
    return str(value) if value is not None else ""


class ComplianceGate:
    """Evalúa reglas 12.1 sin LLM y con trazabilidad de evidencia."""

    def __init__(self, rules: Optional[List[DisqualificationRule]] = None):
        self.rules = rules or get_disqualification_rules()

    def _eval_rule(self, rule: DisqualificationRule, session_data: Dict[str, Any]) -> Dict[str, Any]:
        evidence_value = _dig(session_data, rule.evidence_path)
        evidence_text = _string_blob(evidence_value)
        result: Dict[str, Any] = {
            "code": rule.code,
            "description": rule.description,
            "evidence_path": rule.evidence_path,
            "regex_pattern": rule.regex_pattern,
            "decision": "pass",
            "reason": "",
        }

        # Reglas con fuente externa: advertencia, no bloqueo automático.
        if rule.code in {"12.1.I", "12.1.L", "12.1.M", "12.1.O"}:
            result["decision"] = "warn"
            result["reason"] = "Requiere verificación externa/manual."
            return result

        if rule.code == "12.1.C":
            currency = str(_dig(session_data, "economic.data.currency") or "").upper()
            if currency and currency != "MXN":
                result["decision"] = "block"
                result["reason"] = f"Moneda detectada no permitida: {currency}."
            elif not currency:
                result["decision"] = "warn"
                result["reason"] = "No se detectó moneda explícita."
            return result

        if rule.code == "12.1.D":
            lang = str(_dig(session_data, "analysis.data.propuesta.idioma") or "").lower()
            if lang and "espa" not in lang:
                result["decision"] = "block"
                result["reason"] = f"Idioma detectado no permitido: {lang}."
            elif not lang:
                result["decision"] = "warn"
                result["reason"] = "No se detectó idioma explícito."
            return result

        if rule.code == "12.1.H":
            if not re.search(rule.regex_pattern or "", evidence_text):
                result["decision"] = "warn"
                result["reason"] = "No se detectó la frase 'bajo protesta de decir verdad'."
            return result

        if rule.code == "12.1.N":
            items = _dig(session_data, "economic.data.items") or []
            seen: Dict[str, int] = {}
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("concepto_id") or item.get("partida") or "").strip()
                if not key:
                    continue
                seen[key] = seen.get(key, 0) + 1
            dups = [k for k, v in seen.items() if v > 1]
            if dups:
                result["decision"] = "block"
                result["reason"] = f"Partidas duplicadas detectadas: {dups[:5]}."
            return result

        if rule.code == "12.1.Q":
            validations = _dig(session_data, "economic.data.validation_result.validations") or []
            if isinstance(validations, list):
                for item in validations:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("estado", "")).lower() == "blocking":
                        result["decision"] = "block"
                        result["reason"] = f"Validación económica en blocking: {item.get('regla', 'sin_regla')}."
                        return result
            return result

        if rule.code == "12.1.R":
            delivered = _dig(session_data, "analysis.data.muestras_entregadas")
            if delivered is False:
                result["decision"] = "block"
                result["reason"] = "Muestras marcadas como no entregadas."
            elif delivered is None:
                result["decision"] = "warn"
                result["reason"] = "No hay evidencia estructurada de entrega de muestras."
            return result

        # Reglas textuales deterministas por regex.
        if rule.regex_pattern and re.search(rule.regex_pattern, evidence_text):
            result["decision"] = "block"
            result["reason"] = "Patrón de descalificación detectado en evidencia."
            return result

        # Regla A/P: cobertura mínima de listas de compliance.
        if rule.code in {"12.1.A", "12.1.P"}:
            comp_data = _dig(session_data, "compliance.data") or {}
            total = 0
            if isinstance(comp_data, dict):
                for k in ("administrativo", "tecnico", "formatos"):
                    v = comp_data.get(k)
                    if isinstance(v, list):
                        total += len(v)
            if total == 0:
                result["decision"] = "block"
                result["reason"] = "No hay requisitos de compliance para validar apego a bases."
            return result

        # F/K/J/G: si no hay evidencia, advertir; si hay evidencia negativa textual, bloquear.
        if not evidence_text.strip():
            result["decision"] = "warn"
            result["reason"] = "Sin evidencia estructurada para evaluación determinista."
            return result
        return result

    def evaluate(self, session_data: Dict[str, Any]) -> ComplianceGateResult:
        """Evalúa reglas 12.1 contra datos reales de sesión."""
        failed_rules: List[str] = []
        warnings: List[Dict[str, Any]] = []
        evidence: Dict[str, Any] = {"rules": []}

        for rule in self.rules:
            item = self._eval_rule(rule, session_data)
            evidence["rules"].append(item)
            if item["decision"] == "block":
                failed_rules.append(rule.code)
            elif item["decision"] == "warn":
                warnings.append({"code": rule.code, "reason": item["reason"]})

        return ComplianceGateResult(
            is_blocking=bool(failed_rules),
            failed_rules=failed_rules,
            warnings=warnings,
            evidence=evidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def to_dict(result: ComplianceGateResult) -> Dict[str, Any]:
        """Serializa `ComplianceGateResult` a diccionario JSON-friendly."""
        return asdict(result)
