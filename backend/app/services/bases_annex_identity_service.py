"""
Identidad de anexos desde bases primarias (HRU).

Extrae del PDF de convocatoria/bases: entrada en índice de anexos, requisitos que citan
el anexo y posibles inconsistencias de referencia cruzada (p. ej. Anexo K vs N).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.annex_resolution_service import detect_annex_identity_intent
from app.services.junta_bases_corpus import _PAGE_SPLIT_RE

_NUMBERED_ITEM_RE = re.compile(
    r"(?im)^\s*(\d+(?:\.\d+)?)\.\s+(.+)$",
)
_INDEX_BLOCK_RE = re.compile(r"(?is)\banexo\s+t[ií]tulo\b")
_OCR_NOISE_RE = re.compile(
    r"(?i)transcripci[oó]n del texto|devuelve [úu]nicamente|"
    r"no agregues introducciones|comit[eé] de adquisiciones"
)
_MAX_REQUIREMENT_CHARS = 520
_MIN_REQUIREMENT_CHARS = 24
_ANNEX_LINE_RE = re.compile(
    r"(?i)\banexo\s+"
    r"(iii\s*[-–]\s*[a-z]"
    r"|[ivxlc]{1,6}"
    r"|[a-z]{2,14}"
    r"|[a-z0-9])"
    r"\b"
)
_ANNEX_PAGE_QUERY_RE = (
    re.compile(r"(?i)\b(?:pag(?:ina|\.)?|p\.)\s*\d+\b"),
    re.compile(r"(?i)\bmencion"),
    re.compile(r"(?i)\balusi"),
    re.compile(r"(?i)\bcit[aá]"),
    re.compile(r"(?i)\bdice\b"),
    re.compile(r"(?i)\best[aá]\b"),
)
_THEME_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("interes", ("interes", "intereses")),
    ("antisoborno", ("antisoborno", "soborno")),
    ("integridad", ("integridad",)),
    ("muestra", ("muestra", "muestras")),
    ("contenido_nacional", ("contenido nacional",)),
)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", str(text or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.lower()).strip()


def _normalize_annex_token(raw: str) -> str:
    tok = str(raw or "").strip().lower().replace("–", "-")
    tok = re.sub(r"\s+", "-", tok)
    return tok


def parse_annex_token_from_query(query: str) -> Optional[str]:
    """Token de anexo pedido en la consulta (K, III-K, M, AB, VIII, …)."""
    q = str(query or "")
    m = re.search(r"(?i)\banexo\s+(iii\s*[-–]\s*[a-z])\b", q)
    if m:
        return _normalize_annex_token(m.group(1))
    m = re.search(r"(?i)\banexo\s+([ivxlc]{1,6})\b", q)
    if m:
        return m.group(1).lower()
    m = re.search(r"(?i)\banexo\s+([a-z]{2,14})\b", q)
    if m:
        tok = m.group(1).lower()
        if not tok.startswith("iii"):
            return tok
    m = re.search(r"(?i)\banexo\s+([a-z0-9])\b", q)
    if m:
        return m.group(1).lower()
    return None


def parse_page_from_query(query: str) -> Optional[int]:
    """Página explícita en la consulta (p. 15, página 9, …)."""
    for pat in (
        r"(?i)\bp(?:ag(?:ina|\.)?|\.)\s*(\d+)\b",
        r"(?i)\bpagina\s+(\d+)",
    ):
        m = re.search(pat, str(query or ""))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def detect_annex_bases_intent(query: str) -> bool:
    """
    Consulta sobre identidad o mención de un anexo en las bases primarias.

    Incluye «de qué va el Anexo K» y «¿hay alusión al Anexo K en p. 15?».
    """
    q = str(query or "")
    token = parse_annex_token_from_query(q)
    if not token:
        return False
    qn = _fold(q)
    if "anexo" not in qn:
        return False
    if detect_annex_identity_intent(q):
        return True
    if any(pat.search(q) for pat in _ANNEX_PAGE_QUERY_RE):
        return True
    q_fold = _fold(q)
    if any(
        phrase in q_fold
        for phrase in (
            "de que va",
            "de que trata",
            "que es el",
            "que es",
            "que va",
            "para que",
            "que contiene",
            "que incluye",
            "cual es",
        )
    ):
        return True
    return False


def _annex_reference_pattern(token: str) -> re.Pattern[str]:
    """Patrón que distingue Anexo K de Anexo III-K u otros compuestos."""
    tok = _normalize_annex_token(token)
    if re.match(r"^iii-[a-z]$", tok):
        letter = tok.split("-")[-1]
        return re.compile(rf"(?i)\banexo\s+iii\s*[-–]\s*{re.escape(letter)}\b")
    if re.match(r"^[a-z0-9]$", tok) or tok.isdigit():
        return re.compile(rf"(?i)\banexo\s+{re.escape(tok)}\b(?!\s*[-–])")
    if re.match(r"^[ivxlc]+$", tok):
        return re.compile(rf"(?i)\banexo\s+{re.escape(tok)}\b")
    escaped = re.escape(tok).replace(r"\-", r"[- ]?")
    return re.compile(rf"(?i)\banexo\s+{escaped}\b")


def _paren_annex_pattern(token: str) -> re.Pattern[str]:
    tok = _normalize_annex_token(token)
    return re.compile(rf"(?i)\(\s*anexo\s+{re.escape(tok)}\s*\)")


def _display_annex_token(token: str) -> str:
    tok = _normalize_annex_token(token)
    if re.match(r"^[a-z0-9]$", tok):
        return tok.upper()
    if re.match(r"^iii-[a-z]$", tok):
        return f"III-{tok.split('-')[-1].upper()}"
    return tok.upper()


def _strip_source_noise(text: str) -> str:
    t = re.sub(r"\[FUENTE:[^\]]*\]\s*", "", str(text or ""), flags=re.I)
    t = re.sub(
        r"COMIT[EÉ] DE ADQUISICIONES[^\n]*\n",
        "",
        t,
        flags=re.I,
    )
    return t


def _build_page_spans(full_text: str) -> Tuple[str, List[Tuple[int, int, int]]]:
    parts = _PAGE_SPLIT_RE.split(full_text)
    if len(parts) <= 1:
        return full_text, []
    spans: List[Tuple[int, int, int]] = []
    cursor = 0
    combined_parts: List[str] = []
    if parts[0].strip():
        combined_parts.append(parts[0])
        cursor += len(parts[0])
    for i in range(1, len(parts), 2):
        try:
            pg = int(parts[i])
        except (ValueError, IndexError):
            continue
        body = parts[i + 1] if i + 1 < len(parts) else ""
        start = cursor
        combined_parts.append(body)
        cursor += len(body)
        spans.append((start, cursor, pg))
    return "".join(combined_parts), spans


def _page_at_offset(page_spans: List[Tuple[int, int, int]], offset: int) -> Optional[int]:
    for start, end, pg in page_spans:
        if start <= offset < end:
            return pg
    return page_spans[-1][2] if page_spans else None


def _line_at_match(text: str, match: re.Match[str]) -> str:
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end < 0:
        line_end = min(match.end() + 240, len(text))
    return re.sub(r"\s+", " ", text[line_start:line_end]).strip()


def _themes_in_text(text: str) -> Set[str]:
    low = _fold(text)
    found: Set[str] = set()
    for theme_id, needles in _THEME_KEYWORDS:
        if any(n in low for n in needles):
            found.add(theme_id)
    return found


def _scan_index_catalog(text: str) -> Dict[str, str]:
    """Mapa token → línea del índice de anexos."""
    catalog: Dict[str, str] = {}
    combined, _ = _build_page_spans(text)
    idx_m = _INDEX_BLOCK_RE.search(combined)
    block = combined[idx_m.start() : idx_m.start() + 12000] if idx_m else combined[:12000]
    for m in _ANNEX_LINE_RE.finditer(block):
        line = _line_at_match(block, m)
        if len(line) > 220 or not _is_index_catalog_line(line):
            continue
        raw_tok = m.group(1)
        tok = _normalize_annex_token(raw_tok)
        if tok and tok not in catalog:
            catalog[tok] = line
    return catalog


def _is_index_catalog_line(line: str) -> bool:
    """Línea de índice de anexos (no numeral de requisitos numerado)."""
    stripped = str(line or "").strip()
    if not stripped or re.match(r"^\d+\.", stripped):
        return False
    return bool(re.match(r"(?i)^anexo\s+", stripped))


def _extract_index_entries(
    text: str,
    token: str,
    spans: List[Tuple[int, int, int]],
) -> List[Dict[str, Any]]:
    ref_re = _annex_reference_pattern(token)
    combined, _ = _build_page_spans(text) if not spans else (text, spans)
    idx_m = _INDEX_BLOCK_RE.search(combined)
    search_start = idx_m.start() if idx_m else 0
    search_end = min(search_start + 12000, len(combined)) if idx_m else len(combined)
    search_text = combined[search_start:search_end]

    entries: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for m in ref_re.finditer(search_text):
        line = _line_at_match(search_text, m)
        if not line or line in seen or len(line) > 220:
            continue
        if not _is_index_catalog_line(line):
            continue
        seen.add(line)
        abs_off = search_start + m.start()
        pg = _page_at_offset(spans, abs_off)
        entries.append(
            {
                "kind": "index",
                "text": _strip_source_noise(line),
                "pagina": pg,
                "pagina_label": str(pg) if pg else "?",
            }
        )
    return entries


def _is_valid_requirement_body(body: str) -> bool:
    """Descarta ítems indexados por error o bloques OCR/index masivos."""
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    if len(text) < _MIN_REQUIREMENT_CHARS or len(text) > _MAX_REQUIREMENT_CHARS:
        return False
    if _OCR_NOISE_RE.search(text):
        return False
    if text.lower().count("anexo ") > 2:
        return False
    if "anexo título" in _fold(text):
        return False
    return True


def _extract_requirement_hits(
    text: str,
    token: str,
    spans: List[Tuple[int, int, int]],
) -> List[Dict[str, Any]]:
    ref_re = _annex_reference_pattern(token)
    paren_re = _paren_annex_pattern(token)
    combined, _ = _build_page_spans(text) if not spans else (text, spans)
    hits: List[Dict[str, Any]] = []
    seen_nums: Set[str] = set()

    for m in _NUMBERED_ITEM_RE.finditer(combined):
        num = str(m.group(1)).strip()
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        if num in seen_nums:
            continue
        if not (ref_re.search(body) or paren_re.search(body)):
            continue
        if not _is_valid_requirement_body(body):
            continue
        seen_nums.add(num)
        pg = _page_at_offset(spans, m.start())
        hits.append(
            {
                "kind": "requirement",
                "numero": num,
                "text": _strip_source_noise(body),
                "pagina": pg,
                "pagina_label": str(pg) if pg else "?",
            }
        )

    return hits


def _detect_conflicts(
    token: str,
    index_entries: List[Dict[str, Any]],
    requirements: List[Dict[str, Any]],
    index_catalog: Dict[str, str],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    idx_text = " ".join(str(e.get("text") or "") for e in index_entries)
    idx_themes = _themes_in_text(idx_text)

    for req in requirements:
        req_text = str(req.get("text") or "")
        req_themes = _themes_in_text(req_text)
        if "antisoborno" in req_themes and "interes" in idx_themes:
            n_line = index_catalog.get("n", "")
            note = (
                "El numeral cita **Anexo K**, pero el contenido describe **antisoborno**. "
                "En el índice de anexos, **Anexo K** = Declaración de Intereses y "
                "**Anexo N** = Compromiso Antisoborno"
            )
            if n_line:
                note += f" (`{n_line}`)."
            else:
                note += "."
            conflicts.append(
                {
                    "type": "cross_reference_mismatch",
                    "requirement_num": req.get("numero") or "?",
                    "pagina_label": req.get("pagina_label") or "?",
                    "likely_annex": "N",
                    "message": note,
                }
            )
        elif idx_themes and req_themes and not (idx_themes & req_themes):
            conflicts.append(
                {
                    "type": "theme_mismatch",
                    "requirement_num": req.get("numero") or "?",
                    "pagina_label": req.get("pagina_label") or "?",
                    "likely_annex": "",
                    "message": (
                        "El requisito y la entrada del índice no comparten tema evidente; "
                        "conviene contrastar el nombre exacto en **Fuentes**."
                    ),
                }
            )
    return conflicts


def extract_annex_identity_from_bases(
    full_text: str,
    token: str,
    *,
    source: str = "",
    page_filter: Optional[int] = None,
) -> Dict[str, Any]:
    """Payload estructurado de identidad de anexo desde texto completo indexado."""
    tok = _normalize_annex_token(token)
    if not tok or not full_text or len(full_text) < 120:
        return {
            "ready": False,
            "token": tok,
            "index_entries": [],
            "requirements": [],
            "conflicts": [],
            "source": source,
            "page_filter": page_filter,
        }

    combined, spans = _build_page_spans(full_text)
    index_entries = _extract_index_entries(full_text, tok, spans)
    requirements = _extract_requirement_hits(combined, tok, spans)
    index_catalog = _scan_index_catalog(full_text)
    conflicts = _detect_conflicts(tok, index_entries, requirements, index_catalog)

    if page_filter is not None:
        requirements = [r for r in requirements if r.get("pagina") == page_filter]
        index_entries = [e for e in index_entries if e.get("pagina") == page_filter]

    ready = bool(index_entries or requirements)
    return {
        "ready": ready,
        "token": tok,
        "token_display": _display_annex_token(tok),
        "index_entries": index_entries,
        "requirements": requirements,
        "conflicts": conflicts,
        "index_catalog_excerpt": index_catalog.get(tok, ""),
        "source": source,
        "page_filter": page_filter,
    }


def compose_annex_identity_bases_response(payload: Dict[str, Any]) -> str:
    """Markdown forense para el chatbot."""
    tok_disp = str(payload.get("token_display") or payload.get("token") or "?").upper()
    src = str(payload.get("source") or "bases").strip()
    page_filter = payload.get("page_filter")

    if not payload.get("ready"):
        if page_filter is not None:
            return (
                f"**Anexo {tok_disp} — mención en página {page_filter}**\n\n"
                f"No localicé en las bases indexadas («{src}») una mención al **Anexo {tok_disp}** "
                f"en la **página {page_filter}**. Revise que el PDF primario esté indexado en **Fuentes**."
            )
        return (
            f"**Anexo {tok_disp}**\n\n"
            f"No se localizó en las bases indexadas («{src}») el **Anexo {tok_disp}** "
            f"en el índice ni en requisitos numerados. Verifique el PDF primario en **Fuentes**."
        )

    lines = [
        f"**Anexo {tok_disp} — identidad según bases de la convocatoria**",
        f"(Documento primario: «{src}»; extracción literal del pliego indexado.)",
        "",
    ]

    if page_filter is not None:
        lines = [
            f"**Anexo {tok_disp} — mención en página {page_filter}**",
            f"(Documento primario: «{src}»; extracción literal del pliego indexado.)",
            "",
        ]
        req_count = len(payload.get("requirements") or [])
        if req_count:
            lines.append(
                f"Sí: hay **{req_count}** mención(es) al **Anexo {tok_disp}** "
                f"en la **página {page_filter}** del pliego indexado."
            )
            lines.append("")

    for entry in payload.get("index_entries") or []:
        pg = entry.get("pagina_label") or entry.get("pagina") or "?"
        lines.append(f"### Índice de anexos [PÁGINA {pg}]")
        lines.append("")
        lines.append(str(entry.get("text") or "").strip())
        lines.append("")

    for req in payload.get("requirements") or []:
        pg = req.get("pagina_label") or req.get("pagina") or "?"
        num = str(req.get("numero") or "").strip()
        title = f"Requisito en bases"
        if num:
            title += f" (numeral {num})"
        lines.append(f"### {title} [PÁGINA {pg}]")
        lines.append("")
        lines.append(str(req.get("text") or "").strip())
        lines.append("")

    for conflict in payload.get("conflicts") or []:
        if page_filter is not None and str(conflict.get("pagina_label")) != str(page_filter):
            continue
        lines.append("### Nota de consistencia")
        lines.append("")
        lines.append(str(conflict.get("message") or "").strip())
        likely = str(conflict.get("likely_annex") or "").strip()
        if likely:
            lines.append("")
            lines.append(
                f"*Probable referencia correcta: **Anexo {likely.upper()}** "
                f"(según índice del pliego).*"
            )
        lines.append("")

    lines.append(
        "**Nota operativa:** Esta respuesta proviene del **PDF primario de bases** indexado; "
        "no sustituye el archivo suelto del anexo en el expediente. "
        "Para el formato editable, revise **Formatos/Anexos Detectados**."
    )
    return "\n".join(lines).strip()


def fetch_annex_identity_from_bases(
    session_id: str,
    primary_doc: Optional[str],
    vector_db: Any,
    user_query: str,
) -> Dict[str, Any]:
    """Obtiene identidad de anexo desde documento primario vía índice vectorial."""
    sid = str(session_id or "").strip()
    doc = str(primary_doc or "").strip()
    token = parse_annex_token_from_query(user_query)
    page_filter = parse_page_from_query(user_query)
    if not sid or not doc or not token:
        return {
            "ready": False,
            "token": token or "",
            "index_entries": [],
            "requirements": [],
            "conflicts": [],
            "source": doc,
            "page_filter": page_filter,
        }
    try:
        full = vector_db.get_full_document_text(sid, doc)
    except Exception:
        full = ""
    if not full or len(full) < 200:
        return {
            "ready": False,
            "token": token,
            "index_entries": [],
            "requirements": [],
            "conflicts": [],
            "source": doc,
            "page_filter": page_filter,
        }
    return extract_annex_identity_from_bases(
        full,
        token,
        source=doc,
        page_filter=page_filter,
    )
