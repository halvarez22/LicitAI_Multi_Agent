from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class OutcomeCreate(BaseModel):
    session_id: str
    company_id: Optional[str] = None
    sector: Optional[str] = None
    tipo_licitacion: Optional[str] = None
    resultado: str # ganada, perdida, desclasificada, abandonada, pendiente
    notas: Optional[str] = None
    requirements: List[str] = Field(default_factory=list) # Para fingerprinting manual si no viene de la sesión

class ExperienceResult(BaseModel):
    session_id: str
    sector: Optional[str] = None
    tipo_licitacion: Optional[str] = None
    summary: str
    outcome: str
    score: float
    disclaimer: Optional[str] = None

class ExperienceResponse(BaseModel):
    success: bool
    data: List[ExperienceResult]
    count: int
