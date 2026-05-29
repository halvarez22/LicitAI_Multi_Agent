"""
Enriquece ítems de compliance con ``archivo_fuente`` resuelto al catálogo ingestado.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.ingested_file_resolver import (
    build_ingested_file_index,
    resolve_ingested_file,
)


def enrich_compliance_archivo_fuente(
    compliance_data: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Añade o corrige ``archivo_fuente`` cuando hay plantilla ingestada coincidente.

    Args:
        compliance_data: Dict con claves administrativo / tecnico / formatos.
        documents: Documentos de sesión.

    Returns:
        Misma estructura con flags ``archivo_fuente_resuelto`` en quality_flags.
    """
    if not isinstance(compliance_data, dict):
        return compliance_data
    index = build_ingested_file_index(documents)
    out = dict(compliance_data)
    stats = {"resolved": 0, "already_set": 0, "unresolved": 0}

    for bucket in ("administrativo", "tecnico", "formatos"):
        items = out.get(bucket) or []
        if not isinstance(items, list):
            continue
        new_items: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                new_items.append(item)
                continue
            row = dict(item)
            src = str(row.get("archivo_fuente") or "").strip()
            ref = resolve_ingested_file(src, index) if src else None
            if not ref:
                nombre = str(row.get("nombre") or row.get("descripcion") or "")
                ref = resolve_ingested_file(nombre, index)
            if ref:
                if not src:
                    row["archivo_fuente"] = ref.filename
                    stats["resolved"] += 1
                    flags = list(row.get("quality_flags") or [])
                    if "archivo_fuente_resuelto" not in flags:
                        flags.append("archivo_fuente_resuelto")
                    row["quality_flags"] = flags
                else:
                    stats["already_set"] += 1
            else:
                stats["unresolved"] += 1
            new_items.append(row)
        out[bucket] = new_items

    out["_archivo_fuente_enrichment"] = stats
    return out
