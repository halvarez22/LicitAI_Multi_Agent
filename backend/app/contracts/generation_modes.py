"""
Modos de generación desacoplados (F2 / REQ-1).

Valores canónicos: ``full`` | ``technical`` | ``economic``.
"""

from __future__ import annotations

from enum import Enum


class GenerationMode(str, Enum):
    """Modo explícito de generación documental."""

    FULL = "full"
    TECHNICAL = "technical"
    ECONOMIC = "economic"

    @classmethod
    def values(cls) -> frozenset[str]:
        return frozenset(m.value for m in cls)
