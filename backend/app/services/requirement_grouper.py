"""
Agrupa pendientes HITL en ``InteractionBlock`` usando verdad canónica de sesión.

No inventa requisitos: solo agrupa ``pending_questions`` ya emitidos por el pipeline,
preferentemente por ``block_group_key`` inyectado por EconomicAgent.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.contracts.interaction_block import (
    INTERACTION_BLOCK_SCHEMA_VERSION,
    BlockAnchor,
    InteractionBlock,
    InteractionBlockItem,
    InteractionBlockMetadata,
)


def _analisis_bases_from_session(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Último resultado de ``analisis_bases`` en ``tasks_completed``."""
    for task in reversed(session_state.get("tasks_completed") or []):
        if task.get("task") == "analisis_bases":
            res = task.get("result")
            return res if isinstance(res, dict) else {}
    return {}


def _anchor_from_analisis_and_pending(
    analisis: Dict[str, Any],
    cluster: List[Dict[str, Any]],
) -> BlockAnchor:
    """Construye anclaje desde reglas/alcance canónico y primer pendiente con snippet."""
    reglas = analisis.get("reglas_economicas") if isinstance(analisis.get("reglas_economicas"), dict) else {}
    ref = str(reglas.get("referencia_partidas_anexos_citados") or "").strip()
    title = "Propuesta económica / partidas de oferta"
    if ref and len(ref) > 12:
        title = "Referencias de partidas y anexos (bases)"
    page: Optional[int] = None
    first = cluster[0] if cluster else {}
    oi = first.get("original_item") if isinstance(first, dict) else None
    if isinstance(oi, dict):
        p = oi.get("page") or oi.get("pagina")
        if p is not None:
            try:
                page = int(p)
            except (TypeError, ValueError):
                page = None
    legal = ref[:900] if ref else ""
    if not legal and cluster:
        q0 = cluster[0]
        oi2 = q0.get("original_item") if isinstance(q0, dict) else None
        if isinstance(oi2, dict):
            legal = str(oi2.get("concepto") or oi2.get("descripcion") or "")[:900]
    return BlockAnchor(
        title=title[:280],
        page=page,
        description="",
        legal_reference=legal,
        provenance="analisis_bases" if ref else "pending_only",
    )


def _suggested_price_for_concept(catalog: List[Dict[str, Any]], concept_label: str) -> Optional[float]:
    """Busca precio sugerido en catálogo por descripción similar (conservador)."""
    if not catalog or not concept_label:
        return None
    raw = concept_label.strip().lower()
    for pfx in ("precio (sin iva): ", "precio de: ", "pu oferta económica — ", "pu oferta economica - "):
        if raw.startswith(pfx):
            raw = raw[len(pfx) :].strip()
            break
    best: Optional[float] = None
    for it in catalog:
        if not isinstance(it, dict):
            continue
        desc = str(it.get("description") or it.get("name") or "").strip().lower()
        if not desc:
            continue
        if raw in desc or desc in raw:
            try:
                best = float(it.get("price_base", it.get("price", 0)) or 0)
            except (TypeError, ValueError):
                continue
            break
    return best


def select_economic_cluster(
    pending: List[Dict[str, Any]],
    current_idx: int,
) -> Optional[List[Dict[str, Any]]]:
    """
    Elige un cluster de ``economic_price`` para bloque.

    - Si hay ``block_group_key``, agrupa por esa clave.
    - Si no, agrupa todos los ``economic_price`` si alcanzan el mínimo.
    Prioriza el grupo que contiene ``current_question_index``.
    """
    econ = [q for q in pending if isinstance(q, dict) and q.get("type") == "economic_price"]
    min_n = max(1, int(getattr(settings, "BLOCK_RESOLUTION_MIN_ITEMS", 3) or 3))
    if len(econ) < min_n:
        return None

    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for q in econ:
        k = str(q.get("block_group_key") or "").strip()
        if k:
            by_key.setdefault(k, []).append(q)
    if by_key:
        cur = pending[max(0, min(current_idx, len(pending) - 1))] if pending else {}
        cur_key = str(cur.get("block_group_key") or "").strip()
        if cur_key and cur_key in by_key and len(by_key[cur_key]) >= min_n:
            return by_key[cur_key]
        # Mayor cluster que cumpla mínimo
        best_list: Optional[List[Dict[str, Any]]] = None
        for _k, lst in by_key.items():
            if len(lst) >= min_n and (best_list is None or len(lst) > len(best_list)):
                best_list = lst
        return best_list
    return econ if len(econ) >= min_n else None


def build_interaction_block(
    *,
    session_id: str,
    session_state: Dict[str, Any],
    company_catalog: Optional[List[Dict[str, Any]]] = None,
    current_idx: int = 0,
) -> Optional[InteractionBlock]:
    """
    Construye un ``InteractionBlock`` si el flag está activo y hay cluster válido.

    Args:
        session_id: ID de sesión.
        session_state: Estado de sesión crudo desde memoria.
        company_catalog: Filas de ``company.catalog`` (opcional) para sugerencias.
        current_idx: Índice actual en ``pending_questions`` (priorización).

    Returns:
        Bloque listo para serializar, o None si no aplica.
    """
    if not getattr(settings, "ENABLE_BLOCK_RESOLUTION", False):
        return None

    pending = list(session_state.get("pending_questions") or [])
    cluster = select_economic_cluster(pending, current_idx)
    if not cluster:
        return None

    analisis = _analisis_bases_from_session(session_state)
    anchor = _anchor_from_analisis_and_pending(analisis, cluster)
    catalog = company_catalog or []

    items: List[InteractionBlockItem] = []
    for q in sorted(cluster, key=lambda x: int(x.get("block_item_seq") or 0)):
        field = str(q.get("field") or "").strip()
        if not field:
            continue
        label = str(q.get("label") or field).strip()
        oi = q.get("original_item") if isinstance(q.get("original_item"), dict) else {}
        unit = str(oi.get("unidad") or oi.get("unidad_medida") or "PU").strip() or "PU"
        sug = _suggested_price_for_concept(catalog, label)
        items.append(
            InteractionBlockItem(
                item_id=field,
                label=label,
                unit=unit[:64],
                suggested_value=sug,
                is_required=True,
                format="numeric",
                example="0 si no aplica costo; de lo contrario un número en pesos sin IVA",
                validation_rule="must_be_finite_number",
                block_item_seq=int(q.get("block_item_seq") or 0),
            )
        )

    if len(items) < max(1, int(getattr(settings, "BLOCK_RESOLUTION_MIN_ITEMS", 3) or 3)):
        return None

    block_id = stable_block_id_for_cluster(session_id, [i.item_id for i in items])

    meta = InteractionBlockMetadata(
        total_items=len(items),
        resolved_items=0,
        block_type="economic_proposal",
    )
    return InteractionBlock(
        block_id=block_id,
        block_version=INTERACTION_BLOCK_SCHEMA_VERSION,
        anchor=anchor,
        items=items,
        metadata=meta,
    )


def stable_block_id_for_cluster(session_id: str, item_ids: List[str]) -> str:
    """Id determinista para el mismo conjunto de ítems (idempotencia de preview)."""
    h = hashlib.sha256("|".join(sorted(item_ids)).encode("utf-8")).hexdigest()[:24]
    return f"blk_{session_id[:16]}_{h}"
