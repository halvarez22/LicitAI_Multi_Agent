"""
Consolida preguntas para la **junta de aclaraciones** (audiencia: convocante).

Fuentes:
- Analista: ``preguntas_junta_aclaraciones``, gap/alertas con sugerencia
- Conflictos evidencia ↔ perfil (reformulados para la convocante, no HITL interno)
- Tickets del mini dictamen de anexos
- Brechas Go/No-Go con impacto en bases
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.contracts.junta_aclaraciones_questions import (
    JuntaAclaracionesQuestionItem,
    JuntaAclaracionesQuestionsBundle,
    JuntaAclaracionesQuestionsSummary,
    JuntaQuestionPrioridad,
    JuntaQuestionSource,
    JuntaQuestionStatus,
    JuntaQuestionTipo,
)
from app.core.logging_config import get_logger
from app.services.evidence_profile_service import _CRITICAL_FIELDS, detect_profile_conflicts

logger = get_logger(__name__)

_SCHEMA_VERSION = "1.2.0"

# Ítems de control de calidad del análisis; no se copian al portal de la convocante.
_JUNTA_INTERNAL_SOURCE_REFS = frozenset({"analyst_pending_citation_umbrella"})

_STALE_GROUPED_TICKETS_RE = re.compile(
    r"(?i)10\s+formatos\s+adicionales|grouped_required_annex_not_published"
)

_ARTIFACT_12_3_PREGUNTA_RE = re.compile(
    r"(?i)12\s*a[nñ]os\s+de\s+experiencia.*3\s*a[nñ]os|"
    r"al\s+menos\s+12\s*a[nñ]os.*anexo\s+t[eé]cnico.*3\s*a[nñ]os"
)

# Niveles de calidad de cita (badge en UI)
CITATION_QUALITY_COMPLETE = "cita_completa"
CITATION_QUALITY_DOCUMENT_ONLY = "solo_documento"
CITATION_QUALITY_INSUFFICIENT = "datos_insuficientes"

_PATTERNS_CITA_COMPLETA = frozenset(
    {
        "dual_bases_citation",
        "dual_bases_only",
        "bases_vs_anexo",
        "bases_vs_documento",
        "explicit_conflict",
    }
)

_LEGACY_JUNTA_RE = re.compile(
    r"(?i)Solicitamos aclaración respecto|podrían interpretarse de forma distinta|"
    r"umbral general de las bases"
)

_INTERNAL_TICKET_LEAK_RE = re.compile(
    r"(?i)necesito aclarar con la convocante|motivo detectado\s*:|"
    r"¿\s*deseas prepararlo|prepararlo como punto para la junta"
)

_FIELD_LABELS: Dict[str, str] = {
    "anos_experiencia": "años de experiencia acreditable de la empresa licitante",
    "rfc": "RFC del licitante",
    "capital_contable": "capital contable mínimo",
    "representante_legal": "representante legal",
    "domicilio_fiscal": "domicilio fiscal del licitante",
}

_FIELD_SEARCH_KEYS: Dict[str, List[str]] = {
    "anos_experiencia": ["experiencia", "años", "anios", "cv empresarial", "trayectoria"],
    "rfc": ["rfc", "registro federal de contribuyentes"],
    "representante_legal": ["representante legal", "apoderado", "poder"],
    "domicilio_fiscal": ["domicilio fiscal", "domicilio", "comprobante de domicilio"],
    "capital_contable": ["capital contable", "capital social"],
}

_PLACEHOLDER_RE = re.compile(
    r"(?i)(punto\s+x\b|pregunta\s+t[eé]cnica\s+para\s+clarificar|"
    r"requisito\s*«\s*\.{2,}\s*»|«\s*\.{2,}\s*»|^\s*\.\.\.\s*$|clarificar\s+el\s+punto\s+x|"
    r"respecto al requisito\s*«\s*\.{2,}|fragmento idéntico al párrafo citado)"
)

_ANALYST_SNIPPET_PLACEHOLDER_RE = re.compile(
    r"(?i)fragmento idéntico al párrafo citado|texto literal copiado sin abreviar"
)


def _norm_key(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return re.sub(r"[^a-z0-9áéíóúñ ]", "", t)[:220]


def _dedupe_key(pregunta: str) -> str:
    return hashlib.sha256(_norm_key(pregunta).encode("utf-8")).hexdigest()[:16]


_STALE_GRAMMAR_RE = re.compile(
    r"(?i)Con respecto a el documento|Con respecto a en el apartado|"
    r"apartado documento de la convocatoria|esta redacción genera"
)


def _estimate_minimum_junta_items(
    session_state: Dict[str, Any],
    analysis: Dict[str, Any],
) -> int:
    """Mínimo esperado según evidencia documental y placeholders del analista."""
    n = 0
    for field in _CRITICAL_FIELDS:
        entry = _evidence_field_entry(session_state, field)
        if entry.get("value") not in (None, "", []):
            n += 1
    if _analysis_has_placeholder_only_extracts(analysis):
        n += 1
    return n


def bundle_needs_regeneration(
    payload: Optional[Dict[str, Any]],
    *,
    session_state: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
) -> bool:
    """True si el bundle persistido está obsoleto, incompleto o con redacción antigua."""
    if not isinstance(payload, dict):
        return True
    if str(payload.get("schema_version") or "") != _SCHEMA_VERSION:
        return True

    items = [it for it in (payload.get("items") or []) if isinstance(it, dict)]
    for it in items:
        pregunta = str(it.get("pregunta") or "")
        if _LEGACY_JUNTA_RE.search(pregunta):
            return True
        if _STALE_GRAMMAR_RE.search(pregunta):
            return True
        if _INTERNAL_TICKET_LEAK_RE.search(pregunta):
            return True
        if _ARTIFACT_12_3_PREGUNTA_RE.search(pregunta):
            return True
        if str(it.get("source_ref") or "") == "grouped_required_annex_not_published":
            return True
        if _STALE_GROUPED_TICKETS_RE.search(pregunta):
            return True

    if session_state is None:
        return False

    analysis = analysis if isinstance(analysis, dict) else _extract_analysis_from_session(session_state)
    expected = _estimate_minimum_junta_items(session_state, analysis)
    if len(items) < expected:
        return True

    refs = {str(it.get("source_ref") or "") for it in items}
    if _analysis_has_placeholder_only_extracts(analysis) and "analyst_pending_citation_umbrella" not in refs:
        return True

    for field in _CRITICAL_FIELDS:
        entry = _evidence_field_entry(session_state, field)
        if entry.get("value") in (None, "", []):
            continue
        if not any(r == field or r.startswith(f"{field}_") for r in refs):
            return True

    return False


def is_internal_junta_item(item: Any) -> bool:
    """True si el ítem es solo para operación interna (no portal convocante)."""
    if isinstance(item, JuntaAclaracionesQuestionItem):
        ref = str(item.source_ref or "")
        prov = item.provenance_ui or {}
    elif isinstance(item, dict):
        ref = str(item.get("source_ref") or "")
        prov = item.get("provenance_ui") if isinstance(item.get("provenance_ui"), dict) else {}
    else:
        return False
    if ref in _JUNTA_INTERNAL_SOURCE_REFS:
        return True
    return str(prov.get("audience") or "") == "interno"


def mini_dictamen_needs_co_refresh(
    session_id: str,
    session_state: Dict[str, Any],
    documents: Sequence[Dict[str, Any]],
) -> bool:
    """
    True si tickets/mini dictamen están desalineados con el corpus (p. ej. formatos embebidos en PDF).
    """
    from app.services.junta_bases_corpus import build_bases_corpus, template_embedded_in_bases

    corpus = build_bases_corpus(session_id, documents, session_state=session_state)
    if not corpus.segments:
        return False

    open_annex: List[Dict[str, Any]] = []
    for raw in session_state.get("clarification_tickets") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("status") or "").lower() not in ("open", "ready_for_junta"):
            continue
        if str(raw.get("reason") or "") != "required_annex_not_published":
            continue
        open_annex.append(raw)
    if len(open_annex) >= 3:
        return True
    for raw in open_annex:
        if template_embedded_in_bases(corpus, str(raw.get("display_name") or "")):
            return True

    junta = session_state.get("junta_aclaraciones_questions")
    if isinstance(junta, dict):
        for it in junta.get("items") or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("source_ref") or "") == "grouped_required_annex_not_published":
                return True
            if _ARTIFACT_12_3_PREGUNTA_RE.search(str(it.get("pregunta") or "")):
                return True
    return False


def _has_substantive_analysis(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    if data.get("requisitos_participacion"):
        return True
    ar = data.get("audit_report") if isinstance(data.get("audit_report"), dict) else {}
    if ar.get("preguntas_junta_aclaraciones") or ar.get("gap_analysis") or ar.get("alertas_descalificacion"):
        return True
    return bool(
        data.get("cronograma")
        or data.get("requisitos_filtro")
        or data.get("criterios_evaluacion")
    )


def _merge_analysis_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Fusiona análisis priorizando listas no vacías del overlay de sesión."""
    merged = dict(base)
    for key, val in overlay.items():
        if isinstance(val, list) and not val:
            continue
        if isinstance(val, dict) and not val:
            continue
        merged[key] = val
    ar_b = base.get("audit_report") if isinstance(base.get("audit_report"), dict) else {}
    ar_o = overlay.get("audit_report") if isinstance(overlay.get("audit_report"), dict) else {}
    if ar_b or ar_o:
        merged["audit_report"] = {**ar_b, **{k: v for k, v in ar_o.items() if v not in (None, [], {})}}
    return merged


def _extract_analysis_from_session(
    session_state: Dict[str, Any],
    *,
    analysis_overlay: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if isinstance(analysis_overlay, dict) and analysis_overlay:
        return analysis_overlay
    agent_la = session_state.get("_junta_analysis_from_agent")
    if isinstance(agent_la, dict) and _has_substantive_analysis(agent_la):
        return agent_la
    for task in reversed(session_state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        if str(task.get("task") or "") != "stage_completed:analysis":
            continue
        res = task.get("result") or {}
        data = res.get("data") if isinstance(res.get("data"), dict) else res
        if isinstance(data, dict) and _has_substantive_analysis(data):
            if isinstance(agent_la, dict) and agent_la:
                return _merge_analysis_dict(agent_la, data)
            return data
    if isinstance(agent_la, dict) and agent_la:
        return agent_la
    dictamen = session_state.get("dictamen") or {}
    if isinstance(dictamen, dict):
        ed = dictamen.get("extracted_data") or {}
        data = ed.get("data") if isinstance(ed.get("data"), dict) else ed
        if isinstance(data, dict) and _has_substantive_analysis(data):
            return data
    return {}


async def _enrich_session_for_junta(
    memory: Any,
    session_id: str,
    session_state: Dict[str, Any],
    *,
    company_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Hidrata análisis del agente y perfil maestro para detectar conflictos."""
    state = dict(session_state)
    session_analysis = _extract_analysis_from_session(state)
    try:
        agent_st = await memory.get_agent_state("analyst_001", session_id)
        la = (agent_st or {}).get("last_analysis") if isinstance(agent_st, dict) else None
        if isinstance(la, dict) and la:
            if _has_substantive_analysis(session_analysis):
                state["_junta_analysis_from_agent"] = _merge_analysis_dict(la, session_analysis)
            else:
                state["_junta_analysis_from_agent"] = la
    except Exception:
        if session_analysis:
            state["_junta_analysis_from_agent"] = session_analysis
    if not state.get("master_profile"):
        cid = company_id or state.get("company_id")
        if not cid and isinstance(state.get("global_inputs"), dict):
            cid = state["global_inputs"].get("company_id")
        if cid:
            try:
                company = await memory.get_company(str(cid)) or {}
                mp = company.get("master_profile") or company.get("catalog")
                if isinstance(mp, dict) and mp:
                    state["master_profile"] = mp
            except Exception:
                pass
    return state


def _infer_tipo(text: str, default: JuntaQuestionTipo = JuntaQuestionTipo.TECNICA) -> JuntaQuestionTipo:
    lo = str(text or "").lower()
    if any(k in lo for k in ("precio", "económ", "econom", "moneda", "iva", "cotiz")):
        return JuntaQuestionTipo.ECONOMICA
    if any(k in lo for k in ("legal", "rfc", "acta", "poder", "fiscal", "imss", "repse")):
        return JuntaQuestionTipo.LEGAL
    if any(k in lo for k in ("formato", "anexo", "plantilla", "sobre", "entrega")):
        return JuntaQuestionTipo.ADMINISTRATIVA
    return default


def _prioridad_from_gravedad(gravedad: str) -> JuntaQuestionPrioridad:
    g = str(gravedad or "").upper()
    if g in ("ALTA", "BLOQUEANTE", "CRITICO", "CRÍTICO", "BLOCKING"):
        return JuntaQuestionPrioridad.ALTA
    if g in ("MEDIA", "IMPORTANTE"):
        return JuntaQuestionPrioridad.MEDIA
    return JuntaQuestionPrioridad.BAJA


def _is_low_quality_question(text: str) -> bool:
    """Excluye placeholders del analista o texto sin sustancia."""
    p = str(text or "").strip()
    if len(p) < 24:
        return True
    if _LEGACY_JUNTA_RE.search(p):
        return True
    if _PLACEHOLDER_RE.search(p):
        return True
    if p.count("...") >= 1 and len(re.sub(r"[.\s…]", "", p)) < 28:
        return True
    if p.count("...") >= 2:
        return True
    return False


def _format_pagina(pagina: Any) -> str:
    if pagina in (None, "", 0, "0", "N/A", "n/a"):
        return ""
    return f"la página {pagina}"


def _join_citation_parts(parts: List[str]) -> str:
    """Une fragmentos de ubicación sin producir «de en el apartado»."""
    clean = [p.strip() for p in parts if p and str(p).strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} y {clean[1]}"
    return ", ".join(clean[:-1]) + f" y {clean[-1]}"


def _format_ubicacion_bases(cita: Dict[str, Any]) -> str:
    """Ej.: «la cláusula 13, de la página 21 y en el apartado REQUISITOS DEL PARTICIPANTE»."""
    parts: List[str] = []
    inciso = str(cita.get("inciso") or "").strip()
    if inciso and inciso.lower() not in ("n/a", "na", ""):
        parts.append(f"la cláusula {inciso}")
    pag = _format_pagina(cita.get("pagina"))
    if pag:
        parts.append(pag)
    seccion = str(cita.get("seccion") or "").strip()
    if seccion and seccion.upper() not in ("N/A", "NA"):
        parts.append(f"en el apartado {seccion}")
    archivo = str(cita.get("archivo") or "").strip()
    if archivo and not seccion:
        parts.append(f"en el documento «{archivo}»")
    if not parts:
        return "en las bases de la convocatoria"
    return _join_citation_parts(parts)


def _intro_con_respecto(ubic: str) -> str:
    """Artículo correcto: «Con respecto al documento…» / «Con respecto al apartado…»."""
    u = re.sub(r"^el\s+documento\s+", "documento ", str(ubic or "").strip(), flags=re.I)
    if u.startswith("documento «"):
        return f"Con respecto al {u}"
    apartado = re.match(r"^en el apartado\s+(.+)$", u, re.I)
    if apartado:
        return f"Con respecto al apartado {apartado.group(1).strip()}"
    if u.startswith(("la cláusula ", "la página ", "la ")):
        return f"Con respecto a {u}"
    if u.startswith("en las bases"):
        return f"Con respecto a {u}"
    return f"Con respecto a {u}"


def _format_ubicacion_documento(cita: Dict[str, Any]) -> str:
    """Ej.: «documento «Aclaraciones.pdf», en el apartado …, de la página 8 y en la cláusula b»."""
    parts: List[str] = []
    archivo = str(cita.get("archivo") or "").strip()
    if archivo:
        parts.append(f"documento «{archivo}»")
    seccion = str(cita.get("seccion") or "").strip()
    if seccion and seccion.upper() not in ("N/A", "NA"):
        parts.append(f"en el apartado {seccion}")
    pag = _format_pagina(cita.get("pagina"))
    if pag:
        parts.append(pag)
    inciso = str(cita.get("inciso") or "").strip()
    if inciso and inciso.lower() not in ("n/a", "na", ""):
        parts.append(f"en la cláusula {inciso}")
    if not parts:
        return "un documento de la convocatoria"
    return _join_citation_parts(parts)


def _ubicacion_inline_phrase(cita: Dict[str, Any], *, bases: bool = False) -> str:
    """Frase para «sin embargo, en …» sin duplicar «en documento»."""
    ubic = _format_ubicacion_bases(cita) if bases else _format_ubicacion_documento(cita)
    if ubic.startswith("documento «"):
        return f"en el {ubic}"
    if ubic.startswith(("la cláusula", "la página")):
        return f"en {ubic}"
    if ubic.startswith("en el apartado"):
        return ubic
    return f"en {ubic}"


def _is_bases_citation(cita: Dict[str, Any]) -> bool:
    """True si la cita proviene de bases/convocatoria (no solo anexo suelto)."""
    archivo = str(cita.get("archivo") or "").lower()
    if not archivo:
        return bool(cita.get("seccion") or cita.get("pagina") or cita.get("inciso"))
    return any(k in archivo for k in ("bases", "convocatoria", "licitacion", "licitación"))


def _already_junta_canonical(text: str) -> bool:
    return str(text or "").strip().lower().startswith("con respecto")


def _default_dual_cierre(tema: str) -> str:
    return (
        f"¿a cuál de estos dos criterios sobre {tema} debe apegarse el licitante "
        f"al integrar su proposición?"
    )


def _build_junta_dual_question(
    ref_a: Dict[str, Any],
    texto_a: str,
    ref_b: Dict[str, Any],
    texto_b: str,
    *,
    tema: str,
    cierre: Optional[str] = None,
) -> str:
    """
    Formato canónico junta (estilo cliente): dos ubicaciones, dos textos, pregunta cerrada.

    Primera cita: bases o documento; segunda: bases («más adelante…») o documento («sin embargo…»).
    """
    ta = _truncate_literal(texto_a)
    tb = _truncate_literal(texto_b)
    if _is_bases_citation(ref_a):
        ua = _format_ubicacion_bases(ref_a)
        intro_a = f"{_intro_con_respecto(ua)}, donde la convocante establece que {ta}"
    else:
        ua = _format_ubicacion_documento(ref_a)
        intro_a = f"{_intro_con_respecto(ua)}, donde se indica que {ta}"

    if _is_bases_citation(ref_b):
        ub = _format_ubicacion_bases(ref_b)
        intro_b = f"y más adelante en las bases, en {ub}, se establece que {tb}"
    else:
        intro_b = f"sin embargo, {_ubicacion_inline_phrase(ref_b)}, se indica que {tb}"

    cierre = cierre or _default_dual_cierre(tema)
    return f"{intro_a}, {intro_b}, {cierre}"


def _build_junta_single_question(
    cita: Dict[str, Any],
    texto_establece: str,
    tema: str,
    *,
    contexto: str = "",
) -> str:
    """Un solo punto (bases o anexo) con cierre estándar para la convocante."""
    t = _truncate_literal(texto_establece)
    ctx = ""
    if contexto and contexto.strip():
        ctx = f" {contexto.strip().rstrip('.')};"
    if _is_bases_citation(cita):
        ubic = _format_ubicacion_bases(cita)
        return (
            f"{_intro_con_respecto(ubic)}, donde la convocante establece que {t}.{ctx} "
            f"Esta redacción genera incertidumbre para integrar la proposición sin riesgo de observación. "
            f"¿Cuál es el criterio oficial que la convocante aplicará respecto a {tema}?"
        )
    ubic = _format_ubicacion_documento(cita)
    return (
        f"{_intro_con_respecto(ubic)}, donde se indica que {t}.{ctx} "
        f"Esta redacción genera incertidumbre para integrar la proposición sin riesgo de observación. "
        f"¿Cuál es el criterio oficial que la convocante aplicará respecto a {tema}?"
    )


def _build_junta_from_free_text(
    raw: str,
    *,
    cita: Optional[Dict[str, Any]] = None,
    tema: str = "este requisito",
) -> str:
    """Normaliza texto libre del analista o tickets al formato canónico."""
    p = str(raw or "").strip()
    if not p:
        return p
    if _already_junta_canonical(p):
        return p if p.endswith("?") else f"{p}?"
    if isinstance(cita, dict) and any(cita.get(k) for k in ("pagina", "inciso", "seccion", "archivo", "texto")):
        return _build_junta_single_question(cita, p, tema)
    pregunta = p if p.endswith("?") else f"{p}?"
    return (
        f"Con respecto a lo dispuesto en las bases de la convocatoria sobre {tema}, "
        f"donde la convocante establece un requisito que admite distintas interpretaciones, "
        f"solicitamos aclaración: {pregunta} "
        f"¿Cuál es el criterio oficial que la convocante aplicará para uniformar la evaluación?"
    )


def _cita_from_evidence_entry(entry: Dict[str, Any], doc_name: str) -> Dict[str, Any]:
    cita: Dict[str, Any] = {
        "texto": entry.get("snippet") or "",
        "pagina": entry.get("page") or entry.get("pagina"),
        "archivo": doc_name,
        "inciso": entry.get("inciso"),
    }
    if entry.get("seccion"):
        cita["seccion"] = entry.get("seccion")
    return cita


def _dual_bases_distinct_refs(
    citations: List[Dict[str, Any]],
) -> Optional[Tuple[Tuple[str, Dict[str, Any]], Tuple[str, Dict[str, Any]]]]:
    """Dos fragmentos distintos en bases (mismo campo, redacción divergente)."""
    refs: List[Tuple[str, Dict[str, Any]]] = []
    for c in citations:
        t = str(c.get("texto") or "").strip()
        if len(t) < 12:
            continue
        nk = _norm_key(t[:120])
        if any(nk == _norm_key(str(r[1].get("texto") or "")[:120]) for r in refs):
            continue
        refs.append((t, c))
        if len(refs) >= 2:
            break
    if len(refs) >= 2:
        return refs[0], refs[1]
    return None


def _extract_years_from_text(text: str) -> Optional[str]:
    """
    Extrae años de experiencia de fragmentos literales de bases o anexos.

    Cubre «12 años», «al menos 12», «al menos 3 años en servicios similares», «Máximo: 3».
    """
    t = str(text or "")
    patterns = (
        r"(\d{1,2})\s*a(?:ñ|n)os?(?:\s+de\s+experiencia|\s+en\s+servicios\s+similares)?",
        r"(?:al\s+menos|m[ií]nimo(?:\s+de)?)\s+(\d{1,2})(?:\s+a(?:ñ|n)os?)?",
        r"m[aá]ximo\s*:?\s*(\d{1,2})(?:\s+a(?:ñ|n)os?)?",
        r"(\d{1,2})\s+a(?:ñ|n)os?\s+acreditables?",
    )
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(1)
    return None


def _dual_bases_experience_refs(
    citations: List[Dict[str, Any]],
) -> Optional[Tuple[Tuple[str, Dict[str, Any]], Tuple[str, Dict[str, Any]]]]:
    """Dos ubicaciones en bases con años distintos (estilo junta del cliente)."""
    refs: List[Tuple[str, Dict[str, Any]]] = []
    for c in citations:
        y = _extract_years_from_text(c.get("texto") or "")
        if not y:
            continue
        if any(y == yy for yy, _ in refs):
            continue
        refs.append((y, c))
        if len(refs) >= 2:
            break
    if len(refs) >= 2 and refs[0][0] != refs[1][0]:
        return refs[0], refs[1]
    return None


def _truncate_literal(text: str, limit: int = 220) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 3].rstrip() + "..."


def _search_bases_citations(
    analysis: Dict[str, Any],
    session_state: Dict[str, Any],
    field: str,
) -> List[Dict[str, Any]]:
    """Localiza fragmentos en requisitos de participación y lista de compliance."""
    keys = _FIELD_SEARCH_KEYS.get(field, [field.replace("_", " ")])
    out: List[Dict[str, Any]] = []
    seen_txt: set = set()

    def _add(cita: Dict[str, Any]) -> None:
        texto = str(cita.get("texto") or "").strip()
        if len(texto) < 12:
            return
        nk = _norm_key(texto[:120])
        if nk in seen_txt:
            return
        seen_txt.add(nk)
        out.append(cita)

    for req in analysis.get("requisitos_participacion") or []:
        if not isinstance(req, dict):
            continue
        txt = str(req.get("texto_literal") or req.get("texto") or "").strip()
        if not any(k in txt.lower() for k in keys):
            continue
        _add(
            {
                "texto": txt,
                "pagina": req.get("pagina"),
                "archivo": req.get("archivo_fuente") or req.get("archivo"),
                "seccion": req.get("seccion") or "REQUISITOS DEL PARTICIPANTE",
                "inciso": req.get("inciso"),
            }
        )

    cm = session_state.get("compliance_master_list") or {}
    if isinstance(cm, dict):
        for cat in ("administrativo", "tecnico", "formatos"):
            for it in cm.get(cat) or []:
                if not isinstance(it, dict):
                    continue
                blob = " ".join(
                    [
                        str(it.get("nombre") or ""),
                        str(it.get("descripcion") or ""),
                        str(it.get("snippet") or ""),
                    ]
                )
                if not any(k in blob.lower() for k in keys):
                    continue
                _add(
                    {
                        "texto": str(it.get("snippet") or it.get("descripcion") or it.get("nombre")),
                        "pagina": it.get("page") or it.get("pagina"),
                        "archivo": it.get("archivo_fuente") or it.get("source_file"),
                        "seccion": it.get("seccion") or cat,
                        "inciso": it.get("inciso"),
                    }
                )
    return out[:6]


def _evidence_field_entry(session_state: Dict[str, Any], field: str) -> Dict[str, Any]:
    evidence = session_state.get("evidence_profile") or {}
    fields = evidence.get("fields") if isinstance(evidence, dict) else {}
    if isinstance(fields, dict):
        entry = fields.get(field)
        if isinstance(entry, dict):
            return entry
    return {}


def _build_experience_dual_question(
    ref_a: Dict[str, Any],
    years_a: str,
    ref_b: Dict[str, Any],
    years_b: str,
) -> str:
    """Dos ubicaciones en bases/documento con años distintos (formato canónico)."""
    ta = ref_a.get("texto") or f"al menos {years_a} años de experiencia acreditable"
    tb = ref_b.get("texto") or f"al menos {years_b} años de experiencia en servicios similares"
    return _build_junta_dual_question(
        ref_a,
        str(ta),
        ref_b,
        str(tb),
        tema="los años de experiencia acreditable de la empresa licitante",
        cierre=(
            "¿a cuál de estos dos requisitos de años de experiencia debe apegarse el licitante "
            "al integrar su proposición?"
        ),
    )


def _build_evidence_conflict_question(
    conflict: Dict[str, Any],
    session_state: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Tuple[str, Optional[str], Optional[str], Dict[str, Any]]:
    """
    Redacta pregunta explícita con citas, valores en conflicto y riesgo de mala interpretación.

    Returns:
        (pregunta, archivo_fuente, pagina, provenance_extra)
    """
    field = str(conflict.get("field") or "").strip()
    label = _FIELD_LABELS.get(field, field.replace("_", " "))
    master_val = conflict.get("master_value")
    doc_val = conflict.get("evidence_value")
    doc_name = str(conflict.get("source_doc") or "documento de la convocatoria").strip()
    entry = _evidence_field_entry(session_state, field)
    snippet = _truncate_literal(entry.get("snippet") or "", 200)
    doc_pag = entry.get("page") or entry.get("pagina")

    citations = _search_bases_citations(analysis, session_state, field)

    if field == "anos_experiencia":
        doc_years = _extract_years_from_text(str(doc_val)) or str(doc_val)
        refs_with_years: List[Tuple[str, Dict[str, Any]]] = []
        for c in citations:
            y = _extract_years_from_text(c.get("texto") or "")
            if y:
                refs_with_years.append((y, c))
        if master_val not in (None, "", []):
            my = _extract_years_from_text(str(master_val)) or str(master_val)
            if not any(y == my for y, _ in refs_with_years):
                refs_with_years.insert(
                    0,
                    (
                        my,
                        {
                            "texto": f"experiencia mínima de {my} años (requisito general en bases/perfil)",
                            "seccion": "REQUISITOS DEL PARTICIPANTE",
                        },
                    ),
                )
        if len(refs_with_years) >= 2:
            (ya, ca), (yb, cb) = refs_with_years[0], refs_with_years[1]
            if ya != yb:
                pregunta = _build_experience_dual_question(ca, ya, cb, yb)
                prov = {
                    "bases_years_a": ya,
                    "bases_years_b": yb,
                    "document_years": doc_years,
                    "pattern": "dual_bases_citation",
                }
                return pregunta, doc_name, str(doc_pag or cb.get("pagina") or ""), prov
        if len(refs_with_years) == 1 and doc_years:
            ya, ca = refs_with_years[0]
            if str(ya) != str(doc_years):
                pregunta = _build_experience_dual_question(
                    ca,
                    ya,
                    {
                        "texto": snippet or f"al menos {doc_years} años en servicios similares",
                        "pagina": doc_pag,
                        "archivo": doc_name,
                        "seccion": "CV empresarial o documento anexo",
                    },
                    doc_years,
                )
                prov = {"bases_years": ya, "document_years": doc_years, "pattern": "bases_vs_anexo"}
                return pregunta, doc_name, str(doc_pag or ""), prov

    dual_bases = _dual_bases_distinct_refs(citations)
    if dual_bases:
        (ta, ca), (tb, cb) = dual_bases
        pregunta = _build_junta_dual_question(ca, ta, cb, tb, tema=label)
        prov = {"pattern": "dual_bases_citation", "field": field}
        pag = str(ca.get("pagina") or cb.get("pagina") or "")
        return pregunta, str(ca.get("archivo") or cb.get("archivo") or doc_name), pag, prov

    cita_bases = citations[0] if citations else None
    texto_bases = ""
    if cita_bases:
        texto_bases = str(cita_bases.get("texto") or "")
    elif master_val not in (None, "", []):
        texto_bases = f"se exige o contempla {master_val} como {label}"
        cita_bases = {"seccion": "REQUISITOS DEL PARTICIPANTE", "texto": texto_bases}
    else:
        texto_bases = f"se establece un criterio para {label}"
        cita_bases = {"seccion": "REQUISITOS DEL PARTICIPANTE", "texto": texto_bases}

    texto_doc = snippet or f"se indica {doc_val} para {label}"
    doc_cita = _cita_from_evidence_entry(entry, doc_name)
    if not doc_cita.get("texto"):
        doc_cita["texto"] = texto_doc

    pregunta = _build_junta_dual_question(
        cita_bases,
        texto_bases,
        doc_cita,
        texto_doc,
        tema=label,
    )
    pag = str(cita_bases.get("pagina") or doc_pag or "")
    prov = {
        "master_value": master_val,
        "evidence_value": doc_val,
        "snippet": snippet,
        "pattern": "bases_vs_documento",
    }
    return pregunta, doc_name, pag, prov


def resolve_citation_quality(
    *,
    pregunta: str,
    pattern: Optional[str] = None,
    pagina: Optional[str] = None,
    source: Optional[str] = None,
    provenance_ui: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Clasifica la riqueza de la cita para el badge de UI.

    Returns:
        ``cita_completa`` | ``solo_documento`` | ``datos_insuficientes``
    """
    prov = provenance_ui if isinstance(provenance_ui, dict) else {}
    pat = pattern or prov.get("pattern")
    if pat in _PATTERNS_CITA_COMPLETA:
        return CITATION_QUALITY_COMPLETE
    if pat == "documento_sin_cita_bases":
        return CITATION_QUALITY_DOCUMENT_ONLY

    p = str(pregunta or "").strip().lower()
    if _LEGACY_JUNTA_RE.search(pregunta or ""):
        return CITATION_QUALITY_INSUFFICIENT

    has_ubicacion = any(
        k in p for k in ("cláusula", "clausula", "página", "pagina", "apartado")
    )
    has_dual = (
        "más adelante" in p
        or "sin embargo" in p
        or "y en el anexo" in p
        or "se mencionan" in p
    )
    has_conflict_close = "¿a cuál" in p or "debe apegarse" in p or "apegarnos" in p
    if has_ubicacion and (
        "establece que" in p
        or "se exige" in p
        or "se indica" in p
        or has_dual
        or (has_conflict_close and has_dual)
    ):
        return CITATION_QUALITY_COMPLETE

    if pagina and str(pagina).strip() not in ("", "0", "N/A", "n/a"):
        if "establece que" in p or "se indica" in p or has_dual:
            return CITATION_QUALITY_COMPLETE

    if "documento «" in p or "documento \"" in p:
        if has_ubicacion and (has_dual or has_conflict_close):
            return CITATION_QUALITY_COMPLETE
        if not has_ubicacion:
            return CITATION_QUALITY_DOCUMENT_ONLY

    if pattern in (
        "experience_years_conflict",
        "unresolved_se_adjunta",
        "format_placeholders",
        "certification_cluster",
    ):
        return CITATION_QUALITY_DOCUMENT_ONLY
    if str(prov.get("source") or "") == "thematic_bases":
        return CITATION_QUALITY_DOCUMENT_ONLY

    if str(source or "") in (
        JuntaQuestionSource.ANALYST_JUNTA.value,
        JuntaQuestionSource.ANALYST_GAP.value,
        JuntaQuestionSource.ANALYST_ALERT.value,
        JuntaQuestionSource.GO_NO_GO.value,
    ):
        if has_ubicacion and has_conflict_close and (has_dual or "se exige" in p):
            return CITATION_QUALITY_COMPLETE
        return CITATION_QUALITY_INSUFFICIENT

    if "con respecto" in p and "establece que" in p:
        return CITATION_QUALITY_DOCUMENT_ONLY

    return CITATION_QUALITY_INSUFFICIENT


def _append_item(
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
    *,
    pregunta: str,
    motivo: str,
    source: JuntaQuestionSource,
    source_ref: str,
    tipo: Optional[JuntaQuestionTipo] = None,
    prioridad: JuntaQuestionPrioridad = JuntaQuestionPrioridad.MEDIA,
    referencia_bases: Optional[str] = None,
    archivo_fuente: Optional[str] = None,
    pagina: Optional[str] = None,
    provenance_ui: Optional[Dict[str, Any]] = None,
    preserve_status: Optional[JuntaQuestionStatus] = None,
) -> None:
    p = str(pregunta or "").strip()
    if _is_low_quality_question(p):
        return
    if len(p) < 12:
        return
    dk = _dedupe_key(p)
    if dk in seen:
        return
    seen.add(dk)
    qid = f"JUNTA-{source.value[:4].upper()}-{dk}"
    prov = dict(provenance_ui or {"source": source.value, "source_ref": source_ref})
    prov.setdefault("source", source.value)
    prov.setdefault("source_ref", source_ref)
    if prov.get("citation_quality") not in (
        CITATION_QUALITY_COMPLETE,
        CITATION_QUALITY_DOCUMENT_ONLY,
        CITATION_QUALITY_INSUFFICIENT,
    ):
        prov["citation_quality"] = resolve_citation_quality(
            pregunta=p,
            pattern=str(prov.get("pattern") or "") or None,
            pagina=str(pagina) if pagina not in (None, "") else None,
            source=source.value,
            provenance_ui=prov,
        )
    items.append(
        JuntaAclaracionesQuestionItem(
            question_id=qid,
            tipo=tipo or _infer_tipo(p),
            prioridad=prioridad,
            status=preserve_status or JuntaQuestionStatus.BORRADOR,
            pregunta=p,
            motivo=str(motivo or "")[:2000],
            referencia_bases=referencia_bases,
            archivo_fuente=archivo_fuente,
            pagina=str(pagina) if pagina not in (None, "") else None,
            source=source,
            source_ref=source_ref,
            provenance_ui=prov,
        )
    )


def _analysis_has_placeholder_only_extracts(analysis: Dict[str, Any]) -> bool:
    """True si el analista dejó gaps/preguntas sin texto literal utilizable."""
    audit = analysis.get("audit_report") if isinstance(analysis.get("audit_report"), dict) else {}
    for raw in audit.get("preguntas_junta_aclaraciones") or []:
        if _is_low_quality_question(str(raw or "")):
            return True
    for gap in audit.get("gap_analysis") or []:
        if not isinstance(gap, dict):
            continue
        if _is_low_quality_question(str(gap.get("requisito") or "")):
            return True
        if _is_low_quality_question(str(gap.get("evidence_snippet") or "")):
            return True
    for alert in audit.get("alertas_descalificacion") or []:
        if not isinstance(alert, dict):
            continue
        if _is_low_quality_question(str(alert.get("motivo") or "")):
            return True
        if _is_low_quality_question(str(alert.get("sugerencia") or "")):
            return True
    reqs = analysis.get("requisitos_participacion") or []
    if reqs and all(
        _is_low_quality_question(str(r.get("texto_literal") or r.get("texto") or ""))
        for r in reqs
        if isinstance(r, dict)
    ):
        return True
    return False


def _collect_analyst_pending_citation_umbrella(
    analysis: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> None:
    """
    Una pregunta agregada cuando el analista marcó temas para junta pero sin citas estructuradas.
    Sustituye placeholders («punto X», «...») sin reintroducir basura en el listado.
    """
    if not _analysis_has_placeholder_only_extracts(analysis):
        return
    pregunta = _build_junta_single_question(
        {
            "seccion": "ANÁLISIS DE BASES Y DOCUMENTOS DE LA CONVOCATORIA",
            "texto": (
                "el análisis detectó temas para la junta de aclaraciones, pero no consolidó "
                "requisitos con cláusula, página, apartado y texto literal verificable"
            ),
        },
        (
            "el análisis detectó temas para la junta de aclaraciones, pero no consolidó "
            "requisitos con cláusula, página, apartado y texto literal verificable"
        ),
        "los requisitos que deben aclararse en la junta",
        contexto=(
            "solicitamos que la convocante indique, para cada tema pendiente, "
            "la ubicación exacta en las bases y el criterio oficial de evaluación"
        ),
    )
    _append_item(
        items,
        seen,
        pregunta=pregunta,
        motivo="El analista generó preguntas o brechas sin citas estructuradas (placeholders).",
        source=JuntaQuestionSource.ANALYST_JUNTA,
        source_ref="analyst_pending_citation_umbrella",
        tipo=JuntaQuestionTipo.TECNICA,
        prioridad=JuntaQuestionPrioridad.ALTA,
        provenance_ui={
            "source": "analyst",
            "pattern": "analyst_pending_citation",
            "citation_quality": CITATION_QUALITY_INSUFFICIENT,
            "audience": "interno",
        },
        preserve_status=JuntaQuestionStatus.EXCLUIDA,
    )


def _resolve_bases_corpus(
    session_id: str,
    session_state: Dict[str, Any],
    documents: Optional[Sequence[Dict[str, Any]]] = None,
):
    from app.services.junta_bases_corpus import build_bases_corpus

    docs = list(documents or session_state.get("_junta_session_documents") or [])
    return build_bases_corpus(session_id, docs, session_state=session_state)


def _collect_from_analyst(
    analysis: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
    *,
    corpus: Optional[Any] = None,
) -> None:
    from app.services.junta_citation_gate import (
        alert_item_supported,
        analyst_question_supported,
        gap_item_supported,
    )

    audit = analysis.get("audit_report") if isinstance(analysis.get("audit_report"), dict) else {}
    for idx, raw in enumerate(audit.get("preguntas_junta_aclaraciones") or [], start=1):
        p = str(raw or "").strip()
        if not p or _is_low_quality_question(p):
            continue
        if corpus is not None and not analyst_question_supported(p, corpus, analysis):
            logger.info("junta_analyst_question_filtered", reason="citation_gate", idx=idx)
            continue
        if _already_junta_canonical(p):
            pregunta = p if p.endswith("?") else f"{p}?"
            pl = p.lower()
            pattern = "explicit_conflict"
            if "más adelante" in pl or "sin embargo" in pl:
                pattern = "dual_bases_citation"
            prov = {
                "source": "analyst",
                "reason": "preguntas_junta_aclaraciones",
                "pattern": pattern,
            }
        else:
            pregunta = _build_junta_from_free_text(p, tema="este requisito de las bases")
            prov = {"source": "analyst", "reason": "preguntas_junta_aclaraciones"}
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo="Sugerencia estratégica del análisis de bases para la junta.",
            source=JuntaQuestionSource.ANALYST_JUNTA,
            source_ref=f"audit_report.preguntas_junta_aclaraciones[{idx}]",
            prioridad=JuntaQuestionPrioridad.ALTA,
            provenance_ui=prov,
        )

    for idx, gap in enumerate(audit.get("gap_analysis") or [], start=1):
        if not isinstance(gap, dict):
            continue
        if corpus is not None and not gap_item_supported(gap, corpus):
            logger.info("junta_gap_filtered", reason="citation_gate", idx=idx)
            continue
        sugerencia = str(gap.get("sugerencia") or gap.get("accion_requerida") or "").strip()
        req = str(gap.get("requisito") or "").strip()
        if not sugerencia and not req:
            continue
        if _is_low_quality_question(req) and _is_low_quality_question(sugerencia):
            continue
        if str(gap.get("estado_empresa") or "").upper() not in ("FALTANTE", "VENCIDO", "AMBIGUO"):
            if not sugerencia:
                continue
        pag = str(gap.get("pagina") or "")
        archivo = str(gap.get("archivo_fuente") or "")
        seccion = str(gap.get("seccion") or "REQUISITOS DEL PARTICIPANTE")
        inciso = gap.get("inciso")
        evid = str(gap.get("evidence_snippet") or "").strip()
        if _ANALYST_SNIPPET_PLACEHOLDER_RE.search(evid):
            evid = ""
        if _ANALYST_SNIPPET_PLACEHOLDER_RE.search(req):
            req = ""
        if not req and not evid and not sugerencia:
            continue
        tema = _truncate_literal(req or evid or "este requisito", 80)
        cita_a = {
            "archivo": archivo or None,
            "pagina": pag or None,
            "seccion": seccion,
            "inciso": inciso,
            "texto": req or evid,
        }
        if req and evid and _norm_key(req) != _norm_key(evid):
            cita_b = {**cita_a, "texto": evid, "seccion": seccion or "evidencia en bases"}
            pregunta = _build_junta_dual_question(
                cita_a,
                req,
                cita_b,
                evid,
                tema=tema,
            )
        elif sugerencia and "?" in sugerencia:
            pregunta = _build_junta_from_free_text(
                sugerencia,
                cita=cita_a if (pag or archivo) else None,
                tema=tema,
            )
        elif req or evid:
            pregunta = _build_junta_single_question(
                cita_a,
                req or evid,
                tema,
                contexto=sugerencia if sugerencia else "",
            )
        else:
            pregunta = _build_junta_from_free_text(sugerencia, tema=tema)
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo=f"Brecha detectada en análisis: {req[:200]}",
            source=JuntaQuestionSource.ANALYST_GAP,
            source_ref=f"gap_analysis[{idx}]",
            prioridad=_prioridad_from_gravedad(str(gap.get("gravedad") or "ALTA")),
            referencia_bases=req,
            archivo_fuente=str(gap.get("archivo_fuente") or "") or None,
            pagina=str(gap.get("pagina") or "") or None,
            provenance_ui={"source": "analyst", "reason": "gap_analysis"},
        )

    for idx, alert in enumerate(audit.get("alertas_descalificacion") or [], start=1):
        if not isinstance(alert, dict):
            continue
        if corpus is not None and not alert_item_supported(alert, corpus):
            logger.info("junta_alert_filtered", reason="citation_gate", idx=idx)
            continue
        sug = str(alert.get("sugerencia") or "").strip()
        motivo = str(alert.get("motivo") or "").strip()
        if not sug and not motivo:
            continue
        if _is_low_quality_question(sug) and _is_low_quality_question(motivo):
            continue
        cita = {
            "pagina": alert.get("pagina"),
            "seccion": alert.get("seccion") or "REQUISITOS DE PARTICIPACIÓN",
            "archivo": alert.get("archivo_fuente"),
            "inciso": alert.get("inciso"),
            "texto": motivo or sug,
        }
        raw = sug or (
            f"¿La convocante confirma el alcance y mitigación del siguiente riesgo de descalificación: "
            f"{motivo[:180]}?"
        )
        pregunta = _build_junta_from_free_text(
            raw,
            cita=cita if any(cita.get(k) for k in ("pagina", "archivo", "seccion", "texto")) else None,
            tema="un riesgo de descalificación señalado en las bases",
        )
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo=motivo or "Alerta de descalificación en análisis.",
            source=JuntaQuestionSource.ANALYST_ALERT,
            source_ref=f"alertas_descalificacion[{idx}]",
            prioridad=_prioridad_from_gravedad(str(alert.get("gravedad") or "ALTA")),
            pagina=str(alert.get("pagina") or "") or None,
            provenance_ui={"source": "analyst", "reason": "alertas_descalificacion"},
        )


def _collect_from_evidence_conflicts(
    session_state: Dict[str, Any],
    analysis: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> None:
    master = session_state.get("master_profile") or session_state.get("effective_profile") or {}
    if not isinstance(master, dict):
        master = {}
    evidence = session_state.get("evidence_profile") or {}
    overrides = session_state.get("evidence_profile_overrides") or {}
    conflicts = detect_profile_conflicts(
        master_profile=master,
        evidence_profile=evidence if isinstance(evidence, dict) else {},
        evidence_profile_overrides=overrides if isinstance(overrides, dict) else {},
    )
    for idx, c in enumerate(conflicts, start=1):
        field = str(c.get("field") or "")
        pregunta, archivo, pagina, prov = _build_evidence_conflict_question(
            c, session_state, analysis
        )
        prov_full = {
            "source": "evidence_profile_bridge",
            "master_value": c.get("master_value"),
            "evidence_value": c.get("evidence_value"),
            "error_type": "CONFLICTING_EVIDENCE",
            **prov,
        }
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo=(
                f"Valores distintos para {field}: expediente/perfil «{c.get('master_value')}» "
                f"vs. documento «{c.get('source_doc')}»: «{c.get('evidence_value')}». "
                "Riesgo de interpretación divergente en evaluación."
            ),
            source=JuntaQuestionSource.EVIDENCE_CONFLICT,
            source_ref=field or f"conflict_{idx}",
            tipo=JuntaQuestionTipo.LEGAL if field in ("rfc", "representante_legal") else JuntaQuestionTipo.TECNICA,
            prioridad=JuntaQuestionPrioridad.ALTA,
            archivo_fuente=archivo,
            pagina=pagina,
            provenance_ui=prov_full,
        )

    handled = {str(c.get("field") or "") for c in conflicts}
    _collect_evidence_vs_bases_fields(
        session_state, analysis, items, seen, skip_fields=handled
    )


def _field_values_appear_distinct(field: str, bases_text: str, doc_val: Any) -> bool:
    """Heurística: ¿el valor documental parece divergir del fragmento en bases?"""
    bt = str(bases_text or "").strip()
    dv = str(doc_val or "").strip()
    if not bt or not dv:
        return False
    if field == "anos_experiencia":
        yb = _extract_years_from_text(bt)
        yd = _extract_years_from_text(dv) or dv
        return bool(yb and str(yb) != str(yd))
    nb = _norm_key(bt)
    nd = _norm_key(dv)
    if nd in nb or nb in nd:
        return False
    return nb != nd


def _append_document_fallback_question(
    field: str,
    label: str,
    entry: Dict[str, Any],
    doc_val: Any,
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> bool:
    """Pregunta canónica cuando solo hay evidencia documental (sin cita estructurada en bases)."""
    doc_name = str(entry.get("source_doc") or "").strip()
    texto_doc = _truncate_literal(entry.get("snippet") or "", 200)
    if len(texto_doc) < 20:
        texto_doc = (
            f"en el requisito de {label}, el documento consigna «{_truncate_literal(str(doc_val), 120)}»"
        )
    if not doc_name or _is_low_quality_question(texto_doc):
        return False
    doc_cita = _cita_from_evidence_entry(entry, doc_name)
    pregunta = _build_junta_single_question(
        doc_cita,
        texto_doc,
        label,
        contexto=(
            "no se dispone en el análisis de un fragmento citado de las bases con cláusula y página; "
            "solicitamos confirmar cómo armoniza este documento con el requisito general de la convocatoria"
        ),
    )
    _append_item(
        items,
        seen,
        pregunta=pregunta,
        motivo=(
            f"Evidencia en «{doc_name}» para {label} sin cita estructurada en bases; requiere aclaración."
        ),
        source=JuntaQuestionSource.EVIDENCE_CONFLICT,
        source_ref=f"{field}_documento_sin_cita_bases",
        tipo=JuntaQuestionTipo.LEGAL if field in ("rfc", "representante_legal") else JuntaQuestionTipo.TECNICA,
        prioridad=JuntaQuestionPrioridad.ALTA,
        archivo_fuente=doc_name,
        pagina=str(entry.get("page") or entry.get("pagina") or "") or None,
        provenance_ui={
            "source": "evidence_profile_bridge",
            "pattern": "documento_sin_cita_bases",
            "field": field,
        },
    )
    return True


def _collect_evidence_vs_bases_fields(
    session_state: Dict[str, Any],
    analysis: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
    *,
    skip_fields: set,
) -> None:
    """
    Sin perfil maestro: contrasta evidencia documental con requisitos en bases (formato canónico).
    """
    for field in _CRITICAL_FIELDS:
        if field in skip_fields:
            continue
        label = _FIELD_LABELS.get(field, field.replace("_", " "))
        entry = _evidence_field_entry(session_state, field)
        doc_val = entry.get("value")
        if doc_val in (None, "", []):
            continue

        citations = _search_bases_citations(analysis, session_state, field)

        if field == "anos_experiencia":
            anos_added = False
            dual = _dual_bases_experience_refs(citations)
            if dual:
                (ya, ca), (yb, cb) = dual
                pregunta = _build_experience_dual_question(ca, ya, cb, yb)
                _append_item(
                    items,
                    seen,
                    pregunta=pregunta,
                    motivo=(
                        f"Inconsistencia en bases: un apartado exige {ya} año(s) de experiencia y otro "
                        f"{yb} año(s); el licitante no puede saber a cuál apegarse."
                    ),
                    source=JuntaQuestionSource.EVIDENCE_CONFLICT,
                    source_ref="anos_experiencia_dual_bases",
                    tipo=JuntaQuestionTipo.TECNICA,
                    prioridad=JuntaQuestionPrioridad.ALTA,
                    archivo_fuente=str(ca.get("archivo") or cb.get("archivo") or ""),
                    pagina=str(ca.get("pagina") or ""),
                    provenance_ui={
                        "source": "evidence_profile_bridge",
                        "pattern": "dual_bases_only",
                        "bases_years_a": ya,
                        "bases_years_b": yb,
                    },
                )
                anos_added = True

            if not anos_added:
                doc_years = _extract_years_from_text(str(doc_val)) or str(doc_val)
                snippet = _truncate_literal(entry.get("snippet") or "", 200)
                doc_name = str(entry.get("source_doc") or "documento de la convocatoria").strip()
                doc_pag = entry.get("page") or entry.get("pagina")
                for cita in citations:
                    yb = _extract_years_from_text(cita.get("texto") or "")
                    if yb and str(yb) != str(doc_years):
                        pregunta = _build_experience_dual_question(
                            cita,
                            yb,
                            {
                                "texto": snippet or f"al menos {doc_years} años en servicios similares",
                                "pagina": doc_pag,
                                "archivo": doc_name,
                                "seccion": "CV empresarial o documento anexo",
                            },
                            doc_years,
                        )
                        _append_item(
                            items,
                            seen,
                            pregunta=pregunta,
                            motivo=(
                                f"Divergencia: bases indican {yb} año(s) y «{doc_name}» indica {doc_val}."
                            ),
                            source=JuntaQuestionSource.EVIDENCE_CONFLICT,
                            source_ref="anos_experiencia_bases_vs_doc",
                            tipo=JuntaQuestionTipo.TECNICA,
                            prioridad=JuntaQuestionPrioridad.ALTA,
                            archivo_fuente=doc_name,
                            pagina=str(doc_pag or cita.get("pagina") or ""),
                            provenance_ui={
                                "source": "evidence_profile_bridge",
                                "pattern": "bases_vs_anexo",
                                "bases_years": yb,
                                "document_years": doc_years,
                            },
                        )
                        anos_added = True
                        break
            if not anos_added:
                _append_document_fallback_question(
                    field, label, entry, doc_val, items, seen
                )
            continue

        dual = _dual_bases_distinct_refs(citations)
        if dual:
            (ta, ca), (tb, cb) = dual
            pregunta = _build_junta_dual_question(ca, ta, cb, tb, tema=label)
            _append_item(
                items,
                seen,
                pregunta=pregunta,
                motivo=f"Dos redacciones distintas en bases para {label}.",
                source=JuntaQuestionSource.EVIDENCE_CONFLICT,
                source_ref=f"{field}_dual_bases",
                tipo=JuntaQuestionTipo.LEGAL if field in ("rfc", "representante_legal") else JuntaQuestionTipo.TECNICA,
                prioridad=JuntaQuestionPrioridad.ALTA,
                archivo_fuente=str(ca.get("archivo") or cb.get("archivo") or ""),
                pagina=str(ca.get("pagina") or ""),
                provenance_ui={"source": "evidence_profile_bridge", "pattern": "dual_bases_only", "field": field},
            )
            continue

        if citations:
            cita = citations[0]
            texto_bases = str(cita.get("texto") or "")
            if _field_values_appear_distinct(field, texto_bases, doc_val):
                pseudo = {
                    "field": field,
                    "master_value": texto_bases[:120],
                    "evidence_value": doc_val,
                    "source_doc": entry.get("source_doc"),
                }
                pregunta, archivo, pagina, prov = _build_evidence_conflict_question(
                    pseudo, session_state, analysis
                )
                _append_item(
                    items,
                    seen,
                    pregunta=pregunta,
                    motivo=(
                        f"Divergencia entre bases y «{entry.get('source_doc')}» para {label}: "
                        f"«{texto_bases[:80]}…» frente a «{doc_val}»."
                    ),
                    source=JuntaQuestionSource.EVIDENCE_CONFLICT,
                    source_ref=f"{field}_bases_vs_doc",
                    tipo=JuntaQuestionTipo.LEGAL
                    if field in ("rfc", "representante_legal")
                    else JuntaQuestionTipo.TECNICA,
                    prioridad=JuntaQuestionPrioridad.ALTA,
                    archivo_fuente=archivo,
                    pagina=pagina,
                    provenance_ui={"source": "evidence_profile_bridge", **prov},
                )
                continue

        _append_document_fallback_question(field, label, entry, doc_val, items, seen)


def _collect_from_mini_dictamen(
    session_state: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> None:
    tickets = list(session_state.get("clarification_tickets") or [])
    mini = session_state.get("mini_dictamen_anexos") or {}
    if not tickets and isinstance(mini, dict):
        tickets = list(mini.get("clarification_tickets") or [])
    active: List[Dict[str, Any]] = []
    for raw in tickets:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").lower()
        if status not in ("open", "ready_for_junta"):
            continue
        active.append(raw)

    from app.services.clarification_ticket_copy import (
        build_junta_question_from_clarification_ticket,
        build_junta_question_grouped_missing_templates,
    )

    not_published = [
        t
        for t in active
        if str(t.get("reason") or "") == "required_annex_not_published"
    ]
    other = [t for t in active if t not in not_published]

    if len(not_published) >= 3:
        names = [str(t.get("display_name") or "") for t in not_published]
        pregunta = build_junta_question_grouped_missing_templates(names)
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo="Agrupación de formatos citados en bases sin archivo suelto en expediente.",
            source=JuntaQuestionSource.MINI_DICTAMEN,
            source_ref="grouped_required_annex_not_published",
            tipo=JuntaQuestionTipo.ADMINISTRATIVA,
            prioridad=JuntaQuestionPrioridad.ALTA,
            provenance_ui={
                "source": "mini_dictamen_anexos",
                "pattern": "grouped_missing_templates",
                "ticket_count": len(not_published),
            },
        )
    else:
        for raw in not_published:
            other.append(raw)

    for raw in other:
        display = str(raw.get("display_name") or "anexo").strip()
        pregunta = build_junta_question_from_clarification_ticket(raw)
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo=str(raw.get("reason") or "clarification_required"),
            source=JuntaQuestionSource.MINI_DICTAMEN,
            source_ref=str(raw.get("ticket_id") or ""),
            tipo=JuntaQuestionTipo.ADMINISTRATIVA,
            prioridad=(
                JuntaQuestionPrioridad.ALTA
                if str(raw.get("priority") or "").lower() == "blocking"
                else JuntaQuestionPrioridad.MEDIA
            ),
            archivo_fuente=str(raw.get("source_filename") or "") or None,
            provenance_ui=raw.get("provenance_ui") if isinstance(raw.get("provenance_ui"), dict) else {},
        )


def _collect_from_thematic_discovery(
    corpus: Any,
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> None:
    from app.services.junta_thematic_discovery import discover_thematic_questions

    for raw in discover_thematic_questions(corpus):
        pregunta = str(raw.get("pregunta") or "").strip()
        if not pregunta:
            continue
        prov = raw.get("provenance_ui") if isinstance(raw.get("provenance_ui"), dict) else {}
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo=str(raw.get("motivo") or "thematic_bases"),
            source=JuntaQuestionSource.THEMATIC_BASES,
            source_ref=str(raw.get("source_ref") or "thematic"),
            tipo=raw.get("tipo") or JuntaQuestionTipo.TECNICA,
            prioridad=raw.get("prioridad") or JuntaQuestionPrioridad.ALTA,
            provenance_ui=prov,
        )


def _collect_from_go_no_go(
    session_state: Dict[str, Any],
    items: List[JuntaAclaracionesQuestionItem],
    seen: set,
) -> None:
    gng = session_state.get("go_no_go_result") or {}
    if not isinstance(gng, dict):
        return
    for idx, b in enumerate(gng.get("brechas") or [], start=1):
        if not isinstance(b, dict):
            continue
        desc = str(b.get("descripcion") or b.get("brecha") or "").strip()
        if not desc:
            continue
        if not (b.get("is_knockout") or b.get("knockout")):
            continue
        cita = {
            "seccion": "VIABILIDAD DE PARTICIPACIÓN",
            "texto": desc[:220],
        }
        pregunta = _build_junta_single_question(
            cita,
            desc[:220],
            "la elegibilidad para participar en el procedimiento",
            contexto=(
                "el análisis de viabilidad identificó una brecha bloqueante; solicitamos confirmar "
                "si puede subsanarse en junta de aclaraciones o constituye requisito estricto "
                "de elegibilidad"
            ),
        )
        _append_item(
            items,
            seen,
            pregunta=pregunta,
            motivo="Brecha bloqueante del semáforo Go/No-Go.",
            source=JuntaQuestionSource.GO_NO_GO,
            source_ref=f"brecha_{idx}",
            prioridad=JuntaQuestionPrioridad.ALTA,
            provenance_ui={"source": "go_no_go", "reason": "knockout_brecha"},
        )


def _merge_preserved_status(
    new_items: List[JuntaAclaracionesQuestionItem],
    previous: Optional[Dict[str, Any]],
) -> List[JuntaAclaracionesQuestionItem]:
    if not previous or not isinstance(previous.get("items"), list):
        return new_items
    by_id = {
        str(it.get("question_id") or ""): it
        for it in previous.get("items") or []
        if isinstance(it, dict) and it.get("question_id")
    }
    out: List[JuntaAclaracionesQuestionItem] = []
    for item in new_items:
        prev = by_id.get(item.question_id)
        if prev and str(prev.get("status") or "") in (
            JuntaQuestionStatus.APROBADA.value,
            JuntaQuestionStatus.ENVIADA.value,
            JuntaQuestionStatus.EXCLUIDA.value,
        ):
            try:
                item = item.model_copy(
                    update={"status": JuntaQuestionStatus(str(prev.get("status")))}
                )
            except ValueError:
                pass
        prov = dict(item.provenance_ui or {})
        if not prov.get("citation_quality"):
            prov["citation_quality"] = resolve_citation_quality(
                pregunta=item.pregunta,
                pattern=str(prov.get("pattern") or "") or None,
                pagina=item.pagina,
                source=item.source.value,
                provenance_ui=prov,
            )
            item = item.model_copy(update={"provenance_ui": prov})
        out.append(item)
    return out


def _build_summary(items: List[JuntaAclaracionesQuestionItem]) -> JuntaAclaracionesQuestionsSummary:
    por_tipo: Dict[str, int] = {}
    por_prioridad: Dict[str, int] = {}
    por_fuente: Dict[str, int] = {}
    listas = 0
    convocante = 0
    for it in items:
        por_tipo[it.tipo.value] = por_tipo.get(it.tipo.value, 0) + 1
        por_prioridad[it.prioridad.value] = por_prioridad.get(it.prioridad.value, 0) + 1
        por_fuente[it.source.value] = por_fuente.get(it.source.value, 0) + 1
        if it.status in (JuntaQuestionStatus.APROBADA, JuntaQuestionStatus.BORRADOR):
            listas += 1
        if it.status != JuntaQuestionStatus.EXCLUIDA and not is_internal_junta_item(it):
            convocante += 1
    return JuntaAclaracionesQuestionsSummary(
        total=len(items),
        por_tipo=por_tipo,
        por_prioridad=por_prioridad,
        por_fuente=por_fuente,
        listas_para_junta=listas,
        para_convocante=convocante,
    )


def build_junta_aclaraciones_questions(
    session_id: str,
    session_state: Dict[str, Any],
    *,
    documents: Optional[Sequence[Dict[str, Any]]] = None,
) -> JuntaAclaracionesQuestionsBundle:
    """
    Arma el listado consolidado para la convocante (sin persistir).
    """
    items: List[JuntaAclaracionesQuestionItem] = []
    seen: set = set()
    analysis = _extract_analysis_from_session(session_state)
    corpus = _resolve_bases_corpus(session_id, session_state, documents)

    _collect_from_thematic_discovery(corpus, items, seen)
    _collect_from_analyst(analysis, items, seen, corpus=corpus)
    _collect_from_evidence_conflicts(session_state, analysis, items, seen)
    _collect_from_mini_dictamen(session_state, items, seen)
    _collect_from_go_no_go(session_state, items, seen)
    _collect_analyst_pending_citation_umbrella(analysis, items, seen)

    items.sort(
        key=lambda x: (
            0 if x.prioridad == JuntaQuestionPrioridad.ALTA else 1 if x.prioridad == JuntaQuestionPrioridad.MEDIA else 2,
            x.tipo.value,
            x.pregunta.lower(),
        )
    )
    previous = session_state.get("junta_aclaraciones_questions")
    items = _merge_preserved_status(items, previous if isinstance(previous, dict) else None)

    return JuntaAclaracionesQuestionsBundle(
        schema_version=_SCHEMA_VERSION,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        summary=_build_summary(items),
        items=items,
    )


def format_junta_questions_plain_text(bundle: JuntaAclaracionesQuestionsBundle) -> str:
    """Texto listo para copiar al portal de la junta o a un Word."""
    lines = [
        "LISTADO DE PREGUNTAS PARA LA JUNTA DE ACLARACIONES",
        f"Sesión: {bundle.session_id}",
        f"Generado: {bundle.generated_at.isoformat()}",
        "",
    ]
    active = [
        it
        for it in bundle.items
        if it.status not in (JuntaQuestionStatus.EXCLUIDA,)
        and not is_internal_junta_item(it)
    ]
    for i, it in enumerate(active, start=1):
        lines.append(f"{i}. [{it.tipo.value.upper()}] {it.pregunta}")
        if it.archivo_fuente:
            lines.append(f"   Referencia: {it.archivo_fuente}")
        if it.motivo:
            lines.append(f"   Motivo interno: {it.motivo[:300]}")
        lines.append("")
    return "\n".join(lines).strip()


async def build_and_persist_junta_aclaraciones_questions(
    memory: Any,
    session_id: str,
    *,
    session_state: Optional[Dict[str, Any]] = None,
    company_id: Optional[str] = None,
    force_refresh: bool = False,
) -> JuntaAclaracionesQuestionsBundle:
    """Calcula y persiste el bundle en la sesión (mini dictamen + junta alineados)."""
    raw = session_state if isinstance(session_state, dict) else await memory.get_session(session_id)
    if not raw:
        raise ValueError("Sesión no encontrada.")
    state = await _enrich_session_for_junta(memory, session_id, raw, company_id=company_id)
    try:
        documents = await memory.get_documents(session_id)
    except Exception:
        documents = []
    state["_junta_session_documents"] = documents

    stored = state.get("junta_aclaraciones_questions")
    need_junta = force_refresh or bundle_needs_regeneration(
        stored if isinstance(stored, dict) else None,
        session_state=state,
    )
    need_mini = force_refresh or mini_dictamen_needs_co_refresh(session_id, state, documents)

    if need_mini:
        from app.services.mini_dictamen_anexos_service import build_and_persist_mini_dictamen

        await build_and_persist_mini_dictamen(memory, session_id)
        state = await memory.get_session(session_id) or state
        state = await _enrich_session_for_junta(memory, session_id, state, company_id=company_id)
        state["_junta_session_documents"] = documents
        need_junta = True

    if need_junta:
        bundle = build_junta_aclaraciones_questions(session_id, state, documents=documents)
        await memory.save_session(
            session_id,
            {
                **state,
                "junta_aclaraciones_questions": bundle.model_dump(mode="json"),
            },
        )
        logger.info(
            "junta_aclaraciones_questions_persisted",
            session_id=session_id,
            total=bundle.summary.total,
            listas=bundle.summary.listas_para_junta,
            para_convocante=getattr(bundle.summary, "para_convocante", 0),
        )
        return bundle

    if isinstance(stored, dict):
        return JuntaAclaracionesQuestionsBundle.model_validate(stored)
    bundle = build_junta_aclaraciones_questions(session_id, state, documents=documents)
    await memory.save_session(
        session_id,
        {**state, "junta_aclaraciones_questions": bundle.model_dump(mode="json")},
    )
    return bundle


async def update_junta_question_status(
    memory: Any,
    session_id: str,
    question_id: str,
    *,
    status: str,
) -> JuntaAclaracionesQuestionItem:
    """HITL: aprueba, excluye o marca enviada una pregunta."""
    allowed = {s.value for s in JuntaQuestionStatus}
    st = str(status or "").strip().lower()
    if st not in allowed:
        raise ValueError(f"Estado inválido: {status}")
    state = await memory.get_session(session_id) or {}
    raw = state.get("junta_aclaraciones_questions")
    if not isinstance(raw, dict):
        raise ValueError("No hay listado de junta en la sesión. Ejecuta refresh primero.")
    items = list(raw.get("items") or [])
    matched = False
    updated: Optional[Dict[str, Any]] = None
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("question_id") or "") != question_id:
            continue
        it["status"] = st
        updated = it
        matched = True
        break
    if not matched:
        raise ValueError(f"No existe question_id={question_id}")
    raw["items"] = items
    raw["generated_at"] = datetime.now(timezone.utc).isoformat()
    await memory.save_session(session_id, {**state, "junta_aclaraciones_questions": raw})
    return JuntaAclaracionesQuestionItem.model_validate(updated)
