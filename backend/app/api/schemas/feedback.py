from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class FeedbackCreate(BaseModel):
    session_id: str
    company_id: Optional[str] = None
    agent_id: str
    pipeline_stage: str
    entity_type: str
    entity_ref: str
    field_path: Optional[str] = None
    extracted_value: Optional[str] = None
    user_correction: Optional[str] = None
    was_correct: Optional[bool] = None
    correction_type: Optional[str] = None
    user_comment: Optional[str] = None
    prompt_version: Optional[str] = None
    agent_version: Optional[str] = None

    @field_validator("was_correct")
    @classmethod
    def validate_correction_logic(cls, v: Optional[bool], info):
        # Si was_correct is False, exigir user_correction o correction_type != other con comentario
        # Nota: info.data contiene los otros campos en Pydantic V2
        if v is False:
            user_correction = info.data.get("user_correction")
            correction_type = info.data.get("correction_type")
            user_comment = info.data.get("user_comment")
            
            if not user_correction and (not correction_type or correction_type == "other") and not user_comment:
                raise ValueError("Si la extracción es incorrecta, debe proveer una corrección, un tipo de error válido o un comentario.")
        return v

class FeedbackRead(FeedbackCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

class FeedbackListResponse(BaseModel):
    success: bool
    data: List[FeedbackRead]
    message: str = "Feedback recuperado exitosamente"
