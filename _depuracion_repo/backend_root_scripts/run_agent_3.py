import asyncio
import json
import sys
import os

# Añadir path para importar los módulos del backend
sys.path.append("/app")

from app.agents.economic import EconomicAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_economic_test():
    # Usar el Factory para obtener el adaptador concreto (Postgres)
    memory_adapter = MemoryAdapterFactory.create_adapter()
    
    # Conectar a la base de datos
    if not await memory_adapter.connect():
        print("❌ Error: No se pudo conectar al adaptador de memoria.")
        return

    context_manager = MCPContextManager(memory_repository=memory_adapter)
    agent = EconomicAgent(context_manager=context_manager)
    
    session_id = "sesion-experto-madera"
    input_data = {
        "action": "extract_catalogo_and_prices",
        "priority": "precision_numerical"
    }

    print(f"🚀 Iniciando Análisis Económico Real sobre la sesión '{session_id}'...")
    
    try:
        result = await agent.process(session_id, input_data)
        
        # Guardar resultado
        output_path = "/app/resultado_agente_3.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Análisis Económico completado. Resultado guardado en {output_path}")
        
        # Resumen
        summary = result.get("summary", {})
        print(f"\n--- DICTAMEN ECONÓMICO ---")
        print(f"Total Partidas: {summary.get('total_partidas_detectadas')}")
        print(f"Criterio: {summary.get('criterio_adjudicacion')}")
        print(f"Veredicto: {summary.get('veredicto_economico')}")
        
    except Exception as e:
        print(f"❌ Error durante el procesamiento: {str(e)}")
    finally:
        await memory_adapter.disconnect()

if __name__ == "__main__":
    asyncio.run(run_economic_test())
