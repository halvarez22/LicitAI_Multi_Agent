from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

ValidationState = Literal["ok", "warn", "blocking"]
SourceType = Literal["FILE", "CHAT", "SYSTEM"]

class EvidenceSource(BaseModel):
    source_type: SourceType = "FILE"
    document_id: Optional[str] = None
    page: Optional[int] = None
    row: Optional[int] = None
    message_id: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: Optional[str] = None
    authority_level: int = 1 # 1: AI, 2: System, 3: User (Max Authority)

class EconomicValidationItem(BaseModel):
    regla: str
    estado: ValidationState
    evidencia: str
    severidad: int = 1
    fuente: Optional[EvidenceSource] = Field(default_factory=lambda: EvidenceSource())

class EconomicValidationResult(BaseModel):
    validations: List[EconomicValidationItem] = Field(default_factory=list)
    alerts: List[str] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    perfil_usado: str = "generic"
    trazabilidad: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    audit_log: List[Dict[str, Any]] = Field(default_factory=list) # Fase 3: Log de cambios legal
