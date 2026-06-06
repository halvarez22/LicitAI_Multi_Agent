"""
Contrato canónico del catálogo de fuentes por sesión (post-ingest).

Clasifica cada documento subido en Fuentes: rol, casos de uso para agentes,
entidades extraídas y procedencia visible (ENTERPRISE_CANONICO_HITL).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DocumentCatalogRole(str, Enum):
    """Rol semántico de la fuente respecto al pipeline."""

    TENDER_BASES = "tender_bases"
    TENDER_ANNEX = "tender_annex"
    OFFER_TEMPLATE = "offer_template"
    COMPANY_EXPERIENCE = "company_experience"
    COMPANY_LEGAL = "company_legal"
    COMPANY_FISCAL = "company_fiscal"
    COMPANY_FINANCIAL = "company_financial"
    COMMERCIAL_QUOTE = "commercial_quote"
    VISIT_EVIDENCE = "visit_evidence"
    SUPPORTING = "supporting"
    UNKNOWN = "unknown"


class DocumentCatalogUseCase(str, Enum):
    """Casos de uso que los agentes pueden consultar."""

    FILL_TE03_CLIENTS = "fill_te03_clients"
    FILL_TECHNICAL_PROPOSAL = "fill_technical_proposal"
    FILL_ECONOMIC_PROPOSAL = "fill_economic_proposal"
    GENERATE_FROM_TEMPLATE = "generate_from_template"
    PRESENT_PHYSICAL = "present_physical"
    REFERENCE_ONLY = "reference_only"
    INDEX_FOR_RAG = "index_for_rag"
    COMPANY_PROFILE = "company_profile"


class DocumentCatalogEntry(BaseModel):
    """Entrada del catálogo para un documento de sesión."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    doc_id: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    doc_role: DocumentCatalogRole = DocumentCatalogRole.UNKNOWN
    use_cases: List[DocumentCatalogUseCase] = Field(default_factory=list)
    summary: str = Field(default="", max_length=500)
    entities: Dict[str, Any] = Field(default_factory=dict)
    provenance_ui: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    classification_method: str = Field(default="rules")
    classified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = Field(default="ANALYZED")
    total_pages: Optional[int] = Field(default=None, ge=0)


class DocumentCatalogStats(BaseModel):
    """KPIs materializados del catálogo."""

    model_config = ConfigDict(extra="ignore")

    total_entries: int = 0
    by_role: Dict[str, int] = Field(default_factory=dict)
    experience_client_refs: int = 0


class SessionDocumentCatalog(BaseModel):
    """Contenedor maestro del catálogo por sesión."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    schema_version: str = Field(default="1.0.0", min_length=1)
    session_id: str = Field(..., min_length=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entries: Dict[str, DocumentCatalogEntry] = Field(default_factory=dict)
    stats: DocumentCatalogStats = Field(default_factory=DocumentCatalogStats)
