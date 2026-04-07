"""
session_contracts.py — Fase 0 Hardening
Schema versionado del estado de sesión persistido en PostgreSQL.

Implementa:
  - SessionStateV1: schema actual normalizado con schema_version
  - SessionStateMigrator: migra estados legacy (v0/sin versión) → v1
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Versión actual del schema de sesión
CURRENT_SESSION_VERSION = 1


class SessionStateV1(BaseModel):
    """
    Estado de sesión versionado v1.
    Guarantee: cualquier campo ausente tiene default seguro (no KeyError en producción).
    """
    model_config = {"extra": "allow"}  # allow: absorbe campos legacy sin romper

    schema_version: int = Field(
        default=CURRENT_SESSION_VERSION,
        description="Versión del schema. Permite migración automática de estados viejos."
    )
    status: str = Field(default="initialized")
    global_inputs: Dict[str, Any] = Field(default_factory=dict)
    tasks_completed: List[Dict[str, Any]] = Field(default_factory=list)

    # Estado de generación (checkpoints)
    generation_state: Optional[Dict[str, Any]] = None

    # Checklist de requisitos vs documentos
    checklist: Optional[List[Dict[str, Any]]] = None

    # Última decisión del orquestador (persistida para meta-chatbot)
    last_orchestrator_decision: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializa para guardado en PostgreSQL."""
        return self.model_dump(exclude_none=False)


class SessionStateMigrator:
    """
    Migrador simple de estados de sesión.
    Convierte estados legacy (v0 o sin schema_version) al formato v1.

    Uso:
        raw_state = await memory.get_session(session_id)
        migrated, was_migrated = SessionStateMigrator.migrate(session_id, raw_state)
    """

    @staticmethod
    def migrate(
        session_id: str,
        raw_state: Optional[Dict[str, Any]]
    ) -> tuple[Dict[str, Any], bool]:
        """
        Retorna (estado_migrado, fue_migrado).
        Si no fue necesaria migración, 'fue_migrado' es False.
        """
        if raw_state is None:
            # Estado vacío — inicializar como v1
            migrated = SessionStateV1().to_dict()
            logger.info(
                "[SessionMigrator] session_id=%s: estado None → inicializado como v1",
                session_id
            )
            return migrated, True

        version = raw_state.get("schema_version")

        if version is None:
            # v0: estado legacy sin versión
            migrated = SessionStateMigrator._migrate_v0_to_v1(session_id, raw_state)
            logger.info(
                "[SessionMigrator] session_id=%s: migrado v0 → v1 (campos preservados: %s)",
                session_id,
                list(raw_state.keys())
            )
            return migrated, True

        if version == CURRENT_SESSION_VERSION:
            # Ya está en la versión correcta
            return raw_state, False

        # Versiones futuras — placeholder para cadena de migraciones
        logger.warning(
            "[SessionMigrator] session_id=%s: schema_version=%s desconocido, tratando como v1",
            session_id,
            version
        )
        return raw_state, False

    @staticmethod
    def _migrate_v0_to_v1(
        session_id: str,
        v0_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Migración v0 → v1:
        - Añade schema_version=1
        - Normaliza campos con defaults seguros
        - Preserva todos los datos existentes vía model extra='allow'
        """
        v1 = SessionStateV1(
            schema_version=1,
            status=v0_state.get("status", "initialized"),
            global_inputs=v0_state.get("global_inputs", {}),
            tasks_completed=v0_state.get("tasks_completed", []),
            generation_state=v0_state.get("generation_state"),
            checklist=v0_state.get("checklist"),
            last_orchestrator_decision=v0_state.get("last_orchestrator_decision"),
        )
        result = v1.to_dict()
        # Preservar campos extra no reconocidos (no perder datos legacy)
        for k, v in v0_state.items():
            if k not in result:
                result[k] = v
        return result
