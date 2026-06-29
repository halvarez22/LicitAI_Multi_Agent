"""
Procedencia económica HRU — respuestas deterministas (sin RAG) sobre totales y catálogo.

Universal: obra, servicios, suministros. Deriva hechos de ``economic_proposal``,
``capture_matrix_blocks``, ``economic_user_inputs`` y archivos generados en disco.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_CATALOG_MARKERS = (
    "catalogo de conceptos",
    "catálogo de conceptos",
    "catalogo de concepto",
    "catálogo de concepto",
    "mis precios",
    "mis price",
    "usaste mi catalogo",
    "usaste mi catálogo",
    "usaste para armar",
    "proporcione en mi",
    "proporcione en el",
    "como viste mis precios",
    "como viste mis price",
    "conocerlos ya que se supone",
    "archivos descargados",
    "ya los descargue",
    "ya los descargué",
)

_TOTAL_MARKERS = (
    "de donde sacaste",
    "de dónde sacaste",
    "donde sacaste",
    "dónde sacaste",
    "este total",
    "total de la proposicion",
    "total de la proposición",
    "total de la propuesta",
    "ya generaste nuestra propuesta",
    "ya generaste la propuesta",
    "propuesta economica generada",
    "propuesta económica generada",
    "anexo ae",
    "anexo e-1",
    "documento que generaste",
)

_ORIGIN_MARKERS = (
    "de donde",
    "de dónde",
    "origen",
    "procedencia",
    "como se calculo",
    "como se calculó",
    "porque ese total",
    "por qué ese total",
)

_CATALOG_FILENAME_RE = re.compile(
    r"(?i)\b(catalogo|catálogo|conceptos?|cotiz|presupuesto|precios?|partidas?)\b"
)
_MONEY_IN_QUERY_RE = re.compile(r"\$?\s*([\d]{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?)")


def _normalize(q: str) -> str:
    import unicodedata

    raw = unicodedata.normalize("NFD", (q or "").strip().lower())
    t = "".join(c for c in raw if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t)


def detect_economic_provenance_intent(query: str) -> Optional[str]:
    """
    Detecta consultas sobre procedencia de precios/totales/catálogo.

    Returns:
        ``total`` | ``catalog`` | ``origin`` | ``general`` | None
    """
    qn = _normalize(query)
    if not qn or len(qn) < 8:
        return None

    has_total_marker = any(m in qn for m in _TOTAL_MARKERS)
    has_catalog_marker = any(m in qn for m in _CATALOG_MARKERS)
    has_origin = any(m in qn for m in _ORIGIN_MARKERS)
    has_price_word = any(
        w in qn for w in ("precio", "precios", "total", "importe", "monto", "cotizacion", "cotización")
    )
    has_money = bool(_MONEY_IN_QUERY_RE.search(qn))

    if has_total_marker or (has_origin and (has_money or "total" in qn)):
        return "total"
    if has_catalog_marker or (
        has_price_word and any(w in qn for w in ("catalogo", "catálogo", "conceptos", "fuente", "fuentes"))
    ):
        return "catalog"
    if has_origin and has_price_word:
        return "origin"
    if has_price_word and any(
        w in qn for w in ("usaste", "usaron", "tomaste", "generaste", "armaste", "conocer")
    ):
        return "general"
    return None


def _economic_snapshot(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for task in reversed(list(state.get("tasks_completed") or [])):
        if not isinstance(task, dict):
            continue
        if str(task.get("task") or "") == "economic_proposal":
            result = task.get("result")
            if isinstance(result, dict):
                inner = result.get("data")
                return inner if isinstance(inner, dict) else result
    mps = state.get("master_proposal_state")
    return mps if isinstance(mps, dict) and mps else None


def _money(amount: float, currency: str = "MXN") -> str:
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return "—"
    return f"**${val:,.2f}** {currency}"


@dataclass
class EconomicProvenanceFacts:
    has_snapshot: bool = False
    grand_total: Optional[float] = None
    total_base: Optional[float] = None
    iva_amount: Optional[float] = None
    currency: str = "MXN"
    partidas_count: int = 0
    priced_partidas: int = 0
    top_lines: List[str] = field(default_factory=list)
    catalog_sources: List[str] = field(default_factory=list)
    capture_filled: int = 0
    capture_total: int = 0
    generated_files: List[str] = field(default_factory=list)
    company_label: str = ""


_DETAIL_MAX_CHARS = 320


def _short_label(text: str, max_len: int = 40) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _list_generated_economic_files(session_id: str) -> List[str]:
    if not session_id:
        return []
    root = os.path.join("/data/outputs", session_id)
    found: List[str] = []
    for sub in ("2.propuesta_economica", "propuesta_economica", ""):
        base = os.path.join(root, sub) if sub else root
        if not os.path.isdir(base):
            continue
        try:
            for fn in sorted(os.listdir(base)):
                if fn.lower().endswith((".docx", ".xlsx", ".pdf")):
                    found.append(fn)
        except OSError:
            continue
    # dedupe preserve order
    seen: set[str] = set()
    out: List[str] = []
    for fn in found:
        key = fn.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(fn)
    return out[:8]


def _collect_catalog_sources(state: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for block in state.get("capture_matrix_blocks") or []:
        if not isinstance(block, dict):
            continue
        for key in ("source_filename", "file_name", "filename", "archivo_fuente", "label"):
            val = str(block.get(key) or "").strip()
            if val:
                names.append(val)
                break
    end = state.get("economic_normalized_data")
    if isinstance(end, dict):
        docs = end.get("documents") if isinstance(end.get("documents"), dict) else {}
        for doc_id, payload in docs.items():
            if not isinstance(payload, dict):
                continue
            fn = str(
                payload.get("filename")
                or payload.get("source_filename")
                or payload.get("doc_id")
                or doc_id
            ).strip()
            if fn:
                names.append(fn)
    # Priorizar nombres tipo catálogo
    catalog = [n for n in names if _CATALOG_FILENAME_RE.search(n)]
    if catalog:
        return list(dict.fromkeys(catalog))[:5]
    return list(dict.fromkeys(names))[:5]


def collect_economic_provenance_facts(
    state: Dict[str, Any],
    *,
    session_id: str = "",
) -> EconomicProvenanceFacts:
    facts = EconomicProvenanceFacts()
    mp = state.get("master_profile")
    if isinstance(mp, dict):
        facts.company_label = str(mp.get("razon_social") or mp.get("nombre") or "").strip()

    snap = _economic_snapshot(state)
    if snap:
        facts.has_snapshot = True
        facts.currency = str(snap.get("currency") or "MXN")
        for key, attr in (
            ("grand_total", "grand_total"),
            ("total_base", "total_base"),
            ("iva_amount", "iva_amount"),
        ):
            try:
                val = snap.get(key)
                if val is not None:
                    setattr(facts, attr, float(val))
            except (TypeError, ValueError):
                pass
        items = [i for i in (snap.get("items") or []) if isinstance(i, dict)]
        facts.partidas_count = len(items)
        facts.priced_partidas = sum(
            1 for it in items if float(it.get("precio_unitario") or 0) > 0
        )
        ranked = sorted(
            items,
            key=lambda it: float(it.get("subtotal") or it.get("importe") or 0),
            reverse=True,
        )
        for it in ranked[:2]:
            concept = _short_label(
                str(it.get("concepto") or it.get("descripcion") or "Partida"),
                max_len=40,
            )
            sub = float(it.get("subtotal") or it.get("importe") or 0)
            pu = float(it.get("precio_unitario") or 0)
            qty = it.get("cantidad")
            line = f"**{concept}**"
            if sub > 0:
                line += f" → {_money(sub, facts.currency).replace('**', '')}"
            elif pu > 0:
                line += f" → PU {_money(pu, facts.currency).replace('**', '')}"
            if qty is not None:
                line += f" (cant. {qty})"
            facts.top_lines.append(line)

    from app.services.economic_capture_matrix_service import economic_capture_status

    cap = economic_capture_status(state)
    facts.capture_filled = int(cap.get("filled") or 0)
    facts.capture_total = int(cap.get("total") or 0)
    facts.catalog_sources = _collect_catalog_sources(state)
    facts.generated_files = _list_generated_economic_files(session_id)

    if not facts.grand_total and facts.total_base is not None:
        iva = float(facts.iva_amount or 0)
        facts.grand_total = float(facts.total_base) + iva

    return facts


def build_economic_provenance_message(
    state: Dict[str, Any],
    *,
    session_id: str = "",
    mode: str = "general",
    user_query: str = "",
) -> Optional[str]:
    """Mensaje Gate 5 sobre procedencia económica."""
    from app.services.annex_resolution_service import (
        build_annex_doc_message,
        resolve_economic_annex,
    )
    from app.services.chat_gate5_formatter import format_gate5_message

    facts = collect_economic_provenance_facts(state, session_id=session_id)
    company = facts.company_label or "tu empresa"
    annex_res = resolve_economic_annex(
        state,
        user_query,
        session_id=session_id,
        mode=mode,
    )

    if not facts.has_snapshot and facts.capture_filled == 0 and not facts.generated_files:
        return format_gate5_message(
            status="Aún no hay una **propuesta económica consolidada** en esta sesión.",
            detail=(
                f"Sube tu catálogo o cotización en **Fuentes**, captura precios en "
                f"**Matriz de precios** y pulsa **Generar** con **{company}** seleccionada."
            ),
            cta="Abre **Formatos/Anexos Detectados** o la **Matriz de precios** en el panel central.",
        )

    total_txt = _money(facts.grand_total or 0, facts.currency) if facts.grand_total else "el total calculado"
    sources_txt = ""
    if facts.catalog_sources:
        shown = ", ".join(f"**{s}**" for s in facts.catalog_sources[:2])
        if len(facts.catalog_sources) > 2:
            shown += f" y **{len(facts.catalog_sources) - 2}** más"
        sources_txt = f" Precios tomados de {shown} (indexados en **Fuentes**)."
    elif facts.capture_filled > 0:
        sources_txt = (
            f" Registré **{facts.capture_filled}** precio(s) en la matriz de captura de esta sesión."
        )

    doc_txt = ""
    annex_line = build_annex_doc_message(annex_res, user_query=user_query)
    if annex_line:
        doc_txt = " " + annex_line
    elif facts.generated_files:
        doc_txt = f" Documento generado: **{facts.generated_files[0]}**."
    else:
        doc_txt = " Revisa **Logística y Expedientes** (panel derecho) para el Word/Excel económico."

    if mode == "catalog":
        status = f"Sí — usé tu **catálogo/cotización indexada** y la captura de precios de **{company}**."
        detail = (
            f"La propuesta económica materializada suma {total_txt} "
            f"con **{facts.priced_partidas or facts.partidas_count}** partida(s) con precio.{sources_txt}{doc_txt}"
        )
        if facts.top_lines:
            detail += " Ejemplo: " + facts.top_lines[0] + "."
    elif mode == "total":
        status = f"El total {total_txt} sale del **motor económico** de esta sesión (suma de partidas + IVA)."
        detail = (
            f"**{facts.partidas_count}** partida(s) en el snapshot; "
            f"**{facts.priced_partidas}** con precio unitario.{sources_txt}{doc_txt}"
        )
        if facts.top_lines:
            detail += " Mayor importe: " + facts.top_lines[0] + "."
    else:
        status = f"Procedencia de precios de **{company}** en esta licitación."
        detail = (
            f"Total consolidado: {total_txt}. "
            f"Cascada: **chat/captura** → **Fuentes (catálogo)** → **motor económico** → anexos.{sources_txt}{doc_txt}"
        )

    cta = (
        "Revisa **Logística y Expedientes** o **Formatos/Anexos Detectados**; "
        "para corregir un precio, escríbelo aquí o actualiza la **Matriz de precios**."
    )
    detail_trim = detail.strip()
    if len(detail_trim) > _DETAIL_MAX_CHARS:
        detail_trim = detail_trim[: _DETAIL_MAX_CHARS - 1].rstrip() + "…"
    msg = format_gate5_message(status=status, detail=detail_trim, cta=cta)
    return msg
