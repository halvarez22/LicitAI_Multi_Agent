"""
Motor determinista F8: subtotal / IVA / total para copiloto económico en chat.

Reglas en ``economic_calculation_policy.json``; copy en ``chat_copilot_ux_messages.json``.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.config.settings import settings

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "economic_calculation_policy.json"
)
_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "chat_copilot_ux_messages.json"

_MONEY_Q = Decimal("0.01")


@lru_cache(maxsize=1)
def load_economic_calculation_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_chat_copilot_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def economic_calc_on_capture_enabled() -> bool:
    """Flag F8: totales en chat tras cada captura. Off → comportamiento legacy."""
    return bool(getattr(settings, "ECONOMIC_CHAT_CALC_ON_CAPTURE", True))


def _ux_economic() -> Dict[str, str]:
    raw = load_chat_copilot_ux_messages().get("economic_capture") or {}
    return {str(k): str(v) for k, v in raw.items()}


def _to_money(value: Any) -> Decimal:
    policy = load_economic_calculation_policy()
    decimals = int((policy.get("rounding") or {}).get("money_decimals", 2))
    q = Decimal(10) ** -decimals
    try:
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, str):
            dec = Decimal(value.replace(",", "").replace("$", "").strip() or "0")
        else:
            dec = Decimal(str(value))
    except Exception:
        dec = Decimal("0")
    return dec.quantize(q, rounding=ROUND_HALF_UP)


def format_money_mxn(amount: Any, *, policy: Optional[Dict[str, Any]] = None) -> str:
    """Formatea importe con símbolo y código de moneda (HRU universal)."""
    pol = policy or load_economic_calculation_policy()
    symbol = str(pol.get("currency_symbol") or "$")
    code = str(pol.get("currency_code") or "MXN")
    dec = _to_money(amount)
    decimals = int((pol.get("rounding") or {}).get("money_decimals", 2))
    body = f"{dec:,.{decimals}f}"
    return f"{symbol}{body} {code}"


def _flatten_reglas(session_state: Dict[str, Any]) -> Dict[str, str]:
    analysis = session_state.get("analysis") or {}
    if isinstance(analysis.get("results"), dict):
        nested = analysis["results"].get("analysis")
        if isinstance(nested, dict):
            analysis = nested
    reglas = (
        analysis.get("reglas_economicas")
        or session_state.get("reglas_economicas")
        or {}
    )
    out: Dict[str, str] = {}
    if not isinstance(reglas, dict):
        return out
    for key, val in reglas.items():
        if isinstance(val, dict):
            text = str(val.get("text") or val.get("valor") or val.get("value") or "")
        else:
            text = str(val or "")
        if text.strip():
            out[str(key)] = text.strip()
    return out


def _reglas_blob(session_state: Dict[str, Any], policy: Dict[str, Any]) -> str:
    reglas = _flatten_reglas(session_state)
    keys = list(policy.get("reglas_blob_keys") or []) + list(reglas.keys())
    parts: List[str] = []
    seen = set()
    for key in keys:
        k = str(key)
        if k in seen:
            continue
        seen.add(k)
        if k in reglas:
            parts.append(reglas[k])
    return " ".join(parts).lower()


def _extract_bases_excerpt(session_state: Dict[str, Any], topic: str = "iva") -> Optional[str]:
    anchored = session_state.get("reglas_economicas_anchored_v1")
    if not isinstance(anchored, dict):
        analysis = session_state.get("analysis") or {}
        if isinstance(analysis.get("results"), dict):
            anchored = analysis["results"].get("analysis", {}).get(
                "reglas_economicas_anchored_v1"
            )
    if not isinstance(anchored, dict):
        return None
    topic_l = topic.lower()
    for key, payload in anchored.items():
        if topic_l not in str(key).lower():
            continue
        if isinstance(payload, dict):
            excerpt = payload.get("bases_excerpt") or payload.get("excerpt") or payload.get("text")
            if excerpt:
                return str(excerpt)[:400]
    for payload in anchored.values():
        if not isinstance(payload, dict):
            continue
        blob = str(payload.get("text") or payload.get("bases_excerpt") or "").lower()
        if topic_l in blob:
            ex = payload.get("bases_excerpt") or payload.get("excerpt")
            if ex:
                return str(ex)[:400]
    return None


def resolve_iva_context(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resuelve tasa IVA y exención desde política + reglas de bases (cascada HRU).
    """
    policy = load_economic_calculation_policy()
    defaults = policy.get("provenance_defaults") or {}
    blob = _reglas_blob(session_state, policy)
    exempt_markers = [str(m).lower() for m in (policy.get("iva_exempt_markers") or [])]
    iva_exempt = any(m in blob for m in exempt_markers)

    rate = Decimal(str(policy.get("default_iva_rate", 0.16)))
    if not iva_exempt:
        for spec in policy.get("iva_rate_patterns") or []:
            if not isinstance(spec, dict):
                continue
            pat = str(spec.get("pattern") or "")
            grp = int(spec.get("group") or 1)
            m = re.search(pat, blob, flags=re.I)
            if m:
                try:
                    rate = Decimal(m.group(grp)) / Decimal("100")
                    break
                except Exception:
                    pass

    if iva_exempt:
        rate = Decimal("0")
    excerpt = _extract_bases_excerpt(session_state, "iva")
    basis = (
        defaults.get("iva_exempt")
        if iva_exempt
        else defaults.get("iva_default")
    )
    provenance_ui = {
        "source": "bases_excerpt" if excerpt else "economic_calculation_policy",
        "calculation_basis": basis,
        "iva_rate": float(rate),
        "iva_exempt": iva_exempt,
    }
    if excerpt:
        provenance_ui["bases_excerpt"] = excerpt
    label = "exento" if iva_exempt else f"{float(rate) * 100:.0f} %"
    return {
        "iva_rate": float(rate),
        "iva_exempt": iva_exempt,
        "iva_label": label,
        "provenance_ui": provenance_ui,
    }


def compute_quotation_totals_from_canonical(
    canonical: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calcula subtotal / IVA / total desde ítems canónicos capturados.
    """
    policy = load_economic_calculation_policy()
    allowed = {str(s) for s in (policy.get("include_item_statuses") or ["captured"])}
    subtotal = Decimal("0")
    for raw in canonical.get("items") or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "")
        if status not in allowed:
            continue
        amount = raw.get("amount_mxn")
        if amount is None:
            continue
        subtotal += _to_money(amount)

    iva_ctx = resolve_iva_context(session_state or {})
    rate = Decimal(str(iva_ctx.get("iva_rate") or 0))
    iva = (subtotal * rate).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
    total = (subtotal + iva).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)

    return {
        "subtotal": float(subtotal),
        "iva": float(iva),
        "total": float(total),
        "iva_rate": float(rate),
        "iva_exempt": bool(iva_ctx.get("iva_exempt")),
        "iva_label": str(iva_ctx.get("iva_label") or ""),
        "currency_code": str(policy.get("currency_code") or "MXN"),
        "provenance_ui": iva_ctx.get("provenance_ui") or {},
    }


def attach_totals_to_canonical(
    canonical: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Añade ``totals`` al canónico (idempotente)."""
    out = dict(canonical or {})
    if not economic_calc_on_capture_enabled():
        return out
    totals = compute_quotation_totals_from_canonical(out, session_state=session_state)
    out["totals"] = {
        "subtotal": totals["subtotal"],
        "iva": totals["iva"],
        "total": totals["total"],
    }
    out["totals_provenance_ui"] = totals.get("provenance_ui") or {}
    return out


def format_totals_markdown_block(totals: Dict[str, Any]) -> str:
    """Tabla markdown de totales para Gate 5."""
    ux = _ux_economic()
    pol = load_economic_calculation_policy()
    lines = [
        ux.get("totals_section_title", "**Totales actualizados (cotización):**"),
        "| Concepto | Importe |",
        "|----------|---------|",
        ux.get("totals_row_subtotal", "| Subtotal | {amount} |").format(
            amount=format_money_mxn(totals.get("subtotal", 0), policy=pol)
        ),
        ux.get("totals_row_iva", "| IVA ({iva_label}) | {amount} |").format(
            iva_label=totals.get("iva_label") or "16 %",
            amount=format_money_mxn(totals.get("iva", 0), policy=pol),
        ),
        ux.get("totals_row_total", "| **Total** | **{amount}** |").format(
            amount=format_money_mxn(totals.get("total", 0), policy=pol)
        ),
    ]
    return "\n".join(lines)


def list_missing_capture_labels(
    session_state: Dict[str, Any],
    *,
    limit: int = 8,
) -> List[str]:
    """Etiquetas humanas de precios aún no capturados."""
    from app.services.economic_canonical_v1 import build_economic_canonical_v1_from_session

    canonical = build_economic_canonical_v1_from_session(session_state)
    labels: List[str] = []
    for raw in canonical.get("items") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("status") == "captured" and raw.get("amount_mxn") is not None:
            continue
        label = str(raw.get("label") or raw.get("concept_key") or "").strip()
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            return labels

    blocks = session_state.get("capture_matrix_blocks") or []
    inputs = session_state.get("economic_user_inputs") or {}
    if isinstance(inputs, dict):
        for block in blocks:
            for row in block.get("matrix_rows") or []:
                if not isinstance(row, dict):
                    continue
                field = str(row.get("field") or "").strip()
                if not field or field in inputs:
                    continue
                label = str(row.get("label") or row.get("location_label") or field).strip()
                if label and label not in labels:
                    labels.append(label)
                if len(labels) >= limit:
                    return labels
    return labels


def build_price_capture_confirmation_message(
    *,
    session_state: Dict[str, Any],
    label: str,
    amount_mxn: Any,
    next_label: Optional[str] = None,
    missing_count: Optional[int] = None,
) -> str:
    """
    Mensaje CA-2.9 tras captura exitosa de precio(s).
    """
    from app.services.economic_canonical_v1 import build_economic_canonical_v1_from_session
    from app.services.economic_capture_matrix_service import economic_capture_status

    ux = _ux_economic()
    pol = load_economic_calculation_policy()
    if not economic_calc_on_capture_enabled():
        human = label or "precio"
        return f"Listo, guardé **{human}** → **{amount_mxn}**."

    canonical = attach_totals_to_canonical(
        build_economic_canonical_v1_from_session(session_state),
        session_state=session_state,
    )
    totals = compute_quotation_totals_from_canonical(canonical, session_state=session_state)
    cap = economic_capture_status(session_state)
    missing = (
        int(missing_count)
        if missing_count is not None
        else int(cap.get("missing") or 0)
    )

    parts = [
        ux.get("price_registered_header", "").format(
            label=label,
            amount=format_money_mxn(amount_mxn, policy=pol),
        ),
        "",
        format_totals_markdown_block(totals),
    ]
    if missing > 0 and next_label:
        parts.extend(
            [
                "",
                ux.get("next_missing_prices", "").format(missing=missing),
                ux.get("next_price_prompt", "").format(next_label=next_label),
            ]
        )
    elif missing > 0:
        parts.extend(["", ux.get("next_missing_prices", "").format(missing=missing)])
    else:
        parts.extend(["", ux.get("capture_complete_generate", "")])
    return "\n".join(p for p in parts if p is not None).strip()


def build_price_capture_followup_message(
    *,
    human_saved: str,
    extracted_value: str,
    next_q: Dict[str, Any],
    session_state: Dict[str, Any],
) -> str:
    """Sustituto F8 de ``_format_economic_price_followup``."""
    from app.services.economic_capture_matrix_service import economic_capture_status

    try:
        amount = float(str(extracted_value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        amount = extracted_value
    concept_next = str(
        next_q.get("label")
        or next_q.get("question")
        or next_q.get("field")
        or "siguiente concepto"
    )
    cap = economic_capture_status(session_state)
    base = build_price_capture_confirmation_message(
        session_state=session_state,
        label=human_saved,
        amount_mxn=amount,
        next_label=concept_next,
        missing_count=int(cap.get("missing") or 0),
    )
    blocks = session_state.get("capture_matrix_blocks") or []
    if blocks and len(session_state.get("pending_questions") or []) > 3:
        from app.services.chat_economic_matrix import format_matrix_blocks_markdown

        md = format_matrix_blocks_markdown(blocks, max_rows=6)
        if md:
            return f"{base}\n\n{md}"
    return base


def build_generar_economica_incomplete_message(session_state: Dict[str, Any]) -> str:
    """Repregunta acotada cuando el snapshot económico está incompleto (F8)."""
    from app.services.economic_capture_matrix_service import economic_capture_status
    from app.services.chat_gate5_formatter import format_gate5_message

    ux = _ux_economic()
    cap = economic_capture_status(session_state)
    missing_labels = list_missing_capture_labels(session_state, limit=6)
    table_lines = [ux.get("missing_table_header", "")]
    for lbl in missing_labels:
        table_lines.append(ux.get("missing_row", "• {label}").format(label=lbl))
    if len(table_lines) <= 1:
        table_lines = []

    totals_block = ""
    if economic_calc_on_capture_enabled():
        from app.services.economic_canonical_v1 import build_economic_canonical_v1_from_session

        canonical = attach_totals_to_canonical(
            build_economic_canonical_v1_from_session(session_state),
            session_state=session_state,
        )
        if any(
            isinstance(i, dict) and i.get("amount_mxn") is not None
            for i in (canonical.get("items") or [])
        ):
            totals = compute_quotation_totals_from_canonical(
                canonical, session_state=session_state
            )
            totals_block = "\n\n" + format_totals_markdown_block(totals)

    detail = ux.get("generar_incomplete_detail", "").format(
        filled=int(cap.get("filled") or 0),
        total=int(cap.get("total") or 0),
    )
    if table_lines:
        detail = f"{detail}\n\n" + "\n".join(table_lines)
    if totals_block:
        detail = f"{detail}{totals_block}"

    return format_gate5_message(
        status=ux.get("generar_incomplete_lead", ""),
        detail=detail,
        cta=ux.get("cta_capture_prices", ""),
    )


def build_capture_complete_message(*, human_saved: str, semaforo_change_msg: str = "") -> str:
    """Mensaje al cerrar cola de precios — sin CTA al panel."""
    ux = _ux_economic()
    lead = f"Listo, guardé **{human_saved}**."
    body = ux.get("capture_complete_generate", "")
    return f"{lead}{semaforo_change_msg}\n\n{body}".strip()


def economic_capture_cta(*, capture_complete: bool) -> str:
    """CTA único para rutas de captura económica activa."""
    ux = _ux_economic()
    if capture_complete:
        return ux.get("cta_generate_economic", "")
    return ux.get("cta_capture_prices", "")
