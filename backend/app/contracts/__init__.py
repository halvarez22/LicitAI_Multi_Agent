"""
Contracts package — Fase 0 Hardening
Modelos Pydantic v2 estrictos para boundaries críticas del sistema LicitAI.
"""
from app.contracts.agent_contracts import (
    AgentInput,
    AgentOutput,
    AgentStatus,
)
from app.contracts.orchestrator_contracts import OrchestratorState
from app.contracts.session_contracts import SessionStateV1
from app.contracts.document_inventory import (
    DocumentEnvelope,
    DocumentInventory,
    InventoryItem,
    InventoryItemStatus,
    InventoryStats,
    InventoryTier,
    ItemAnchor,
)

__all__ = [
    "AgentInput",
    "AgentOutput",
    "AgentStatus",
    "OrchestratorState",
    "SessionStateV1",
    "DocumentEnvelope",
    "DocumentInventory",
    "InventoryItem",
    "InventoryItemStatus",
    "InventoryStats",
    "InventoryTier",
    "ItemAnchor",
]
