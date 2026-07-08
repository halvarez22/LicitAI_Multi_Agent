"""Tests de cobertura de empaquetado en vista de entrega (F3.4)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.output_delivery_view import build_delivery_structure


def test_inventory_includes_partial_packaging_coverage(tmp_path: Path) -> None:
    root = tmp_path / "sess-partial"
    validated = root / "_compranet_validated" / "SobreEconomica"
    validated.mkdir(parents=True)
    (validated / "01_anexo.xlsx").write_bytes(b"xlsx")
    manifest = {
        "coverage_status": "partial",
        "sobres_present": ["SobreEconomica"],
        "sobres_missing": ["SobreComplementaria", "SobreTecnica"],
        "partial_note": "Expediente parcial",
        "files": [],
    }
    (root / "_compranet_validated" / "MANIFIESTO_SHA256.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    _structure, inventory = build_delivery_structure(str(root))
    assert inventory.get("packaging_coverage_status") == "partial"
    assert "SobreEconomica" in (inventory.get("packaging_sobres_present") or [])
