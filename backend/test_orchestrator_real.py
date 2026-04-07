import asyncio
import os
import sys
import json

sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def test_orchestrator_real():
    print("--- INICIANDO PRUEBA DE AGENTE 0 (ORQUESTADOR) ---")
    
    # 1. Configurar memoria y contexto
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    mcp_manager = MCPContextManager(memory_repository=memory)
    
    # El Orquestador necesita registrar a sus subordinados si usara registro dinámico,
    # pero nuestra nueva implementación los importa directamente (Paso 1).
    orchestrator = OrchestratorAgent(context_manager=mcp_manager)
    
    # Usaremos la sesión maestra que ya tiene los vectores inyectados
    session_id = "ba0acfbc-e762-479b-aac3-6ff3ce3e62e4"
    
    input_data = {
        "title": "Prueba de Estrés MAS - ISSSTE",
        "company_data": {
            "name": "Licitante Pro S.A.",
            "rfc": "LPR123456ABC"
        }
    }
    
    print(f"Ejecutando Orquestador sobre la sesión: {session_id}...")
    result = await orchestrator.process(session_id, input_data)
    
    print("\n--- RESULTADO DEL ORQUESTADOR (Veredicto MAS) ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_orchestrator_real())
