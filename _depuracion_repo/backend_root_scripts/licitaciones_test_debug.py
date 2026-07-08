import asyncio
import os
import sys
import json

sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.agents.economic import EconomicAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def test_economic_real():
    print("--- INICIANDO AUDITORÍA ECONÓMICA REAL (AGENTE 2) ---")
    
    # 1. Configurar memoria y contexto
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    mcp_manager = MCPContextManager(memory_repository=memory)
    agent = EconomicAgent(context_manager=mcp_manager)
    
    # Sesión maestra con Bases e Ingesta de Excel
    session_id = "full_mas_test_999"
    
    print(f"Ejecutando {agent.name} sobre la sesión: {session_id}")
    print("Esto invocará múltiples fases de RAG (Catálogo, Cotizaciones, Evaluación, Financiero, Logística)...")

    result = await agent.process(session_id, {})
    
    print("\n--- RESULTADO DE LA AUDITORÍA ECONÓMICA ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_economic_real())
