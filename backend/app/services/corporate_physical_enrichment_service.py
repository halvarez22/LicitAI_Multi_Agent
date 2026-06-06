"""
Extrae credenciales empresariales (IMSS, SAT, acta, etc.) desde páginas de requisitos en bases.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.services.document_deliverable_filter import (
    _canonical_physical_credential_label,
    is_bases_admin_physical_credential_line,
    is_corporate_physical_credential_for_panel,
    physical_credential_dedupe_key,
)

_NUMBERED_REQ_RE = re.compile(
    r"(?m)^\s*(\d+)\.(\d+)\.?\s+(.{12,420}?)(?=\n\s*\d+\.|\n\n|---\s*PÁGINA|\Z)",
    re.DOTALL,
)

_MULTILEVEL_REQ_LINE_RE = re.compile(
    r"(?m)^\s*(\d+(?:\.\d+)+)\s*[\.\-]?\s*(.{15,800}?)\s*$"
)

_LETTERED_REQ_ITEM_RE = re.compile(
    r"(?m)^\s*([a-z])\)\s*",
)


def _iter_lettered_requirement_items(blob: str) -> List[Tuple[str, str]]:
    """Segmenta ítems a) b) c) aunque haya encabezados de página entre medias."""
    normalized = _normalize_admin_requirements_blob(blob)
    marks = list(_LETTERED_REQ_ITEM_RE.finditer(normalized))
    items: List[Tuple[str, str]] = []
    for idx, match in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(normalized)
        raw = re.sub(r"\s+", " ", normalized[match.end() : end]).strip()
        if len(raw) >= 15:
            items.append((match.group(1).upper(), raw))
    return items

# Garantías de participación (suelen ir en §2.x, no en 6.x).
_GUARANTEE_REQ_RE = re.compile(
    r"(?i)(\d+\.\d+\.?\s+)?garant[ií]a\s+de\s+seriedad.{0,220}",
)

_DOCUMENTO_NO_BLOCK_RE = re.compile(
    r"(?is)documento\s+no\.?\s*(\d+)\s+(.{25,5000}?)(?=documento\s+no\.?\s*\d+|---\s*p[aá]gina|\Z)"
)

# Credenciales típicas en bloques «Documento No. N» (universitarios, estatales, federales).
_DOCNO_CREDENTIAL_SPECS: Tuple[Tuple[str, str, str], ...] = (
    (
        "Identificación oficial vigente del representante",
        "documento_no_identificacion",
        r"(?is)identificaci[oó]n\s+oficial.{0,220}",
    ),
    (
        "Acta constitutiva de la empresa",
        "documento_no_acta",
        r"(?is)acta\s+constitutiva",
    ),
    (
        "Poder notarial o escritura (si el poder no consta en el acta)",
        "documento_no_poder",
        r"(?is)poder\s+notarial|escritura\s+en\s+caso\s+de\s+que\s+el\s+poder",
    ),
    (
        "Última modificación a los estatutos (si aplica)",
        "documento_no_mod_estatutos",
        r"(?is)modificaci[oó]n\s+a\s+los\s+estatutos",
    ),
    (
        "Constancia de situación fiscal vigente y opinión positiva del SAT",
        "documento_no_csf_sat",
        r"(?is)constancia\s+de\s+situaci[oó]n\s+fiscal.{0,120}?sat",
    ),
    (
        "Opinión de cumplimiento estatal en sentido positivo (Finanzas del Estado)",
        "documento_no_opinion_estatal",
        r"(?is)opini[oó]n\s+de\s+cumplimiento\s+de\s+obligaciones\s+estatales",
    ),
    (
        "Padrón de proveedores del Gobierno del Estado (alta o refrendo vigente)",
        "documento_no_padron",
        r"(?is)padr[oó]n\s+de\s+proveedores",
    ),
    (
        "Relación de clientes principales (bienes semejantes al objeto)",
        "documento_no_relacion_clientes",
        r"(?is)relaci[oó]n\s+de\s+clientes",
    ),
    (
        "Carta poder simple (si quien firma no es el representante legal)",
        "documento_no_carta_poder",
        r"(?is)carta\s+poder\s+simple",
    ),
    (
        "Garantía de seriedad de la propuesta",
        "documento_no_garantia_seriedad",
        r"(?is)garant[ií]a\s+de\s+seriedad\s+de\s+la\s+propuesta|cheque\s+de\s+caja.{0,80}?fianza\s+emitida",
    ),
)


def _bases_requisitos_blob(
    session_id: str,
    vector_db: Any = None,
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Fallback RAG por páginas Chroma usando archivos de bases de la sesión."""
    from app.services.junta_bases_corpus import _is_bases_like_filename
    from app.services.vector_service import VectorDbServiceClient

    vdb = vector_db or VectorDbServiceClient()
    sources: List[str] = []
    if isinstance(session_state, dict):
        for raw in session_state.get("ingested_files") or []:
            if not isinstance(raw, dict):
                continue
            fn = str(raw.get("filename") or raw.get("name") or "").strip()
            if fn and _is_bases_like_filename(fn) and fn not in sources:
                sources.append(fn)
    if not sources:
        sources = ["bases.pdf"]
    parts: List[str] = []
    for src in sources:
        for pg in range(1, 96):
            try:
                for doc in vdb.fetch_page_documents(session_id, src, pg) or []:
                    parts.append(str(doc))
            except Exception:
                continue
    return "\n".join(parts)


def _append_credential_row(
    *,
    section: str,
    raw_line: str,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
    confidence: float = 0.86,
    reason: str = "numbered_bases_admin_credential",
) -> None:
    if not is_bases_admin_physical_credential_line(raw_line):
        return
    label = _canonical_physical_credential_label(
        f"{section}. {raw_line}"
        if section and not raw_line.lower().startswith(section.lower())
        else raw_line
    )
    if not is_corporate_physical_credential_for_panel(label, "", raw_line, "presentar_fisico"):
        return
    key = physical_credential_dedupe_key(label)
    if key in seen:
        return
    seen.add(key)
    out.append(
        {
            "document_id": f"corp-bases-{len(out)+1:02d}",
            "nombre": label,
            "categoria": "expediente_empresarial",
            "tipo_accion_propuesto": "presentar_fisico",
            "tipo_accion_final": "presentar_fisico",
            "confidence": confidence,
            "evidence_snippet": raw_line[:600],
            "provenance_ui": {
                "source": source,
                "reason": reason,
                "section": section,
            },
        }
    )


def _normalize_admin_requirements_blob(blob: str) -> str:
    """Une saltos OCR (p. ej. «i)\\nCédula…») y quita separadores de página."""
    text = str(blob or "")
    text = re.sub(r"---\s*PÁGINA\s+\d+\s*---", "\n", text, flags=re.I)
    text = re.sub(r"(?m)^\s*([a-z])\)\s*\n\s*", r"\1) ", text)
    return text


def _rows_from_lettered_blob(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    """Requisitos tipo a) b) c) en bloques de documentación complementaria (ISSSTE, etc.)."""
    for section, raw_line in _iter_lettered_requirement_items(blob):
        _append_credential_row(
            section=section,
            raw_line=raw_line,
            source=source,
            seen=seen,
            out=out,
            reason="lettered_bases_admin_credential",
        )


def _rows_from_multilevel_lines(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    """Escanea líneas 5.1 / 6.6 / 7.2.1 (OCR conserva saltos de línea por requisito)."""
    if not blob.strip():
        return
    for m in _MULTILEVEL_REQ_LINE_RE.finditer(blob):
        section = m.group(1).strip()
        raw_line = re.sub(r"\s+", " ", m.group(2)).strip()
        if len(raw_line) < 15:
            continue
        _append_credential_row(
            section=section,
            raw_line=raw_line,
            source=source,
            seen=seen,
            out=out,
            reason="multilevel_bases_line",
        )


def _rows_from_documento_no_blocks(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    """Extrae credenciales desde bloques «Documento No. N» del PDF de bases."""
    if not str(blob or "").strip():
        return
    for doc_match in _DOCUMENTO_NO_BLOCK_RE.finditer(blob):
        block_l = doc_match.group(2).lower()
        if re.search(r"(?i)anexo\s+[ivxlc\d]+", block_l[:120]) and not re.search(
            r"(?i)identificaci[oó]n\s+oficial|acta\s+constitutiva|padr[oó]n|constancia\s+de\s+situaci",
            block_l,
        ):
            continue
        for label, reason, pattern in _DOCNO_CREDENTIAL_SPECS:
            if not re.search(pattern, doc_match.group(2)):
                continue
            m = re.search(pattern, doc_match.group(2))
            snippet = re.sub(r"\s+", " ", m.group(0)).strip() if m else label
            if not is_corporate_physical_credential_for_panel(
                label, "", snippet, "presentar_fisico"
            ):
                continue
            key = physical_credential_dedupe_key(label)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "document_id": f"corp-bases-{len(out)+1:02d}",
                    "nombre": label,
                    "categoria": "expediente_empresarial",
                    "tipo_accion_propuesto": "presentar_fisico",
                    "tipo_accion_final": "presentar_fisico",
                    "confidence": 0.92,
                    "evidence_snippet": snippet[:600],
                    "provenance_ui": {
                        "source": source,
                        "reason": reason,
                        "section": f"Documento No. {doc_match.group(1)}",
                    },
                }
            )


def _rows_from_misc_credential_phrases(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    """Frases de credencial fuera de bloques Documento No. (relación clientes, carta poder, etc.)."""
    extras: Tuple[Tuple[str, str], ...] = (
        (
            "Relación de clientes principales (bienes semejantes al objeto)",
            r"(?is)relaci[oó]n\s+de\s+clientes\s+principales",
        ),
        (
            "Carta poder simple (si quien firma no es el representante legal)",
            r"(?is)carta\s+poder\s+simple",
        ),
    )
    for label, pattern in extras:
        m = re.search(pattern, blob)
        if not m:
            continue
        snippet = re.sub(r"\s+", " ", m.group(0)).strip()
        if not is_corporate_physical_credential_for_panel(label, "", snippet, "presentar_fisico"):
            continue
        key = physical_credential_dedupe_key(label)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "document_id": f"corp-bases-{len(out)+1:02d}",
                "nombre": label,
                "categoria": "expediente_empresarial",
                "tipo_accion_propuesto": "presentar_fisico",
                "tipo_accion_final": "presentar_fisico",
                "confidence": 0.85,
                "evidence_snippet": snippet[:600],
                "provenance_ui": {"source": source, "reason": "bases_misc_credential"},
            }
        )


def _rows_from_guarantee_seriedad_blob(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    """Garantía de seriedad en § descalificación (cheque/fianza), no plantilla «Texto FIANZA»."""
    m = re.search(
        r"(?i)garant[ií]a\s+de\s+seriedad.{0,200}?(?:cheque\s+de\s+caja|fianza\s+emitida)",
        blob,
    )
    if not m:
        return
    label = "Garantía de seriedad de la propuesta"
    if not is_corporate_physical_credential_for_panel(label, "", m.group(0), "presentar_fisico"):
        return
    key = physical_credential_dedupe_key(label)
    if key in seen:
        return
    seen.add(key)
    snippet = re.sub(r"\s+", " ", m.group(0)).strip()
    out.append(
        {
            "document_id": f"corp-bases-{len(out)+1:02d}",
            "nombre": label,
            "categoria": "expediente_empresarial",
            "tipo_accion_propuesto": "presentar_fisico",
            "tipo_accion_final": "presentar_fisico",
            "confidence": 0.88,
            "evidence_snippet": snippet[:600],
            "provenance_ui": {"source": source, "reason": "bases_garantia_seriedad"},
        }
    )


def _rows_from_numbered_blob(
    blob: str,
    *,
    source: str,
    seen: Set[str],
    out: List[Dict[str, Any]],
) -> None:
    if not blob.strip():
        return
    _rows_from_documento_no_blocks(blob, source=source, seen=seen, out=out)
    _rows_from_guarantee_seriedad_blob(blob, source=source, seen=seen, out=out)
    _rows_from_misc_credential_phrases(blob, source=source, seen=seen, out=out)
    _rows_from_lettered_blob(blob, source=source, seen=seen, out=out)
    _rows_from_multilevel_lines(blob, source=source, seen=seen, out=out)
    for m in _NUMBERED_REQ_RE.finditer(blob):
        raw_line = re.sub(r"\s+", " ", m.group(3)).strip()
        if len(raw_line) < 15:
            continue
        _append_credential_row(
            section=f"{m.group(1)}.{m.group(2)}",
            raw_line=raw_line,
            source=source,
            seen=seen,
            out=out,
        )
    for m in _GUARANTEE_REQ_RE.finditer(blob):
        raw_line = re.sub(r"\s+", " ", m.group(0)).strip()
        if len(raw_line) < 20:
            continue
        _append_credential_row(
            section="",
            raw_line=raw_line,
            source=source,
            seen=seen,
            out=out,
            confidence=0.84,
            reason="guarantee_seriedad_bases",
        )


def _participant_requirements_window(blob: str, width: int = 18000) -> str:
    """Recorta el corpus al apartado típico de expediente del licitante (bases MX)."""
    text = str(blob or "")
    if not text.strip():
        return ""
    marker = re.search(
        r"(?is)c\)\s+identificaci[oó]n\s+oficial\s+vigente\s+de\s+quien\s+firma",
        text,
    )
    if marker:
        start = text.rfind("\nb)", max(0, marker.start() - 8000), marker.start())
        if start < 0:
            start = text.rfind("\na)", max(0, marker.start() - 8000), marker.start())
        if start < 0:
            start = max(0, marker.start() - 1200)
        else:
            start += 1
        after_c = text[marker.start() : marker.start() + width]
        u_match = re.search(r"(?m)^\s*u\)\s+", after_c)
        if u_match:
            after_u = after_c[u_match.end() :]
            v_match = re.search(r"(?m)^\s*[v-z]\)\s+", after_u)
            end = marker.start() + u_match.end() + (v_match.start() if v_match else min(2800, len(after_u)))
        else:
            next_major = re.search(
                r"(?m)^\s*(?:4\.\d+|5\.\d+|6\.\d+|7\.\d+|8\.\d+|9\.\d+)\s+",
                after_c,
            )
            end = marker.start() + (next_major.start() if next_major else len(after_c))
        return text[start:end]
    priority_anchors = (
        r"(?is)documento\s+no\.?\s*2\b",
        r"(?is)para\s+acreditar\s+su\s+personalidad",
        r"(?is)requisitos\s+del\s+participante",
        r"(?is)documentos\s+que\s+deber[aá]n\s+presentar",
        r"(?is)requisitos\s+administrativos",
        r"(?is)documentaci[oó]n\s+legal\s+del\s+licitante",
        r"(?is)acrediten\s+su\s+personalidad\s+jur[ií]dica",
        r"(?is)identificaci[oó]n\s+oficial\s+vigente\s+de\s+quien\s+firma",
        r"(?is)documentos?\s*,?\s*debidamente\s+requisitada",
    )
    for anchor in priority_anchors:
        match = re.search(anchor, text)
        if not match:
            continue
        start = match.start()
        lettered_back = text.rfind("\na)", max(0, start - 5000), start)
        if lettered_back >= 0:
            start = lettered_back + 1
        else:
            numbered_back = re.search(
                r"(?m)^\s*\d+\.\d+\s+",
                text[max(0, start - 1200) : start],
            )
            if numbered_back:
                start = max(0, start - 1200) + numbered_back.start()
        return text[start : start + width]
    lettered = re.search(r"(?is)(?:^|\n)\s*a\)\s+.{10,200}?(?:\n|\s)b\)\s+", text)
    if lettered:
        return text[lettered.start() : lettered.start() + width]
    return text


def extract_corporate_physical_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """
    Localiza requisitos numerados de expediente en el texto indexado de bases (sin hardcode por licitación).
    """
    combined = str(getattr(corpus, "combined", "") or "")
    if not combined.strip():
        return []
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    _rows_from_numbered_blob(
        combined,
        source="bases_corpus",
        seen=seen,
        out=out,
    )
    window = _participant_requirements_window(combined)
    if window and window != combined:
        _rows_from_numbered_blob(
            window,
            source="bases_corpus_window",
            seen=seen,
            out=out,
        )
    return out


def extract_corporate_physical_from_bases_rag(
    session_id: str,
    *,
    vector_db: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
    documents: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Fallback: corpus de sesión o páginas Chroma indexadas (sin nombres fijos por licitación).
    """
    if documents:
        from app.services.junta_bases_corpus import build_bases_corpus

        corpus = build_bases_corpus(session_id, documents, session_state=session_state)
        rows = extract_corporate_physical_from_bases_corpus(corpus)
        if rows:
            return rows
    blob = _bases_requisitos_blob(session_id, vector_db, session_state=session_state)
    if not blob.strip():
        return []
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    _rows_from_numbered_blob(
        blob,
        source="bases_rag_requisitos",
        seen=seen,
        out=out,
    )
    return out


def extract_corporate_physical_from_session_documents(
    session_id: str,
    documents: Sequence[Dict[str, Any]],
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Corpus de sesión → credenciales físicas (fuente principal, universal)."""
    from app.services.junta_bases_corpus import build_bases_corpus

    corpus = build_bases_corpus(session_id, documents, session_state=session_state)
    return extract_corporate_physical_from_bases_corpus(corpus)
