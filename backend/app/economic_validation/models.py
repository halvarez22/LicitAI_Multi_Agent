from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ValidationState = Literal["ok", "warn", "blocking"]


class EconomicValidationItem(BaseModel):
    regla: str
    estado: ValidationState
    evidencia: str
    severidad: int = 1


class EconomicValidationResult(BaseModel):
    validations: List[EconomicValidationItem] = Field(default_factory=list)
    alerts: List[str] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    perfil_usado: str = "generic"
    trazabilidad: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
