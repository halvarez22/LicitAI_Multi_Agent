from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    state_data = Column(JSON, default={})
    conversation_history = Column(JSON, default=[])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")
    agent_states = relationship("AgentState", back_populates="session", cascade="all, delete-orphan")
    outcomes = relationship("LicitacionOutcome", back_populates="session", cascade="all, delete-orphan")
    feedback = relationship("ExtractionFeedback", back_populates="session", cascade="all, delete-orphan")
