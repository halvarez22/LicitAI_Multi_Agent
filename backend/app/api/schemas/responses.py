from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime

class GenericResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

class AgentExecutionResponse(BaseModel):
    status: str
    session_id: str
    chatbot_message: Optional[str] = None
    agent_decision: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    auto_filled: Optional[List[str]] = None
    missing_fields: Optional[List[Dict[str, Any]]] = None
    generation_state: Optional[Dict[str, Any]] = None

class ChatbotResponse(BaseModel):
    reply: str
    citations: List[Dict[str, Any]]
    confidence: str
    expert_suggestion: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: Dict[str, str]
