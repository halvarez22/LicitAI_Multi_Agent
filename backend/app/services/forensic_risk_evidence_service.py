"""
Resolución HRU de evidencia (página, fragmento, fuente) para riesgos forenses.

Cascada: contexto panel > dictamen/causales > vectores (primary_doc) > vectores general > heal.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.economic_alert_classifier import alert_fingerprint

_PRIMARY_DOC_KEYWORDS = ("bases", "convocatoria", "licitacion", "licitación", "pliego", "vigilancia")


def _normalize_vector_hits(res: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    dists = res.get("distances") or []
    if docs and isinstance(docs[0], list):
        docs = docs[0]
    if metas and isinstance(metas[0], list):
        metas = metas[0]
    if dists and isinstance(dists[0], list):
        dists = dists[0]
    return list(docs or []), list(metas or []), [float(d) if d is not None else 999.0 for d in (dists or [])]


def _primary_bases_source(sources: List[str]) -> Optional[str]:
    for s in sources or []:
        sl = str(s).lower()
        if any(k in sl for k in _PRIMARY_DOC_KEYWORDS):
            return str(s)
    return str(sources[0]) if sources else None


def _hallazgo_text(h: Dict[str, Any]) -> str:
    t = h.get("texto")
    if isinstance(t, dict):
        return str(t.get("descripcion") or t.get("nombre") or t.get("requisito") or "")
    return str(t or "")


def _evidence_from_causales(causales: List[Dict[str, Any]], literal: str) -> Dict[str, Any]:
    fp = alert_fingerprint(literal)
    if not fp:
        return {}
    for h in causales or []:
        if not isinstance(h, dict):
            continue
        txt = _hallazgo_text(h)
        if not txt:
            continue
        hfp = alert_fingerprint(txt)
        if fp[:48] in hfp or hfp[:48] in fp:
            page = h.get("page")
            snippet = h.get("snippet") or txt
            if page is not None or snippet:
                return {
                    "page": page,
                    "snippet": str(snippet)[:420],
                    "source": "dictamen",
                    "match_confidence": "alta",
                    "provenance": "dictamen_causales",
                }
    return {}


def _money_digit_cores(text: str) -> set[str]:
    """Núcleos numéricos de montos (tolera $1,000,000.00 vs 1.000.000 vs 1'000,000)."""
    cores: set[str] = set()
    for m in re.finditer(r"(?:\$|MXN|M\.N\.)?\s*[\d][\d,\.'\s]{2,}[\d]", str(text or ""), flags=re.I):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) < 5:
            continue
        core = digits.lstrip("0") or digits
        cores.add(core)
        if len(digits) > 2 and digits.endswith("00"):
            cores.add((digits[:-2]).lstrip("0") or digits[:-2])
    return cores


def _extract_search_terms(literal: str) -> List[str]:
    terms: List[str] = []
    if literal.strip():
        terms.append(literal.strip()[:280])
    for m in re.findall(r"\$[\d,]+(?:\.\d{2})?", literal):
        terms.append(f"presupuesto {m}")
        terms.append(f"propuesta mínima {m}")
        terms.append(f"importe mínimo {m}")
        terms.append(m)
    for core in sorted(_money_digit_cores(literal), key=len, reverse=True)[:2]:
        terms.append(f"presupuesto {core}")
        terms.append(core)
    seen: set[str] = set()
    out: List[str] = []
    for t in terms:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out[:8]


def _snippet_from_doc(literal: str, doc: str, *, max_len: int = 420) -> str:
    doc_clean = re.sub(r"===\s*PÁGINA\s+\d+\s*===", " ", doc, flags=re.I)
    doc_clean = re.sub(r"\s+", " ", doc_clean).strip()
    lit_norm = alert_fingerprint(literal)
    doc_norm = alert_fingerprint(doc_clean)
    if lit_norm and lit_norm[:50] in doc_norm:
        idx = doc_norm.find(lit_norm[:50])
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(doc_clean), idx + len(literal) + 120)
            return doc_clean[start:end].strip()
    for token in re.findall(r"\$[\d,]+(?:\.\d{2})?", literal):
        pos = doc_clean.lower().find(token.lower())
        if pos >= 0:
            start = max(0, pos - 100)
            end = min(len(doc_clean), pos + 180)
            return doc_clean[start:end].strip()
    return doc_clean[:max_len].strip()


def _literal_matches_doc(literal: str, doc: str) -> bool:
    if not literal or not doc:
        return False
    lit_fp = alert_fingerprint(literal)
    doc_fp = alert_fingerprint(doc)
    if lit_fp and lit_fp[:48] in doc_fp:
        return True
    lit_cores = _money_digit_cores(literal)
    doc_cores = _money_digit_cores(doc)
    if lit_cores and lit_cores & doc_cores:
        return True
    for token in re.findall(r"\$[\d,]+(?:\.\d{2})?", literal):
        norm = token.replace(",", "")
        doc_norm = doc.replace(",", "")
        if norm in doc_norm:
            return True
        if norm.endswith(".00") and norm[:-3] in doc_norm:
            return True
    return False


def _evidence_from_session_analyst(state: Dict[str, Any], literal: str) -> Dict[str, Any]:
    """Reglas del analista con el mismo monto (sin página — contexto de procedencia)."""
    tasks = state.get("tasks_completed") if isinstance(state.get("tasks_completed"), dict) else {}
    analyst = (tasks.get("analyst") or {}).get("data") if isinstance(tasks.get("analyst"), dict) else {}
    if not isinstance(analyst, dict):
        analyst = {}
    reglas = analyst.get("reglas_economicas") or {}
    if isinstance(reglas, dict):
        for val in reglas.values():
            txt = str(val or "").strip()
            if txt and _literal_matches_doc(literal, txt):
                return {
                    "snippet": txt[:420],
                    "source": "analyst_reglas_economicas",
                    "match_confidence": "media",
                    "provenance": "analyst_reglas_economicas",
                }
    econ = (tasks.get("economic") or {}).get("data") if isinstance(tasks.get("economic"), dict) else {}
    if isinstance(econ, dict):
        ctx = (econ.get("contexto_bases_analista") or {}).get("reglas_economicas") or {}
        if isinstance(ctx, dict):
            for val in ctx.values():
                txt = str(val or "").strip()
                if txt and _literal_matches_doc(literal, txt):
                    return {
                        "snippet": txt[:420],
                        "source": "economic_reglas_analista",
                        "match_confidence": "media",
                        "provenance": "economic_reglas_analista",
                    }
    return {}


_PROVENANCE_ONLY_SOURCES = frozenset({
    "dictamen",
    "dictamen_causales",
    "panel_context",
    "vector_primary",
    "vector_general",
    "evidence_snippet",
    "vector_index",
})


def _normalize_index_source(vdb: Any, session_id: str, source: Optional[str]) -> Optional[str]:
    """Mapea metadatos de procedencia al nombre de archivo indexado en Chroma."""
    try:
        sources = vdb.get_sources(session_id) or []
    except Exception:
        sources = []
    if not sources:
        return None
    src = str(source or "").strip()
    if src and src not in _PROVENANCE_ONLY_SOURCES and src in sources:
        return src
    if src and src not in _PROVENANCE_ONLY_SOURCES:
        sl = src.lower()
        for candidate in sources:
            cl = str(candidate).lower()
            if sl == cl or sl in cl or cl in sl:
                return str(candidate)
    return _primary_bases_source(sources)


def _fetch_page_text(
    vdb: Any,
    session_id: str,
    page: Any,
    *,
    preferred_source: Optional[str] = None,
    literal: str = "",
) -> tuple[str, Optional[str]]:
    """Recupera texto de página probando fuentes indexadas hasta encontrar ancla verificable."""
    sources = vdb.get_sources(session_id) or []
    ordered: List[str] = []
    resolved = _normalize_index_source(vdb, session_id, preferred_source)
    if resolved:
        ordered.append(resolved)
    for s in sources:
        if s not in ordered:
            ordered.append(s)

    best_text = ""
    best_source: Optional[str] = None
    for src in ordered:
        chunks = vdb.fetch_page_documents(session_id, str(src), page)
        text = re.sub(r"===\s*PÁGINA\s+\d+\s*===", "\n", "\n".join(chunks or []), flags=re.I).strip()
        if not text:
            try:
                text = str(vdb.get_full_pages(session_id, str(src), [int(page)]) or "").strip()
            except (TypeError, ValueError):
                text = ""
        if not text:
            continue
        if literal and _literal_matches_doc(literal, text):
            return text, str(src)
        if not best_text:
            best_text = text
            best_source = str(src)
    return best_text, best_source


def _best_verified_vector_hit(
    vdb: Any,
    session_id: str,
    literal: str,
    *,
    source_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Solo devuelve hits donde el literal/monto aparece en el fragmento indexado."""
    best: Dict[str, Any] = {}
    best_score = 999.0
    for query in _extract_search_terms(literal):
        if source_filter:
            res = vdb.query_texts_filtered(session_id, query, source_filter, n_results=16)
        else:
            res = vdb.query_texts(session_id, query, n_results=16)
        docs, metas, dists = _normalize_vector_hits(res)
        for doc, meta, dist in zip(docs, metas, dists):
            if not doc or not _literal_matches_doc(literal, doc):
                continue
            meta = meta if isinstance(meta, dict) else {}
            score = float(dist)
            if score >= best_score:
                continue
            best_score = score
            best = {
                "page": meta.get("page"),
                "snippet": _snippet_from_doc(literal, doc),
                "source": meta.get("source") or meta.get("filename") or source_filter,
                "match_confidence": "alta",
                "provenance": "vector_primary" if source_filter else "vector_general",
            }
    return best


def _scan_index_for_literal(
    vdb: Any,
    session_id: str,
    literal: str,
    *,
    source_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Escaneo determinista del índice por ancla de monto.
    Puente HRU entre alertas parafraseadas del agente económico y texto real del PDF.
    """
    chunks = vdb.scan_session_chunks(session_id, source_filter=source_filter)
    if not chunks and source_filter:
        chunks = vdb.scan_session_chunks(session_id)
    best: Dict[str, Any] = {}
    best_rank = -1
    for doc, meta in chunks:
        if not _literal_matches_doc(literal, doc):
            continue
        src = str(meta.get("source") or "").lower()
        rank = 1
        if any(k in src for k in _PRIMARY_DOC_KEYWORDS):
            rank = 3
        elif meta.get("page") is not None:
            rank = 2
        if rank < best_rank:
            continue
        best_rank = rank
        best = {
            "page": meta.get("page"),
            "snippet": _snippet_from_doc(literal, doc),
            "source": meta.get("source"),
            "match_confidence": "alta",
            "provenance": "index_scan",
        }
    return best


def verify_forensic_risk_evidence(
    vdb: Any,
    session_id: str,
    literal: str,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Fail-closed: descarta página/fuente no verificables en el índice.
    Evita citar página 1 u otra por similitud semántica sin ancla literal.
    """
    ev = dict(evidence or {})
    page = ev.get("page")
    snippet = str(ev.get("snippet") or "").strip()
    lit_fp = alert_fingerprint(literal)

    if page is not None:
        page_text, resolved_source = _fetch_page_text(
            vdb,
            session_id,
            page,
            preferred_source=ev.get("source"),
            literal=literal,
        )
        if page_text and _literal_matches_doc(literal, page_text):
            ev["page"] = page
            ev["source"] = resolved_source
            ev["snippet"] = _snippet_from_doc(literal, page_text)
            ev["match_confidence"] = "alta"
            return ev
        ev.pop("page", None)

    verified = _best_verified_vector_hit(vdb, session_id, literal)
    if not verified:
        sources = vdb.get_sources(session_id) or []
        primary = _primary_bases_source(sources)
        if primary:
            verified = _best_verified_vector_hit(vdb, session_id, literal, source_filter=primary)
    if not verified:
        verified = _scan_index_for_literal(vdb, session_id, literal)
        if not verified:
            sources = vdb.get_sources(session_id) or []
            primary = _primary_bases_source(sources)
            if primary:
                verified = _scan_index_for_literal(vdb, session_id, literal, source_filter=primary)
    if verified:
        vpage = verified.get("page")
        if vpage is not None:
            page_text, resolved_source = _fetch_page_text(
                vdb,
                session_id,
                vpage,
                preferred_source=verified.get("source"),
                literal=literal,
            )
            if page_text and _literal_matches_doc(literal, page_text):
                verified["source"] = resolved_source
                verified["snippet"] = _snippet_from_doc(literal, page_text)
                return verified
        if verified.get("snippet"):
            return verified

    if snippet and lit_fp and lit_fp[:48] not in alert_fingerprint(snippet):
        ev["snippet"] = snippet
        ev["match_confidence"] = "media"
    else:
        ev.pop("snippet", None)
        ev["match_confidence"] = "baja"
    if ev.get("source") in _PROVENANCE_ONLY_SOURCES:
        ev.pop("source", None)
    return ev


def _best_vector_hit(vdb: Any, session_id: str, literal: str, *, source_filter: Optional[str] = None) -> Dict[str, Any]:
    best: Dict[str, Any] = {}
    best_score = 999.0
    for query in _extract_search_terms(literal):
        if source_filter:
            res = vdb.query_texts_filtered(session_id, query, source_filter, n_results=12)
        else:
            res = vdb.query_texts(session_id, query, n_results=12)
        docs, metas, dists = _normalize_vector_hits(res)
        for doc, meta, dist in zip(docs, metas, dists):
            if not doc:
                continue
            meta = meta if isinstance(meta, dict) else {}
            matches = _literal_matches_doc(literal, doc)
            score = dist - (0.4 if matches else 0.0)
            if score >= best_score:
                continue
            best_score = score
            best = {
                "snippet": _snippet_from_doc(literal, doc),
                "source": meta.get("source") or meta.get("filename") or source_filter,
                "match_confidence": "alta" if matches else "media",
                "provenance": "vector_primary" if source_filter else "vector_general",
            }
            if matches:
                best["page"] = meta.get("page")
    return best


def _merge_evidence(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    if not primary:
        return dict(secondary)
    if not secondary:
        return dict(primary)
    out = dict(primary)
    if not out.get("page") and secondary.get("page"):
        out["page"] = secondary.get("page")
    if not out.get("snippet") and secondary.get("snippet"):
        out["snippet"] = secondary.get("snippet")
    if not out.get("source") and secondary.get("source"):
        out["source"] = secondary.get("source")
    if secondary.get("match_confidence") == "alta":
        out["match_confidence"] = "alta"
    return out


def _from_risk_context(risk_ctx: Dict[str, Any]) -> Dict[str, Any]:
    page = risk_ctx.get("page")
    snippet = risk_ctx.get("snippet")
    if page is None and not (snippet and str(snippet).strip()):
        return {}
    provenance = str(
        risk_ctx.get("provenance") or risk_ctx.get("provenance_hint") or "panel_context"
    )
    return {
        "page": page,
        "snippet": str(snippet).strip() if snippet else None,
        "source": risk_ctx.get("source"),
        "match_confidence": "alta" if page is not None else "media",
        "provenance": provenance,
    }


async def resolve_forensic_risk_evidence(
    session_id: str,
    literal: str,
    risk_ctx: Optional[Dict[str, Any]] = None,
    session_state: Optional[Dict[str, Any]] = None,
    *,
    memory: Any = None,
) -> Dict[str, Any]:
    """Resuelve page/snippet/source con cascada HRU."""
    risk_ctx = risk_ctx or {}
    evidence = _from_risk_context(risk_ctx)

    state = session_state or {}
    if memory and not state:
        try:
            state = await memory.get_session(session_id) or {}
        except Exception:
            state = {}

    dictamen = state.get("dictamen") if isinstance(state.get("dictamen"), dict) else {}
    causales = list(dictamen.get("causales") or [])
    evidence = _merge_evidence(evidence, _evidence_from_causales(causales, literal))
    evidence = _merge_evidence(evidence, _evidence_from_session_analyst(state, literal))

    if not session_id or not literal.strip():
        return evidence

    try:
        from app.services.vector_service import VectorDbServiceClient

        vdb = VectorDbServiceClient()
        sources = vdb.get_sources(session_id)
        if memory and not sources:
            try:
                from app.services.vector_sync_service import VectorSyncService

                await VectorSyncService().ensure_session_indexed(memory, session_id)
                sources = vdb.get_sources(session_id)
            except Exception:
                pass

        if not (evidence.get("page") and evidence.get("match_confidence") == "alta"):
            primary = _primary_bases_source(sources)
            if primary:
                vec_primary = _best_vector_hit(vdb, session_id, literal, source_filter=primary)
                evidence = _merge_evidence(evidence, vec_primary)
            if not evidence.get("page"):
                vec_general = _best_vector_hit(vdb, session_id, literal)
                evidence = _merge_evidence(evidence, vec_general)

        evidence = verify_forensic_risk_evidence(vdb, session_id, literal, evidence)
        if memory and not evidence.get("page") and vdb.count_session_chunks(session_id) == 0:
            try:
                from app.services.vector_sync_service import VectorSyncService

                await VectorSyncService().ensure_session_indexed(memory, session_id, force=False)
                evidence = verify_forensic_risk_evidence(vdb, session_id, literal, evidence)
            except Exception as heal_exc:
                from app.core.logging_config import get_logger

                get_logger(__name__).warning(
                    "forensic_evidence_index_heal_failed session=%s err=%s",
                    session_id,
                    heal_exc,
                )
    except Exception as resolve_exc:
        from app.core.logging_config import get_logger

        get_logger(__name__).warning(
            "forensic_evidence_resolve_failed session=%s literal=%s err=%s",
            session_id,
            literal[:80],
            resolve_exc,
        )

    return evidence
