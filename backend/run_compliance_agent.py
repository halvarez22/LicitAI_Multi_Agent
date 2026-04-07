import asyncio
import os
import json
from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_agent():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    
    # Setup context
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    agent = ComplianceAgent(context_manager)
    
    print(f"[*] Ejecutando Agente Compliance para sesión: {session_id}")
    input_data = {
        "company_id": "test_company",
        "company_data": {"mode": "full"}
    }
    
    result = await agent.process(session_id, input_data)
    
    print("\n--- RESULTADO DEL AGENTE COMPLIANCE (RESUMEN) ---")
    data = result.get("data", {})
    print(f"Administrativos: {len(data.get('administrativo', []))}")
    print(f"Técnicos: {len(data.get('tecnico', []))}")
    print(f"Formatos: {len(data.get('formatos', []))}")
    
    # Guardar resultado completo para análisis
    with open("compliance_full_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_agent())
