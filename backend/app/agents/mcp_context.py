import logging
from typing import Any, Dict, FrozenSet

from app.memory.repository import MemoryRepository
from app.contracts.session_contracts import SessionStateMigrator, SessionStateV1

logger = logging.getLogger(__name__)

# Tareas cuyo resultado debe ser único por sesión: cada nueva corrida sustituye la anterior
# (evita mezclar cronogramas u outputs viejos con la certificación del último análisis).
_TASK_SINGLETON_BY_NAME: FrozenSet[str] = frozenset(
    {
        "analisis_bases",
        "stage_completed:analysis",
    }
)

class MCPContextManager:
    """
    Model Context Protocol (MCP) Manager.
    Estándar para que todos los agentes extraigan e inyecten contexto de sesión
    de manera uniforme, controlando el flujo y la persistencia.
    
    Fase 0 Hardening: Implementa versionado de estado de sesión (SessionStateV1).
    """
    def __init__(self, memory_repository: MemoryRepository):
        self.memory = memory_repository

    async def initialize_session(self, session_id: str, initial_data: Dict) -> bool:
        """Inicializa una nueva sesión en MCP con schema_version=1."""
        existing = await self.memory.get_session(session_id)
        preserved_name = None
        if isinstance(existing, dict) and existing.get("name"):
            preserved_name = existing.get("name")

        state = SessionStateV1(
            status="initialized",
            global_inputs=initial_data,
            tasks_completed=[]
        )
        payload = state.to_dict()
        if preserved_name:
            payload["name"] = preserved_name

        logger.info(f"[MCP] Inicializando sesión {session_id} v{state.schema_version}")
        return await self.memory.save_session(session_id, payload)

    async def get_global_context(self, session_id: str) -> Dict[str, Any]:
        """
        Recupera el contexto global de la sesión.
        Aplica migración automática si el estado es legacy (v0).
        """
        raw_session_data = await self.memory.get_session(session_id)
        if raw_session_data is None:
            raise ValueError(f"No existe contexto para la sesión: {session_id}")
        
        # --- Fase 0: Migración Automática ---
        session_data, was_migrated = SessionStateMigrator.migrate(session_id, raw_session_data)
        if was_migrated:
            # Guardar el estado migrado para evitar repetir el proceso
            await self.memory.save_session(session_id, session_data)
            logger.info(f"[MCP] Sesión {session_id} migrada a v1 en caliente.")
        
        # Recupera los metadatos de los documentos adjuntos a esta sesión
        documents = await self.memory.get_documents(session_id)
        
        return {
            "session_state": session_data,
            "documents_summary": [
                {"id": d["id"], "type": d.get("metadata", {}).get("type"), "filename": d.get("metadata", {}).get("filename")}
                for d in documents if isinstance(d, dict)
            ]
        }

    async def record_task_completion(self, session_id: str, task_name: str, result: Dict) -> bool:
        """
        Inyecta el resultado de un agente al contexto global de la sesión.

        Para ciertas tareas (`analisis_bases`, `stage_completed:analysis`) elimina
        entradas previas con el mismo nombre antes de añadir la nueva, de modo que
        consultas y certificación se alineen siempre con la última corrida.
        """
        raw_session_data = await self.memory.get_session(session_id)
        if not raw_session_data:
            return False
            
        # Asegurar v1 antes de actualizar
        session_data, _ = SessionStateMigrator.migrate(session_id, raw_session_data)
        
        if "tasks_completed" not in session_data:
            session_data["tasks_completed"] = []

        if task_name in _TASK_SINGLETON_BY_NAME:
            session_data["tasks_completed"] = [
                t for t in session_data["tasks_completed"] if t.get("task") != task_name
            ]
            
        session_data["tasks_completed"].append({
            "task": task_name,
            "result": result
        })
        return await self.memory.save_session(session_id, session_data)
