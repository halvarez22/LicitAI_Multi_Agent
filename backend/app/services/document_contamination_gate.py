"""
Detección universal de contaminación semántica en documentos generados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.config.settings import settings

_APU_FILENAME_RE = re.compile(r"(?i)precios[_\s]?unitarios|analisis[_\s]?precios|apu\b")


@dataclass
class ContaminationHit:
    error_type: str
    field_key: str
    detected_value: str
    expected_rule: str

    def as_fill_issue_dict(self, *, document_id: str, severity: str, provenance: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "error_type": self.error_type,
            "severity": severity,
            "document_id": document_id,
            "field_key": self.field_key,
            "detected_value": self.detected_value[:240],
            "expected_rule": self.expected_rule,
            "provenance": provenance,
        }


def _severity(base: str) -> str:
    mode = str(getattr(settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit") or "audit").lower()
    if mode != "enforce":
        return "warn"
    return base


def is_apu_document(*text_parts: str) -> bool:
    blob = " ".join(str(p or "") for p in text_parts).lower()
    return bool(
        re.search(r"an[aá]lisis\s+de\s+precios|precios\s+unitarios|\bapu\b", blob)
    )


_LLM_REFUSAL_RE = re.compile(
    r"(?i)(lo\s+siento|no\s+puedo\s+generar|como\s+asistente\s+de\s+ia|"
    r"no\s+estoy\s+autorizado\s+a\s+generar|en\s+qu[eé]\s+puedo\s+ayudarte)"
)

_ADJUDICATION_RE = re.compile(
    r"(?i)(hemos\s+sido\s+seleccionados|como\s+proveedores|proveedor\s+adjudicado|"
    r"ya\s+fueron\s+seleccionados|proveedor\s+seleccionado)"
)

_ADJUDICATION_WHITELIST_RE = re.compile(
    r"(?i)en\s+caso\s+de\s+resultar\s+adjudicad"
)

_EVALUATOR_RE = re.compile(
    r"(?i)(criterios\s+de\s+evaluaci[oó]n|objetivo\s+evaluar\s+la\s+propuesta|"
    r"el\s+comit[eé]\s+evaluar[aá]|dictamen\s+del\s+comit[eé]|"
    r"el\s+presente\s+an[aá]lisis\s+ha\s+sido\s+realizado|"
    r"evaluar\s+la\s+propuesta\s+econ[oó]mica\s+presentada)"
)

_META_LEAK_RE = re.compile(
    r"(?i)(transcripci[oó]n\s+fiel|nota:\s*el\s+contenido\s+anterior|"
    r"rellenando\s+solo\s+los\s+datos\s+espec[ií]ficos\s+de\s+la\s+empresa|"
    r"omitiendo\s+secciones\s+que\s+no\s+eran\s+relevantes)"
)

_ANTI_PLACEHOLDER_RULE_LEAK_RE = re.compile(
    r"(?is)\(?(?:texto\s+estricto\)\s*)?"
    r"regla\s+.+?"
    r"si\s+no\s+tienes\s+un\s+dato\s+real\s+verificado.+?"
    r"(?:placeholders\s+entre\s+corchetes|sin\s+huecos)\.?"
)

_TRUNCATION_RE = re.compile(
    r"(?i)(que\s+no\s+se…|que\s+no\s+se\.\.\.|antes\s+de\s+l\.|"
    r"manifestando\s+bajo\s+protesta\s+de\s+decir\s+verdad\s+que\s+no\s+se[^\w]{0,3}$)"
)

_CHECKLIST_META_RE = re.compile(
    r"(?i)a\s+continuaci[oó]n,?\s+se\s+presentan\s+los\s+documentos\s+requeridos"
)

_GENERIC_FALLBACK_RE = re.compile(
    r"(?i)cambio\s+material,?\s+informar[eé]\s+de\s+inmediato\s+a\s+la\s+convocante"
)

_CONTRACT_IN_PROPOSAL_RE = re.compile(
    r"(?i)contrato\s+que\s+se\s+deriva|contrato\s+derivado\s+de"
)

_DATE_ES_BODY_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b",
    re.I,
)

_EMPTY_PRICE_CELL_RE = re.compile(r"(?i)\|\s*\$\s*\|\s*\$|\$\s*\|\s*\$|precio\s+unitario\s+propuesto\s*\|\s*\$")

# Anexos obra con texto íntegro del pliego (T-3 contrato, T-4 bases): criterios de evaluación son norma, no contaminación.
_PLIEGO_FULL_REPRO_DEDUPE = frozenset({"obra|T3", "obra|T4"})


def is_pliego_full_reproduction_annex(basename: str = "", dedupe_key: str = "") -> bool:
    """True si el entregable reproduce clausulado/bases del pliego (no carta del concursante)."""
    if dedupe_key:
        return dedupe_key in _PLIEGO_FULL_REPRO_DEDUPE
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    return pliego_format_dedupe_key(basename) in _PLIEGO_FULL_REPRO_DEDUPE


def strip_llm_meta_leaks(text: str) -> str:
    """Elimina párrafos y fragmentos de meta-instrucción del LLM antes de materializar."""
    if not text:
        return text
    cleaned = _ANTI_PLACEHOLDER_RULE_LEAK_RE.sub("", text)
    lines = []
    for line in cleaned.split("\n"):
        if _META_LEAK_RE.search(line):
            continue
        if re.search(r"(?i)^---\s*nota:", line.strip()):
            continue
        lines.append(line)
    out = "\n".join(lines).strip()
    return re.sub(r"[ \t]{2,}", " ", out)


def scan_text_contamination(
    text: str,
    *,
    basename: str = "",
    stage: str = "",
    dedupe_key: str = "",
) -> List[ContaminationHit]:
    """Escanea texto completo del documento."""
    if not text or not str(text).strip():
        return []
    blob = str(text)
    low = blob.lower()
    hits: List[ContaminationHit] = []
    pliego_repro = is_pliego_full_reproduction_annex(basename, dedupe_key)

    m = _LLM_REFUSAL_RE.search(blob)
    if m:
        hits.append(
            ContaminationHit(
                "llm_refusal_detected",
                "content",
                m.group(0),
                "no_llm_refusal_in_deliverable",
            )
        )

    if _META_LEAK_RE.search(blob):
        hits.append(
            ContaminationHit(
                "llm_meta_leak_detected",
                "content",
                _META_LEAK_RE.search(blob).group(0)[:120],
                "no_prompt_meta_in_deliverable",
            )
        )

    if _ADJUDICATION_RE.search(blob) and not _ADJUDICATION_WHITELIST_RE.search(blob):
        m = _ADJUDICATION_RE.search(blob)
        if m:
            hits.append(
                ContaminationHit(
                    "adjudication_language_in_proposal_stage",
                    "content",
                    m.group(0),
                    "concursante_stage_lexicon",
                )
            )

    is_apu = bool(_APU_FILENAME_RE.search(basename)) or is_apu_document(basename, blob[:500])
    if not pliego_repro and (
        _EVALUATOR_RE.search(blob)
        or (is_apu and re.search(r"(?i)evaluar\s+la\s+propuesta", blob))
    ):
        m = _EVALUATOR_RE.search(blob) or re.search(r"(?i)evaluar\s+la\s+propuesta", blob)
        if m:
            hits.append(
                ContaminationHit(
                    "evaluator_perspective_detected",
                    "content",
                    m.group(0),
                    "bidder_perspective_only",
                )
            )

    if is_apu and _EMPTY_PRICE_CELL_RE.search(blob):
        hits.append(
            ContaminationHit(
                "apu_empty_prices",
                "economic_totals",
                "celdas de precio vacías",
                "apu_requires_materialized_amounts",
            )
        )

    if is_apu and stage in ("formats", "economic", "economic_writer"):
        if re.search(r"(?i)criterios\s+de\s+evaluaci[oó]n\s+econ[oó]mica", blob):
            hits.append(
                ContaminationHit(
                    "evaluator_perspective_detected",
                    "content",
                    "Criterios de Evaluación Económica",
                    "apu_must_not_include_evaluation_criteria",
                )
            )

    if _TRUNCATION_RE.search(blob):
        m = _TRUNCATION_RE.search(blob)
        hits.append(
            ContaminationHit(
                "legal_text_truncated",
                "content",
                (m.group(0) if m else "truncated")[:120],
                "complete_legal_clause_required",
            )
        )

    if _CHECKLIST_META_RE.search(blob):
        hits.append(
            ContaminationHit(
                "bases_checklist_in_letter_body",
                "content",
                _CHECKLIST_META_RE.search(blob).group(0)[:120],
                "letter_must_not_embed_document_inventory",
            )
        )

    if _GENERIC_FALLBACK_RE.search(blob) and stage == "formats":
        hits.append(
            ContaminationHit(
                "generic_legal_fallback_body",
                "content",
                "fallback boilerplate",
                "prefer_deterministic_anexo_clause",
            )
        )

    if _CONTRACT_IN_PROPOSAL_RE.search(blob) and stage in ("formats", ""):
        if not _ADJUDICATION_WHITELIST_RE.search(blob):
            m = _CONTRACT_IN_PROPOSAL_RE.search(blob)
            hits.append(
                ContaminationHit(
                    "contract_language_in_proposal_stage",
                    "content",
                    m.group(0) if m else "contrato",
                    "use_conditional_adjudication_lexicon",
                )
            )

    return hits


def scan_date_after_deadline(
    text: str,
    *,
    deadline_dt_iso: Optional[str] = None,
    fecha_es: str = "",
) -> Optional[ContaminationHit]:
    if not deadline_dt_iso:
        return None
    from app.services.cronograma_bases_extract import parse_spanish_date_fragment

    deadline = parse_spanish_date_fragment(deadline_dt_iso) or None
    if not deadline and "T" in str(deadline_dt_iso):
        try:
            deadline = datetime.fromisoformat(str(deadline_dt_iso).replace("Z", ""))
        except Exception:
            deadline = None
    if not deadline:
        return None

    for fragment in (fecha_es, text[:800]):
        doc_dt = parse_spanish_date_fragment(fragment)
        if doc_dt and doc_dt.date() > deadline.date():
            return ContaminationHit(
                "document_date_after_submission_deadline",
                "fecha",
                fragment[:80],
                "document_date_on_or_before_submission_deadline",
            )
    return None


def scan_all_document_dates(
    text: str,
    *,
    deadline_dt_iso: Optional[str] = None,
    canonical_fecha_es: str = "",
) -> List[ContaminationHit]:
    """Escanea todas las fechas en español del cuerpo frente al cierre de proposiciones."""
    if not deadline_dt_iso or not text:
        return []
    from app.services.cronograma_bases_extract import parse_spanish_date_fragment

    deadline = parse_spanish_date_fragment(str(deadline_dt_iso))
    if not deadline and "T" in str(deadline_dt_iso):
        try:
            deadline = datetime.fromisoformat(str(deadline_dt_iso).replace("Z", ""))
        except Exception:
            deadline = None
    if not deadline:
        return []

    hits: List[ContaminationHit] = []
    seen: set[str] = set()
    for m in _DATE_ES_BODY_RE.finditer(text):
        frag = m.group(0)
        key = frag.lower()
        if key in seen:
            continue
        seen.add(key)
        doc_dt = parse_spanish_date_fragment(frag)
        if doc_dt and doc_dt.date() > deadline.date():
            hits.append(
                ContaminationHit(
                    "document_date_after_submission_deadline",
                    "fecha",
                    frag,
                    "document_date_on_or_before_submission_deadline",
                )
            )
    if canonical_fecha_es:
        one = scan_date_after_deadline(
            text,
            deadline_dt_iso=deadline_dt_iso,
            fecha_es=canonical_fecha_es,
        )
        if one and one.detected_value.lower() not in seen:
            hits.append(one)
    return hits


def infer_document_stage(
    *,
    sobre: str = "",
    basename: str = "",
    dedupe_key: str = "",
) -> str:
    """Infiera etapa de generación por sobre/nombre (universal, sin licitación fija)."""
    blob = f"{sobre} {basename} {dedupe_key}".lower()
    if "sobeeconomica" in blob.replace("_", "") or "economica" in blob:
        return "economic_writer"
    if is_apu_document(basename, dedupe_key):
        return "economic_writer"
    if "sobetecnica" in blob.replace("_", "") or "tecnica" in blob or "propuesta_tecnica" in dedupe_key:
        return "technical"
    return "formats"


def scan_conflicting_document_dates(
    text: str,
    *,
    canonical_fecha_es: str = "",
    dedupe_key: str = "",
    basename: str = "",
) -> Optional[ContaminationHit]:
    """
    Detecta fechas españolas múltiples distintas a la fecha canónica del documento.

    Aplica a cartas/anexos administrativos donde solo debe figurar la fecha del encabezado.
    """
    if not text or not canonical_fecha_es:
        return None
    blob = f"{dedupe_key} {basename}".lower()
    is_letter = (
        dedupe_key.startswith("pliego|ANEXO_")
        or "carta" in blob
        or "propuesta_tecnica" in dedupe_key
        or re.search(r"(?i)te[\s_-]*01|propuesta\s+t[eé]cnica", basename)
    )
    if not is_letter:
        return None

    canon = re.sub(r"\s+", " ", canonical_fecha_es.strip().lower())
    found: set[str] = set()
    for m in _DATE_ES_BODY_RE.finditer(text):
        found.add(re.sub(r"\s+", " ", m.group(0).strip().lower()))

    if len(found) <= 1:
        return None
    extras = sorted(d for d in found if d != canon)
    if not extras:
        return None
    return ContaminationHit(
        "document_multiple_dates_in_body",
        "fecha",
        "; ".join(extras)[:240],
        "single_canonical_document_date",
    )


def contamination_enforce_at_pack() -> bool:
    """True si el gate P0 debe bloquear empaquetado CompraNet."""
    if not bool(getattr(settings, "DOCUMENT_CONTAMINATION_GATE_ENABLED", True)):
        return False
    if not bool(getattr(settings, "DELIVERY_CONTAMINATION_ENFORCE_AT_PACK", True)):
        return False
    mode = str(getattr(settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce") or "enforce").lower()
    return mode == "enforce"


def contamination_hits_to_issues(
    hits: Sequence[ContaminationHit],
    *,
    document_id: str,
    provenance: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    prov = provenance or {"source": "document_contamination_gate", "confidence": 1.0}
    out: List[Dict[str, Any]] = []
    for h in hits:
        out.append(
            h.as_fill_issue_dict(
                document_id=document_id,
                severity=_severity("block"),
                provenance=prov,
            )
        )
    return out
