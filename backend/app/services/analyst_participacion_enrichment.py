"""
Enriquecimiento determinista de salida del Analista (requisitos_participacion y audit_report).

Extrae citas reales del contexto RAG (páginas con marcadores) y descarta placeholders del LLM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.logging_config import get_logger

logger = get_logger(__name__)

_PAGE_HEADER_RE = re.compile(
    r"(?:---\s*PÁGINA\s*(\d+)\s*\(([^)]+)\)\s*---|"
    r"\[FUENTE:\s*([^|\]]+?)\s*\|\s*PÁGINA:\s*(\d+)\])",
    re.IGNORECASE,
)

_INCISO_LINE_RE = re.compile(
    r"(?m)^\s*([a-z]|[ivx]{1,4}|\d{1,2})[\).\)]\s+(.{24,420}?)(?=\n\s*(?:[a-z]|\d{1,2})[\).\)]|\n\n|$)",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(
    r"(?i)(punto\s+x\b|pregunta\s+t[eé]cnica\s+para\s+clarificar|"
    r"clarificar\s+el\s+punto\s+x|^\s*\.\.\.\s*$|"
    r"requisito\s*«\s*\.{2,}\s*»|«\s*\.{2,}\s*»)"
)

_PARTICIPACION_KEYWORDS = (
    "participar",
    "licitante",
    "proponente",
    "elegibilidad",
    "requisitos del participante",
    "requisitos para participar",
    "experiencia",
    "años de experiencia",
    "anios de experiencia",
    "representante legal",
    "rfc",
    "domicilio fiscal",
    "integridad",
    "certificado digital",
    "compranet",
    "personalidad jurídica",
    "capacidad jurídica",
    "acuse de recibo",
    "propuesta técnica",
    "propuesta económica",
)

_MIN_LITERAL_LEN = 28


def is_placeholder_analyst_text(text: str) -> bool:
    """True si el texto es placeholder o sin sustancia auditable."""
    p = str(text or "").strip()
    if len(p) < _MIN_LITERAL_LEN:
        return True
    if _PLACEHOLDER_RE.search(p):
        return True
    if p.count("...") >= 1 and len(re.sub(r"[.\s…]", "", p)) < 32:
        return True
    if p.count("...") >= 2:
        return True
    return False


def _norm_key(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return re.sub(r"[^a-z0-9áéíóúñ ]", "", t)[:220]


def _split_context_into_page_blocks(context: str) -> List[Dict[str, str]]:
    """Parte el contexto en bloques con página y archivo fuente."""
    if not context or not context.strip():
        return []
    blocks: List[Dict[str, str]] = []
    current_page = ""
    current_file = ""
    buf: List[str] = []

    def _flush() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            blocks.append(
                {
                    "pagina": current_page,
                    "archivo_fuente": current_file,
                    "texto": body,
                }
            )
        buf = []

    for line in (context or "").splitlines():
        m = _PAGE_HEADER_RE.search(line)
        if m:
            _flush()
            if m.group(1):
                current_page = str(m.group(1)).strip()
                current_file = str(m.group(2) or "").strip()
            else:
                current_file = str(m.group(3) or "").strip()
                current_page = str(m.group(4) or "").strip()
            continue
        buf.append(line)
    _flush()
    if blocks:
        return blocks

    # Sin marcadores de página: un solo bloque
    body = (context or "").strip()
    if body:
        return [{"pagina": "", "archivo_fuente": "", "texto": body}]
    return []


def _extract_incisos_from_block(block: Dict[str, str]) -> List[Dict[str, str]]:
    """Extrae incisos tipo a) b) de un bloque de página."""
    texto = block.get("texto") or ""
    pagina = str(block.get("pagina") or "").strip()
    archivo = str(block.get("archivo_fuente") or "").strip()
    out: List[Dict[str, str]] = []
    for m in _INCISO_LINE_RE.finditer(texto):
        inciso = str(m.group(1)).strip().lower()
        literal = " ".join(str(m.group(2)).split())
        if is_placeholder_analyst_text(literal):
            continue
        out.append(
            {
                "inciso": inciso,
                "texto_literal": literal,
                "pagina": pagina,
                "archivo_fuente": archivo,
                "evidence_snippet": literal[:500],
                "source_hint": "rag_inciso",
            }
        )
    return out


def _extract_keyword_sentences_from_block(block: Dict[str, str]) -> List[Dict[str, str]]:
    """Oraciones con señales de elegibilidad/participación."""
    texto = block.get("texto") or ""
    pagina = str(block.get("pagina") or "").strip()
    archivo = str(block.get("archivo_fuente") or "").strip()
    lower = texto.lower()
    if not any(k in lower for k in _PARTICIPACION_KEYWORDS):
        return []

    out: List[Dict[str, str]] = []
    # Oraciones separadas por punto seguido de mayúscula o salto de línea
    for raw in re.split(r"(?<=[.;])\s+|\n{2,}", texto):
        sent = " ".join(raw.split())
        if len(sent) < _MIN_LITERAL_LEN or is_placeholder_analyst_text(sent):
            continue
        if "===" in sent or "sección " in sent.lower():
            continue
        lo = sent.lower()
        hits = sum(1 for k in _PARTICIPACION_KEYWORDS if k in lo)
        if hits < 1:
            continue
        if hits == 1 and lo.startswith("causas de exclusión"):
            continue
        out.append(
            {
                "inciso": "",
                "texto_literal": sent[:420],
                "pagina": pagina,
                "archivo_fuente": archivo,
                "evidence_snippet": sent[:500],
                "source_hint": "rag_sentence",
            }
        )
    return out


def extract_requisitos_from_rag_context(context: str) -> List[Dict[str, str]]:
    """
    Extrae requisitos de participación desde contexto RAG (smart_search / secciones).

    Returns:
        Lista de dicts compatibles con normalize_requisitos_participacion_list.
    """
    merged: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for block in _split_context_into_page_blocks(context):
        candidates = _extract_incisos_from_block(block) + _extract_keyword_sentences_from_block(block)
        for item in candidates:
            key = _norm_key(item.get("texto_literal") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _participacion_section_slice(full_context: str) -> str:
    """Recorta la sección de participación del contexto ensamblado del analista."""
    if not full_context:
        return ""
    start_markers = (
        "=== SECCIÓN PARTICIPACIÓN",
        "=== sección participación",
    )
    end_markers = (
        "=== SECCIÓN FILTROS",
        "=== SECCIÓN ECONÓMICA",
        "=== SECCIÓN ALCANCE",
    )
    lower = full_context.lower()
    start = -1
    for mk in start_markers:
        pos = lower.find(mk.lower())
        if pos >= 0:
            start = pos
            break
    if start < 0:
        return full_context
    end = len(full_context)
    for mk in end_markers:
        pos = lower.find(mk.lower(), start + 10)
        if pos > start:
            end = min(end, pos)
    return full_context[start:end]


def _hydrate_requisito(
    req: Dict[str, str],
    candidates: List[Dict[str, str]],
) -> Dict[str, str]:
    """Completa página/archivo/texto si el LLM devolvió placeholder."""
    txt = str(req.get("texto_literal") or "").strip()
    needs_text = is_placeholder_analyst_text(txt)
    needs_page = not str(req.get("pagina") or "").strip() or str(req.get("pagina")).strip() in (
        "...",
        "0",
        "N/A",
    )
    needs_file = not str(req.get("archivo_fuente") or "").strip()

    if not needs_text and not needs_page and not needs_file:
        return req

    best: Optional[Dict[str, str]] = None
    best_score = 0
    inciso = str(req.get("inciso") or "").strip().lower()
    for cand in candidates:
        score = 0
        c_inc = str(cand.get("inciso") or "").strip().lower()
        c_txt = str(cand.get("texto_literal") or "")
        if inciso and c_inc == inciso:
            score += 4
        if txt and not needs_text:
            if _norm_key(txt)[:80] in _norm_key(c_txt):
                score += 5
        elif needs_text:
            # Coincidencia por palabras clave compartidas
            words = set(_norm_key(txt or inciso or "requisito").split()) - {"", "requisito"}
            c_words = set(_norm_key(c_txt).split())
            score += len(words & c_words)
        if score > best_score:
            best_score = score
            best = cand

    if not best or best_score < 2:
        return req

    out = dict(req)
    if needs_text and best.get("texto_literal"):
        out["texto_literal"] = best["texto_literal"]
        out["evidence_snippet"] = str(best.get("evidence_snippet") or best["texto_literal"])[:500]
    if needs_page and best.get("pagina"):
        out["pagina"] = str(best["pagina"])
    if needs_file and best.get("archivo_fuente"):
        out["archivo_fuente"] = str(best["archivo_fuente"])
    out["enrichment_source"] = "rag_hydrate"
    return out


def _checklist_to_requisitos(checklist: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(checklist, list):
        return out
    for item in checklist:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("descripción") or item.get("descripcion") or "").strip()
        if is_placeholder_analyst_text(desc):
            continue
        pag = item.get("página") or item.get("pagina") or ""
        claus = item.get("cláusula") or item.get("clausula") or item.get("inciso") or ""
        if str(pag).strip().lower() in ("no especificado", "n/a", ""):
            pag = ""
        if str(claus).strip().lower() in ("no especificado", "n/a"):
            claus = ""
        out.append(
            {
                "inciso": str(claus).strip(),
                "texto_literal": desc,
                "pagina": str(pag).strip() if pag else "",
                "archivo_fuente": "",
                "evidence_snippet": desc[:500],
                "source_hint": "checklist_consolidado",
            }
        )
    return out


def _gap_to_requisitos(gap_analysis: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(gap_analysis, list):
        return out
    for gap in gap_analysis:
        if not isinstance(gap, dict):
            continue
        req = str(gap.get("requisito") or "").strip()
        snip = str(gap.get("evidence_snippet") or req).strip()
        if is_placeholder_analyst_text(req) and is_placeholder_analyst_text(snip):
            continue
        literal = snip if not is_placeholder_analyst_text(snip) else req
        if is_placeholder_analyst_text(literal):
            continue
        out.append(
            {
                "inciso": "",
                "texto_literal": literal,
                "pagina": str(gap.get("pagina") or gap.get("page") or "").strip(),
                "archivo_fuente": str(gap.get("archivo_fuente") or gap.get("source") or "").strip(),
                "evidence_snippet": literal[:500],
                "source_hint": "gap_analysis",
            }
        )
    return out


def merge_requisitos_participacion(
    llm_reqs: List[Dict[str, str]],
    *,
    rag_candidates: List[Dict[str, str]],
    gap_reqs: Optional[List[Dict[str, str]]] = None,
    checklist_reqs: Optional[List[Dict[str, str]]] = None,
    max_items: int = 40,
) -> List[Dict[str, str]]:
    """
    Fusiona salida LLM con extracción RAG; descarta placeholders y deduplica.
    """
    seen: Set[str] = set()
    merged: List[Dict[str, str]] = []

    def _append(item: Dict[str, str]) -> None:
        txt = str(item.get("texto_literal") or "").strip()
        if not txt or is_placeholder_analyst_text(txt):
            return
        key = _norm_key(txt)
        if key in seen:
            return
        seen.add(key)
        merged.append(
            {
                "inciso": str(item.get("inciso") or "").strip(),
                "texto_literal": txt,
                "pagina": str(item.get("pagina") or "").strip(),
                "archivo_fuente": str(item.get("archivo_fuente") or "").strip(),
                "evidence_snippet": str(item.get("evidence_snippet") or txt)[:500],
            }
        )

    all_candidates = list(rag_candidates)
    if gap_reqs:
        all_candidates.extend(gap_reqs)
    if checklist_reqs:
        all_candidates.extend(checklist_reqs)

    for req in llm_reqs or []:
        if not isinstance(req, dict):
            continue
        hydrated = _hydrate_requisito(req, all_candidates)
        _append(hydrated)

    # RAG primero en prioridad si el LLM devolvió poco o solo basura
    llm_valid = len(merged)
    for cand in rag_candidates:
        _append(cand)
    if gap_reqs:
        for g in gap_reqs:
            _append(g)
    if checklist_reqs and llm_valid < 3:
        for c in checklist_reqs:
            _append(c)

    return merged[:max_items]


def sanitize_audit_report(
    audit_report: Dict[str, Any],
    *,
    rag_candidates: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Elimina preguntas placeholder y enriquece gaps sin evidencia.
    """
    ar = dict(audit_report or {})
    preguntas = []
    for raw in ar.get("preguntas_junta_aclaraciones") or []:
        p = str(raw or "").strip()
        if p and not is_placeholder_analyst_text(p):
            preguntas.append(p)
    ar["preguntas_junta_aclaraciones"] = preguntas

    gaps_out: List[Dict[str, Any]] = []
    for gap in ar.get("gap_analysis") or []:
        if not isinstance(gap, dict):
            continue
        g = dict(gap)
        req = str(g.get("requisito") or "").strip()
        snip = str(g.get("evidence_snippet") or "").strip()
        if is_placeholder_analyst_text(req) and rag_candidates:
            for cand in rag_candidates:
                if str(cand.get("pagina") or "") == str(g.get("pagina") or ""):
                    continue
                c_txt = str(cand.get("texto_literal") or "")
                if not is_placeholder_analyst_text(c_txt):
                    g["requisito"] = c_txt[:200]
                    g["evidence_snippet"] = c_txt[:500]
                    if not g.get("pagina"):
                        g["pagina"] = cand.get("pagina")
                    if not g.get("archivo_fuente"):
                        g["archivo_fuente"] = cand.get("archivo_fuente")
                    break
        if is_placeholder_analyst_text(str(g.get("requisito") or "")):
            if not is_placeholder_analyst_text(snip):
                g["requisito"] = snip[:200]
            else:
                continue
        if is_placeholder_analyst_text(str(g.get("evidence_snippet") or "")):
            g["evidence_snippet"] = str(g.get("requisito") or "")[:500]
        gaps_out.append(g)
    ar["gap_analysis"] = gaps_out

    alertas_out: List[Dict[str, Any]] = []
    for alert in ar.get("alertas_descalificacion") or []:
        if not isinstance(alert, dict):
            continue
        a = dict(alert)
        if is_placeholder_analyst_text(str(a.get("motivo") or "")):
            continue
        if is_placeholder_analyst_text(str(a.get("sugerencia") or "")):
            a["sugerencia"] = ""
        alertas_out.append(a)
    ar["alertas_descalificacion"] = alertas_out

    return ar


def enrich_analyst_participacion_output(
    extracted_data: Dict[str, Any],
    *,
    participacion_context: str,
    full_context: str = "",
) -> Dict[str, Any]:
    """
    Post-procesa la salida del Analista: requisitos con citas RAG y audit_report sin placeholders.

    Modifica ``extracted_data`` in-place y lo devuelve.
    """
    if not isinstance(extracted_data, dict):
        return extracted_data

    section = _participacion_section_slice(full_context)
    rag_ctx = "\n\n".join(x for x in (participacion_context, section) if x and x.strip())
    rag_candidates = extract_requisitos_from_rag_context(rag_ctx)

    ar = extracted_data.get("audit_report")
    if isinstance(ar, dict):
        gap_reqs = _gap_to_requisitos(ar.get("gap_analysis"))
        extracted_data["audit_report"] = sanitize_audit_report(ar, rag_candidates=rag_candidates)
    else:
        gap_reqs = []

    checklist_reqs = _checklist_to_requisitos(extracted_data.get("checklist_consolidado"))

    llm_reqs = extracted_data.get("requisitos_participacion")
    if not isinstance(llm_reqs, list):
        llm_reqs = []

    merged = merge_requisitos_participacion(
        llm_reqs,
        rag_candidates=rag_candidates,
        gap_reqs=gap_reqs,
        checklist_reqs=checklist_reqs,
    )
    before = len(llm_reqs)
    extracted_data["requisitos_participacion"] = merged
    extracted_data["participacion_enrichment"] = {
        "rag_candidates": len(rag_candidates),
        "merged_count": len(merged),
        "llm_before": before,
    }
    logger.info(
        "analyst_participacion_enriched",
        rag_candidates=len(rag_candidates),
        merged=len(merged),
        llm_before=before,
    )
    return extracted_data
