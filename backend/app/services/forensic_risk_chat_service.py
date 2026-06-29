"""
Respuesta conversacional anclada para consultas desde el panel de riesgos forenses (HRU).

Cascada: evidencia indexada → desambiguación por fragmento → plantilla policy → refinado LLM opcional.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.services.economic_alert_classifier import (
    SUBTYPE_AMBIGUOUS_PRESUPUESTO,
    SUBTYPE_CONVOCANTE_BUDGET,
    SUBTYPE_GUARANTEE_INSURANCE,
    SUBTYPE_OFFER_FLOOR,
    UX_REASON_BY_SUBTYPE,
    ux_reason_for_subtype,
    _load_policy,
    classify_economic_alert_text,
    disambiguate_subtype_with_evidence,
    resolve_session_currency,
)

_FORBIDDEN_INVENTED_ORG = re.compile(
    r"(?i)\b(direcci[oó]n\s+general|secretar[ií]a\s+de|dependencia\s+municipal|"
    r"gobierno\s+del\s+estado|ayuntamiento)\b"
)

_TEMPLATE_KEY_BY_SUBTYPE: Dict[str, str] = {
    SUBTYPE_OFFER_FLOOR: "offer_floor",
    SUBTYPE_AMBIGUOUS_PRESUPUESTO: "ambiguous_presupuesto",
    SUBTYPE_CONVOCANTE_BUDGET: "convocante_budget",
    SUBTYPE_GUARANTEE_INSURANCE: "guarantee_insurance",
}


def _literal_from_context(ctx: Dict[str, Any]) -> str:
    lit = str(ctx.get("literal") or ctx.get("texto") or "").strip()
    if lit:
        return lit
    texto = ctx.get("texto")
    if isinstance(texto, dict):
        return str(
            texto.get("descripcion") or texto.get("nombre") or texto.get("requisito") or ""
        ).strip()
    return str(texto or "").strip()


def _resolve_subtype(
    ctx: Dict[str, Any],
    literal: str,
    snippet: Optional[str],
) -> str:
    base = classify_economic_alert_text(literal)
    stale = str(ctx.get("alert_subtype") or "").strip()
    if base == "generic_economic" and stale:
        base = stale
    return disambiguate_subtype_with_evidence(base, literal, snippet)


def _extract_amount(literal: str) -> str:
    m = re.search(r"\$[\d,]+(?:\.\d{2})?", literal)
    return m.group(0) if m else "el monto indicado en las bases"


def _currency_suffix(currency: str) -> str:
    c = str(currency or "").strip()
    return f" {c}" if c else ""


def _build_page_block(
    templates: Dict[str, str],
    literal: str,
    page: Any,
    snippet: Any,
    *,
    amount: str = "",
    currency_suffix: str = "",
) -> str:
    page_str = str(page).strip() if page is not None else ""
    if page_str:
        snippet_block = ""
        if snippet and str(snippet).strip():
            sn = str(snippet).strip()
            if len(sn) > 320:
                sn = sn[:317] + "…"
            snippet_block = templates.get("snippet_block", "").format(snippet=sn)
        return templates.get("page_block_with_page", "").format(
            page=page_str,
            snippet_block=snippet_block,
        )
    tpl = templates.get("page_block_without_page", "")
    try:
        return tpl.format(
            literal=literal[:200],
            amount=amount or _extract_amount(literal),
            currency_suffix=currency_suffix,
        )
    except KeyError:
        return tpl.format(literal=literal[:200])


def _sanitize_reply(text: str, literal: str, snippet: str = "") -> str:
    if not text:
        return text
    allowed = f"{literal} {snippet}".lower()

    def _replace_if_not_allowed(match: re.Match[str]) -> str:
        frag = match.group(0)
        if frag.lower() in allowed:
            return frag
        return "la dependencia convocante"

    return _FORBIDDEN_INVENTED_ORG.sub(_replace_if_not_allowed, text)


def build_forensic_risk_chat_reply(
    ctx: Dict[str, Any],
    *,
    evidence: Optional[Dict[str, Any]] = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Genera respuesta en prosa desde plantilla policy + evidencia."""
    literal = _literal_from_context(ctx)
    kind = str(ctx.get("risk_kind") or "").strip()

    page = ctx.get("page")
    snippet = ctx.get("snippet")
    if evidence:
        ev_conf = str(evidence.get("match_confidence") or "").lower()
        if ev_conf == "alta":
            if page is None or str(page).strip() == "":
                page = evidence.get("page")
        else:
            page = None
        if not snippet or not str(snippet).strip():
            snippet = evidence.get("snippet")

    snippet_str = str(snippet or "").strip()
    subtype = _resolve_subtype(ctx, literal, snippet_str or None)

    templates = dict(_load_policy().get("conversational_templates") or {})
    amount = _extract_amount(literal)
    currency = resolve_session_currency(session_state)
    currency_suffix = _currency_suffix(currency)
    page_block = _build_page_block(
        templates, literal, page, snippet, amount=amount, currency_suffix=currency_suffix,
    )

    if kind == "knockout_causal":
        template_key = "knockout_causal"
    else:
        template_key = _TEMPLATE_KEY_BY_SUBTYPE.get(subtype, "economic_alert")

    body_tpl = templates.get(template_key) or templates.get("economic_alert", "")
    if not body_tpl:
        reason = ux_reason_for_subtype(subtype)
        body = f"El riesgo detectado se refiere a: «{literal}». {reason}{page_block}"
    else:
        body = body_tpl.format(
            amount=amount,
            currency_suffix=currency_suffix,
            literal=literal,
            page_block=page_block,
        )

    return _sanitize_reply(body.strip(), literal, snippet_str)


def _enforce_evidence_page_in_reply(text: str, draft: str, evidence: Dict[str, Any]) -> str:
    """Evita que el refinado LLM invente o cambie el número de página."""
    page = evidence.get("page")
    page_str = str(page).strip() if page is not None else ""
    if not text:
        return draft
    if not page_str:
        cleaned = re.sub(r"(?i)\ben la p[aá]gina\s+\d+\b", "", text)
        cleaned = re.sub(r"(?i)\bp[aá]gina\s+\d+\b", "", cleaned)
        return re.sub(r"\s{2,}", " ", cleaned).strip() or draft
    if page_str not in text:
        if page_str in draft:
            return draft
        return f"{text.rstrip()} Puedes leer el párrafo completo en las bases que subiste: ve a la página {page_str}."
    return text


async def _maybe_refine_with_llm(
    draft: str,
    literal: str,
    evidence: Dict[str, Any],
    *,
    session_id: str = "",
) -> str:
    """Refina prosa con LLM solo si hay fragmento indexado (anclaje estricto)."""
    snippet = str(evidence.get("snippet") or "").strip()
    if not snippet or len(snippet) < 20:
        return draft
    page = evidence.get("page")
    if page is None:
        return draft
    policy = _load_policy()
    system = str(policy.get("llm_refine_system_prompt") or "").strip()
    if not system:
        return draft

    page_txt = str(page).strip() if page is not None else "no determinada"
    prompt = (
        f"LITERAL DEL DICTAMEN:\n{literal}\n\n"
        f"PÁGINA EN BASES:\n{page_txt}\n\n"
        f"FRAGMENTO INDEXADO:\n{snippet}\n\n"
        f"BORRADOR A REESCRIBIR (mantén los hechos, mejora claridad):\n{draft}\n"
    )
    try:
        from app.services.resilient_llm import ResilientLLMClient

        llm = ResilientLLMClient()
        res = await llm.generate(
            prompt=prompt,
            system_prompt=system,
            correlation_id=session_id or "forensic-risk-chat",
        )
        if res.success and res.response and len(res.response.strip()) > 40:
            refined = res.response.strip()
            refined = _sanitize_reply(refined, literal, snippet)
            return _enforce_evidence_page_in_reply(refined, draft, evidence)
    except Exception:
        pass
    return draft


async def try_answer_forensic_risk_question(
    user_query: str,
    ctx: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
    memory: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """Devuelve respuesta anclada si hay contexto de riesgo forense."""
    if not user_query or not isinstance(ctx, dict):
        return None
    if not ctx.get("force_grounded") and not ctx.get("risk_id"):
        return None
    literal = _literal_from_context(ctx)
    if not literal:
        return None

    state = session_state or {}
    evidence: Dict[str, Any] = {}
    sid = str(session_id or ctx.get("session_id") or "").strip()
    if sid:
        from app.services.forensic_risk_evidence_service import resolve_forensic_risk_evidence

        evidence = await resolve_forensic_risk_evidence(
            sid,
            literal,
            risk_ctx=ctx,
            session_state=state,
            memory=memory,
        )

    draft = build_forensic_risk_chat_reply(
        ctx,
        evidence=evidence or None,
        session_state=state,
    )
    refined = await _maybe_refine_with_llm(draft, literal, evidence, session_id=sid)

    from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1

    excerpt = await fetch_bases_excerpt_v1(
        sid,
        literal,
        session_state=state,
        memory=memory,
        evidence=evidence,
    )
    from app.services.economic_risk_evidence_v1 import build_evidence_v1

    evidence_v1 = build_evidence_v1(evidence, literal=literal)
    return {"respuesta": refined, "bases_excerpt_v1": excerpt, "evidence_v1": evidence_v1}
