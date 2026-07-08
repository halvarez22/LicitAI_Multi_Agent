"""
Alcances canónicos de descarga post-generación (F5 / REQ-3).

Valores: ``technical`` | ``economic`` | ``full``.
"""

from __future__ import annotations

from enum import Enum


class DeliveryScope(str, Enum):
    """Alcance de artefactos descargables tras generación desacoplada."""

    TECHNICAL = "technical"
    ECONOMIC = "economic"
    FULL = "full"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(m.value for m in cls)
