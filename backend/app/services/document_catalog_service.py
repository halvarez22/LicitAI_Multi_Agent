"""
Catálogo universal de fuentes de sesión (Fuentes).

Se ejecuta tras ANALYZED en ingest: clasifica rol, casos de uso, entidades y
procedencia. Los agentes y la UI consumen ``session_state['document_catalog']``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.document_catalog import (
    DocumentCatalogEntry,
    DocumentCatalogRole,
    DocumentCatalogStats,
    DocumentCatalogUseCase,
    SessionDocumentCatalog,
)
from app.services.company_experience_context import (
    _is_experience_source_filename,
    extract_client_references_from_documents,
)
from app.services.evidence_profile_service import build_evidence_profile_from_documents
from app.services.session_template_catalog import classify_ingested_filename

CATALOG_SCHEMA_VERSION = "1.0.0"

_ROLE_UI_LABELS: Dict[str, str] = {
    DocumentCatalogRole.TENDER_BASES.value: "Bases / convocatoria",
    DocumentCatalogRole.TENDER_ANNEX.value: "Anexo de licitación",
    DocumentCatalogRole.OFFER_TEMPLATE.value: "Plantilla de oferta",
    DocumentCatalogRole.COMPANY_EXPERIENCE.value: "Experiencia empresa",
    DocumentCatalogRole.COMPANY_LEGAL.value: "Legal / acta / poder",
    DocumentCatalogRole.COMPANY_FISCAL.value: "Fiscal / SAT",
    DocumentCatalogRole.COMPANY_FINANCIAL.value: "Financiero",
    DocumentCatalogRole.COMMERCIAL_QUOTE.value: "Cotización / precios",
    DocumentCatalogRole.VISIT_EVIDENCE.value: "Evidencia de visita",
    DocumentCatalogRole.SUPPORTING.value: "Soporte",
    DocumentCatalogRole.UNKNOWN.value: "Sin clasificar",
}

_FISCAL_TEXT_RE = re.compile(
    r"(?i)(opini[oó]n\s+(?:del\s+)?cumplimiento|constancia\s+de\s+situaci[oó]n\s+fiscal|"
    r"sat\s|servicio\s+de\s+administraci[oó]n\s+tributaria|c\s?\.\s?f\s?\.)"
)
_LEGAL_TEXT_RE = re.compile(
    r"(?i)(acta\s+constitutiva|poder\s+(?:notarial|general|especial)|"
    r"escritura\s+p[uú]blica|protocolizaci[oó]n)"
)
_FINANCIAL_TEXT_RE = re.compile(
    r"(?i)(estado\s+de\s+resultados|balance\s+general|estados\s+financieros|"
    r"capital\s+contable|patrimonio\s+neto)"
)
_QUOTE_TEXT_RE = re.compile(
    r"(?i)(cotizaci[oó]n|propuesta\s+econ[oó]mica|integraci[oó]n\s+del\s+costo|"
    r"tabla\s+de\s+precios|precio\s+unitario)"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(content: Dict[str, Any]) -> str:
    text = content.get("extracted_text") or ""
    return text if isinstance(text, str) else ""


def _build_provenance_ui(
    role: DocumentCatalogRole,
    method: str,
    confidence: float,
) -> Dict[str, Any]:
    role_val = role.value if isinstance(role, DocumentCatalogRole) else str(role)
    return {
        "source": "document_catalog",
        "method": method,
        "confidence": round(confidence, 2),
        "label": _ROLE_UI_LABELS.get(role_val, role_val),
        "badge": role_val,
    }


def _use_cases_for_role(role: DocumentCatalogRole) -> List[DocumentCatalogUseCase]:
    mapping: Dict[DocumentCatalogRole, List[DocumentCatalogUseCase]] = {
        DocumentCatalogRole.TENDER_BASES: [
            DocumentCatalogUseCase.INDEX_FOR_RAG,
            DocumentCatalogUseCase.REFERENCE_ONLY,
        ],
        DocumentCatalogRole.TENDER_ANNEX: [
            DocumentCatalogUseCase.INDEX_FOR_RAG,
            DocumentCatalogUseCase.REFERENCE_ONLY,
        ],
        DocumentCatalogRole.OFFER_TEMPLATE: [
            DocumentCatalogUseCase.GENERATE_FROM_TEMPLATE,
            DocumentCatalogUseCase.INDEX_FOR_RAG,
        ],
        DocumentCatalogRole.COMPANY_EXPERIENCE: [
            DocumentCatalogUseCase.FILL_TE03_CLIENTS,
            DocumentCatalogUseCase.FILL_TECHNICAL_PROPOSAL,
            DocumentCatalogUseCase.COMPANY_PROFILE,
            DocumentCatalogUseCase.REFERENCE_ONLY,
        ],
        DocumentCatalogRole.COMPANY_LEGAL: [
            DocumentCatalogUseCase.PRESENT_PHYSICAL,
            DocumentCatalogUseCase.COMPANY_PROFILE,
        ],
        DocumentCatalogRole.COMPANY_FISCAL: [
            DocumentCatalogUseCase.PRESENT_PHYSICAL,
            DocumentCatalogUseCase.COMPANY_PROFILE,
        ],
        DocumentCatalogRole.COMPANY_FINANCIAL: [
            DocumentCatalogUseCase.PRESENT_PHYSICAL,
            DocumentCatalogUseCase.COMPANY_PROFILE,
        ],
        DocumentCatalogRole.COMMERCIAL_QUOTE: [
            DocumentCatalogUseCase.FILL_ECONOMIC_PROPOSAL,
            DocumentCatalogUseCase.REFERENCE_ONLY,
        ],
        DocumentCatalogRole.VISIT_EVIDENCE: [
            DocumentCatalogUseCase.PRESENT_PHYSICAL,
        ],
        DocumentCatalogRole.SUPPORTING: [
            DocumentCatalogUseCase.REFERENCE_ONLY,
        ],
        DocumentCatalogRole.UNKNOWN: [
            DocumentCatalogUseCase.INDEX_FOR_RAG,
        ],
    }
    return list(mapping.get(role, [DocumentCatalogUseCase.INDEX_FOR_RAG]))


def _classify_by_content(filename: str, text: str) -> Optional[Tuple[DocumentCatalogRole, float]]:
    """Señales en texto extraído (prioridad sobre nombre cuando hay evidencia clara)."""
    snippet = (text or "")[:12000]
    if not snippet.strip():
        return None
    if _FISCAL_TEXT_RE.search(snippet):
        return DocumentCatalogRole.COMPANY_FISCAL, 0.82
    if _LEGAL_TEXT_RE.search(snippet):
        return DocumentCatalogRole.COMPANY_LEGAL, 0.80
    if _FINANCIAL_TEXT_RE.search(snippet):
        return DocumentCatalogRole.COMPANY_FINANCIAL, 0.78
    if _QUOTE_TEXT_RE.search(snippet):
        return DocumentCatalogRole.COMMERCIAL_QUOTE, 0.75
    return None


def _map_template_class(
    document_class: str,
    accion: str,
) -> Tuple[DocumentCatalogRole, float]:
    """Traduce ``classify_ingested_filename`` al rol del catálogo."""
    if document_class == "pliego_referencia":
        return DocumentCatalogRole.TENDER_BASES, 0.88
    if document_class == "plantilla_oferta":
        return DocumentCatalogRole.OFFER_TEMPLATE, 0.85
    if document_class == "credencial_empresa":
        if accion == "presentar_fisico":
            return DocumentCatalogRole.COMPANY_LEGAL, 0.80
        return DocumentCatalogRole.COMPANY_LEGAL, 0.72
    if document_class == "evidencia_visita":
        return DocumentCatalogRole.VISIT_EVIDENCE, 0.90
    if document_class == "informativo":
        return DocumentCatalogRole.SUPPORTING, 0.55
    return DocumentCatalogRole.UNKNOWN, 0.40


def classify_document_entry(
    doc_id: str,
    content: Dict[str, Any],
) -> DocumentCatalogEntry:
    """
    Clasifica un documento ya analizado (reglas deterministas, sin LLM).

    Args:
        doc_id: Identificador del documento en sesión.
        content: Payload ``content`` del documento (filename, extracted_text, status).

    Returns:
        Entrada validada del catálogo.
    """
    filename = str(content.get("filename") or content.get("name") or "documento")
    text = _safe_text(content)
    status = str(content.get("status") or "ANALYZED").upper()
    total_pages = content.get("total_pages")
    if total_pages is not None:
        try:
            total_pages = int(total_pages)
        except (TypeError, ValueError):
            total_pages = None

    role: DocumentCatalogRole = DocumentCatalogRole.UNKNOWN
    confidence = 0.40
    method = "rules"

    if _is_experience_source_filename(filename):
        role = DocumentCatalogRole.COMPANY_EXPERIENCE
        confidence = 0.86
        method = "rules_experience_filename"

    content_hit = _classify_by_content(filename, text)
    if content_hit:
        c_role, c_conf = content_hit
        if c_conf >= confidence:
            role = c_role
            confidence = c_conf
            method = "rules_content"

    doc_class, accion, _sobre = classify_ingested_filename(filename)
    mapped_role, mapped_conf = _map_template_class(doc_class, accion)
    if role == DocumentCatalogRole.UNKNOWN or (
        mapped_conf > confidence and role not in (
            DocumentCatalogRole.COMPANY_EXPERIENCE,
            DocumentCatalogRole.COMPANY_FISCAL,
            DocumentCatalogRole.COMPANY_LEGAL,
        )
    ):
        role = mapped_role
        confidence = max(confidence, mapped_conf)
        method = "rules_template_catalog"

    use_cases = _use_cases_for_role(role)
    entities = _extract_entities(role, doc_id, filename, content, text)
    summary = _build_summary(role, filename, entities, total_pages)

    return DocumentCatalogEntry(
        doc_id=doc_id,
        filename=filename,
        doc_role=role,
        use_cases=use_cases,
        summary=summary,
        entities=entities,
        provenance_ui=_build_provenance_ui(role, method, confidence),
        confidence=confidence,
        classification_method=method,
        classified_at=_utc_now(),
        status=status,
        total_pages=total_pages,
    )


def _extract_entities(
    role: DocumentCatalogRole,
    doc_id: str,
    filename: str,
    content: Dict[str, Any],
    text: str,
) -> Dict[str, Any]:
    """Entidades estructuradas según el rol (delegación a servicios existentes)."""
    entities: Dict[str, Any] = {"doc_id": doc_id, "filename": filename}

    if role == DocumentCatalogRole.COMPANY_EXPERIENCE and text.strip():
        doc_record = {"id": doc_id, "content": content}
        refs = extract_client_references_from_documents([doc_record])
        if refs:
            entities["client_refs"] = refs[:12]
            entities["client_ref_count"] = len(refs)

    if role in (
        DocumentCatalogRole.COMPANY_EXPERIENCE,
        DocumentCatalogRole.COMPANY_LEGAL,
        DocumentCatalogRole.COMPANY_FISCAL,
        DocumentCatalogRole.COMPANY_FINANCIAL,
    ):
        profile = build_evidence_profile_from_documents([{"content": content, "id": doc_id}])
        fields = profile.get("fields") if isinstance(profile, dict) else {}
        if isinstance(fields, dict) and fields:
            slim: Dict[str, Any] = {}
            for key, entry in fields.items():
                if not isinstance(entry, dict):
                    continue
                val = entry.get("value")
                if val is None or val == "" or val == []:
                    continue
                slim[key] = {
                    "value": val,
                    "source_doc": entry.get("source_doc") or filename,
                }
            if slim:
                entities["evidence_fields"] = slim

    if role in (DocumentCatalogRole.TENDER_BASES, DocumentCatalogRole.TENDER_ANNEX):
        entities["text_chars"] = len(text)
        if text.strip():
            entities["preview"] = text[:280].strip()

    return entities


def _build_summary(
    role: DocumentCatalogRole,
    filename: str,
    entities: Dict[str, Any],
    total_pages: Optional[int],
) -> str:
    pages_bit = f", {total_pages} pág." if total_pages else ""
    if role == DocumentCatalogRole.COMPANY_EXPERIENCE:
        n = int(entities.get("client_ref_count") or 0)
        if n:
            return f"Experiencia: {n} referencia(s) de clientes detectadas{pages_bit}."
        return f"Documento de experiencia empresarial{pages_bit}."
    if role == DocumentCatalogRole.TENDER_BASES:
        return f"Bases o convocatoria para RAG y referencia{pages_bit}."
    if role == DocumentCatalogRole.OFFER_TEMPLATE:
        return f"Plantilla de oferta a rellenar o generar{pages_bit}."
    if role == DocumentCatalogRole.COMPANY_FISCAL:
        return f"Documento fiscal / SAT (presentación física){pages_bit}."
    if role == DocumentCatalogRole.COMPANY_LEGAL:
        return f"Documento legal corporativo{pages_bit}."
    if role == DocumentCatalogRole.VISIT_EVIDENCE:
        return f"Evidencia de visita a instalaciones{pages_bit}."
    return f"Fuente «{filename}» clasificada como {_ROLE_UI_LABELS.get(role.value, role.value)}{pages_bit}."


def _compute_stats(entries: Dict[str, DocumentCatalogEntry]) -> DocumentCatalogStats:
    by_role: Dict[str, int] = {}
    client_refs = 0
    for entry in entries.values():
        role_key = entry.doc_role.value if isinstance(entry.doc_role, DocumentCatalogRole) else str(entry.doc_role)
        by_role[role_key] = by_role.get(role_key, 0) + 1
        ents = entry.entities if isinstance(entry.entities, dict) else {}
        client_refs += int(ents.get("client_ref_count") or 0)
    return DocumentCatalogStats(
        total_entries=len(entries),
        by_role=by_role,
        experience_client_refs=client_refs,
    )


def build_session_document_catalog(
    session_id: str,
    documents: List[Dict[str, Any]],
) -> SessionDocumentCatalog:
    """Reconstruye el catálogo completo desde ``memory.get_documents``."""
    entries: Dict[str, DocumentCatalogEntry] = {}
    for doc in documents or []:
        doc_id = str(doc.get("id") or "")
        content = doc.get("content") if isinstance(doc.get("content"), dict) else {}
        if not doc_id or not content:
            continue
        status = str(content.get("status") or "").upper()
        if status not in ("ANALYZED", "COMPLETED", "OK"):
            continue
        entries[doc_id] = classify_document_entry(doc_id, content)

    return SessionDocumentCatalog(
        schema_version=CATALOG_SCHEMA_VERSION,
        session_id=session_id,
        updated_at=_utc_now(),
        entries=entries,
        stats=_compute_stats(entries),
    )


def catalog_from_session_state(session_state: Dict[str, Any]) -> Optional[SessionDocumentCatalog]:
    """Parsea el blob persistido en sesión."""
    raw = session_state.get("document_catalog")
    if not isinstance(raw, dict):
        return None
    try:
        return SessionDocumentCatalog.model_validate(raw)
    except Exception:
        return None


def get_entries_by_use_case(
    session_state: Dict[str, Any],
    use_case: str,
) -> List[DocumentCatalogEntry]:
    """Filtra entradas del catálogo por caso de uso."""
    catalog = catalog_from_session_state(session_state)
    if not catalog:
        return []
    out: List[DocumentCatalogEntry] = []
    for entry in catalog.entries.values():
        cases = [uc.value if hasattr(uc, "value") else str(uc) for uc in entry.use_cases]
        if use_case in cases:
            out.append(entry)
    return out


def get_catalog_ui_by_doc_id(session_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Mapa doc_id → badge/resumen para panel Fuentes."""
    catalog = catalog_from_session_state(session_state)
    if not catalog:
        return {}
    ui: Dict[str, Dict[str, Any]] = {}
    for doc_id, entry in catalog.entries.items():
        prov = entry.provenance_ui if isinstance(entry.provenance_ui, dict) else {}
        ui[doc_id] = {
            "doc_role": entry.doc_role.value if hasattr(entry.doc_role, "value") else str(entry.doc_role),
            "label": prov.get("label") or _ROLE_UI_LABELS.get(entry.doc_role.value, ""),
            "summary": entry.summary,
            "use_cases": [
                uc.value if hasattr(uc, "value") else str(uc) for uc in entry.use_cases
            ],
            "confidence": entry.confidence,
        }
    return ui


def experience_client_refs_from_catalog(
    session_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Referencias de clientes agregadas desde entradas de experiencia."""
    refs: List[Dict[str, Any]] = []
    for entry in get_entries_by_use_case(session_state, DocumentCatalogUseCase.FILL_TE03_CLIENTS.value):
        ents = entry.entities if isinstance(entry.entities, dict) else {}
        for row in ents.get("client_refs") or []:
            if isinstance(row, dict):
                refs.append(row)
    return refs


async def classify_and_persist_catalog_entry(
    memory: Any,
    session_id: str,
    doc_id: str,
    content: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Clasifica un documento y fusiona la entrada en ``document_catalog`` de la sesión.

    Returns:
        Entrada serializada (dict JSON-safe).
    """
    entry = classify_document_entry(doc_id, content)
    session = await memory.get_session(session_id) or {}
    raw_catalog = session.get("document_catalog")
    if isinstance(raw_catalog, dict):
        entries_raw = raw_catalog.get("entries") or {}
    else:
        entries_raw = {}

    entries: Dict[str, DocumentCatalogEntry] = {}
    for eid, raw in entries_raw.items():
        if isinstance(raw, dict):
            try:
                entries[str(eid)] = DocumentCatalogEntry.model_validate(raw)
            except Exception:
                continue

    entries[doc_id] = entry
    catalog = SessionDocumentCatalog(
        schema_version=CATALOG_SCHEMA_VERSION,
        session_id=session_id,
        updated_at=_utc_now(),
        entries=entries,
        stats=_compute_stats(entries),
    )
    await memory.save_session(
        session_id,
        {"document_catalog": catalog.model_dump(mode="json")},
    )
    return entry.model_dump(mode="json")


async def refresh_session_document_catalog(
    memory: Any,
    session_id: str,
) -> Dict[str, Any]:
    """Reconstruye y persiste el catálogo completo."""
    documents = await memory.get_documents(session_id) or []
    catalog = build_session_document_catalog(session_id, documents)
    await memory.save_session(
        session_id,
        {"document_catalog": catalog.model_dump(mode="json")},
    )
    return catalog.model_dump(mode="json")
