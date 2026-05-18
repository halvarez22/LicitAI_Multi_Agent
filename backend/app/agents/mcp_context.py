import logging
from app.core.logging_config import get_logger
from typing import Any, Dict, FrozenSet

from app.memory.repository import MemoryRepository
from app.contracts.session_contracts import SessionStateMigrator, SessionStateV1

logger = get_logger(__name__)

# Tareas cuyo resultado debe ser único por sesión: cada nueva corrida sustituye la anterior
# (evita mezclar cronogramas u outputs viejos con la certificación del último análisis).
_TASK_SINGLETON_BY_NAME: FrozenSet[str] = frozenset(
    {
        "analisis_bases",
        "stage_completed:analysis",
        "stage_completed:compliance",
        "stage_completed:economic",
        # Última corrida económica (éxito o bloqueo por validación): el chat y servicios leen una sola entrada.
        "economic_proposal",
        "master_compliance_list",
        "document_inventory",
        "intake_plan",
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
        
        CORREGIDO: Valida que todos los documentos pertenezcan a la sesión especificada.
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
        
        # CORRECCIÓN: Filtrar documentos que pertenezcan a la sesión correcta
        filtered_documents = []
        for d in documents:
            if isinstance(d, dict):
                doc_session_id = d.get("session_id") or d.get("metadata", {}).get("session_id")
                if doc_session_id and doc_session_id != session_id:
                    logger.warning(
                        f"[MCP] Documento {d.get('id')} pertenece a sesión {doc_session_id}, "
                        f"no a {session_id}. Filtrando para evitar mezcla de datos."
                    )
                    continue
                filtered_documents.append(d)
        
        return {
            "session_state": session_data,
            "documents_summary": [
                {"id": d["id"], "type": d.get("metadata", {}).get("type"), "filename": d.get("metadata", {}).get("filename")}
                for d in filtered_documents if isinstance(d, dict)
            ]
        }

    async def record_task_completion(self, session_id: str, task_name: str, result: Dict) -> bool:
        """
        Inyecta el resultado de un agente al contexto global de la sesión.

        Para ciertas tareas (`analisis_bases`, `stage_completed:analysis`,
        `economic_proposal`, etc.) elimina entradas previas con el mismo nombre
        antes de añadir la nueva, de modo que consultas y certificación se alineen
        con la última corrida.
        
        CORREGIDO: Valida que el resultado no contenga referencias a otras sesiones.
        """
        raw_session_data = await self.memory.get_session(session_id)
        if not raw_session_data:
            return False
            
        # Asegurar v1 antes de actualizar
        session_data, _ = SessionStateMigrator.migrate(session_id, raw_session_data)
        
        # CORRECCIÓN: Validar que el resultado no contenga referencias a otras sesiones
        if not self._validate_task_result_ownership(session_id, result):
            logger.warning(
                f"[MCP] Resultado de tarea {task_name} contiene referencias a otras sesiones. "
                f"Se registrará pero revise los datos."
            )
        
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
    
    def _validate_task_result_ownership(self, session_id: str, result: Dict) -> bool:
        """
        Valida que el resultado de una tarea no contenga referencias a otras sesiones.
        
        Returns:
            True si el resultado es válido (no contiene referencias a otras sesiones)
            False si contiene referencias a otras sesiones
        """
        if not isinstance(result, dict):
            return True
        
        # Buscar session_id en el resultado
        result_session_id = result.get("session_id")
        if result_session_id and result_session_id != session_id:
            logger.warning(
                f"[MCP] Validación fallida: resultado tiene session_id={result_session_id}, "
                f"se esperaba {session_id}"
            )
            return False
        
        # Buscar session_id en campos anidados (como data, metadata, etc.)
        for key, value in result.items():
            if isinstance(value, dict):
                nested_session_id = value.get("session_id")
                if nested_session_id and nested_session_id != session_id:
                    logger.warning(
                        f"[MCP] Validación fallida: resultado.{key} tiene session_id={nested_session_id}, "
                        f"se esperaba {session_id}"
                    )
                    return False
        
        return True