import asyncio
import json
import sys
import os

# Añadir path para importar los módulos del backend
sys.path.append("/app")

from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_agent_test():
    # Usar el Factory para obtener el adaptador concreto (Postgres)
    memory_adapter = MemoryAdapterFactory.create_adapter()
    
    # Conectar a la base de datos
    if not await memory_adapter.connect():
        print("❌ Error: No se pudo conectar al adaptador de memoria.")
        return

    context_manager = MCPContextManager(memory_repository=memory_adapter)
    agent = ComplianceAgent(context_manager=context_manager)
    
    session_id = "sesion-experto-madera"
    input_data = {
        "action": "full_compliance_audit",
        "priority": "max_precision"
    }

    # Inicializar sesión si no existe
    try:
        await context_manager.get_global_context(session_id)
    except Exception:
        print(f"Inicializando sesión {session_id} en MCP...")
        await context_manager.initialize_session(session_id, {"project": "Licitacion Madera VLM"})
    
    print(f"🚀 Iniciando Auditoría Maestra del Agente 2 sobre la sesión '{session_id}'...")
    
    try:
        result = await agent.process(session_id, input_data)
        
        # Guardar resultado
        output_path = "/app/resultado_agente_2.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Auditoría completada. Resultado guardado en {output_path}")
        
        # Resumen
        summary = result.get("summary", {})
        print(f"\n--- RESUMEN AGENTE 2 ---")
        print(f"Estado Global: {summary.get('estado_global')}")
        print(f"Total Requisitos: {summary.get('total_requisitos')}")
        print(f"Riesgos de Desechamiento: {summary.get('riesgos_desechamiento')}")
        print(f"Veredicto: {summary.get('veredicto')}")
        
    except Exception as e:
        print(f"❌ Error durante el procesamiento del agente: {str(e)}")
    finally:
        await memory_adapter.disconnect()

if __name__ == "__main__":
    asyncio.run(run_agent_test())
