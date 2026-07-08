"""
Extracción determinista (HRU) de entrega/recepción de muestras en bases primarias.

Ancla secciones c), d) y e) del apartado de actos del procedimiento; opcional Anexo L (sobre).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.services.junta_bases_corpus import _PAGE_SPLIT_RE

_SECTION_C_RE = re.compile(
    r"(?is)\bc\)\s*caracter[ií]sticas de muestras\b"
)
_SECTION_D_RE = re.compile(
    r"(?is)\bd\)\s*entrega y recepci[oó]n de muestras\b"
)
_SECTION_E_RE = re.compile(
    r"(?is)\be\)\s*evaluaci[oó]n de muestras\b"
)
_SECTION_F_RE = re.compile(
    r"(?is)\bf\)\s*presentaci[oó]n y apertura de proposiciones\b"
)
_ANEXO_L_REQ_RE = re.compile(
    r"(?is)(?:^|\n)\s*31\.\s+copia simple del recibo de muestras.{0,900}?partida 2\."
)
_OCR_NOISE_RE = re.compile(
    r"(?i)80%,\s*90%,\s*2%|constantes,\s*f[oó]rmulas,\s*fechas y valores monetarios"
)
_SAMPLE_DELIVERY_QUERY_MARKERS = (
    "entrega y recepcion",
    "entrega recepcion",
    "recepcion de muestras",
    "recepción de muestras",
    "entrega de muestras",
    "recibo de muestras",
    "comprobante de entrega de muestra",
    "anexo l",
    "caracteristicas de muestras",
    "características de muestras",
    "evaluacion de muestras",
    "evaluación de muestras",
)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", str(text or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t.lower()).strip()


def detect_sample_delivery_intent(query: str) -> bool:
    """True si la consulta apunta a logística de entrega/recepción de muestras (no certificados/RPBI)."""
    qn = _fold(query)
    if "muestr" not in qn:
        return False
    if any(m in qn for m in _SAMPLE_DELIVERY_QUERY_MARKERS):
        return True
    if "entreg" in qn and "recepc" in qn:
        return True
    return False


def _strip_source_noise(text: str) -> str:
    t = re.sub(r"\[FUENTE:[^\]]*\]\s*", "", str(text or ""), flags=re.I)
    t = re.sub(
        r"COMIT[EÉ] DE ADQUISICIONES[^\n]*\n",
        "",
        t,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", t).strip()


def _page_at_offset(page_spans: List[Tuple[int, int, int]], offset: int) -> Optional[int]:
    for start, end, pg in page_spans:
        if start <= offset < end:
            return pg
    return page_spans[-1][2] if page_spans else None


def _page_at_match_body(
    page_spans: List[Tuple[int, int, int]], match: re.Match[str]
) -> Optional[int]:
    """Página donde inicia el contenido sustantivo del match (ignora saltos de línea previos)."""
    lead = len(match.group(0)) - len(match.group(0).lstrip())
    return _page_at_offset(page_spans, match.start() + lead)


def _build_page_spans(full_text: str) -> Tuple[str, List[Tuple[int, int, int]]]:
    """Devuelve texto concatenado y spans (start, end, page_num)."""
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


def _slice_section(full_text: str, start_re: re.Pattern[str], end_re: Optional[re.Pattern[str]]) -> str:
    m = start_re.search(full_text)
    if not m:
        return ""
    start = m.start()
    end = len(full_text)
    if end_re:
        em = end_re.search(full_text, m.end())
        if em:
            end = em.start()
    chunk = full_text[start:end].strip()
    return _strip_source_noise(chunk)


def _format_page_label(pages: List[int]) -> str:
    uniq = sorted({p for p in pages if p})
    if not uniq:
        return "?"
    if len(uniq) == 1:
        return str(uniq[0])
    if uniq == list(range(uniq[0], uniq[-1] + 1)):
        return f"{uniq[0]}-{uniq[-1]}"
    return ", ".join(str(p) for p in uniq)


def _pages_for_range(
    spans: List[Tuple[int, int, int]], start: int, end: int
) -> List[int]:
    """Páginas que intersectan un rango de caracteres en el texto concatenado."""
    if start < 0 or end <= start:
        return []
    pages: List[int] = []
    for span_start, span_end, pg in spans:
        if span_end > start and span_start < end:
            pages.append(pg)
    return sorted({p for p in pages})


def _section_char_range(
    text: str,
    start_re: re.Pattern[str],
    end_re: Optional[re.Pattern[str]],
) -> Tuple[int, int]:
    m = start_re.search(text)
    if not m:
        return -1, -1
    start = m.start()
    end = len(text)
    if end_re:
        em = end_re.search(text, m.end())
        if em:
            end = em.start()
    return start, end


def extract_sample_delivery_sections(full_text: str, *, source: str = "") -> Dict[str, Any]:
    """
    Extrae bloques c), d), e) y requisito Anexo L desde texto de bases con marcadores de página.
    """
    text, spans = _build_page_spans(full_text)
    if not text.strip():
        return {"ready": False, "sections": [], "source": source}

    sec_c = _slice_section(text, _SECTION_C_RE, _SECTION_D_RE)
    sec_d = _slice_section(text, _SECTION_D_RE, _SECTION_E_RE)
    sec_e = _slice_section(text, _SECTION_E_RE, _SECTION_F_RE)

    anexo_l = ""
    m31 = _ANEXO_L_REQ_RE.search(text)
    if m31:
        anexo_l = _strip_source_noise(m31.group(0))

    sections: List[Dict[str, Any]] = []

    def _append_section(
        section_id: str,
        title: str,
        body: str,
        *,
        char_start: int,
        char_end: int,
        note: str = "",
    ) -> None:
        body = _strip_source_noise(body)
        if len(body) < 40 or _OCR_NOISE_RE.search(body):
            return
        pgs = _pages_for_range(spans, char_start, char_end)
        item: Dict[str, Any] = {
            "section_id": section_id,
            "title": title,
            "text": body,
            "pagina": pgs[0] if len(pgs) == 1 else None,
            "pagina_label": _format_page_label(pgs) if pgs else "?",
        }
        if note:
            item["note"] = note
        sections.append(item)

    c_rng = _section_char_range(text, _SECTION_C_RE, _SECTION_D_RE)
    if sec_c and c_rng[0] >= 0:
        _append_section("c", "c) Características de Muestras", sec_c, char_start=c_rng[0], char_end=c_rng[1])

    d_rng = _section_char_range(text, _SECTION_D_RE, _SECTION_E_RE)
    if sec_d and d_rng[0] >= 0:
        _append_section(
            "d",
            "d) Entrega y Recepción de Muestras de los Licitantes",
            sec_d,
            char_start=d_rng[0],
            char_end=d_rng[1],
        )

    e_rng = _section_char_range(text, _SECTION_E_RE, _SECTION_F_RE)
    if sec_e and e_rng[0] >= 0:
        _append_section("e", "e) Evaluación de Muestras", sec_e, char_start=e_rng[0], char_end=e_rng[1])

    if anexo_l and m31:
        pg = _page_at_match_body(spans, m31)
        sections.append(
            {
                "section_id": "anexo_l",
                "title": "Requisito documental en sobre (Anexo L — inciso 31)",
                "text": anexo_l,
                "pagina": pg,
                "pagina_label": str(pg) if pg else "?",
                "note": "Comprobante para la propuesta técnica; no sustituye el acto físico de entrega en almacén.",
            }
        )

    ready = bool(sec_c or sec_d or sec_e)
    return {"ready": ready, "sections": sections, "source": source}


def compose_sample_delivery_chat_response(payload: Dict[str, Any]) -> str:
    """Markdown forense para el chatbot."""
    if not payload.get("ready"):
        return (
            "**Entrega y recepción de muestras**\n\n"
            "No se localizó en las bases indexadas el apartado c)/d)/e) de muestras. "
            "Verifique que el PDF primario de convocatoria esté indexado."
        )
    src = str(payload.get("source") or "bases").strip()
    lines = [
        "**Entrega y recepción de muestras — bases de la convocatoria**",
        f"(Documento primario: «{src}»; extracción literal del pliego indexado.)",
        "",
    ]
    for sec in payload.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        pg_label = sec.get("pagina_label") or sec.get("pagina") or "?"
        lines.append(f"### {sec.get('title', 'Sección')} [PÁGINA {pg_label}]")
        lines.append("")
        lines.append(str(sec.get("text") or "").strip())
        note = str(sec.get("note") or "").strip()
        if note:
            lines.append("")
            lines.append(f"*{note}*")
        lines.append("")
    lines.extend(
        [
            "**Nota operativa:** La **recepción física de muestras en almacén** (inciso d) es un acto "
            "logístico distinto de la **apertura de proposiciones** (inciso f) y del **recibo Anexo L** "
            "en el sobre técnico.",
        ]
    )
    return "\n".join(lines).strip()


def fetch_sample_delivery_excerpt_from_session(
    session_id: str,
    primary_doc: Optional[str],
    vector_db: Any,
) -> Dict[str, Any]:
    """Obtiene excerpt desde el documento primario vía índice vectorial."""
    sid = str(session_id or "").strip()
    doc = str(primary_doc or "").strip()
    if not sid or not doc:
        return {"ready": False, "sections": [], "source": doc}
    try:
        full = vector_db.get_full_document_text(sid, doc)
    except Exception:
        full = ""
    if not full or len(full) < 200:
        return {"ready": False, "sections": [], "source": doc}
    return extract_sample_delivery_sections(full, source=doc)
