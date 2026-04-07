import asyncio
import os
import json
from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_agent():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    
    # Setup context
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    agent = AnalystAgent(context_manager)
    
    print(f"[*] Ejecutando Agente Analista para sesión: {session_id}")
    input_data = {
        "company_id": "test_company",
        "company_data": {"mode": "analysis_only"}
    }
    
    result = await agent.process(session_id, input_data)
    
    print("\n--- RESULTADO DEL AGENTE ANALISTA ---")
    print(json.dumps(result, indent=2))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_agent())
