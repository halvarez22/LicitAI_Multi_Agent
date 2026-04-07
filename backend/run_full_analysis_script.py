
import asyncio
import os
import sys
import json

# path to app
sys.path.insert(0, '/app')

from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_analysis():
    session_id = 'maderas_chihuahua_luminarias_'
    print(f"🚀 Iniciando análisis completo para sesión: {session_id}")
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    mcp_manager = MCPContextManager(memory_repository=memory)
    orchestrator = OrchestratorAgent(context_manager=mcp_manager)
    
    # Datos de la empresa para que los agentes de cumplimiento y económicos validen
    company_data = {
        "razon_social": "Maderas Chihuahua S.A. de C.V.",
        "rfc": "MCHI900101XYZ",
        "direccion": "Av. Independencia 123, Chihuahua, Chih.",
        "padrón_proveedores": "VIGENTE",
        "capital_contable": 5000000.0
    }
    
    try:
        resultado = await orchestrator.process(
            session_id=session_id,
            input_data={"company_data": company_data}
        )
        
        # Guardar resultados en un archivo JSON para persistencia y lectura fácil
        output_path = "/app/ultima_licitacion_completa.json"
        with open(output_path, "w", encoding='utf-8') as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False)
            
        print(f"\n✅ Análisis completado. Resultados guardados en {output_path}")
        print("\n--- RESUMEN DE EJECUCIÓN ---")
        print(json.dumps(resultado.get("orchestrator_decision", {}), indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"❌ Error durante la ejecución: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_analysis())
