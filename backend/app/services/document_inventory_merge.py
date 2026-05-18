"""
Fusión de inventario de documentos exigidos en bases.

El ComplianceAgent (map-reduce por zonas) suele devolver pocos ítems; los escritores
solo generan tantos Word como filas en la lista maestra. Este módulo amplía
``compliance_master_list`` con:

- Detección por regex de claves típicas (Forma DD/AT/AE…).
- Lista adicional vía LLM sobre contexto RAG agregado (documentación capítulos 6–8).

Los ítems sintéticos llevan ``inventory_synthetic: true`` para que TechnicalWriter
y FormatsAgent los incluyan aunque no pasen filtros históricos restrictivos.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Set

from app.config.settings import settings
from app.core.observability import get_logger
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient

logger = get_logger(__name__)

_FORM_RE = re.compile(r"(?i)\b(?:forma\s+)?((?:DD|AT|AE)[-\s]?\d{1,2}[A-Za-z]?)\b")


def _norm_id(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _existing_id_set(lists: Dict[str, List[Any]]) -> Set[str]:
    out: Set[str] = set()
    for cat in ("administrativo", "tecnico", "formatos"):
        for it in lists.get(cat) or []:
            if not isinstance(it, dict):
                continue
            rid = _norm_id(str(it.get("id", "")))
            if rid:
                out.add(rid)
    return out


def _collect_rag_context(session_id: str, max_chars: int) -> str:
    vdb = VectorDbServiceClient()
    chunks: List[str] = []
    queries = [
        "documentación presentar proposición técnica económica sobres cerrados",
        "Forma DD manifestación protesta decir verdad integridad correo",
        "Forma AT programa calendarizado relación contratos maquinaria superintendente experiencia",
        "Forma AE catálogo conceptos listado insumos proposición económica garantía seriedad",
    ]
    for q in queries:
        res = vdb.query_texts(session_id, q, n_results=18)
        docs = res.get("documents") or []
        if isinstance(docs, list):
            chunks.extend(str(d) for d in docs if d)
    text = "\n\n---\n\n".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _regex_synthetic_items(context: str, existing: Set[str]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for m in _FORM_RE.finditer(context):
        raw = m.group(1).replace(" ", "").replace("–", "-").upper()
        if not raw:
            continue
        nid = _norm_id(raw)
        if not nid or nid in existing or nid in seen:
            continue
        seen.add(nid)
        if raw.startswith("AT"):
            cat = "tecnico"
        elif raw.startswith("DD") or raw.startswith("AE"):
            cat = "formatos"
        else:
            cat = "formatos"
        out.append(
            {
                "id": raw[:32],
                "nombre": f"Documento {raw} (borrador generado)",
                "descripcion": "Detectado en texto de bases; revisar literal contra convocatoria oficial.",
                "tipo": "tecnico" if cat == "tecnico" else "formato",
                "categoria": cat,
                "match_tier": "inventory_expand",
                "evidence_match": True,
                "inventory_synthetic": True,
            }
        )
    return out


async def _llm_synthetic_items(context: str, correlation_id: str) -> List[Dict[str, Any]]:
    llm = ResilientLLMClient()
    prompt = (
        "Eres auditor de licitaciones. Del texto de bases (fragmento), enumera cada "
        "DOCUMENTO escrito que el licitante debe elaborar o llenar (manifestaciones, "
        "programas, relaciones, formularios Forma DD/AT/AE, cartas compromiso, catálogos, "
        "proposición técnica desglosada).\n"
        "No listes credenciales o constancias que solo se exhiben sin redactar (INE, "
        "constancia SAT del SAT como tal), salvo que sea un escrito de solicitud.\n"
        'Devuelve SOLO JSON válido: array de objetos '
        '{"id":"clave_corta_unica","nombre":"titulo","descripcion":"max 200 chars",'
        '"categoria":"administrativo"|"tecnico"|"formatos"}.\n'
        "Máximo 45 objetos. Sin markdown.\n\n"
        f"Texto:\n\n{context[:22000]}"
    )
    resp = await llm.generate(
        prompt=prompt,
        system_prompt="Solo JSON array. Sin explicación.",
        correlation_id=correlation_id,
    )
    if not resp.success or not (resp.response or "").strip():
        return []
    raw = resp.response.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("document_inventory_llm_json_fail", snippet=raw[:240])
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("id") or "").strip()
        if not cid:
            continue
        cat = str(it.get("categoria") or "formatos").lower()
        if cat not in ("administrativo", "tecnico", "formatos"):
            cat = "formatos"
        out.append(
            {
                "id": cid[:64],
                "nombre": str(it.get("nombre") or cid)[:220],
                "descripcion": str(it.get("descripcion") or "")[:500],
                "tipo": "tecnico" if cat == "tecnico" else "formato",
                "categoria": cat,
                "match_tier": "inventory_expand",
                "evidence_match": True,
                "inventory_synthetic": True,
            }
        )
    return out


def merge_synthetic_into_master_list(
    cm: Dict[str, Any],
    additions: List[Dict[str, Any]],
    max_additions: int,
) -> Dict[str, Any]:
    """Añade ítems sintéticos sin duplicar ids normalizados. Preserva claves extra (p. ej. audit_summary)."""
    out_full: Dict[str, Any] = dict(cm) if isinstance(cm, dict) else {}
    for k in ("administrativo", "tecnico", "formatos"):
        out_full[k] = list(cm.get(k) or []) if isinstance(cm, dict) else []

    lists = {k: out_full[k] for k in ("administrativo", "tecnico", "formatos")}
    existing_ids = _existing_id_set(lists)
    added = 0
    for add in additions:
        if added >= max_additions:
            break
        aid = _norm_id(str(add.get("id", "")))
        if not aid or aid in existing_ids:
            continue
        cat = str(add.get("categoria") or "formatos").lower()
        if cat not in ("administrativo", "tecnico", "formatos"):
            cat = "formatos"
        out_full[cat].append(add)
        existing_ids.add(aid)
        added += 1
    return out_full


async def merge_inventory_into_compliance_list(
    *,
    session_id: str,
    compliance_master_list: Dict[str, Any],
    correlation_id: str = "",
) -> Dict[str, Any]:
    """
    Amplía la lista maestra de compliance con documentos detectados en bases.

    Args:
        session_id: Sesión Chroma / outputs.
        compliance_master_list: dict con claves administrativo, tecnico, formatos.
        correlation_id: trazabilidad LLM.

    Returns:
        Nuevo dict (copia) con ítems extra; si está deshabilitado o sin contexto, devuelve el original.
    """
    if not settings.DOCUMENT_INVENTORY_MERGE_ENABLED:
        return dict(compliance_master_list) if isinstance(compliance_master_list, dict) else {}

    cm: Dict[str, Any] = (
        dict(compliance_master_list) if isinstance(compliance_master_list, dict) else {}
    )
    max_ctx = max(8000, int(settings.DOCUMENT_INVENTORY_CONTEXT_CHARS))
    max_add = max(5, int(settings.DOCUMENT_INVENTORY_MAX_ADD))

    ctx = _collect_rag_context(session_id, max_ctx)
    if len(ctx) < 400:
        logger.info("document_inventory_skipped_short_context", session_id=session_id, chars=len(ctx))
        return cm

    lists = {k: list(cm.get(k) or []) for k in ("administrativo", "tecnico", "formatos")}
    existing = _existing_id_set(lists)
    by_regex = _regex_synthetic_items(ctx, existing)
    for it in by_regex:
        existing.add(_norm_id(str(it.get("id", ""))))

    llm_items = await _llm_synthetic_items(ctx, correlation_id)
    merged = merge_synthetic_into_master_list(cm, by_regex + llm_items, max_additions=max_add)

    logger.info(
        "document_inventory_merge_done",
        session_id=session_id,
        regex_n=len(by_regex),
        llm_n=len(llm_items),
        totals={k: len(merged.get(k) or []) for k in ("administrativo", "tecnico", "formatos")},
    )
    return merged
