"""IO CSV para exportar e importar bloques de captura económica."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.contracts.interaction_block import InteractionBlock


_EXPORT_HEADERS = [
    "item_id",
    "label",
    "unit",
    "suggested_value",
    "value",
    "validation_rule",
    "example",
]

_VALUE_HEADERS = ("value", "valor", "precio", "price")


def interaction_block_to_csv_rows(block: InteractionBlock) -> List[Dict[str, str]]:
    """Serializa un ``InteractionBlock`` a filas CSV listas para captura humana."""
    rows: List[Dict[str, str]] = []
    for item in block.items:
        suggested = ""
        if item.suggested_value is not None:
            suggested = f"{float(item.suggested_value):.6f}".rstrip("0").rstrip(".")
        rows.append(
            {
                "item_id": item.item_id,
                "label": item.label,
                "unit": item.unit,
                "suggested_value": suggested,
                "value": "",
                "validation_rule": item.validation_rule,
                "example": item.example,
            }
        )
    return rows


def write_interaction_block_csv(block: InteractionBlock, csv_path: Path) -> Path:
    """Escribe el bloque a CSV con una columna vacía ``value`` para captura masiva."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = interaction_block_to_csv_rows(block)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_EXPORT_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def write_interaction_block_metadata(
    block: InteractionBlock,
    metadata_path: Path,
    *,
    session_id: str,
    company_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Escribe un sidecar JSON con metadatos útiles para trazabilidad del lote."""
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "company_id": company_id,
        "block_id": block.block_id,
        "block_version": block.block_version,
        "item_ids": [item.item_id for item in block.items],
        "anchor": block.anchor.model_dump(mode="json"),
        "metadata": block.metadata.model_dump(mode="json"),
    }
    if extra:
        payload["extra"] = extra
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata_path


def read_mass_save_rows(csv_path: Path) -> List[Dict[str, str]]:
    """Lee un CSV capturado por humano y devuelve filas ``{item_id, value}`` no vacías."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        value_key = next((name for name in reader.fieldnames if str(name).strip().lower() in _VALUE_HEADERS), None)
        if value_key is None:
            raise ValueError("El CSV no contiene columna value/valor/precio.")
        rows: List[Dict[str, str]] = []
        for row in reader:
            item_id = str(row.get("item_id") or "").strip()
            value = str(row.get(value_key) or "").strip()
            if not item_id or not value:
                continue
            rows.append({"item_id": item_id, "value": value})
    return rows
