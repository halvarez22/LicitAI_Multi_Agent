"""Motor de plantillas legales con verificación de integridad determinista."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class TemplateIntegrityError(Exception):
    """Error cuando el texto legal renderizado no conserva integridad."""


class LegalTemplateEngine:
    """Renderiza plantillas legales Jinja2 y valida integridad del texto estático."""

    def __init__(self, templates_dir: Path | None = None):
        base_dir = templates_dir or (Path(__file__).resolve().parents[1] / "templates" / "legal")
        self.templates_dir = base_dir
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=False,
            lstrip_blocks=False,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _static_blocks(template_text: str) -> List[str]:
        parts = re.split(r"\{\{.*?\}\}", template_text, flags=re.DOTALL)
        blocks = []
        for part in parts:
            norm = LegalTemplateEngine._normalize_text(part)
            if norm:
                blocks.append(norm)
        return blocks

    def _template_text(self, template_id: str) -> str:
        path = self.templates_dir / f"{template_id}.j2"
        return path.read_text(encoding="utf-8")

    def render(self, template_id: str, data: Dict[str, Any]) -> str:
        """Renderiza plantilla legal con datos dinámicos validados por Jinja2."""
        template = self.env.get_template(f"{template_id}.j2")
        return template.render(**data)

    def verify_integrity(self, rendered_text: str, template_id: str) -> bool:
        """Valida que los bloques estáticos del template estén intactos en el render."""
        template_text = self._template_text(template_id)
        static_blocks = self._static_blocks(template_text)
        rendered_norm = self._normalize_text(rendered_text)
        for block in static_blocks:
            if block not in rendered_norm:
                return False
        return True

    def static_hash(self, template_id: str) -> str:
        """Hash SHA256 de los bloques estáticos concatenados del template."""
        template_text = self._template_text(template_id)
        joined = "\n".join(self._static_blocks(template_text))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()
