"""
tests/test_fase3_redis_bus.py
Pruebas mock de integración para el bus de mensajería Redis.
"""
import pytest
from unittest.mock import MagicMock, patch
from app.agents.communication.redis_bus import RedisAgentBus, AgentMessage, AgentMessageType

@patch("redis.Redis")
def test_redis_bus_publish(mock_redis_cls):
    mock_instance = mock_redis_cls.return_value
    bus = RedisAgentBus(host="localhost", port=6379)
    
    msg = AgentMessage(
        message_id="msg-1",
        session_id="sess-1",
        correlation_id="corr-1",
        from_agent="orchestrator",
        message_type=AgentMessageType.VALIDATION_NOTE,
        payload={"test": 123}
    )
    
    success = bus.publish("sess-1", msg)
    assert success is True
    # Debería haber llamado a lpush y expire
    assert mock_instance.lpush.called

@patch("redis.Redis")
def test_redis_bus_drain_messages(mock_redis_cls):
    mock_instance = mock_redis_cls.return_value
    # Simular un solo mensaje en la cola y luego vacío
    msg_json = '{"message_id":"msg-1","session_id":"s-1","correlation_id":"c-1","from_agent":"a","message_type":"validation_note","payload":{},"created_at":1}'
    mock_instance.rpop.side_effect = [msg_json, None]
    
    bus = RedisAgentBus()
    messages = bus.drain_messages("s-1")
    
    assert len(messages) == 1
    assert messages[0].message_id == "msg-1"
