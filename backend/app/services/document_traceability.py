from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterable, Optional


def safe_file_sha256(path: str | None) -> Optional[str]:
    """Calcula SHA-256 de un archivo si existe; si no, retorna ``None``."""
    if not path or not os.path.isfile(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                if not isinstance(chunk, (bytes, bytearray)):
                    return None
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def attach_traceability(
    doc: Dict[str, Any],
    *,
    source_doc_id: Optional[str] = None,
    source_filename: Optional[str] = None,
    source_path: Optional[str] = None,
    source_hash: Optional[str] = None,
    template_id: Optional[str] = None,
    mirror_mode: Optional[str] = None,
    materialization_route: Optional[str] = None,
    output_hash: Optional[str] = None,
    provenance_ui: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Adjunta campos de trazabilidad sin destruir metadata previa."""
    out = dict(doc)
    fields = {
        "source_doc_id": source_doc_id,
        "source_filename": source_filename,
        "source_path": source_path,
        "source_hash": source_hash,
        "template_id": template_id,
        "mirror_mode": mirror_mode,
        "materialization_route": materialization_route,
        "output_hash": output_hash,
    }
    for key, value in fields.items():
        if value is not None and value != "":
            out[key] = value
    if isinstance(provenance_ui, dict) and provenance_ui:
        merged = dict(out.get("provenance_ui") or {})
        merged.update(provenance_ui)
        out["provenance_ui"] = merged
    return out


def build_materialization_metrics(
    *,
    stage: str,
    documents: Iterable[Dict[str, Any]],
    elapsed_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Resume volumen, rutas y peso materializado por etapa."""
    total_bytes = 0
    total_files = 0
    routes: Dict[str, int] = {}
    unique_sources: set[str] = set()
    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        total_files += 1
        route = str(doc.get("materialization_route") or "unspecified")
        routes[route] = routes.get(route, 0) + 1
        src = str(doc.get("source_doc_id") or doc.get("source_filename") or "").strip()
        if src:
            unique_sources.add(src)
        path = str(doc.get("ruta") or "").strip()
        if path and os.path.isfile(path):
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass
    return {
        "stage": stage,
        "files_count": total_files,
        "total_bytes": total_bytes,
        "routes": routes,
        "mirrored_count": routes.get("mirror", 0),
        "fill_excel_count": routes.get("fill_excel", 0),
        "generated_count": routes.get("generate_controlled", 0) + routes.get("template_locked", 0) + routes.get("deterministic", 0),
        "unique_sources_count": len(unique_sources),
        "elapsed_ms": elapsed_ms,
    }
