from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any, List

class DocumentUploadRequest(BaseModel):
    session_id: str = Field(..., description="ID de la sesión de licitación")
    document_type: str = Field(..., description="Tipo de adjunto: bases, anexo, acta, etc.")
    
class ProcessBasesRequest(BaseModel):
    session_id: str = Field(..., description="ID autogenerado para esta Licitación")
    company_id: Optional[str] = Field(None, description="ID de la empresa participante")
    company_data: Dict[str, Any] = Field(default_factory=dict, description="Metadatos de la empresa")
    resume_generation: bool = Field(False, description="Si es True, continúa desde el último checkpoint de generación.")
    generation_mode: Optional[str] = Field(
        None,
        description="Modo desacoplado F2: technical | economic | full (default full). También aceptable en company_data.",
    )
    generation_stream: Optional[str] = Field(
        None,
        description="Stream F6 (ADR-001): technical | economic | full. Default derivado de generation_mode.",
    )

class ChatbotRequest(BaseModel):
    session_id: str
    # Vacío: modo proactivo (pending_questions) o mensaje guía sin invocar RAG.
    query: str = Field(default="", max_length=12000)
    company_id: Optional[str] = None
    # Archivo ya subido vía POST /upload (cotización Excel/CSV en chat).
    doc_id: Optional[str] = None
    # Contexto estructurado de riesgo forense (panel HITL) para respuesta anclada.
    forensic_risk_context: Optional[Dict[str, Any]] = None
