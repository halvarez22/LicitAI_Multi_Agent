import asyncio
import os
import sys
import json

sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def test_agent_1_real():
    print("--- INICIANDO LECTURA REAL AGENTE 1 (ANALISTA) ---")
    
    # 1. Configurar memoria y contexto
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    mcp_manager = MCPContextManager(memory_repository=memory)
    agent = AnalystAgent(context_manager=mcp_manager)
    
    session_id = "ba0acfbc-e762-479b-aac3-6ff3ce3e62e4"
    
    # 2. El contexto vectorial ya esta lleno gracias a la ingestión previa
    # Por lo que solo le pedimos al agente que piense y extraiga.
    input_data = {
        "document_type": "bases_multiples",
    }
    
    print(f"Ejecutando {agent.name} sobre la sesion con todos los documentos...")
    result = await agent.process(session_id, input_data)
    
    print("\n--- DICTAMEN DEL AGENTE 1 ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_agent_1_real())
