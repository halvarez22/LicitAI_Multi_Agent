from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MiniDictamenSourceStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    CROSS_TENDER = "cross_tender"
    REFERENCE_ONLY = "reference_only"
    AMBIGUOUS = "ambiguous"
    NOT_EXPECTED = "not_expected"


class MiniDictamenDeliveryAction(str, Enum):
    MIRROR = "mirror"
    GENERATE_CONTROLLED = "generate_controlled"
    PRESENTAR_FISICO = "presentar_fisico"
    CLARIFICATION_REQUIRED = "clarification_required"
    NOT_APPLICABLE = "not_applicable"


class MiniDictamenCoverageStatus(str, Enum):
    COVERED = "covered"
    PENDING = "pending"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class MiniDictamenSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCKING = "blocking"


class ClarificationTicketStatus(str, Enum):
    OPEN = "open"
    READY_FOR_JUNTA = "ready_for_junta"
    ANSWERED = "answered"
    WAIVED = "waived"
    RESOLVED = "resolved"


class MiniDictamenAnexoItem(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    canonical_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    category: str = Field(default="administrativo")
    required_by_bases: bool = False
    official_template_expected: bool = False
    official_template_present: bool = False
    source_status: MiniDictamenSourceStatus = MiniDictamenSourceStatus.NOT_EXPECTED
    delivery_action: MiniDictamenDeliveryAction = MiniDictamenDeliveryAction.NOT_APPLICABLE
    coverage_status: MiniDictamenCoverageStatus = MiniDictamenCoverageStatus.NOT_APPLICABLE
    severity: MiniDictamenSeverity = MiniDictamenSeverity.INFO
    source_filename: Optional[str] = None
    source_document_class: Optional[str] = None
    source_action_recommended: Optional[str] = None
    compliance_linked: bool = False
    compliance_bucket: Optional[str] = None
    compliance_tipo_accion: Optional[str] = None
    coverage_linked: bool = False
    coverage_match_method: Optional[str] = None
    delivered_file: Optional[str] = None
    clarification_candidate: bool = False
    clarification_reason: Optional[str] = None
    blocking_error_type: Optional[str] = None
    notes: List[str] = Field(default_factory=list)
    provenance_ui: Dict[str, Any] = Field(default_factory=dict)


class ClarificationTicket(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ticket_id: str = Field(..., min_length=1)
    canonical_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    status: ClarificationTicketStatus = ClarificationTicketStatus.OPEN
    priority: MiniDictamenSeverity = MiniDictamenSeverity.BLOCKING
    question: str = Field(..., min_length=3)
    reason: str = Field(..., min_length=1)
    evidence_snippet: Optional[str] = None
    source_filename: Optional[str] = None
    source_status: MiniDictamenSourceStatus = MiniDictamenSourceStatus.MISSING
    resolution_note: Optional[str] = None
    resolution_source: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance_ui: Dict[str, Any] = Field(default_factory=dict)


class MiniDictamenSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = 0
    required_by_bases: int = 0
    official_template_expected: int = 0
    official_template_present: int = 0
    coverage_covered: int = 0
    coverage_pending: int = 0
    coverage_blocked: int = 0
    clarification_candidates: int = 0
    blocking_items: int = 0


class MiniDictamenAnexos(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    schema_version: str = Field(default="1.0.0", min_length=1)
    session_id: str = Field(..., min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: MiniDictamenSummary = Field(default_factory=MiniDictamenSummary)
    items: List[MiniDictamenAnexoItem] = Field(default_factory=list)
    clarification_tickets: List[ClarificationTicket] = Field(default_factory=list)
