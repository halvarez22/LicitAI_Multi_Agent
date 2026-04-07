"""
redis_bus.py — Fase 3 Backtracking
Implementación mínima del bus de mensajería entre agentes usando Redis.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import redis

from app.config.settings import settings


from enum import Enum

class AgentMessageType(str, Enum):
    CHALLENGE = "challenge"
    CORRECTION = "correction"
    REQUEST_RERUN = "request_rerun"
    VALIDATION_NOTE = "validation_note"


class AgentMessage(BaseModel):
    """
    Contrato estricto para mensajes entre agentes en el bus.
    """
    model_config = {"extra": "forbid"}

    message_id: str
    session_id: str
    correlation_id: str
    from_agent: str
    to_agent: Optional[str] = None
    message_type: AgentMessageType
    payload: Dict[str, Any]
    created_at: float = Field(default_factory=time.time)


class RedisAgentBus:
    """
    Bus de comunicación basado en Redis (LPUSH/BRPOP) para el pipeline LicitAI.
    """

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or getattr(settings, "REDIS_HOST", "localhost")
        self.port = port or getattr(settings, "REDIS_PORT", 6379)
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
        return self._client

    def publish(self, channel_suffix: str, message: AgentMessage) -> bool:
        """
        Publica un mensaje en una lista de Redis (cola) con TTL corto.
        """
        try:
            channel = f"{settings.BACKTRACK_REDIS_CHANNEL_PREFIX}:{channel_suffix}"
            data = message.model_dump_json()
            # Usamos LPUSH para encolar
            self.client.lpush(channel, data)
            # TTL de 24h para limpieza automática si nadie los consume
            self.client.expire(channel, 86400)
            return True
        except Exception:
            return False

    def drain_messages(self, channel_suffix: str) -> List[AgentMessage]:
        """
        Recupera y elimina todos los mensajes de una cola (drain).
        """
        messages = []
        try:
            channel = f"{settings.BACKTRACK_REDIS_CHANNEL_PREFIX}:{channel_suffix}"
            while True:
                # RPOP para sacar el mensaje más antiguo (FIFO)
                raw = self.client.rpop(channel)
                if not raw:
                    break
                messages.append(AgentMessage.model_validate_json(raw))
        except Exception:
            pass
        return messages
