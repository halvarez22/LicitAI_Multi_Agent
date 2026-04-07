from sqlalchemy import Column, String, DateTime, Enum as SQLEnum, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from .base import Base

class OutcomeEnum(str, enum.Enum):
    GANADA = "ganada"
    PERDIDA = "perdida"
    DESCLASIFICADA = "desclasificada"
    ABANDONADA = "abandonada"
    PENDIENTE = "pendiente"

class LicitacionOutcome(Base):
    __tablename__ = "licitacion_outcomes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False, unique=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=True)
    
    session = relationship("Session", back_populates="outcomes")
    sector = Column(String, nullable=True)
    tipo_licitacion = Column(String, nullable=True) # Nacional, Internacional, etc.
    resultado = Column(SQLEnum(OutcomeEnum), default=OutcomeEnum.PENDIENTE)
    notas = Column(Text, nullable=True)
    requirements_fingerprint = Column(String, nullable=True) # Hash normalizado
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
