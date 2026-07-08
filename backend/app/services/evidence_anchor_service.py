"""
Ancla de evidencia HRU (F12.1) — normalización y calidad fail-closed.

Toda afirmación «la convocante pide X» debe llevar ``evidence_anchor_v1``
con ``anchor_quality`` honesta. Anclas sintéticas (pág. inventada) nunca
cuentan como ``verified``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.config.settings import settings

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
_POLICY_PATH = _CONTRACTS_DIR / "evidence_anchor_policy.json"
_SCHEMA_PATH = _CONTRACTS_DIR / "evidence_anchor_v1.json"
_UX_PATH = _CONTRACTS_DIR / "pliego_pedagogico_ux_messages.json"

SCHEMA_VERSION = "evidence-anchor-v1.0.0"

_QUALITY_VERIFIED = "verified"
_QUALITY_DOCUMENT_ONLY = "document_only"
_QUALITY_INSUFFICIENT = "insufficient"
_QUALITY_SYNTHETIC = "synthetic"

_CLAIM_VISIBLE = frozenset({_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY})


@lru_cache(maxsize=1)
def load_evidence_anchor_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_pliego_pedagogico_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_evidence_anchor_policy().get("policy_version") or "")


def evidence_anchor_enabled() -> bool:
    return bool(getattr(settings, "EVIDENCE_ANCHOR_ENABLED", True))


def _as_page(raw: Any) -> Optional[int]:
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    return page if page >= 1 else None


def _as_row(raw: Any) -> Optional[int]:
    try:
        row = int(float(raw))
    except (TypeError, ValueError):
        return None
    return row if row >= 1 else None


def _looks_synthetic_snippet(snippet: str, policy: Dict[str, Any]) -> bool:
    for pat in policy.get("synthetic_snippet_markers") or []:
        if re.search(str(pat), snippet or ""):
            return True
    return False


def _looks_synthetic_source(source: str, policy: Dict[str, Any]) -> bool:
    for pat in policy.get("synthetic_source_markers") or []:
        if re.search(str(pat), source or ""):
            return True
    return False


def _provenance_ui(
    *,
    quality: str,
    source_name: str,
    page: Optional[int],
) -> Dict[str, Any]:
    if quality == _QUALITY_VERIFIED and page:
        label = f"Bases · p. {page}"
        if source_name and not _looks_synthetic_source(source_name, load_evidence_anchor_policy()):
            short = source_name if len(source_name) <= 42 else source_name[:39] + "…"
            label = f"Bases · {short} · p. {page}"
        return {
            "source": "bases_document",
            "page": page,
            "label": label,
            "anchor_quality": quality,
        }
    if quality == _QUALITY_DOCUMENT_ONLY:
        return {
            "source": "bases_document",
            "page": None,
            "label": "Según el pliego (sin página localizada)",
            "anchor_quality": quality,
        }
    return {
        "source": "none",
        "page": None,
        "label": "",
        "anchor_quality": quality if quality in (_QUALITY_INSUFFICIENT, _QUALITY_SYNTHETIC) else _QUALITY_INSUFFICIENT,
    }


def build_insufficient_anchor(*, claim_id: str = "") -> Dict[str, Any]:
    """Ancla canónica cuando no hay locus usable."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source_name": "",
        "page": None,
        "row_index": None,
        "snippet": "",
        "numeral_hint": "",
        "annex_hint": "",
        "anchor_quality": _QUALITY_INSUFFICIENT,
        "verification": {"method": "none", "passed": False},
        "claim_id": claim_id or "",
        "provenance_ui": _provenance_ui(quality=_QUALITY_INSUFFICIENT, source_name="", page=None),
    }


def normalize_evidence_anchor(
    raw: Optional[Dict[str, Any]],
    *,
    claim_id: str = "",
    treat_missing_as_insufficient: bool = True,
    force_synthetic: bool = False,
    page_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normaliza un dict heterogéneo a ``evidence_anchor_v1``.

    Args:
        raw: Diccionario con campos legacy (page/pagina/page_number, snippet, source…).
        claim_id: Identificador auditable del claim.
        treat_missing_as_insufficient: Si raw vacío → insufficient.
        force_synthetic: Marca calidad synthetic (fallback chat).
        page_text: Texto de la página para verificación opcional substring.

    Returns:
        Ancla canónica con ``anchor_quality``.
    """
    policy = load_evidence_anchor_policy()
    min_snip = int(policy.get("min_snippet_len") or 12)
    min_verified = int(policy.get("min_snippet_len_verified") or 20)

    if not isinstance(raw, dict) or not raw:
        if treat_missing_as_insufficient:
            return build_insufficient_anchor(claim_id=claim_id)
        return build_insufficient_anchor(claim_id=claim_id)

    source = str(
        raw.get("source_name")
        or raw.get("source")
        or raw.get("archivo_fuente")
        or raw.get("documento")
        or ""
    ).strip()
    page = _as_page(
        raw.get("page")
        if raw.get("page") is not None
        else raw.get("pagina")
        if raw.get("pagina") is not None
        else raw.get("page_number")
    )
    row_index = _as_row(raw.get("row_index"))
    snippet = str(
        raw.get("snippet")
        or raw.get("evidence_snippet")
        or raw.get("context_snippet")
        or raw.get("texto_literal")
        or ""
    ).strip()
    numeral = str(raw.get("numeral_hint") or raw.get("numeral") or "").strip()
    annex = str(raw.get("annex_hint") or raw.get("anexo") or "").strip()
    claimed_synthetic = force_synthetic or bool(raw.get("is_synthetic")) or str(
        raw.get("anchor_quality") or ""
    ).strip().lower() == _QUALITY_SYNTHETIC

    synthetic = claimed_synthetic or _looks_synthetic_snippet(snippet, policy)
    # page=1 + snippet sintético / source genérico → synthetic
    if page == 1 and (_looks_synthetic_snippet(snippet, policy) or _looks_synthetic_source(source, policy)):
        synthetic = True

    verification: Dict[str, Any] = {"method": "none", "passed": False}
    if page_text and snippet and len(snippet) >= min_snip:
        verification = verify_snippet_on_page_text(snippet, page_text)

    if synthetic and bool(policy.get("forbid_synthetic_as_verified", True)):
        quality = _QUALITY_SYNTHETIC
    elif page and len(snippet) >= min_verified and not synthetic:
        if page_text:
            quality = _QUALITY_VERIFIED if verification.get("passed") else _QUALITY_DOCUMENT_ONLY
            if not verification.get("passed"):
                verification = {
                    "method": verification.get("method") or "substring_on_page",
                    "passed": False,
                }
        else:
            quality = _QUALITY_VERIFIED
            verification = {"method": "metadata_only", "passed": True}
    elif page and len(snippet) >= min_snip and not synthetic:
        quality = _QUALITY_VERIFIED
        verification = {"method": "metadata_only", "passed": True}
    elif (source and not _looks_synthetic_source(source, policy)) or row_index:
        quality = _QUALITY_DOCUMENT_ONLY
    elif page and not snippet:
        quality = _QUALITY_DOCUMENT_ONLY
    else:
        quality = _QUALITY_INSUFFICIENT

    # Para claims de UI, synthetic se degrada a insufficient en visibility
    effective_quality = quality
    if quality == _QUALITY_SYNTHETIC:
        # Persistimos synthetic para auditoría; visibility se trata como insufficient
        effective_quality = _QUALITY_SYNTHETIC

    return {
        "schema_version": SCHEMA_VERSION,
        "source_name": source,
        "page": page,
        "row_index": row_index,
        "snippet": snippet[:500],
        "numeral_hint": numeral,
        "annex_hint": annex,
        "anchor_quality": effective_quality,
        "verification": verification,
        "claim_id": claim_id or str(raw.get("claim_id") or ""),
        "provenance_ui": _provenance_ui(
            quality=_QUALITY_INSUFFICIENT if effective_quality == _QUALITY_SYNTHETIC else effective_quality,
            source_name=source,
            page=page if effective_quality == _QUALITY_VERIFIED else None,
        ),
    }


def verify_snippet_on_page_text(snippet: str, page_text: str) -> Dict[str, Any]:
    """
    Verificación ligera: substring normalizado o 3 tokens consecutivos.
    Reusa el espíritu de ``junta_citation_gate`` sin acoplar corpus completo.
    """
    from app.services.junta_citation_gate import (
        _consecutive_token_run_at_citation_start,
        _accent_fold,
    )

    s = str(snippet or "").strip()
    t = str(page_text or "")
    if not s or not t:
        return {"method": "substring_on_page", "passed": False}
    folded_s = _accent_fold(s.lower())
    folded_t = _accent_fold(t.lower())
    if len(folded_s) >= 12 and folded_s[:80] in folded_t:
        return {"method": "substring_on_page", "passed": True}
    if _consecutive_token_run_at_citation_start(s, t, run_len=3):
        return {"method": "token_run_on_page", "passed": True}
    return {"method": "substring_on_page", "passed": False}


def is_claim_locus_visible(anchor: Optional[Dict[str, Any]]) -> bool:
    """True si el claim puede mostrar locus de bases al usuario."""
    if not isinstance(anchor, dict):
        return False
    q = str(anchor.get("anchor_quality") or "")
    if q == _QUALITY_SYNTHETIC:
        return False
    return q in _CLAIM_VISIBLE


def claim_quality_for_ux(anchor: Optional[Dict[str, Any]]) -> str:
    """Calidad efectiva para plantillas UX (synthetic → insufficient)."""
    if not isinstance(anchor, dict):
        return _QUALITY_INSUFFICIENT
    q = str(anchor.get("anchor_quality") or _QUALITY_INSUFFICIENT)
    if q == _QUALITY_SYNTHETIC:
        return _QUALITY_INSUFFICIENT
    return q


def format_claim_locus(anchor: Optional[Dict[str, Any]]) -> str:
    """Fragmento corto «(Bases · p. N)» o vacío si no hay locus visible."""
    if not evidence_anchor_enabled():
        return ""
    msgs = load_pliego_pedagogico_ux_messages()
    locus_tpl = msgs.get("claim_locus") if isinstance(msgs.get("claim_locus"), dict) else {}
    q = claim_quality_for_ux(anchor)
    if q == _QUALITY_VERIFIED:
        page = (anchor or {}).get("page")
        source = str((anchor or {}).get("source_name") or "").strip()
        if source and not _looks_synthetic_source(source, load_evidence_anchor_policy()):
            return str(locus_tpl.get("verified_with_source") or "(Bases · {source_name} · p. {page})").format(
                page=page,
                source_name=source[:42],
            )
        return str(locus_tpl.get("verified") or "(Bases · p. {page})").format(page=page)
    if q == _QUALITY_DOCUMENT_ONLY:
        return str(locus_tpl.get("document_only") or "")
    return str(locus_tpl.get("insufficient") or "")


def reason_plain_with_anchor(
    *,
    policy_reason: str,
    anchor: Optional[Dict[str, Any]],
) -> str:
    """
    Reason de briefing: si hay ancla verified, conserva el reason de política
    (el locus visible va en first_action). Si no hay locus, degrada sin fingir PDF.
    """
    msgs = load_pliego_pedagogico_ux_messages()
    q = claim_quality_for_ux(anchor)
    base = str(policy_reason or "").strip()
    if q == _QUALITY_VERIFIED:
        return base
    if q == _QUALITY_DOCUMENT_ONLY:
        locus = format_claim_locus(anchor)
        return f"{base} {locus}".strip() if base else locus
    degraded = str(msgs.get("reason_degraded") or "").strip()
    return degraded or base


def extract_anchor_from_pending_question(pending: Dict[str, Any]) -> Dict[str, Any]:
    """Deriva ancla desde pending HITL (blocking_items / original_item / campos planos)."""
    if not isinstance(pending, dict):
        return build_insufficient_anchor(claim_id="pending")

    items = pending.get("blocking_items") if isinstance(pending.get("blocking_items"), list) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        raw = {
            "source_name": it.get("source_name") or it.get("source"),
            "page": it.get("page_number") if it.get("page_number") is not None else it.get("page"),
            "snippet": it.get("context_snippet") or it.get("snippet"),
            "row_index": it.get("row_index"),
            "claim_id": "pending.blocking_item",
        }
        anchor = normalize_evidence_anchor(raw, claim_id="pending.blocking_item")
        if str(anchor.get("anchor_quality")) in (_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY):
            return anchor

    oi = pending.get("original_item") if isinstance(pending.get("original_item"), dict) else {}
    if oi:
        return normalize_evidence_anchor(
            {
                "source_name": oi.get("source"),
                "page": oi.get("page"),
                "snippet": oi.get("snippet"),
                "row_index": oi.get("row_index"),
            },
            claim_id="pending.original_item",
            force_synthetic=bool(oi.get("is_synthetic")),
        )

    return normalize_evidence_anchor(
        {
            "source_name": pending.get("archivo_fuente") or pending.get("source"),
            "page": pending.get("pagina") if pending.get("pagina") is not None else pending.get("page"),
            "snippet": pending.get("evidence_snippet") or pending.get("snippet"),
        },
        claim_id="pending.flat",
    )


def extract_anchor_from_compliance_items(
    items: Sequence[Dict[str, Any]],
    *,
    claim_id: str = "compliance",
) -> Dict[str, Any]:
    """Primera ancla usable desde ítems de compliance / CCC."""
    for item in items:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        if page is None:
            page = item.get("pagina")
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        if page is None:
            page = evidence.get("page")
        snippet = (
            item.get("snippet")
            or item.get("evidence_snippet")
            or evidence.get("snippet")
            or item.get("texto_literal")
            or ""
        )
        source = (
            item.get("archivo_fuente")
            or item.get("source")
            or item.get("source_name")
            or evidence.get("source")
            or ""
        )
        anchor = normalize_evidence_anchor(
            {
                "source_name": source,
                "page": page,
                "snippet": snippet,
            },
            claim_id=claim_id,
        )
        if str(anchor.get("anchor_quality")) in (_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY):
            return anchor
    return build_insufficient_anchor(claim_id=claim_id)


def extract_anchor_from_session_for_track(
    session_state: Dict[str, Any],
    track: str,
) -> Dict[str, Any]:
    """
    Cascada de precedencia F12 para el primer paso del briefing.
    """
    if not evidence_anchor_enabled():
        return build_insufficient_anchor(claim_id=f"briefing.{track}")

    state = session_state if isinstance(session_state, dict) else {}

    # 1) Pending blocking / price_source
    for q in state.get("pending_questions") or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "")
        if track == "economic" and qtype in (
            "economic_validation_blocking",
            "economic_price",
            "economic_price_matrix",
        ):
            anchor = extract_anchor_from_pending_question(q)
            if claim_quality_for_ux(anchor) in (_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY):
                return anchor

    # 2) Compliance por categoría del track
    cml = state.get("compliance_master_list") if isinstance(state.get("compliance_master_list"), dict) else {}
    cat_map = {
        "economic": ["economico"],
        "technical": ["tecnico", "formatos"],
        "administrative": ["administrativo"],
    }
    items: List[Dict[str, Any]] = []
    for cat in cat_map.get(track, []):
        for it in cml.get(cat) or []:
            if isinstance(it, dict):
                items.append(it)
    if items:
        anchor = extract_anchor_from_compliance_items(items, claim_id=f"briefing.{track}.compliance")
        if claim_quality_for_ux(anchor) in (_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY):
            return anchor

    # 3) Line items con page en extra
    if track == "economic":
        for row in state.get("session_line_items") or []:
            if not isinstance(row, dict):
                continue
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            raw = {
                "source_name": extra.get("source") or evidence.get("source") or row.get("source"),
                "page": extra.get("page") or evidence.get("page") or row.get("page"),
                "snippet": extra.get("snippet") or evidence.get("snippet") or row.get("snippet"),
                "row_index": row.get("row_index") or extra.get("row_index"),
            }
            anchor = normalize_evidence_anchor(raw, claim_id="briefing.economic.line_item")
            if claim_quality_for_ux(anchor) in (_QUALITY_VERIFIED, _QUALITY_DOCUMENT_ONLY):
                return anchor

    # 4) page_refs del bloque ya construido (si vienen en session briefing previo)
    briefing = state.get("convocatoria_briefing_v1")
    if isinstance(briefing, dict):
        for block in briefing.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("block_id") or "") != track and not (
                track == "administrative" and block.get("block_id") == "administrative"
            ):
                if str(block.get("block_id") or "") not in (track,):
                    continue
            prov = block.get("provenance_ui") if isinstance(block.get("provenance_ui"), dict) else {}
            refs = prov.get("page_refs") if isinstance(prov.get("page_refs"), list) else []
            if refs:
                page = _as_page(refs[0])
                if page:
                    return normalize_evidence_anchor(
                        {
                            "source_name": str(prov.get("source") or "bases"),
                            "page": page,
                            "snippet": " ".join(str(x) for x in (block.get("example_items") or [])[:1]),
                        },
                        claim_id=f"briefing.{track}.page_refs",
                    )

    return build_insufficient_anchor(claim_id=f"briefing.{track}")


def attach_evidence_anchor_to_dict(
    target: Dict[str, Any],
    anchor: Dict[str, Any],
) -> Dict[str, Any]:
    """Adjunta ancla y sincroniza ``provenance_ui.page_refs`` cuando hay página verified."""
    out = dict(target)
    out["evidence_anchor"] = anchor
    page = anchor.get("page") if claim_quality_for_ux(anchor) == _QUALITY_VERIFIED else None
    prov = dict(out.get("provenance_ui") or {}) if isinstance(out.get("provenance_ui"), dict) else {}
    if page:
        refs = list(prov.get("page_refs") or [])
        if page not in refs:
            refs = [page] + [r for r in refs if r != page]
        prov["page_refs"] = refs[:6]
        prov["label"] = (anchor.get("provenance_ui") or {}).get("label") or prov.get("label")
        prov["anchor_quality"] = anchor.get("anchor_quality")
    else:
        prov.setdefault("page_refs", [])
        prov["anchor_quality"] = claim_quality_for_ux(anchor)
    out["provenance_ui"] = prov
    return out
