"""
Servicio de traducción de validaciones técnicas a UX humano.

Carga reglas desde `app/contracts/validation_mapping.json` y permite:
- resolver metadata por `error_type`
- renderizar plantillas con contexto
- generar `validation_event` listo para frontend
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class ValidationMappingService:
    """Servicio liviano para mapear errores técnicos a payload UX."""

    def __init__(self, mapping_path: Optional[Path] = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self._mapping_path = mapping_path or (base_dir / "contracts" / "validation_mapping.json")
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            payload = json.loads(self._mapping_path.read_text(encoding="utf-8"))
            rules = payload.get("validation_rules") or []
            if isinstance(rules, list):
                self._rules = {
                    str(rule.get("error_type")): rule
                    for rule in rules
                    if isinstance(rule, dict) and rule.get("error_type")
                }
        except Exception:
            self._rules = {}

    def get_rule(self, error_type: str) -> Optional[Dict[str, Any]]:
        """Obtiene la regla de mapeo para un `error_type`."""
        self._load()
        return self._rules.get(error_type)

    @staticmethod
    def _render_template(text: str, context: Dict[str, Any]) -> str:
        if not isinstance(text, str) or "{{" not in text:
            return text
        out = text
        for k, v in context.items():
            out = out.replace(f"{{{{{k}}}}}", str(v))
        return out

    def build_event(
        self,
        *,
        error_type: str,
        context: Optional[Dict[str, Any]] = None,
        raw_message: str = "",
        policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Construye evento de validación para frontend.

        Si no existe regla, devuelve fallback minimalista y no rompe flujo.
        """
        rule = self.get_rule(error_type)
        ctx = context or {}
        policy = policy or {}

        if not rule:
            return {
                "error_type": error_type,
                "severity": "warn",
                "context": ctx,
                "ux": {
                    "title": "Validación pendiente",
                    "user_message": raw_message or f"Se detectó una validación: {error_type}",
                    "primary_action": {"label": "Revisar", "type": "navigate"},
                    "impact": "Puede requerir ajuste antes de finalizar.",
                },
                "meta": {
                    "mapping_found": False,
                    "raw_message": raw_message,
                },
            }

        severity = str(rule.get("severity") or "warn")
        ux = rule.get("ux") or {}
        skip_allowed = bool(policy.get("allow_skip_with_justification")) and bool(
            (ux.get("secondary_action") or {}).get("skip_condition") == "allow_skip_with_justification"
        )
        if severity == "block" and skip_allowed:
            severity = "warn"

        user_message = self._render_template(str(ux.get("user_message") or ""), ctx)
        title = self._render_template(str(ux.get("title") or ""), ctx)
        impact = self._render_template(str(ux.get("impact") or ""), ctx)

        primary = dict(ux.get("primary_action") or {})
        secondary = dict(ux.get("secondary_action") or {})
        if primary.get("target"):
            primary["target"] = self._render_template(str(primary["target"]), ctx)
        if secondary.get("target"):
            secondary["target"] = self._render_template(str(secondary["target"]), ctx)

        event: Dict[str, Any] = {
            "error_type": error_type,
            "severity": severity,
            "context": ctx,
            "ux": {
                "title": title,
                "user_message": user_message,
                "primary_action": primary,
                "impact": impact,
            },
            "meta": {
                "mapping_found": True,
                "raw_message": raw_message,
            },
        }
        if secondary:
            event["ux"]["secondary_action"] = secondary
        return event


validation_mapping_service = ValidationMappingService()

