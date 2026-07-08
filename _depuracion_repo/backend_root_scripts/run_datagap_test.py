import asyncio
import os
import json
from app.agents.data_gap import DataGapAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    company_id = "co_1774286420505" # Servicios de Tecnologia Integrales
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    agent = DataGapAgent(context_manager)
    
    print(f"[*] Ejecutando Agente DataGap para Empresa ID: {company_id}")
    
    # Input data mock (similar to what orchestrator sends)
    input_data = {
        "company_id": company_id,
        "company_data": {
            "name": "Servicios de Tecnologia Integrales SA de CV",
            "master_profile": {} # El agente debe jalarlo de la BD segun su logica en la linea 76
        }
    }
    
    result = await agent.process(session_id, input_data)
    
    print("\n--- RESULTADO DEL AGENTE DATAGAP ---")
    print(f"Status: {result.get('status')}")
    print(f"Auto-completados: {result.get('auto_filled')}")
    
    print("\n[Chatbot Message Preview]:")
    print(result.get('chatbot_message'))
    
    # Guardar para reporte
    with open("datagap_full_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run())
