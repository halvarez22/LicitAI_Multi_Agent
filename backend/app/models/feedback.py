from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from .base import Base

class ExtractionFeedback(Base):
    __tablename__ = "extraction_feedback"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    company_id = Column(String, ForeignKey("companies.id"), nullable=True)
    
    session = relationship("Session", back_populates="feedback")
    agent_id = Column(String, nullable=False)
    pipeline_stage = Column(String, nullable=False) # analysis, compliance, economic, etc.
    entity_type = Column(String, nullable=False)   # requirement, field, document_slot
    entity_ref = Column(String, nullable=False)    # id estable del ítem, ej. AD-01
    field_path = Column(String, nullable=True)     # dot-path en el payload
    extracted_value = Column(Text, nullable=True)
    user_correction = Column(Text, nullable=True)
    was_correct = Column(Boolean, nullable=True)   # true/false/null = “parcial”
    correction_type = Column(String, nullable=True) # value_error, missing, false_positive, other
    user_comment = Column(Text, nullable=True)
    prompt_version = Column(String, nullable=True)
    agent_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
