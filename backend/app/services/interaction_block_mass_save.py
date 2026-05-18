"""
Guardado masivo validado fila a fila para ``InteractionBlock`` (Hito A1).

Persistencia alineada con captura atómica del chatbot: catálogo de empresa
y actualización de ``pending_questions`` sin borrar filas no validadas.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config.settings import settings


def _parse_economic_value(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """Parsea valor numérico de precio; devuelve (valor, error)."""
    if raw is None:
        return None, "vacío"
    s = str(raw).strip().replace("$", "").replace("mxn", "").replace("MXN", "").replace(",", "")
    if not s:
        return None, "vacío"
    low = s.lower()
    if low in ("n/a", "na", "pendiente", "—", "-"):
        return None, "use número o 0"
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    try:
        v = float(s)
    except ValueError:
        return None, "no es un número válido"
    if not (v == v):  # NaN
        return None, "no es un número válido"
    return v, None


async def _save_price_to_company_catalog(
    memory: Any,
    company_id: str,
    question: Dict[str, Any],
    price: float,
) -> bool:
    """Replica la lógica de catálogo de ``ChatbotRAGAgent._save_price_to_catalog`` (sin instanciar agente)."""
    try:
        company = await memory.get_company(company_id)
        if not company:
            return False
        catalog = list(company.get("catalog") or [])
        raw_lbl = str(question.get("label", "Desconocido") or "")
        for _pfx in (
            "Precio de: ",
            "PU oferta económica — ",
            "PU oferta economica - ",
            "Precio (sin IVA): ",
        ):
            raw_lbl = raw_lbl.replace(_pfx, "")
        new_item = {
            "description": raw_lbl.strip() or "Concepto",
            "price_base": float(price),
            "currency": "MXN",
            "id": question.get("field", ""),
            "source": "chatbot_block",
        }
        found = False
        for i, it in enumerate(catalog):
            if it.get("id") == new_item["id"] or it.get("description") == new_item["description"]:
                catalog[i] = new_item
                found = True
                break
        if not found:
            catalog.append(new_item)
        company["catalog"] = catalog
        await memory.save_company(company_id, company)
        return True
    except Exception:
        return False


async def mass_save_economic_block(
    memory: Any,
    *,
    session_id: str,
    company_id: str,
    block_id: str,
    correlation_id: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Valida y guarda filas de precios; elimina de ``pending_questions`` solo las exitosas.

    Args:
        memory: Adaptador Postgres (misma interfaz que usa MCPContextManager.memory).
        session_id: Sesión activa.
        company_id: Empresa seleccionada.
        block_id: Id del bloque (debe coincidir con preview para misma sesión/cluster).
        correlation_id: Correlación HITL.
        rows: Lista de dicts con ``item_id`` y ``value``.

    Returns:
        Dict con ``success_count``, ``failed_items``, ``removed_fields``.
    """
    if not getattr(settings, "ENABLE_BLOCK_RESOLUTION", False):
        return {
            "success_count": 0,
            "failed_items": [{"item_id": "*", "error": "LICITAI_ENABLE_BLOCK_RESOLUTION está desactivado"}],
            "removed_fields": [],
        }

    session_state = await memory.get_session(session_id) or {}
    pending = list(session_state.get("pending_questions") or [])
    by_field = {str(q.get("field")): q for q in pending if isinstance(q, dict) and q.get("field")}

    success_count = 0
    failed_items: List[Dict[str, str]] = []
    removed_fields: List[str] = []

    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        val_raw = row.get("value")
        if not item_id:
            failed_items.append({"item_id": "", "error": "item_id ausente"})
            continue
        q = by_field.get(item_id)
        if not q or q.get("type") != "economic_price":
            failed_items.append({"item_id": item_id, "error": "pendiente no encontrado o no es precio"})
            continue
        num, err = _parse_economic_value("" if val_raw is None else str(val_raw))
        if err or num is None:
            failed_items.append({"item_id": item_id, "error": err or "valor inválido"})
            continue
        ok = await _save_price_to_company_catalog(memory, company_id, q, num)
        if not ok:
            failed_items.append({"item_id": item_id, "error": "no se pudo persistir en catálogo"})
            continue
        success_count += 1
        removed_fields.append(item_id)

    if removed_fields:
        removed_set = set(removed_fields)
        still = [q for q in pending if str(q.get("field")) not in removed_set]
        old_idx = int(session_state.get("current_question_index") or 0)
        old_idx = max(0, min(old_idx, max(0, len(pending) - 1)))
        old_q = pending[old_idx] if pending else None
        if still and old_q and str(old_q.get("field") or "") not in removed_set:
            nf = str(old_q.get("field"))
            new_idx = next((i for i, q in enumerate(still) if str(q.get("field")) == nf), 0)
        else:
            new_idx = 0
        session_state["pending_questions"] = still
        session_state["current_question_index"] = new_idx if still else 0

    audit = list(session_state.get("interaction_block_audit") or [])
    audit.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "block_id": block_id,
            "correlation_id": correlation_id or "",
            "success_count": success_count,
            "failed": failed_items,
            "removed_fields": removed_fields,
        }
    )
    session_state["interaction_block_audit"] = audit[-50:]

    await memory.save_session(session_id, session_state)

    return {
        "success_count": success_count,
        "failed_items": failed_items,
        "removed_fields": removed_fields,
        "block_id": block_id,
        "correlation_id": correlation_id or "",
    }
