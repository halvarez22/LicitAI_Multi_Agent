"""
Cláusulas determinísticas para anexos económicos de obra pública (E-1 a E-5).

HRU: montos desde motor económico verificado; sin inventar desgloses APU ni programas Gantt.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.administrative_letter_clauses import (
    _markdown_table,
    _slot,
    extract_obra_annex_inventory_requirement,
)
from app.services.official_format_text import (
    is_boilerplate_obra_capture,
    normalize_official_template_text,
)


def looks_like_session_slug(text: str, session_id: str = "") -> bool:
    """
    True si el texto parece slug interno de sesión (no número de licitación real).

    Evita usar ``barda_primaria_lopez_rayon`` como concurso u objeto de obra.
    """
    t = re.sub(r"\s+", " ", str(text or "").strip().upper())
    sid = str(session_id or "").strip().lower()
    if not t or not sid:
        return False
    if t == sid.replace("_", " ").upper():
        return True
    if t.replace(" ", "_").lower() == sid:
        return True
    if re.search(r"[A-Z]/\d+/\d+", text):
        return False
    tokens = [tok for tok in sid.split("_") if len(tok) > 2]
    if len(tokens) >= 2 and all(tok.upper() in t for tok in tokens):
        return True
    return False


def is_hru_consignar_placeholder(text: str) -> bool:
    """True si el valor es un marcador [Consignar] HRU (no dato de negocio)."""
    t = str(text or "").strip()
    if not t:
        return True
    return bool(re.match(r"^\[?\s*consignar\b", t, re.IGNORECASE))


def _money(value: float) -> str:
    return f"${float(value or 0):,.2f}"


def resolve_obra_concurso_label(
    *,
    session_state: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    corpus: str = "",
) -> str:
    """Número/nombre de licitación desde sesión, carta o corpus — nunca slug de sesión."""
    from app.services.administrative_letter_clauses import resolve_letter_session_metadata
    from app.services.convocante_resolver import extract_convocante_from_text

    state = session_state or {}
    letter = resolve_letter_session_metadata(state)
    candidates: List[Any] = [
        state.get("concurso_label"),
        state.get("licitacion_id"),
        state.get("tender_name"),
        state.get("concurso"),
        state.get("session_hint"),
        letter.get("concurso_label"),
    ]
    for container_key in ("last_analysis", "analysis_snapshot"):
        block = state.get(container_key)
        if isinstance(block, dict):
            candidates.extend(
                [
                    block.get("concurso_label"),
                    block.get("licitacion_id"),
                    block.get("tender_name"),
                ]
            )
    for raw in candidates:
        c = str(raw or "").strip()
        if (
            c
            and not looks_like_session_slug(c, session_id)
            and not is_hru_consignar_placeholder(c)
        ):
            m_code = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", c)
            if m_code:
                return f"Licitación Pública Num. {m_code.group(1).upper()}"
            return c

    blob = str(corpus or "")
    extracted = extract_convocante_from_text(blob)
    proc = str(extracted.get("concurso_label") or "").strip()
    if proc and not looks_like_session_slug(proc, session_id):
        return proc

    m = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", blob)
    if m:
        return f"Licitación Pública Num. {m.group(1).upper()}"

    m2 = re.search(
        r"(?i)licitaci[oó]n\s+p[uú]blica[^\n,]{0,100}",
        blob,
    )
    if m2:
        line = re.sub(r"\s+", " ", m2.group(0)).strip()[:120]
        if not looks_like_session_slug(line, session_id) and not is_hru_consignar_placeholder(line):
            return line

    return "[Consignar — número de licitación]"


def resolve_obra_objeto(
    *,
    session_state: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    corpus: str = "",
    explicit: str = "",
) -> str:
    """Objeto de la obra desde sesión o bases — nunca slug interno de sesión."""
    state = session_state or {}
    for raw in (
        explicit,
        state.get("objeto_obra"),
        state.get("obra_descripcion"),
        state.get("name"),
    ):
        val = str(raw or "").strip()
        if (
            val
            and not looks_like_session_slug(val, session_id)
            and not is_hru_consignar_placeholder(val)
        ):
            if not is_boilerplate_obra_capture(val):
                return val.upper() if len(val) < 200 else val
    obra = extract_obra_descripcion_from_corpus(str(corpus or ""), "")
    return obra or "[Consignar — objeto de la obra en bases]"


def _e3_subannex_checklist(snippet: str) -> List[str]:
    """Renglones E-3 A–F detectados en snippet de bases."""
    blob = str(snippet or "")
    labels = (
        ("E-3 A", r"anexo\s+e[\s_.-]*3\s*a|an[aá]lisis\s+de\s+los\s+precios\s+unitarios"),
        ("E-3 B", r"e[\s_.-]*3\s*b|factor\s+de\s+salario\s+real"),
        ("E-3 C", r"e[\s_.-]*3\s*c|factor\s+de\s+indirectos"),
        ("E-3 D", r"e[\s_.-]*3\s*d|costo\s+de\s+financiamiento"),
        ("E-3 E", r"e[\s_.-]*3\s*e|cargo\s+por\s+utilidad"),
        ("E-3 F", r"e[\s_.-]*3\s*f|an[aá]lisis\s+de\s+b[aá]sicos"),
    )
    found: List[str] = []
    for code, pat in labels:
        if re.search(pat, blob, re.I):
            found.append(code)
    if not found:
        found = ["E-3 A", "E-3 B", "E-3 C", "E-3 D", "E-3 E", "E-3 F"]
    return found


def extract_obra_plazo_ejecucion(corpus: str) -> str:
    """
    Extrae plazo de ejecución publicado en bases (sin inventar días).

    Returns:
        Fragmento breve del plazo o cadena vacía si no hay evidencia.
    """
    text = str(corpus or "")
    patterns = (
        r"(?i)(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles)(?:\s+y\s+\d{1,2}\s*d[ií]as)?[^.\n]{0,90}(?:conclusi[oó]n|ejecuci[oó]n|entrega|obra))",
        r"(?i)contando\s+con\s+(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles)[^.\n]{0,90}(?:conclusi[oó]n|obra))",
        r"(?i)(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles))[^.\n]{0,70}obra",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        line = re.sub(r"\s+", " ", m.group(0)).strip(" .;")
        if re.search(r"\d", line) and 8 <= len(line) <= 200:
            return line
    return ""


def _resolve_concurso_label(concurso: str, corpus: str, fallback: str, session_id: str = "") -> str:
    """Etiqueta de procedimiento desde metadata o corpus (sin slug de sesión)."""
    label = str(concurso or "").strip()
    if label and not looks_like_session_slug(label, session_id):
        if re.search(r"[A-Z]/\d+/\d+", label) or "licitaci" in label.lower():
            return label
    m = re.search(
        r"(?i)licitaci[oó]n\s+p[uú]blica\s+(?:nacional\s+)?(?:num\.?\s*)?([A-Z]/\d+/\d+)",
        str(corpus or ""),
    )
    if m:
        return f"Licitación Pública Num. {m.group(1).replace(' ', '')}"
    m2 = re.search(r"(?i)licitaci[oó]n\s+p[uú]blica[^\n,]{0,90}", str(corpus or ""))
    if m2:
        line = re.sub(r"\s+", " ", m2.group(0)).strip()[:120]
        if not looks_like_session_slug(line, session_id) and not is_hru_consignar_placeholder(line):
            return line
    fb = str(fallback or "").strip()
    if fb and not looks_like_session_slug(fb, session_id) and not is_hru_consignar_placeholder(fb):
        return fb
    return "[Consignar — número de licitación]"


_ECONOMIC_REQ_CONTAMINATION_RE = re.compile(
    r"(?i)de\s+las\s+causas\s+de|descalific|desechamient|causa[s]?\s+de\s+exclusi[oó]n|"
    r"ser[aá]\s+descalificad|no\s+se\s+aceptar[aá]n|dictamen\s+de\s+evaluaci[oó]n|"
    r"mecanismo\s+de\s+puntos|propuesta\s+conveniente,\s*y\s+que\s+de\s+acuerdo"
)


def _sanitize_economic_req_line(line: str, annex_code: str) -> str:
    """Elimina cola contaminada (p. ej. causas de descalificación pegadas al inventario)."""
    text = re.sub(r"\s+", " ", str(line or "").strip(" .;"))
    if not text:
        return ""
    if _ECONOMIC_REQ_CONTAMINATION_RE.search(text):
        cut = _ECONOMIC_REQ_CONTAMINATION_RE.search(text)
        if cut and cut.start() > 24:
            text = text[: cut.start()].strip(" .;,:")
    for cut_pat in (
        r"(?i)\s*:\s*DE LAS CAUSAS\b",
        r"(?i)\s+DE LAS CAUSAS\b",
    ):
        parts = re.split(cut_pat, text, maxsplit=1)
        if parts and parts[0].strip():
            text = parts[0].strip(" .;,:")
    if annex_code.upper() == "E-5":
        m = re.search(
            r"(?i)(deber[aá]\s+presentar\s+cotizaciones[^:]{0,160}|"
            r"cotizaciones?\s+de\s+(?:los\s+)?(?:siguientes\s+)?materiales[^:]{0,160})",
            text,
        )
        if m:
            text = re.sub(r"\s+", " ", m.group(1)).strip(" .;,:")
    return text


def _clean_economic_req_line(snippet: str, annex_code: str, fallback: str) -> str:
    """Prefiere texto breve del inventario; evita ruido OCR del corpus completo."""
    from app.services.administrative_letter_clauses import (
        extract_obra_annex_inventory_requirement,
    )

    raw = str(snippet or "").strip()
    candidates: List[str] = []
    if raw:
        candidates.append(_sanitize_economic_req_line(raw, annex_code))
    inv = extract_obra_annex_inventory_requirement(raw, annex_code)
    if inv:
        candidates.append(_sanitize_economic_req_line(inv, annex_code))
    for line in candidates:
        if (
            line
            and 12 <= len(line) <= 420
            and not re.search(r"(?i)\[fuente:|presupuesto\s+52", line)
            and not _ECONOMIC_REQ_CONTAMINATION_RE.search(line)
        ):
            return line
    return fallback


_E1_FORMAT_START_RE = re.compile(
    r"(?is)anexo\s+e[\s_.-]*1\s*(?:\(\s*formato\s*\))?\s*"
    r"[\s\r\n]*carta\s+compromiso\s+de\s+proposici[oó]n"
)
_E1_FORMAT_ALT_START_RE = re.compile(
    r"(?is)(?:^|\n)\s*carta\s+compromiso\s+de\s+proposici[oó]n\s*(?:\n|$)"
)
_E1_HACEMOS_REF_RE = re.compile(
    r"(?is)hacemos\s+referencia\s+al\s+procedimiento\s+de\s+adjudicaci[oó]n"
)


def fetch_obra_e1_format_corpus_from_index(session_id: str) -> str:
    """
    Recupera chunks del índice que contienen el machote E-1 embebido en bases.
    """
    if not str(session_id or "").strip():
        return ""
    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    parts: List[str] = []
    seen: set = set()

    def _add(text: str) -> None:
        t = str(text or "").strip()
        if not t or t in seen:
            return
        low = t.lower()
        if "carta compromiso" not in low and "carta-compromiso" not in low:
            return
        if "anexo" in low and "e-1" not in low and "e 1" not in low:
            if "hacemos referencia" not in low and "presente" not in low:
                return
        seen.add(t)
        parts.append(t)

    queries = (
        "ANEXO E-1 FORMATO CARTA COMPROMISO DE PROPOSICION PRESENTE",
        "CARTA COMPROMISO DE PROPOSICIÓN DIRECTOR GENERAL OBRA PÚBLICA PRESENTE",
        "HACEMOS REFERENCIA AL PROCEDIMIENTO DE ADJUDICACIÓN POR LICITACIÓN PÚBLICA",
        "REALIZACIÓN DE LA OBRA GUANAJUATO LEÓN CARTA COMPROMISO",
    )
    for q in queries:
        try:
            res = vdb.query_texts(session_id, q, n_results=20)
            for doc in res.get("documents") or []:
                _add(str(doc or ""))
        except Exception:
            continue

    try:
        for doc, _meta in vdb.scan_session_chunks(session_id):
            _add(str(doc or ""))
    except Exception:
        pass

    return "\n\n".join(parts)[:160000]


def assemble_obra_e1_corpus(
    *,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    bases_corpus_hint: str = "",
    req_snippet: str = "",
    req_desc: str = "",
) -> str:
    """Corpus unificado para detectar y rellenar el machote E-1 (HRU, sin hardcode)."""
    state = session_state or {}
    chunks: List[str] = []
    for part in (
        str(state.get("_obra_e1_format_corpus") or ""),
        fetch_obra_e1_format_corpus_from_index(session_id),
        str(state.get("_obra_e1_snippet") or ""),
        str(bases_corpus_hint or ""),
        str(req_snippet or ""),
        str(req_desc or ""),
        str(state.get("bases_corpus_hint") or "")[:120000],
    ):
        p = str(part or "").strip()
        if p and p not in chunks:
            chunks.append(p)
    return "\n\n".join(chunks)


def is_official_obra_e1_mirror_content(content: str) -> bool:
    """True si el cuerpo ya es el machote E-1 de bases (no carta genérica)."""
    up = str(content or "").upper()
    if "ANEXO E-1" in up and "FORMATO" in up:
        return True
    return (
        "CARTA COMPROMISO DE PROPOSICI" in up
        and "HACEMOS REFERENCIA AL PROCEDIMIENTO" in up
        and "PRESENTE" in up
    )


def extract_obra_e1_official_format(corpus: str) -> Optional[str]:
    """
    Extrae el machote «Anexo E-1 / Carta compromiso» embebido en bases (fail-closed).

    Returns:
        Texto del formato oficial o None si no hay ancla verificable.
    """
    text = str(corpus or "")
    if len(text) < 120:
        return None
    start = -1
    start_m = _E1_FORMAT_START_RE.search(text)
    if start_m:
        start = start_m.start()
    else:
        alt_m = _E1_FORMAT_ALT_START_RE.search(text)
        if alt_m:
            start = alt_m.start()
        else:
            carta_m = re.search(r"(?is)carta\s+compromiso\s+de\s+proposici[oó]n", text)
            if carta_m:
                window = text[carta_m.start() : carta_m.start() + 2400]
                if "presente" in window.lower() or _E1_HACEMOS_REF_RE.search(window):
                    start = carta_m.start()
            if start < 0:
                ref_m = _E1_HACEMOS_REF_RE.search(text)
                if ref_m:
                    head = text[max(0, ref_m.start() - 1200) : ref_m.start()]
                    carta_back = re.search(
                        r"(?is)carta\s+compromiso\s+de\s+proposici[oó]n",
                        head,
                    )
                    start = (
                        max(0, ref_m.start() - 1200) + carta_back.start()
                        if carta_back
                        else max(0, ref_m.start() - 400)
                    )
    if start < 0:
        return None
    tail = text[start:]
    end_m = re.search(
        r"(?is)(a\s*t\s*e\s*n\s*t\s*a\s*m\s*e\s*n\s*t\s*e"
        r"(?:\s*\n+\s*nombre\s+y\s+firma\s+del\s+participante)?)",
        tail,
    )
    chunk = tail[: end_m.end()] if end_m else tail[:4000]
    chunk = re.sub(r"[ \t]+\n", "\n", chunk)
    chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip()
    if len(chunk) < 180:
        return None
    low = chunk.lower()
    if "presente" not in low and "licitaci" not in low:
        return None
    if "propuesta" not in low and "proposici" not in low:
        return None
    return normalize_official_template_text(chunk)


def extract_obra_descripcion_from_corpus(corpus: str, fallback: str = "") -> str:
    """Objeto de la obra publicado en bases (sin inventar denominación)."""
    text = str(corpus or "")
    patterns = (
        r"(?is)adjudicar el contrato relativo a la realizaci[oó]n de la obra[:\s_]+(.+?)(?:\.|_{4,}|\n)",
        r"(?is)realizaci[oó]n de la obra[:\s_]+(.+?)(?:\.|_{4,}|\n)",
        r"(?is)relacionado\s+con\s+la\s+obra[:\s_]+(.+?)(?:\s+es\s+del|\n)",
        r"(?is)obra p[uú]blica[^.\n]{0,60}(?:denominada|consistente en)[:\s]+(.+?)(?:\.|_{4,})",
        r"(?is)construcci[oó]n de[^.\n]{10,160}",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        desc = re.sub(r"\s+", " ", m.group(1) if m.lastindex else m.group(0)).strip(" _.")
        if len(desc) < 10 or is_boilerplate_obra_capture(desc):
            continue
        return desc.upper()
    fb = str(fallback or "").strip()
    if fb and not is_boilerplate_obra_capture(fb):
        return fb.upper()
    return ""


def _extract_licitacion_numero(concurso: str, corpus: str, session_id: str = "") -> str:
    blob = f"{concurso} {corpus}"
    for pat in (
        r"(?i)licitaci[oó]n\s+p[uú]blica\s+(?:num\.?\s*)?([A-Z]/\d+/\d+)",
        r"(?i)\b([A-Z]/\d+/\d+)\b",
        r"(?i)num\.?\s*([A-Z]/\d+/\d+)",
    ):
        m = re.search(pat, blob)
        if m:
            return m.group(1).replace(" ", "").upper()
    label = str(concurso or "").strip()
    if (
        label
        and not looks_like_session_slug(label, session_id)
        and not is_hru_consignar_placeholder(label)
    ):
        direct = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", label)
        if direct:
            return direct.group(1).upper()
        if "licitaci" in label.lower() and re.search(r"[A-Z]/\d+/\d+", label):
            return label[:80]
    return "[Consignar]"


def fill_obra_e1_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    obra_descripcion: str,
    master_profile: Dict[str, Any],
    resumen: Dict[str, Any],
    plazo_ejecucion: str,
    session_id: str = "",
) -> str:
    """Rellena el machote E-1 de bases con datos del oferente y motor económico."""
    out = normalize_official_template_text(str(template or ""))
    num = _extract_licitacion_numero(concurso, corpus, session_id=session_id)
    if not num or num == "[Consignar]":
        direct = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", f"{concurso} {corpus}")
        if direct:
            num = direct.group(1).upper()
    obra = str(obra_descripcion or "").strip() or extract_obra_descripcion_from_corpus(
        corpus, ""
    )
    obra_ok = obra and not is_hru_consignar_placeholder(obra)
    razon = _slot(master_profile.get("razon_social"), "[Consignar — razón social]")
    rfc = _slot(master_profile.get("rfc"), "[Consignar — RFC]")
    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "[Consignar — representante legal]",
    )
    total = float(resumen.get("total") or 0)
    plazo = str(plazo_ejecucion or "").strip() or extract_obra_plazo_ejecucion(corpus)
    plazo_fill = plazo.upper() if plazo else "[CONSIGNAR — PLAZO EN BASES]"

    num_ok = bool(num) and num != "[Consignar]" and not is_hru_consignar_placeholder(num)
    if num_ok:
        out = re.sub(
            r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?\s*)_{3,}",
            rf"\g<1>{num}",
            out,
        )
        out = re.sub(r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?\s*)_{3,}", rf"\g<1>{num}", out)

    if obra_ok:
        for pat in (
            r"(?is)(realizaci[oó]n de la obra[:\s]*)_{3,}",
            r"(?is)(de la obra[:\s]*)_{3,}",
            r"(?is)(relativo a la obra[:\s]*)_{3,}",
        ):
            if re.search(pat, out):
                out = re.sub(pat, rf"\g<1>{obra}", out, count=1)
                break

    if total > 0:
        money = f"${total:,.2f}"
        out = re.sub(r"\$\s*_{3,}", money, out)
        if re.search(r"(?i)\(PESOS\s+00/100", out):
            out = re.sub(
                r"(?i)\(PESOS\s+00/100\s*M\.N\.\)",
                f"({money} M.N.)",
                out,
                count=1,
            )
        elif re.search(r"(?i)\(PESOS\s+00/100", out):
            out = re.sub(
                r"(?i)\(PESOS\s+00/100",
                f"({money}",
                out,
                count=1,
            )
    else:
        out = re.sub(
            r"\$\s*_{3,}",
            "[Consignar — importe total con I.V.A. del motor económico]",
            out,
        )

    out = re.sub(
        r"(?i)plazo de ejecuci[oó]n de\s*_{2,}\s*al\s*_{2,}",
        f"PLAZO DE EJECUCIÓN DE {plazo_fill}",
        out,
    )
    out = re.sub(
        r"(?i)plazo de ejecuci[oó]n de_{2,} al _{2,}",
        f"PLAZO DE EJECUCIÓN DE {plazo_fill}",
        out,
    )
    out = re.sub(
        r"(?i)(?:en un )?plazo de ejecuci[oó]n de\s*_{2,}(?:\s*al\s*_{2,})?",
        f"PLAZO DE EJECUCIÓN DE {plazo_fill}",
        out,
        count=1,
    )

    signature = (
        f"\n\n{rep.upper()}\n"
        f"REPRESENTANTE LEGAL\n"
        f"{razon.upper()}\n"
        f"R.F.C. {rfc.upper()}"
    )
    out = re.sub(
        r"(?i)nombre\s+y\s+firma\s+del\s+participante\.?",
        signature.strip(),
        out,
    )
    if "REPRESENTANTE LEGAL" not in out.upper():
        out = out.rstrip() + signature
    return out.strip()


_E3E_FORMAT_START_RE = re.compile(
    r"(?is)anexo\s+e[\s_.-]*3\s*e\b"
)
_E3E_UTILIDAD_RE = re.compile(
    r"(?is)la\s+utilidad\s+propuesta\s+para\s+el\s+concurso"
)


def fetch_obra_licitacion_corpus_from_index(session_id: str) -> str:
    """Chunks de bases con número de licitación y objeto de obra (consulta genérica)."""
    if not str(session_id or "").strip():
        return ""
    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    parts: List[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        t = str(text or "").strip()
        if not t or t in seen:
            return
        low = t.lower()
        if not (
            re.search(r"[a-z]/\d+/\d+", low)
            or "realizaci" in low
            or "construcci" in low
            or "licitaci" in low
        ):
            return
        seen.add(t)
        parts.append(t)

    for q in (
        "LICITACIÓN PÚBLICA NUMERO D/080/2025 convocatoria",
        "adjudicar el contrato relativo a la realización de la obra",
        "construcción barda perimetral primaria",
        "presentación de proposiciones licitación pública obra",
    ):
        try:
            res = vdb.query_texts(session_id, q, n_results=14)
            for doc in res.get("documents") or []:
                _add(str(doc or ""))
        except Exception:
            continue
    return "\n\n".join(parts)[:120000]


def _expanded_obra_corpus(
    corpus: str,
    session_state: Optional[Dict[str, Any]] = None,
    *,
    session_id: str = "",
) -> str:
    """Une corpus de machote, hints de sesión y snippets de panel."""
    state = session_state or {}
    chunks: List[str] = []
    for part in (
        str(corpus or ""),
        str(state.get("bases_corpus_hint") or ""),
        str(state.get("session_hint") or ""),
        str(state.get("_obra_e1_snippet") or ""),
        str(state.get("_obra_e3e_snippet") or ""),
        str(state.get("_obra_e3_snippet") or ""),
    ):
        p = str(part or "").strip()
        if p and p not in chunks:
            chunks.append(p)
    if session_id:
        for blob in (
            fetch_obra_licitacion_corpus_from_index(session_id),
            fetch_obra_e1_format_corpus_from_index(session_id),
            fetch_obra_e3e_format_corpus_from_index(session_id),
        ):
            b = str(blob or "").strip()
            if b and b not in chunks:
                chunks.append(b)
    return "\n\n".join(chunks)[:160000]


def _resolve_e3e_fill_slots(
    *,
    concurso: str,
    corpus: str,
    obra_descripcion: str,
    master_profile: Dict[str, Any],
    utilidad_rate: float,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
) -> tuple[str, str, str]:
    """Resuelve número de licitación, objeto de obra y % utilidad para E-3 E."""
    state = session_state or {}
    blob = _expanded_obra_corpus(corpus, state, session_id=session_id)

    num = _extract_licitacion_numero(concurso, blob, session_id=session_id)
    if not num or num == "[Consignar]" or is_hru_consignar_placeholder(num):
        num = _extract_licitacion_numero("", blob, session_id=session_id)
    if not num or num == "[Consignar]" or is_hru_consignar_placeholder(num):
        label = resolve_obra_concurso_label(
            session_state=state,
            session_id=session_id,
            corpus=blob,
        )
        num = _extract_licitacion_numero(label, blob, session_id=session_id)
        if is_hru_consignar_placeholder(num) or num == "[Consignar]":
            m = re.search(r"(?i)\b([A-Z]/\d+/\d+)\b", label)
            num = m.group(1).upper() if m else ""

    obra = resolve_obra_objeto(
        session_state=state,
        session_id=session_id,
        corpus=blob,
        explicit=str(obra_descripcion or ""),
    )
    if is_hru_consignar_placeholder(obra):
        obra = extract_obra_descripcion_from_corpus(blob, "") or ""

    rate = float(utilidad_rate or 0)
    if rate > 1:
        pct_fill = f"{rate:.2f}%"
    elif 0 < rate < 1:
        pct_fill = f"{rate * 100:.2f}%"
    else:
        pct_fill = "[Consignar — % utilidad del motor económico]"

    return num, obra, pct_fill


def _apply_e3e_final_slot_values(
    out: str,
    *,
    num: str,
    obra: str,
    pct_fill: str,
) -> str:
    """Sustituye placeholders residuales y normaliza la línea ES DEL … %."""
    text = str(out or "")
    num_ok = bool(num) and num != "[Consignar]" and not is_hru_consignar_placeholder(num)
    obra_ok = bool(obra) and not is_hru_consignar_placeholder(obra)

    if num_ok:
        text = re.sub(
            r"(?i)\[Consignar[^\]]*n[uú]mero de licitaci[oó]n[^\]]*\]",
            num,
            text,
        )
        text = re.sub(
            r"(?i)concurso\s+no:\s*\[Consignar[^\]]+\]",
            f"CONCURSO No: {num}",
            text,
        )
    if obra_ok:
        text = re.sub(
            r"(?i)\[Consignar[^\]]*objeto[^\]]*obra[^\]]*\]",
            obra,
            text,
        )
        # Quitar línea suelta duplicada de objeto si ya quedó en el párrafo principal.
        kept: List[str] = []
        obra_in_main = bool(
            re.search(
                r"(?i)relacionado\s+con\s+la\s+obra[:\s]*"
                + re.escape(obra[:40]),
                text,
            )
        )
        for line in text.splitlines():
            if (
                obra_in_main
                and is_hru_consignar_placeholder(line.strip())
                and "obra" in line.lower()
            ):
                continue
            kept.append(line)
        text = "\n".join(kept)

    text = re.sub(
        r"(?i)es\s+del\s+(?:\[consignar[^\]]+\]|_[\s_]{2,}%?|[\d.,]+\s*%)",
        f"ES DEL {pct_fill}",
        text,
        count=1,
    )
    return text.strip()


def fetch_obra_e3e_format_corpus_from_index(session_id: str) -> str:
    """Recupera chunks del índice con el machote Anexo E-3 E (utilidad %)."""
    if not str(session_id or "").strip():
        return ""
    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    parts: List[str] = []
    seen: set = set()

    def _add(text: str) -> None:
        t = str(text or "").strip()
        if not t or t in seen:
            return
        low = t.lower()
        if "e-3 e" not in low and "e 3 e" not in low and "utilidad propuesta" not in low:
            return
        seen.add(t)
        parts.append(t)

    for q in (
        "ANEXO E-3 E LA UTILIDAD PROPUESTA PARA EL CONCURSO",
        "UTILIDAD PROPUESTA ART 63 FRACCIÓN IV LEY DE OBRA PÚBLICA GUANAJUATO",
        "CARGO POR UTILIDAD OBLIGACIONES LABORALES FISCALES FIRMA",
    ):
        try:
            res = vdb.query_texts(session_id, q, n_results=16)
            for doc in res.get("documents") or []:
                _add(str(doc or ""))
        except Exception:
            continue
    try:
        for doc, _meta in vdb.scan_session_chunks(session_id):
            _add(str(doc or ""))
    except Exception:
        pass
    return "\n\n".join(parts)[:120000]


def assemble_obra_e3e_corpus(
    *,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    bases_corpus_hint: str = "",
    req_snippet: str = "",
) -> str:
    """Corpus unificado para detectar y rellenar el machote E-3 E."""
    state = session_state or {}
    chunks: List[str] = []
    for part in (
        fetch_obra_e3e_format_corpus_from_index(session_id),
        str(state.get("_obra_e3_snippet") or ""),
        str(bases_corpus_hint or ""),
        str(req_snippet or ""),
        str(state.get("bases_corpus_hint") or "")[:120000],
    ):
        p = str(part or "").strip()
        if p and p not in chunks:
            chunks.append(p)
    return "\n\n".join(chunks)


def is_official_obra_e3e_mirror_content(content: str) -> bool:
    """True si el cuerpo es el machote E-3 E de bases."""
    up = str(content or "").upper()
    return (
        "UTILIDAD PROPUESTA" in up
        and ("ANEXO E-3 E" in up or "ART. 63" in up or "ART 63" in up)
    )


def extract_obra_e3e_official_format(corpus: str) -> Optional[str]:
    """Extrae machote Anexo E-3 E embebido en bases (fail-closed)."""
    text = str(corpus or "")
    if len(text) < 80:
        return None
    start = -1
    m = _E3E_FORMAT_START_RE.search(text)
    if m:
        start = m.start()
    else:
        u = _E3E_UTILIDAD_RE.search(text)
        if u:
            start = max(0, u.start() - 200)
    if start < 0:
        return None
    tail = text[start:]
    end_m = re.search(r"(?is)\bfirma\b", tail)
    chunk = tail[: end_m.end()] if end_m else tail[:2200]
    chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip()
    if len(chunk) < 100:
        return None
    if "utilidad" not in chunk.lower() or "%" not in chunk:
        return None
    return normalize_official_template_text(chunk)


def fill_obra_e3e_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    obra_descripcion: str,
    master_profile: Dict[str, Any],
    utilidad_rate: float,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Rellena machote E-3 E con % utilidad verificado del motor económico."""
    out = normalize_official_template_text(str(template or ""))
    blob = _expanded_obra_corpus(corpus, session_state, session_id=session_id)
    num, obra, pct_fill = _resolve_e3e_fill_slots(
        concurso=concurso,
        corpus=blob,
        obra_descripcion=obra_descripcion,
        master_profile=master_profile,
        utilidad_rate=utilidad_rate,
        session_id=session_id,
        session_state=session_state,
    )
    obra_ok = obra and not is_hru_consignar_placeholder(obra)
    razon = _slot(
        master_profile.get("razon_social"),
        "[Consignar — razón social]",
    )
    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "[Consignar — representante legal]",
    )

    if session_id:
        slug = session_id.replace("_", " ").upper()
        if slug and slug in out.upper():
            if num and num != "[Consignar]" and not is_hru_consignar_placeholder(num):
                out = re.sub(re.escape(slug), num, out, flags=re.I)
            if obra_ok:
                out = re.sub(re.escape(slug), obra, out, flags=re.I)

    num_ok = bool(num) and num != "[Consignar]" and not is_hru_consignar_placeholder(num)
    if num_ok:
        out = re.sub(
            r"(?i)(concurso\s+no[:\s]*)(?:_{2,}|[^\n]{0,120}?)(?=\s*relacionado|\n)",
            rf"\1{num} ",
            out,
            count=1,
        )
        out = re.sub(r"(?i)concurso\s+no[:\s]*_{3,}", f"CONCURSO NO: {num}", out)
    if obra_ok:
        out = re.sub(
            r"(?i)(relacionado\s+con\s+la\s+obra[:\s]*)(?:_{2,}|[^\n]{0,200}?)(?=\s*es\s+del|\n)",
            rf"\1{obra} ",
            out,
            count=1,
        )
        out = re.sub(
            r"(?i)relacionado\s+con\s+la\s+obra[:\s]*_{3,}",
            f"RELACIONADO CON LA OBRA: {obra}",
            out,
            count=1,
        )
        if re.search(r"_{8,}", out):
            out = re.sub(r"_{8,}", obra, out, count=1)

    out = _apply_e3e_final_slot_values(out, num=num, obra=obra, pct_fill=pct_fill)
    signature = f"\n\n{razon.upper()}\n{rep.upper()}\nFIRMA"
    out = re.sub(r"(?i)\bfirma\b\.?", signature, out, count=1)
    return out.strip()


def build_obra_e3e_utilidad_markdown(
    *,
    concurso: str,
    master_profile: Dict[str, Any],
    utilidad_rate: float = 0.0,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    bases_corpus_hint: str = "",
    req_snippet: str = "",
    obra_descripcion: str = "",
    session_name: str = "",
) -> str:
    """Anexo E-3 E — utilidad propuesta (espejo HRU o shell fail-closed)."""
    corpus = assemble_obra_e3e_corpus(
        session_id=session_id,
        session_state=session_state,
        bases_corpus_hint=bases_corpus_hint,
        req_snippet=req_snippet,
    )
    concurso_label = resolve_obra_concurso_label(
        session_state=session_state,
        session_id=session_id,
        corpus=corpus,
    )
    if looks_like_session_slug(concurso, session_id):
        concurso = concurso_label
    obra = resolve_obra_objeto(
        session_state=session_state,
        session_id=session_id,
        corpus=corpus,
        explicit=str(obra_descripcion or ""),
    )
    official = extract_obra_e3e_official_format(corpus)
    if official:
        return fill_obra_e3e_official_format(
            official,
            concurso=concurso_label,
            corpus=corpus,
            obra_descripcion=obra,
            master_profile=master_profile,
            utilidad_rate=utilidad_rate,
            session_id=session_id,
            session_state=session_state,
        )
    from app.services.official_format_resolver import (
        build_official_miss_shell,
        should_use_miss_shell_instead_of_generic,
    )

    req_line = _clean_economic_req_line(
        req_snippet,
        "E-3 E",
        "Declaración de utilidad propuesta conforme al Art. 63 LOPSRM.",
    )
    concurso_label = _resolve_concurso_label(concurso, corpus, concurso, session_id=session_id)
    return build_official_miss_shell(
        "obra|E3E",
        concurso=concurso_label,
        req_line=req_line,
        master_profile=master_profile,
    )


def build_obra_e1_carta_compromiso_markdown(
    *,
    concurso: str,
    master_profile: Dict[str, Any],
    resumen: Dict[str, Any],
    req_snippet: str = "",
    plazo_ejecucion: str = "",
    obra_descripcion: str = "",
    session_name: str = "",
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    bases_corpus_hint: str = "",
    req_desc: str = "",
) -> str:
    """
    Carta-compromiso de la proposición (Anexo E-1) con importe total e IVA desde motor.

    Si las bases publican el machote E-1, se usa como espejo (HRU); si no, carta genérica.
    """
    corpus = assemble_obra_e1_corpus(
        session_id=session_id,
        session_state=session_state,
        bases_corpus_hint=bases_corpus_hint,
        req_snippet=req_snippet,
        req_desc=req_desc,
    )
    concurso_label = resolve_obra_concurso_label(
        session_state=session_state,
        session_id=session_id,
        corpus=corpus,
    )
    if looks_like_session_slug(concurso, session_id):
        concurso = concurso_label
    state = session_state or {}
    plazo = (
        str(plazo_ejecucion or "").strip()
        or str(state.get("_obra_plazo_hint") or "").strip()
        or extract_obra_plazo_ejecucion(corpus)
    )
    official = extract_obra_e1_official_format(corpus)
    if official:
        obra = resolve_obra_objeto(
            session_state=state,
            session_id=session_id,
            corpus=corpus,
            explicit=str(obra_descripcion or ""),
        )
        return fill_obra_e1_official_format(
            official,
            concurso=concurso_label,
            corpus=corpus,
            obra_descripcion=obra,
            master_profile=master_profile,
            resumen=resumen,
            plazo_ejecucion=plazo,
            session_id=session_id,
        )

    from app.services.official_format_resolver import (
        build_official_miss_shell,
        should_use_miss_shell_instead_of_generic,
    )

    req_line = _clean_economic_req_line(
        req_snippet,
        "E-1",
        "Carta-compromiso en papel membretado del participante con el importe total "
        "de la proposición (incluyendo I.V.A.) y el plazo de ejecución solicitado.",
    )
    concurso_label = _resolve_concurso_label(concurso, corpus, concurso)
    if should_use_miss_shell_instead_of_generic(corpus, "obra|E1"):
        return build_official_miss_shell(
            "obra|E1",
            concurso=concurso_label,
            req_line=req_line,
            master_profile=master_profile,
        )

    razon = _slot(master_profile.get("razon_social"), "la empresa concursante")
    rfc = _slot(master_profile.get("rfc"), "S/D")
    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "el representante legal",
    )
    domicilio = _slot(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio"),
        "domicilio fiscal registrado ante el SAT",
    )
    total = float(resumen.get("total") or 0)
    iva = float(resumen.get("iva") or 0)
    moneda = str(resumen.get("moneda") or "MXN")
    total_line = (
        f"**{_money(total)}** ({moneda}), incluyendo I.V.A. por **{_money(iva)}**"
        if total > 0
        else "**[Consignar]** — importe total con I.V.A. verificado en el motor económico"
    )
    plazo_line = plazo if plazo else "**[Consignar]** — plazo congruente con el programa de ejecución"

    parts = [
        "**ANEXO E-1 — CARTA-COMPROMISO DE LA PROPOSICIÓN**\n",
        f"**Concurso:** {concurso_label}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\nNosotros, **"
        f"{razon}**, con domicilio en {domicilio}, Registro Federal de Contribuyentes "
        f"**{rfc}**, representados en este acto por **{rep}**, en su carácter de "
        "Representante Legal, **bajo protesta de decir verdad**, manifestamos:\n",
        "\n1. Presentamos la presente carta-compromiso en **papel membretado del "
        "participante**, conforme al Anexo E-1 de las bases.\n",
        f"\n2. **Importe total de la proposición (incluyendo I.V.A.):** {total_line}.\n",
        f"\n3. **Plazo de ejecución solicitado:** {plazo_line}.\n",
        "\n4. Nos obligamos a cumplir los términos de la proposición económica "
        "presentada y a mantener los importes durante el procedimiento de adjudicación "
        "y, en su caso, durante la vigencia del contrato respectivo.\n",
        "\nLo anterior, en cumplimiento del Anexo E-1 de las bases.\n",
        "\nProtesto lo necesario.",
    ]
    return "\n".join(parts)


_E2_FORMAT_START_RE = re.compile(r"(?is)anexo\s+e[\s_.-]*2\b")
_E4_FORMAT_START_RE = re.compile(r"(?is)anexo\s+e[\s_.-]*4\b")
_E5_FORMAT_START_RE = re.compile(r"(?is)anexo\s+e[\s_.-]*5\b")


def _obra_e2_catalog_table_block(
    mapeo_items: List[Dict[str, Any]],
    resumen: Dict[str, Any],
) -> str:
    """Tabla de catálogo E-2 desde motor económico."""
    cols = ("PARTIDA", "CONCEPTO", "UNIDAD", "CANT.", "P.U.", "IMPORTE")
    rows: List[List[str]] = []
    for item in mapeo_items:
        pu = float(item.get("precio_unitario") or 0)
        imp = float(item.get("importe") or 0)
        if pu <= 0 and imp > 0:
            cant = float(item.get("cantidad") or 1)
            pu = imp / cant if cant else 0
        rows.append(
            [
                str(item.get("partida") or ""),
                str(item.get("descripcion") or item.get("concepto") or "")[:200],
                str(item.get("unidad") or "[Consignar]"),
                str(item.get("cantidad") or ""),
                _money(pu) if pu > 0 else "[Consignar]",
                _money(imp) if imp > 0 else "[Consignar]",
            ]
        )
    if not rows:
        rows = [["[Consignar]"] * len(cols)]
    parts = ["\n**Catálogo de conceptos y precios unitarios:**\n", _markdown_table(list(cols), rows)]
    if resumen.get("obra_breakdown"):
        parts.extend(
            [
                f"\n**Costos directos:** {_money(float(resumen.get('costos_directos') or 0))}",
                f"**Costos indirectos:** {_money(float(resumen.get('costos_indirectos') or 0))}",
                f"**Utilidad:** {_money(float(resumen.get('utilidad') or 0))}",
                f"**Subtotal antes de IVA:** {_money(float(resumen.get('subtotal') or 0))}",
                f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))}",
                f"**Total de la proposición:** {_money(float(resumen.get('total') or 0))}\n",
            ]
        )
    else:
        parts.append(
            f"\n**Subtotal:** {_money(float(resumen.get('subtotal') or 0))} | "
            f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))} | "
            f"**Total:** {_money(float(resumen.get('total') or 0))}\n"
        )
    return "\n".join(parts)


def extract_obra_e2_official_format(corpus: str) -> Optional[str]:
    """Extrae machote Anexo E-2 embebido en bases."""
    text = str(corpus or "")
    if len(text) < 80:
        return None
    start = -1
    m = _E2_FORMAT_START_RE.search(text)
    if m:
        start = m.start()
    else:
        alt = re.search(r"(?is)cat[aá]logo de conceptos", text)
        if alt:
            start = alt.start()
    if start < 0:
        return None
    tail = text[start:]
    end_m = re.search(
        r"(?is)(total de la proposici[oó]n|protesto lo necesario|nombre\s+y\s+firma)",
        tail,
    )
    chunk = tail[: end_m.end() if end_m else 3200]
    if len(chunk) < 80:
        return None
    low = chunk.lower()
    if "concepto" not in low and "catálogo" not in low and "catalogo" not in low:
        return None
    return normalize_official_template_text(chunk)


def is_official_obra_e2_mirror_content(content: str) -> bool:
    """True si el cuerpo es machote E-2 de bases (no builder determinístico)."""
    text = str(content or "")
    up = text.upper()
    if "**ANEXO E-2 — CATÁLOGO DE CONCEPTOS" in up:
        return False
    return (
        ("ANEXO E-2" in up or "CATÁLOGO DE CONCEPTOS" in up or "CATALOGO DE CONCEPTOS" in up)
        and ("PRECIOS UNITARIOS" in up or "UNIDADES DE MEDICIÓN" in up or "UNIDADES DE MEDICION" in up)
    )


def fill_obra_e2_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    mapeo_items: List[Dict[str, Any]],
    resumen: Dict[str, Any],
) -> str:
    """Rellena machote E-2 con catálogo del motor económico."""
    out = normalize_official_template_text(str(template or ""))
    num = _extract_licitacion_numero(concurso, corpus)
    out = re.sub(r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?\s*)_{3,}", rf"\g<1>{num}", out)
    out = re.sub(r"(?i)\bnum\.?\s*_{3,}", f"NUM. {num}", out, count=1)
    table = _obra_e2_catalog_table_block(mapeo_items, resumen)
    return f"{out.strip()}\n{table}".strip()


def extract_obra_e4_official_format(corpus: str) -> Optional[str]:
    """Extrae machote Anexo E-4 (programas Gantt) embebido en bases."""
    text = str(corpus or "")
    if len(text) < 60:
        return None
    start = -1
    m = _E4_FORMAT_START_RE.search(text)
    if m:
        start = m.start()
    else:
        alt = re.search(r"(?is)programas?\s+de\s+obra", text)
        if alt and "gantt" in text.lower():
            start = alt.start()
    if start < 0:
        return None
    tail = text[start:]
    end_m = re.search(r"(?is)(protesto lo necesario|nombre\s+y\s+firma)", tail)
    chunk = tail[: end_m.end() if end_m else 2400]
    if len(chunk) < 60 or "gantt" not in chunk.lower():
        return None
    return normalize_official_template_text(chunk)


def is_official_obra_e4_mirror_content(content: str) -> bool:
    """True si el cuerpo es machote E-4 de bases."""
    up = str(content or "").upper()
    if "**ANEXO E-4 — PROGRAMAS DE OBRA" in up:
        return False
    return "ANEXO E-4" in up and "GANTT" in up


def fill_obra_e4_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    has_gantt_attachments: bool = False,
) -> str:
    """Rellena machote E-4; Gantt físico queda en HITL."""
    out = normalize_official_template_text(str(template or ""))
    num = _extract_licitacion_numero(concurso, corpus)
    out = re.sub(r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?\s*)_{3,}", rf"\g<1>{num}", out)
    if has_gantt_attachments:
        out += (
            "\n\n**Bajo protesta de decir verdad**, anexo los programas de obra en formato Gantt "
            "exigidos en bases."
        )
    else:
        out += (
            "\n\n**[Consignar]** — Adjunte ambos programas Gantt (físico y de montos mensuales) "
            "conforme al plazo de ejecución y calendario de bases."
        )
    return out.strip()


def extract_obra_e5_official_format(corpus: str) -> Optional[str]:
    """Extrae machote Anexo E-5 (cotizaciones) embebido en bases."""
    text = str(corpus or "")
    if len(text) < 60:
        return None
    start = -1
    m = _E5_FORMAT_START_RE.search(text)
    if m:
        start = m.start()
    else:
        alt = re.search(r"(?is)cotizaciones?\s+de\s+(?:los\s+)?materiales", text)
        if alt:
            start = alt.start()
    if start < 0:
        return None
    tail = text[start:]
    end_m = re.search(r"(?is)(protesto lo necesario|nombre\s+y\s+firma)", tail)
    chunk = tail[: end_m.end() if end_m else 2200]
    if len(chunk) < 60 or "material" not in chunk.lower():
        return None
    return normalize_official_template_text(chunk)


def is_official_obra_e5_mirror_content(content: str) -> bool:
    """True si el cuerpo es machote E-5 de bases."""
    up = str(content or "").upper()
    if "**ANEXO E-5 — COTIZACIONES DE MATERIALES" in up:
        return False
    return "ANEXO E-5" in up or "COTIZACIONES DE MATERIALES" in up or "COTIZACIONES DE LOS MATERIALES" in up


def fill_obra_e5_official_format(
    template: str,
    *,
    concurso: str,
    corpus: str,
    has_cotizaciones_attachments: bool = False,
) -> str:
    """Rellena machote E-5; cotizaciones físicas quedan en HITL."""
    out = normalize_official_template_text(str(template or ""))
    num = _extract_licitacion_numero(concurso, corpus)
    out = re.sub(r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?\s*)_{3,}", rf"\g<1>{num}", out)
    if has_cotizaciones_attachments:
        out += (
            "\n\n**Bajo protesta de decir verdad**, anexo las cotizaciones de materiales "
            "exigidas en bases."
        )
    else:
        out += (
            "\n\n**[Consignar]** — Adjunte cotizaciones originales en hoja membretada de "
            "proveedores. El sistema no inventa precios sin evidencia documental."
        )
    return out.strip()


def build_obra_e2_catalog_markdown(
    *,
    concurso: str,
    mapeo_items: List[Dict[str, Any]],
    resumen: Dict[str, Any],
    req_snippet: str = "",
) -> str:
    """
    Catálogo E-2 con unidad, cantidad y precio unitario (sin inventar partidas).

    Returns:
        Markdown del cuerpo del Anexo E-2 / AE.
    """
    req_line = _clean_economic_req_line(
        req_snippet,
        "E-2",
        "Catálogo de conceptos, unidades de medición, cantidades de trabajo, "
        "precios unitarios propuestos y el total de la proposición.",
    )
    official = extract_obra_e2_official_format(req_snippet)
    if official:
        return fill_obra_e2_official_format(
            official,
            concurso=concurso,
            corpus=req_snippet,
            mapeo_items=mapeo_items,
            resumen=resumen,
        )
    cols = ("PARTIDA", "CONCEPTO", "UNIDAD", "CANT.", "P.U.", "IMPORTE")
    rows: List[List[str]] = []
    for item in mapeo_items:
        pu = float(item.get("precio_unitario") or 0)
        imp = float(item.get("importe") or 0)
        if pu <= 0 and imp > 0:
            cant = float(item.get("cantidad") or 1)
            pu = imp / cant if cant else 0
        rows.append(
            [
                str(item.get("partida") or ""),
                str(item.get("descripcion") or item.get("concepto") or "")[:200],
                str(item.get("unidad") or "[Consignar]"),
                str(item.get("cantidad") or ""),
                _money(pu) if pu > 0 else "[Consignar]",
                _money(imp) if imp > 0 else "[Consignar]",
            ]
        )
    if not rows:
        rows = [["[Consignar]"] * len(cols)]

    parts = [
        "**ANEXO E-2 — CATÁLOGO DE CONCEPTOS Y PRECIOS UNITARIOS**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\n**Bajo protesta de decir verdad**, presento el catálogo de conceptos con "
        "cantidades y precios unitarios propuestos:\n\n",
        _markdown_table(list(cols), rows),
        "\n",
    ]
    if resumen.get("obra_breakdown"):
        parts.extend(
            [
                f"\n**Costos directos:** {_money(float(resumen.get('costos_directos') or 0))}",
                f"**Costos indirectos:** {_money(float(resumen.get('costos_indirectos') or 0))}",
                f"**Utilidad:** {_money(float(resumen.get('utilidad') or 0))}",
                f"**Subtotal antes de IVA:** {_money(float(resumen.get('subtotal') or 0))}",
                f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))}",
                f"**Total de la proposición:** {_money(float(resumen.get('total') or 0))}\n",
            ]
        )
    else:
        parts.append(
            f"\n**Subtotal:** {_money(float(resumen.get('subtotal') or 0))} | "
            f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))} | "
            f"**Total:** {_money(float(resumen.get('total') or 0))}\n"
        )
    parts.extend(
        [
            "\nLos importes anteriores provienen del motor económico de la sesión; "
            "cualquier corrección de precios unitarios debe reflejarse en el catálogo "
            "y en las tarjetas APU antes de la entrega.\n",
            "\nLo anterior, en cumplimiento del Anexo E-2 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e3_annex_markdown(
    *,
    concurso: str,
    mapeo_items: List[Dict[str, Any]],
    req_snippet: str = "",
    tabla_precios_basename: str = "",
    has_verified_apu_cards: bool = False,
) -> str:
    """
    Portada E-3 sin desglose APU inventado.

    Las tarjetas APU por concepto (E-3 A–F) son HITL o importación desde Excel.
    """
    req_line = _clean_economic_req_line(
        req_snippet,
        "E-3",
        "Análisis de los precios unitarios estructurados por costos directos, "
        "indirectos, financiamiento y utilidad, con subanexos E-3 A a E-3 F.",
    )
    checklist = _e3_subannex_checklist(req_snippet)
    concept_lines = []
    for item in mapeo_items[:50]:
        desc = str(item.get("descripcion") or item.get("concepto") or "").strip()
        if desc:
            concept_lines.append(
                f"- Partida {item.get('partida', '')}: {desc[:160]}"
            )
    parts = [
        "**ANEXO E-3 — ANÁLISIS DE PRECIOS UNITARIOS**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\n**Subanexos exigidos en bases:**\n",
    ]
    for code in checklist:
        parts.append(f"- **{code}**")
    parts.append("")
    if concept_lines:
        parts.append("**Conceptos del catálogo sujetos a tarjeta APU:**\n")
        parts.extend(concept_lines)
        parts.append("")
    if tabla_precios_basename:
        parts.append(
            f"**Soporte tabular:** `{tabla_precios_basename}` (catálogo / precios unitarios).\n"
        )
    if has_verified_apu_cards:
        parts.append(
            "\n**Bajo protesta de decir verdad**, integro las **tarjetas de análisis de "
            "precios unitarios** desglosadas por concepto, conforme a los subanexos E-3 A a E-3 F.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo las **tarjetas de "
                "análisis de precios unitarios** por cada concepto del catálogo, con los "
                "subanexos exigidos en bases.\n",
                "\n**Documentos requeridos (no generables automáticamente sin HITL):**\n",
                "- Tarjetas APU por concepto (costos directos, indirectos, financiamiento, utilidad).\n",
                "- Desglose factor de salario real (E-3 B), indirectos (E-3 C), financiamiento (E-3 D), "
                "utilidad/fiscal (E-3 E) y básicos de cuadrillas/materiales (E-3 F).\n",
                "\n**[Consignar]** — Adjunte las tarjetas APU verificadas. El sistema **no** "
                "inventa porcentajes de materiales/mano de obra sin evidencia documental.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-3 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e4_programa_markdown(
    *,
    concurso: str,
    req_snippet: str = "",
    has_gantt_attachments: bool = False,
) -> str:
    """Anexo E-4: programas Gantt (HITL físico)."""
    official = extract_obra_e4_official_format(req_snippet)
    if official:
        return fill_obra_e4_official_format(
            official,
            concurso=concurso,
            corpus=req_snippet,
            has_gantt_attachments=has_gantt_attachments,
        )
    req_line = extract_obra_annex_inventory_requirement(req_snippet, "E-4")
    if not req_line:
        req_line = "Programas de obra en barras de Gantt (físico y de montos mensuales)."
    parts = [
        "**ANEXO E-4 — PROGRAMAS DE OBRA (GANTT)**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
    ]
    if has_gantt_attachments:
        parts.append(
            "\n**Bajo protesta de decir verdad**, anexo los programas de obra en formato Gantt "
            "exigidos en bases:\n"
            "- Programa de obra físico por conceptos o partidas.\n"
            "- Programa de obra físico de montos mensuales por conceptos o partidas.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo los programas de obra "
                "en formato Gantt exigidos en bases.\n",
                "\n**Documentos requeridos (no generables por el sistema):**\n",
                "a) **Programa de obra físico** en barras de Gantt, por conceptos o partidas.\n",
                "b) **Programa de obra físico de montos mensuales** en barras de Gantt.\n",
                "\n**[Consignar]** — Adjunte ambos programas elaborados conforme al plazo de "
                "ejecución de la obra y al calendario de bases.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-4 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e5_cotizaciones_markdown(
    *,
    concurso: str,
    req_snippet: str = "",
    has_cotizaciones_attachments: bool = False,
) -> str:
    """
    Anexo E-5: cotizaciones de materiales (HITL físico).

    No afirma adjuntar cotizaciones sin evidencia documental en sesión.
    """
    corpus = str(req_snippet or "")
    official = extract_obra_e5_official_format(corpus)
    if official:
        return fill_obra_e5_official_format(
            official,
            concurso=concurso,
            corpus=corpus,
            has_cotizaciones_attachments=has_cotizaciones_attachments,
        )
    req_line = _clean_economic_req_line(
        corpus,
        "E-5",
        "Cotizaciones de los materiales a utilizar en la obra.",
    )
    concurso_label = _resolve_concurso_label(concurso, corpus, concurso)
    parts = [
        "**ANEXO E-5 — COTIZACIONES DE MATERIALES**\n",
        f"**Concurso:** {concurso_label}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
    ]
    if has_cotizaciones_attachments:
        parts.append(
            "\n**Bajo protesta de decir verdad**, anexo las cotizaciones de materiales "
            "exigidas en bases, emitidas por los proveedores correspondientes.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo las cotizaciones "
                "de materiales exigidas en las bases.\n",
                "\n**Documentos requeridos (no generables por el sistema):**\n",
                "- Cotizaciones de los materiales a utilizar en la obra, en original o copia "
                "certificada conforme a bases.\n",
                "- Deben corresponder a los insumos y costos básicos de materiales "
                "utilizados en el Anexo E-3.\n",
                "\n**[Consignar]** — Adjunte las cotizaciones originales en hoja membretada "
                "de los proveedores. El sistema **no** inventa precios de proveedores "
                "sin evidencia documental.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-5 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)
