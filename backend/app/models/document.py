from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    content = Column(JSON, default={})
    metadata_info = Column(JSON, default={})
    document_type = Column(String, nullable=False) # e.g., 'base', 'anexo', 'acta'
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="documents")
    line_items = relationship("SessionLineItem", back_populates="document", cascade="all, delete-orphan")