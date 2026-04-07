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

class ChatbotRequest(BaseModel):
    session_id: str
    # Vacío: modo proactivo (pending_questions) o mensaje guía sin invocar RAG.
    query: str = Field(default="", max_length=12000)
    company_id: Optional[str] = None
