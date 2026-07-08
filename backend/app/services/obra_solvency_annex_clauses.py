"""
Cláusulas HRU para solvencia económica obra (capital contable comprometido / liquidez).

Patrón extract → fill → mirror; montos solo con procedencia verificable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.administrative_letter_clauses import (
    _contratos_rows_from_profile,
    _slot,
    extract_obra_annex_inventory_requirement,
)
from app.services.official_format_text import normalize_official_template_text


def _money(value: float) -> str:
    return f"${float(value or 0):,.2f}"


def _parse_money(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        return v if v > 0 else None
    text = str(raw).strip()
    if not text or text.startswith("["):
        return None
    cleaned = re.sub(r"[^\d.,]", "", text.replace(",", ""))
    if not cleaned:
        return None
    try:
        v = float(cleaned)
        return v if v > 0 else None
    except ValueError:
        return None


@dataclass
class SolvencyFigures:
    """Cifras de solvencia con procedencia HRU."""

    capital_contable: Optional[float] = None
    capital_comprometido: Optional[float] = None
    liquidez: Optional[float] = None
    obras_pendientes: Optional[float] = None
    liquidez_minima_bases: Optional[float] = None
    pct_capital_regla: float = 0.25
    provenance: Dict[str, str] = field(default_factory=dict)
    slots_pending: List[str] = field(default_factory=list)

    def has_verified_amounts(self) -> bool:
        return bool(
            self.capital_contable is not None
            or self.capital_comprometido is not None
            or self.liquidez is not None
        )


def _provenance_ui(field: str, source: str, detail: str = "") -> Dict[str, Any]:
    return {
        "field": field,
        "source": source,
        "detail": detail,
        "confidence": "verified" if source.startswith("user") or source.startswith("profile") else "derived",
    }


def resolve_solvency_figures(
    *,
    master_profile: Optional[Dict[str, Any]] = None,
    session_state: Optional[Dict[str, Any]] = None,
    corpus: str = "",
) -> SolvencyFigures:
    """
    Resuelve cifras de solvencia con cascada HRU (sin inventar montos).

    Usuario/intake > perfil maestro > T-2 (obras vigentes) > mínimos en bases.
    """
    mp = dict(master_profile or {})
    st = dict(session_state or {})
    out = SolvencyFigures()
    prov: Dict[str, str] = {}
    pending: List[str] = []

    user_inputs = st.get("economic_user_inputs") or {}
    if isinstance(user_inputs, dict):
        cap_ui = _parse_money(user_inputs.get("capital_contable"))
        if cap_ui is not None:
            out.capital_contable = cap_ui
            prov["capital_contable"] = "user_economic_inputs"
        liq_ui = _parse_money(user_inputs.get("liquidez"))
        if liq_ui is not None:
            out.liquidez = liq_ui
            prov["liquidez"] = "user_economic_inputs"
        liq_min_ui = _parse_money(user_inputs.get("liquidez_minima"))
        if liq_min_ui is not None:
            out.liquidez_minima_bases = liq_min_ui
            prov["liquidez_minima_bases"] = "user_economic_inputs"
        if out.liquidez is None:
            ac = _parse_money(user_inputs.get("activo_circulante"))
            pc = _parse_money(user_inputs.get("pasivo_circulante"))
            if ac is not None and pc is not None:
                out.liquidez = ac - pc
                prov["liquidez"] = "derived_user_ac_minus_pc"

    for profile_key in ("capital_contable", "liquidez", "patrimonio_neto"):
        if getattr(out, profile_key if profile_key != "patrimonio_neto" else "capital_contable", None):
            continue
        val = _parse_money(mp.get(profile_key))
        if val is not None:
            if profile_key == "patrimonio_neto" and out.capital_contable is None:
                out.capital_contable = val
                prov["capital_contable"] = "master_profile.patrimonio_neto"
            elif profile_key == "capital_contable":
                out.capital_contable = val
                prov["capital_contable"] = "master_profile.capital_contable"
            elif profile_key == "liquidez":
                out.liquidez = val
                prov["liquidez"] = "master_profile.liquidez"

    solv = mp.get("solvencia_economica")
    if isinstance(solv, dict):
        for key, attr in (
            ("capital_contable", "capital_contable"),
            ("capital_contable_minimo", "capital_contable"),
            ("liquidez", "liquidez"),
        ):
            if getattr(out, attr, None) is not None:
                continue
            block = solv.get(key)
            raw = block.get("value") if isinstance(block, dict) else block
            val = _parse_money(raw)
            if val is not None:
                setattr(out, attr, val)
                prov[attr] = f"master_profile.solvencia_economica.{key}"

    blob = str(corpus or "")
    m_pct = re.search(
        r"(?i)(\d{1,3})\s*%\s*(?:del|de\s+las?\s+obras?|veinticinco|25)",
        blob,
    )
    if m_pct:
        try:
            out.pct_capital_regla = float(m_pct.group(1)) / 100.0
        except ValueError:
            pass
    elif re.search(r"(?i)veinticinco\s+por\s+ciento|25\s*%\s*del", blob):
        out.pct_capital_regla = 0.25

    m_liq_min = re.search(
        r"(?i)liquidez\s+m[ií]nima[^\$]{0,40}\$?\s*([\d,]+(?:\.\d{2})?)",
        blob,
    )
    if m_liq_min:
        val = _parse_money(m_liq_min.group(1))
        if val is not None:
            out.liquidez_minima_bases = val
            prov["liquidez_minima_bases"] = "bases_corpus"

    rows = _contratos_rows_from_profile(mp)
    pending_sum = 0.0
    has_row_money = False
    for row in rows:
        if not row or len(row) < 4:
            continue
        imp = _parse_money(row[3])
        if imp is None:
            continue
        has_row_money = True
        avance_raw = row[4] if len(row) > 4 else ""
        avance = _parse_money(str(avance_raw).replace("%", ""))
        if avance is not None and 0 <= avance <= 100:
            pending_sum += imp * (1.0 - avance / 100.0)
        else:
            pending_sum += imp

    if has_row_money:
        out.obras_pendientes = pending_sum
        prov["obras_pendientes"] = "master_profile.contratos_obra_t2"
        derived_commit = pending_sum * out.pct_capital_regla
        if out.capital_comprometido is None:
            out.capital_comprometido = derived_commit
            prov["capital_comprometido"] = "derived_t2_pct"

    if out.capital_contable is None:
        pending.append("capital_contable")
    if out.liquidez is None:
        pending.append("liquidez")
    if out.capital_comprometido is None and out.obras_pendientes is None:
        pending.append("capital_comprometido")

    out.provenance = prov
    out.slots_pending = pending
    return out


def fetch_solvency_format_corpus_from_index(session_id: str) -> str:
    """Recupera fragmentos de bases sobre capital contable / liquidez."""
    if not str(session_id or "").strip():
        return ""
    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    parts: List[str] = []
    seen: set = set()
    queries = (
        "CAPITAL CONTABLE COMPROMETIDO LIQUIDEZ SOLVENCIA ECONOMICA",
        "CUADRO DE FINIQUITO OBRAS VIGENTES ANEXO T-2",
        "ACTIVO CIRCULANTE MENOS PASIVO CIRCULANTE",
        "SOLVENCIA ECONOMICA CAPITAL CONTABLE",
    )

    def _add(text: str) -> None:
        t = str(text or "").strip()
        if not t or t in seen:
            return
        low = t.lower()
        if not any(
            k in low
            for k in (
                "capital contable",
                "liquidez",
                "solvencia",
                "finiquito",
                "activo circulante",
            )
        ):
            return
        seen.add(t)
        parts.append(t)

    for q in queries:
        try:
            res = vdb.query_texts(session_id, q, n_results=15)
            for doc in res.get("documents") or []:
                _add(str(doc or ""))
        except Exception:
            continue
    return "\n\n".join(parts)[:120000]


def assemble_solvency_corpus(
    *,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    bases_corpus_hint: str = "",
    req_snippet: str = "",
    req_desc: str = "",
) -> str:
    """Corpus unificado para detectar machote / reglas de solvencia."""
    state = session_state or {}
    chunks: List[str] = []
    for part in (
        fetch_solvency_format_corpus_from_index(session_id),
        str(state.get("_obra_tb_solvencia_snippet") or ""),
        str(bases_corpus_hint or "")[:120000],
        str(req_snippet or ""),
        str(req_desc or ""),
    ):
        p = str(part or "").strip()
        if p and p not in chunks:
            chunks.append(p)
    return "\n\n".join(chunks)


_SOLVENCY_START_RE = re.compile(
    r"(?is)(?:capital\s+contable\s+comprometid[oa]|"
    r"declaraci[oó]n.*capital\s+contable|"
    r"solvencia\s+econ[oó]mica|"
    r"liquidez\s+comprometida)"
)


def extract_obra_tb_solvencia_official_format(corpus: str) -> Optional[str]:
    """
    Extrae texto de formato / requisito literal de solvencia en bases.

    Returns:
        Fragmento del machote o None si no hay ancla verificable.
    """
    text = str(corpus or "")
    if len(text) < 80:
        return None
    m = _SOLVENCY_START_RE.search(text)
    if not m:
        inv = extract_obra_annex_inventory_requirement(text, "T-B")
        if not inv and not re.search(r"(?i)capital\s+contable", text):
            return None
        segment = inv or text[:2500]
        if len(segment) < 60:
            return None
        return normalize_official_template_text(segment[:3500])
    start = max(0, m.start() - 200)
    tail = text[start : start + 4500]
    end_m = re.search(
        r"(?is)(protesto\s+lo\s+necesario|atentamente|nombre\s+y\s+firma)",
        tail[400:],
    )
    chunk = tail[: 400 + end_m.end()] if end_m else tail
    chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip()
    if len(chunk) < 80:
        return None
    return normalize_official_template_text(chunk)


def is_official_obra_tb_solvencia_mirror_content(content: str) -> bool:
    """True si el cuerpo refleja requisito de bases (no carta LLM genérica)."""
    up = str(content or "").upper()
    if "OPM/MUN/" in up and "D/080/" not in up:
        return False
    markers = (
        "CAPITAL CONTABLE",
        "LIQUIDEZ",
        "PROTESTA DE DECIR VERDAD",
        "ANEXO T-2",
    )
    hits = sum(1 for m in markers if m in up)
    return hits >= 2 and "CONVOCATORIA PÚBLICA NACIONAL NO." not in up[:800]


def fill_obra_tb_solvencia_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    master_profile: Dict[str, Any],
    figures: SolvencyFigures,
) -> str:
    """Rellena huecos del machote con cifras verificadas o [Consignar]."""
    out = normalize_official_template_text(str(template or ""))
    num = str(concurso or "").strip()
    if not num:
        m = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", corpus)
        num = m.group(1).upper() if m else "[Consignar — número de licitación]"

    cap = (
        _money(figures.capital_contable)
        if figures.capital_contable is not None
        else "[Consignar — capital contable]"
    )
    comprometido = (
        _money(figures.capital_comprometido)
        if figures.capital_comprometido is not None
        else "[Consignar — capital comprometido]"
    )
    liquidez = (
        _money(figures.liquidez)
        if figures.liquidez is not None
        else "[Consignar — liquidez]"
    )
    pendiente = (
        _money(figures.obras_pendientes)
        if figures.obras_pendientes is not None
        else "[Consignar — obras pendientes T-2]"
    )

    out = re.sub(
        r"(?i)(licitaci[oó]n\s+p[uú]blica[^\n]{0,80})_{3,}",
        rf"\g<1>{num}",
        out,
    )
    for pat, repl in (
        (r"\$_{3,}", comprometido),
        (r"(?i)capital\s+contable[^\$]{0,40}\$[\d,\.]+", f"capital contable de {cap}"),
    ):
        if re.search(pat, out):
            out = re.sub(pat, repl, out, count=1)

    if "[Consignar" not in comprometido and "capital comprometido" not in out.lower():
        out += (
            f"\n\nManifiesto que el capital contable comprometido asciende a "
            f"**{comprometido}** (obras pendientes de ejecutar: {pendiente}, "
            f"regla {int(figures.pct_capital_regla * 100)}% conforme bases)."
        )
    if "[Consignar" not in liquidez:
        out += f"\n\nDeclaro liquidez (activo circulante menos pasivo circulante) de **{liquidez}**."
    if figures.liquidez_minima_bases is not None:
        out += (
            f"\n\nMínimo exigido en bases para liquidez: "
            f"**{_money(figures.liquidez_minima_bases)}**."
        )
    return out.strip()


def build_obra_tb_solvencia_markdown(
    *,
    concurso: str,
    master_profile: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    req_snippet: str = "",
    req_desc: str = "",
    bases_corpus_hint: str = "",
) -> str:
    """
    Genera declaración de solvencia (extract → fill → mirror o shell HRU).

    No inventa montos; usa [Consignar] si faltan fuentes verificadas.
    """
    corpus = assemble_solvency_corpus(
        session_id=session_id,
        session_state=session_state,
        bases_corpus_hint=bases_corpus_hint,
        req_snippet=req_snippet,
        req_desc=req_desc,
    )
    figures = resolve_solvency_figures(
        master_profile=master_profile,
        session_state=session_state,
        corpus=corpus,
    )
    template = extract_obra_tb_solvencia_official_format(corpus)
    req_line = extract_obra_annex_inventory_requirement(corpus, "T-B") or (
        "Acreditar solvencia económica: capital contable comprometido y liquidez mínima."
    )

    if template:
        body = fill_obra_tb_solvencia_official_format(
            template,
            concurso=concurso,
            corpus=corpus,
            master_profile=master_profile,
            figures=figures,
        )
    else:
        razon = _slot(master_profile.get("razon_social"), "[Consignar — razón social]")
        cap = (
            _money(figures.capital_contable)
            if figures.capital_contable is not None
            else "[Consignar — capital contable]"
        )
        comprometido = (
            _money(figures.capital_comprometido)
            if figures.capital_comprometido is not None
            else "[Consignar — capital comprometido]"
        )
        liquidez = (
            _money(figures.liquidez)
            if figures.liquidez is not None
            else "[Consignar — liquidez]"
        )
        body = (
            f"**CAPITAL CONTABLE COMPROMETIDO / SOLVENCIA ECONÓMICA**\n\n"
            f"**Requisito publicado en bases:** {req_line}\n\n"
            f"**Bajo protesta de decir verdad**, manifiesto que **{razon}** cumple con los "
            f"requisitos de solvencia económica del procedimiento **{concurso or '[Consignar]'}**.\n\n"
            f"- Capital contable declarado: **{cap}**\n"
            f"- Capital contable comprometido (regla {int(figures.pct_capital_regla * 100)}% "
            f"sobre obras vigentes del Anexo T-2): **{comprometido}**\n"
            f"- Liquidez (activo circulante − pasivo circulante): **{liquidez}**\n\n"
            "**[Consignar]** — Si alguna cifra aparece entre corchetes, captúrela en el chat "
            "o complete el Anexo T-2 con contratos vigentes verificables.\n"
        )

    phys = (
        "\n\n**Documentos físicos requeridos (no sustituibles por esta declaración):**\n"
        "- Estados financieros dictaminados / auditados, si las bases los exigen.\n"
        "- Cuadro de finiquito de obras, si aplica.\n"
        "- Anexo T-2 con contratos de obra vigentes y soportes.\n"
    )
    prov_lines = []
    for k, src in figures.provenance.items():
        prov_lines.append(f"- {k}: {src}")
    if prov_lines:
        body += "\n\n**Procedencia de cifras:**\n" + "\n".join(prov_lines)
    body += phys + "\n\nProtesto lo necesario."
    return body


def solvency_provenance_ui(figures: SolvencyFigures) -> Dict[str, Any]:
    """Bloque provenance_ui para API/UI."""
    items = [
        _provenance_ui(k, v) for k, v in (figures.provenance or {}).items()
    ]
    return {
        "items": items,
        "slots_pending": list(figures.slots_pending or []),
        "has_verified_amounts": figures.has_verified_amounts(),
    }
