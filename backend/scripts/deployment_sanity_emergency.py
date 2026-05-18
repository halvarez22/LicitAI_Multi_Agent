#!/usr/bin/env python3
"""
Sanidad de despliegue (evidencia reproducible): flag de bloques + filtros económicos documentales.

Ejecutar en el host (con venv) o dentro del contenedor backend, desde /app:

    python scripts/deployment_sanity_emergency.py
"""
from __future__ import annotations

import os
import sys

# Raíz backend en PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from app.config.settings import settings
    from app.services.economic_cotization_filters import (
        _HARD_DOC_PATTERNS,
        is_contaminated_economic_pending_question,
    )

    print("=== LicitAI — deployment_sanity_emergency ===")
    print(f"ENABLE_BLOCK_RESOLUTION (settings): {settings.ENABLE_BLOCK_RESOLUTION}")
    print(f"BLOCK_RESOLUTION_MIN_ITEMS: {settings.BLOCK_RESOLUTION_MIN_ITEMS}")
    print(f"Env LICITAI_ENABLE_BLOCK_RESOLUTION raw: {os.environ.get('LICITAI_ENABLE_BLOCK_RESOLUTION', '<no definida>')}")

    phrase = "Escrito bajo protesta de decir verdad"
    m = _HARD_DOC_PATTERNS.search(phrase)
    print(f"_HARD_DOC_PATTERNS match on «{phrase}»: {bool(m)} (fragmento: {m.group(0) if m else None})")

    q = {"type": "economic_price", "label": f"Precio de: {phrase}"}
    contaminated = is_contaminated_economic_pending_question(q)
    print(f"is_contaminated_economic_pending_question (pending simulado): {contaminated}")

    ok = (
        settings.ENABLE_BLOCK_RESOLUTION is True
        and m is not None
        and contaminated is True
    )
    if not ok:
        print("\nFALLO: revisa variables de entorno y versión del código montada en el contenedor.")
        return 1
    print("\nOK: flag True, filtro duro activo, pending documental detectado como contaminado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
