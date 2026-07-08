"""
UX HRU para deducciones operativas por personal (servicios en sitio).

Contratos:
  - ``operational_deduction_policy.json`` (detección y escaneo de fragmentos)
  - ``operational_deduction_ux_messages.json`` (copy al usuario)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "operational_deduction_policy.json"
_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "operational_deduction_ux_messages.json"

_GOODS_MORA_MARKERS = (
    "mora",
    "bienes pendientes de entregar",
    "2.5%",
    "atraso en la entrega",
    "retraso en la entrega",
)


@lru_cache(maxsize=1)
def load_operational_deduction_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_operational_deduction_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_operational_deduction_policy().get("policy_version") or "")


def ux_messages_version() -> str:
    return str(load_operational_deduction_ux_messages().get("messages_version") or "")


def _norm_query(query: str) -> str:
    raw = (query or "").strip().lower()
    nk = raw.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", nk).strip()


def detect_operational_personnel_penalty_intent(
    query: str,
    *,
    penalty_intent: bool = False,
) -> bool:
    """True si la consulta es por deducciones operativas de personal, no penas contractuales genéricas."""
    if penalty_intent:
        return False
    cfg = load_operational_deduction_policy().get("intent") or {}
    q = _norm_query(query)
    personnel = [str(x).lower() for x in (cfg.get("personnel_markers") or [])]
    penalty = [str(x).lower() for x in (cfg.get("penalty_markers") or [])]
    if cfg.get("require_personnel_marker") and not any(m in q for m in personnel):
        return False
    if cfg.get("require_penalty_marker") and not any(m in q for m in penalty):
        return False
    return True


def _clip_excerpt(text: str, limit: int = 280) -> str:
    clean = re.sub(r"\s+", " ", str(text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rsplit(" ", 1)[0] + "…"


def extract_deduction_bullet_from_fragments(context_docs: Sequence[str]) -> str:
    """Resume deducción desde fragmentos indexados del pliego (sin páginas fijas)."""
    policy = load_operational_deduction_policy().get("fragment_scan") or {}
    topics = [str(x).lower() for x in (policy.get("topic_markers") or [])]
    substance = [str(x).lower() for x in (policy.get("substance_markers") or [])]
    ux = load_operational_deduction_ux_messages()
    tpl = str(ux.get("from_bases_bullet") or "")
    for doc in context_docs or []:
        low = str(doc or "").lower()
        if not any(t in low for t in topics):
            continue
        if not any(s in low for s in substance):
            continue
        return tpl.format(excerpt=_clip_excerpt(doc))
    return ""


def build_fallback_deduction_bullet() -> str:
    return str(load_operational_deduction_ux_messages().get("fallback_bullet") or "")


def llm_system_rule_text() -> str:
    return str(load_operational_deduction_ux_messages().get("llm_system_rule") or "")


def insolvency_budget_alert_text() -> str:
    return str(load_operational_deduction_ux_messages().get("insolvency_budget_alert") or "")


def _content_suggests_goods_mora_hallucination(content: str) -> bool:
    low = str(content or "").lower()
    return any(m in low for m in _GOODS_MORA_MARKERS)


def apply_goods_mora_correction(content: str) -> str:
    """Sustituye frases de mora en bienes por redacción universal."""
    policy = load_operational_deduction_policy()
    replacement = str(policy.get("goods_mora_replacement") or "")
    out = str(content or "")
    for phrase in policy.get("goods_mora_hallucination_phrases") or []:
        p = str(phrase)
        if p in out:
            out = out.replace(p, replacement)
    return out


def apply_operational_deduction_post_llm(
    content: str,
    *,
    context_docs: Sequence[str],
) -> str:
    """
    Corrige respuestas RAG que mezclan penas por bienes con deducciones operativas de personal.
    """
    if not _content_suggests_goods_mora_hallucination(content):
        return content

    ux = load_operational_deduction_ux_messages()
    deduc_text = extract_deduction_bullet_from_fragments(context_docs)
    if not deduc_text:
        deduc_text = build_fallback_deduction_bullet()

    clean_content = apply_goods_mora_correction(content)
    note = str(ux.get("correction_note") or "").strip()
    if note and "deducciones operativas" not in clean_content.lower():
        clean_content = f"{clean_content}\n\n{note}"

    if "deducción" not in clean_content.lower() and "deduccion" not in clean_content.lower():
        header = str(ux.get("section_header") or "")
        clean_content = f"{clean_content}\n\n{header}\n{deduc_text}"

    return clean_content
