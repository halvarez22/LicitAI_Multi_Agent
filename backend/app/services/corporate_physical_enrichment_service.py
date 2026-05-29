"""
Extrae credenciales empresariales (IMSS, SAT, acta, etc.) desde páginas de requisitos en bases.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.services.document_deliverable_filter import (
    is_corporate_physical_credential_for_panel,
    normalize_deliverable_key,
)

_NUMBERED_REQ_RE = re.compile(
    r"(?m)^\s*(\d+)\.\s+(.{12,280}?)(?=\n\s*\d+\.|\n\n|\Z)",
    re.DOTALL,
)


def _bases_requisitos_blob(session_id: str, vector_db: Any = None) -> str:
    from app.services.vector_service import VectorDbServiceClient

    vdb = vector_db or VectorDbServiceClient()
    parts: List[str] = []
    for src in ("bases_0001.pdf", "bases.pdf", "bases_convocatoria.pdf"):
        for pg in range(8, 28):
            try:
                for doc in vdb.fetch_page_documents(session_id, src, pg) or []:
                    parts.append(str(doc))
            except Exception:
                continue
    return "\n".join(parts)


def extract_corporate_physical_from_bases_rag(
    session_id: str,
    *,
    vector_db: Any = None,
) -> List[Dict[str, Any]]:
    """
    Localiza requisitos numerados de expediente empresarial en el PDF de bases indexado.
    """
    blob = _bases_requisitos_blob(session_id, vector_db)
    if not blob.strip():
        return []

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for m in _NUMBERED_REQ_RE.finditer(blob):
        raw_line = re.sub(r"\s+", " ", m.group(2)).strip()
        if len(raw_line) < 15:
            continue
        if not is_corporate_physical_credential_for_panel(raw_line, "", raw_line):
            continue
        key = normalize_deliverable_key(raw_line, "expediente_empresarial")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "document_id": f"corp-rag-{len(out)+1:02d}",
                "nombre": raw_line[:220],
                "categoria": "expediente_empresarial",
                "tipo_accion_propuesto": "presentar_fisico",
                "tipo_accion_final": "presentar_fisico",
                "confidence": 0.82,
                "evidence_snippet": raw_line[:600],
                "provenance_ui": {
                    "source": "bases_rag_requisitos",
                    "reason": "numbered_requirement_credential_pattern",
                },
            }
        )
    return out
