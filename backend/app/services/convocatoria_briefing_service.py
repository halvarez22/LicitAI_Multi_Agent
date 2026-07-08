"""
Briefing HRU de convocatoria — síntesis canónica de qué solicita la convocante.

Deriva bloques (administrativo · técnico · económico) y primer paso conversacional
desde estado de sesión post-análisis. Sin mapas por convocante.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config.settings import settings

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
_POLICY_PATH = _CONTRACTS_DIR / "convocatoria_briefing_policy.json"
_SCHEMA_PATH = _CONTRACTS_DIR / "convocatoria_briefing_canonical_v1.json"

SCHEMA_VERSION = "convocatoria-briefing-v1.0.0"

_USER_TIPOS = frozenset({"presentar_fisico", "aportar_documento", "consignar_fisico"})
_GENERABLE_TIPOS = frozenset(
    {
        "generar",
        "requiere_datos_licitante",
        "presentar_digital",
        "llenar_formato",
        "llenar_plantilla",
    }
)


@lru_cache(maxsize=1)
def load_convocatoria_briefing_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def convocatoria_briefing_enabled() -> bool:
    return bool(getattr(settings, "CONVOCATORIA_BRIEFING_ENABLED", True))


def policy_version() -> str:
    return str(load_convocatoria_briefing_policy().get("policy_version") or "")


def _item_name(item: Dict[str, Any]) -> str:
    raw = str(
        item.get("nombre_canonico")
        or item.get("display_name")
        or item.get("nombre")
        or item.get("label")
        or item.get("descripcion")
        or ""
    ).strip()
    if not raw:
        return ""
    try:
        from app.services.formats_panel_hru_service import resolve_panel_display_name

        raw = resolve_panel_display_name(raw)
    except Exception:
        pass
    return raw


def _item_tipo(item: Dict[str, Any]) -> str:
    return str(
        item.get("tipo_accion_final")
        or item.get("tipo_accion_propuesto")
        or item.get("tipo_accion")
        or item.get("tipo")
        or ""
    ).strip().lower()


def _extract_page_refs(items: List[Dict[str, Any]]) -> List[int]:
    pages: Set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("page", "pagina", "source_page"):
            val = item.get(key)
            if isinstance(val, int) and val > 0:
                pages.add(val)
        ev = item.get("evidence")
        if isinstance(ev, dict):
            p = ev.get("page")
            if isinstance(p, int) and p > 0:
                pages.add(p)
    return sorted(pages)[:6]


def _iter_compliance(state: Dict[str, Any], categories: List[str]) -> List[Dict[str, Any]]:
    cml = state.get("compliance_master_list")
    if not isinstance(cml, dict):
        return []
    out: List[Dict[str, Any]] = []
    for cat in categories:
        for item in cml.get(cat) or []:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("categoria", cat)
                out.append(row)
    return out


def _iter_ccc(state: Dict[str, Any], buckets: List[str]) -> List[Dict[str, Any]]:
    ccc = state.get("document_candidates_consolidated")
    if not isinstance(ccc, dict):
        return []
    out: List[Dict[str, Any]] = []
    for bucket in buckets:
        for item in ccc.get(bucket) or []:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("ccc_bucket", bucket)
                out.append(row)
    return out


def _is_admin_item(item: Dict[str, Any], policy_block: Dict[str, Any]) -> bool:
    tipo = _item_tipo(item)
    if tipo in set(policy_block.get("user_action_types") or []):
        return True
    cat = str(item.get("categoria") or "").lower()
    if cat == "administrativo":
        return True
    if item.get("requires_user_document") is True:
        return True
    if str(item.get("categoria") or "") == "expediente_empresarial":
        return True
    return False


def _is_technical_item(item: Dict[str, Any], policy_block: Dict[str, Any]) -> bool:
    tipo = _item_tipo(item)
    if tipo in _USER_TIPOS:
        return False
    cat = str(item.get("categoria") or "").lower()
    if cat in ("tecnico", "formatos"):
        if tipo in _GENERABLE_TIPOS or tipo == "generar":
            return True
        name = _item_name(item).lower()
        if "económ" in name or "econom" in name or "presupuesto" in name:
            return False
        return True
    bucket = str(item.get("ccc_bucket") or "")
    if bucket == "sobre_1_tecnico":
        return True
    return False


def _is_economic_item(item: Dict[str, Any], policy_block: Dict[str, Any]) -> bool:
    tipo = _item_tipo(item)
    cat = str(item.get("categoria") or "").lower()
    if cat == "economico":
        return True
    bucket = str(item.get("ccc_bucket") or "")
    if bucket == "sobre_2_economico":
        return True
    name = _item_name(item).lower()
    if any(k in name for k in ("cotización", "cotizacion", "precio", "presupuesto", "cédula económica")):
        return True
    return False


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        name = _item_name(item)
        key = re.sub(r"\s+", " ", name.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _collect_block_items(state: Dict[str, Any], block_id: str) -> List[Dict[str, Any]]:
    policy = load_convocatoria_briefing_policy()
    block_cfg = (policy.get("blocks") or {}).get(block_id) or {}
    items: List[Dict[str, Any]] = []
    items.extend(_iter_compliance(state, list(block_cfg.get("compliance_categories") or [])))
    items.extend(_iter_ccc(state, list(block_cfg.get("ccc_buckets") or [])))

    if block_id == "administrative":
        items = [i for i in items if _is_admin_item(i, block_cfg)]
    elif block_id == "technical":
        items = [i for i in items if _is_technical_item(i, block_cfg)]
    elif block_id == "economic":
        items = [i for i in items if _is_economic_item(i, block_cfg)]
        line_items = state.get("session_line_items") or []
        if isinstance(line_items, list) and line_items:
            for row in line_items:
                if isinstance(row, dict):
                    items.append({"nombre": _line_item_label(row), "source": "session_line_items"})

    return _dedupe_items(items)


def _line_item_label(row: Dict[str, Any]) -> str:
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    return str(
        extra.get("location_label")
        or row.get("concepto_raw")
        or row.get("label")
        or "concepto de cotización"
    ).strip()


def _build_block(state: Dict[str, Any], block_id: str) -> Dict[str, Any]:
    policy = load_convocatoria_briefing_policy()
    block_cfg = (policy.get("blocks") or {}).get(block_id) or {}
    items = _collect_block_items(state, block_id)
    max_ex = int(policy.get("max_example_items") or 3)
    from app.services.convocatoria_briefing_ux import humanize_plain_label
    from app.services.evidence_anchor_service import (
        attach_evidence_anchor_to_dict,
        extract_anchor_from_compliance_items,
    )

    examples = [humanize_plain_label(_item_name(i)) for i in items[:max_ex] if _item_name(i)]
    source = f"compliance_master_list+document_candidates.{block_id}"
    if block_id == "economic" and state.get("session_line_items"):
        source = "session_line_items+compliance_master_list.economico"

    block = {
        "block_id": block_id,
        "title_plain": str(block_cfg.get("title_plain") or block_id),
        "summary_plain": str(block_cfg.get("summary_plain") or ""),
        "example_items": examples,
        "item_count": len(items),
        "envelope_hint": str(block_cfg.get("envelope_hint") or ""),
        "provenance_ui": {
            "source": source,
            "page_refs": _extract_page_refs(items),
        },
    }
    anchor = extract_anchor_from_compliance_items(items, claim_id=f"briefing.block.{block_id}")
    return attach_evidence_anchor_to_dict(block, anchor)


def _tender_category(state: Dict[str, Any]) -> str:
    triage = state.get("triage_context") if isinstance(state.get("triage_context"), dict) else {}
    cat = str(triage.get("tender_category") or triage.get("category") or "").strip().upper()
    if cat:
        return cat
    name = str(state.get("name") or "").upper()
    if "OBRA" in name or "BARDA" in name:
        return "OBRA"
    return "SERVICIOS"


def _has_price_source_pending(state: Dict[str, Any]) -> bool:
    for q in state.get("pending_questions") or []:
        if not isinstance(q, dict):
            continue
        if str(q.get("type") or "") != "economic_validation_blocking":
            continue
        if str(q.get("input_mode") or "").strip().lower() == "price_source":
            return True
        if str(q.get("field") or "").strip() == "economic_price_source":
            return True
        items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []
        if any(str(it.get("requested_input") or "").strip().lower() == "price_source" for it in items):
            return True
    return False


def _economic_capture_incomplete(state: Dict[str, Any]) -> bool:
    from app.services.economic_capture_matrix_service import (
        count_filled_price_inputs,
        economic_capture_status,
    )

    if _has_price_source_pending(state):
        return True
    cap = economic_capture_status(state)
    if cap.get("capture_complete"):
        return False
    if int(cap.get("missing") or 0) > 0:
        return True
    rows = state.get("session_line_items") or []
    inputs = state.get("economic_user_inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    if isinstance(rows, list) and rows and count_filled_price_inputs(inputs) < len(rows):
        return True
    if state.get("economic_post_analysis_hook_pending"):
        return True
    total = int(cap.get("total") or 0)
    filled = count_filled_price_inputs(inputs)
    if total > 0 and filled < total:
        return True
    return bool(rows) and filled <= 0


def _technical_slots_pending(state: Dict[str, Any]) -> bool:
    tech_items = _collect_block_items(state, "technical")
    if not tech_items and not state.get("technical_post_analysis_hook_pending"):
        return False
    from app.services.technical_slot_mapper import technical_capture_status

    cap = technical_capture_status(state)
    if int(cap.get("total") or 0) <= 0:
        return bool(state.get("technical_post_analysis_hook_pending"))
    return not cap.get("capture_complete") and int(cap.get("missing") or 0) > 0


def _only_user_documents_pending(state: Dict[str, Any]) -> bool:
    if _economic_capture_incomplete(state) or _technical_slots_pending(state):
        return False
    if state.get("session_line_items"):
        return False
    admin_items = _collect_block_items(state, "administrative")
    if len(admin_items) >= 1:
        tech_items = _collect_block_items(state, "technical")
        eco_items = _collect_block_items(state, "economic")
        if not eco_items and not tech_items:
            return True
        try:
            from app.services.chat_expediente_bootstrap_service import collect_expediente_bootstrap_facts

            facts = collect_expediente_bootstrap_facts(state)
            if facts.user_attach_count > 0:
                return True
        except Exception:
            return len(admin_items) >= 2
    return False


def _resolve_first_track(state: Dict[str, Any]) -> Tuple[str, str]:
    policy = load_convocatoria_briefing_policy()
    reasons = policy.get("reason_plain") if isinstance(policy.get("reason_plain"), dict) else {}
    obra_cfg = policy.get("obra_technical_first") if isinstance(policy.get("obra_technical_first"), dict) else {}
    obra_cats = {str(c).upper() for c in (obra_cfg.get("tender_categories") or [])}
    category = _tender_category(state)
    line_items = state.get("session_line_items") or []

    if _economic_capture_incomplete(state):
        return "economic", str(reasons.get("economic") or "")
    if (
        category in obra_cats
        and obra_cfg.get("require_no_line_items")
        and not line_items
        and _technical_slots_pending(state)
    ):
        return "technical", str(reasons.get("technical") or "")
    if _only_user_documents_pending(state):
        return "administrative", str(reasons.get("administrative") or "")
    if line_items or category in ("SERVICIOS", "SERVICIO", "BIENES"):
        return "economic", str(reasons.get("economic") or "")
    if _technical_slots_pending(state):
        return "technical", str(reasons.get("technical") or "")
    return "administrative", str(reasons.get("administrative") or "")


def _resolve_first_action(state: Dict[str, Any], track: str) -> Dict[str, Any]:
    from app.services.evidence_anchor_service import (
        attach_evidence_anchor_to_dict,
        extract_anchor_from_session_for_track,
    )

    if track == "economic":
        from app.services.economic_capture_matrix_service import economic_capture_status

        cap = economic_capture_status(state)
        label = str(cap.get("next_label") or cap.get("next_field_label") or "").strip()
        if not label:
            rows = state.get("session_line_items") or []
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                label = _line_item_label(rows[0])
        if _has_price_source_pending(state):
            for q in state.get("pending_questions") or []:
                if not isinstance(q, dict):
                    continue
                items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []
                if items:
                    lbl = str(items[0].get("concepto_label") or "").strip()
                    if lbl:
                        label = lbl
                        break
            if not label or label == "concepto de cotización":
                label = "tu tabla de costos o cotización"
        if not label:
            label = "el primer concepto de tu cotización"
        from app.services.convocatoria_briefing_ux import humanize_plain_label

        label = humanize_plain_label(label)
        action = {
            "track": "economic",
            "label_plain": label,
            "field_key": str(cap.get("next_field") or "economic.first_price"),
            "input_mode": "price_source" if _has_price_source_pending(state) else "unit_price",
            "provenance_ui": {"source": "session_line_items", "page_refs": []},
        }
        anchor = extract_anchor_from_session_for_track(state, "economic")
        return attach_evidence_anchor_to_dict(action, anchor)

    if track == "technical":
        from app.services.technical_capture_ux import list_missing_technical_labels

        labels = list_missing_technical_labels(state, limit=1)
        label = labels[0] if labels else "cómo ejecutarás el servicio"
        from app.services.convocatoria_briefing_ux import humanize_plain_label

        action = {
            "track": "technical",
            "label_plain": humanize_plain_label(label),
            "field_key": "technical.first_slot",
            "provenance_ui": {"source": "technical_slot_mapper", "page_refs": []},
        }
        anchor = extract_anchor_from_session_for_track(state, "technical")
        return attach_evidence_anchor_to_dict(action, anchor)

    try:
        from app.services.chat_expediente_bootstrap_service import collect_expediente_bootstrap_facts

        facts = collect_expediente_bootstrap_facts(state)
        label = facts.user_attach_labels[0] if facts.user_attach_labels else "tus documentos empresariales"
    except Exception:
        label = "tus documentos empresariales"
    from app.services.convocatoria_briefing_ux import humanize_plain_label

    action = {
        "track": "administrative",
        "label_plain": humanize_plain_label(label),
        "field_key": "administrative.user_documents",
        "provenance_ui": {"source": "document_inventory", "page_refs": []},
    }
    anchor = extract_anchor_from_session_for_track(state, "administrative")
    return attach_evidence_anchor_to_dict(action, anchor)


def _tender_object_plain(state: Dict[str, Any]) -> str:
    triage = state.get("triage_context") if isinstance(state.get("triage_context"), dict) else {}
    for key in ("descripcion_objeto", "object_description", "objeto", "description"):
        val = str(triage.get(key) or "").strip()
        if val and len(val) > 12:
            return val[:280]
    name = str(state.get("name") or "").strip()
    if name:
        return f"Licitación: {name}"
    return "esta licitación"


def _quality_signals(state: Dict[str, Any], blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    policy = load_convocatoria_briefing_policy()
    min_items = int(policy.get("min_items_for_confidence_alta") or 2)
    populated = sum(1 for b in blocks if int(b.get("item_count") or 0) >= min_items)
    has_analysis = any(
        isinstance(t, dict) and str(t.get("task") or "") == "stage_completed:analysis"
        for t in (state.get("tasks_completed") or [])
    )
    if not has_analysis:
        confidence = "baja"
    elif populated >= 2:
        confidence = "alta"
    elif populated >= 1:
        confidence = "media"
    else:
        confidence = "baja"
    eco_block = next((b for b in blocks if b.get("block_id") == "economic"), None)
    eco_anchor = bool(state.get("session_line_items")) or int((eco_block or {}).get("item_count") or 0) > 0
    return {
        "blocks_complete": populated >= 2,
        "economic_anchor_verified": eco_anchor,
        "confidence": confidence,
    }


def build_convocatoria_briefing_canonical_v1(
    session_state: Dict[str, Any],
    *,
    bases_corpus_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construye briefing canónico desde estado de sesión.

    Args:
        session_state: Estado persistido de la licitación.
        bases_corpus_text: Texto de bases (reservado; no inventa requisitos vía LLM).

    Returns:
        Dict conforme a ``convocatoria_briefing_canonical_v1``.
    """
    if not isinstance(session_state, dict):
        session_state = {}

    blocks = [
        _build_block(session_state, "administrative"),
        _build_block(session_state, "technical"),
        _build_block(session_state, "economic"),
    ]
    track, reason = _resolve_first_track(session_state)
    first_action = _resolve_first_action(session_state, track)
    from app.services.evidence_anchor_service import reason_plain_with_anchor

    reason = reason_plain_with_anchor(
        policy_reason=reason,
        anchor=first_action.get("evidence_anchor") if isinstance(first_action, dict) else None,
    )

    briefing = {
        "schema_version": SCHEMA_VERSION,
        "tender_object_plain": _tender_object_plain(session_state),
        "blocks": blocks,
        "recommended_first_track": track,
        "recommended_first_track_reason_plain": reason,
        "recommended_first_action": first_action,
        "quality_signals": _quality_signals(session_state, blocks),
        "policy_version": policy_version(),
    }
    briefing["content_hash"] = briefing_content_hash(briefing)
    return briefing


def briefing_content_hash(briefing: Dict[str, Any]) -> str:
    """Hash semántico estable (excluye content_hash)."""
    payload = {k: v for k, v in briefing.items() if k != "content_hash"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def merge_convocatoria_briefing_v1(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recalcula briefing si está habilitado; retorna updates para merge en sesión.

    Returns:
        Dict con ``convocatoria_briefing_v1`` si aplica.
    """
    if not convocatoria_briefing_enabled():
        return {}
    briefing = build_convocatoria_briefing_canonical_v1(session_state)
    prev = session_state.get("convocatoria_briefing_v1")
    if isinstance(prev, dict) and prev.get("content_hash") == briefing.get("content_hash"):
        return {}
    return {"convocatoria_briefing_v1": briefing}


async def run_convocatoria_briefing_post_analysis_hook(
    memory: Any,
    session_id: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Persiste briefing tras análisis. Hook universal post ``stage_completed:analysis``.
    """
    if not convocatoria_briefing_enabled():
        return None

    state = dict(session_state or {})
    if memory is not None:
        try:
            fresh = await memory.get_session(session_id)
            if isinstance(fresh, dict):
                state = fresh
        except Exception:
            pass

    updates = merge_convocatoria_briefing_v1(state)
    if not updates:
        existing = state.get("convocatoria_briefing_v1")
        if isinstance(existing, dict):
            return {"status": "unchanged", "content_hash": existing.get("content_hash")}
        return None

    await memory.save_session(session_id, updates)
    briefing = updates.get("convocatoria_briefing_v1") or {}
    return {
        "status": "persisted",
        "content_hash": briefing.get("content_hash"),
        "recommended_first_track": briefing.get("recommended_first_track"),
    }
