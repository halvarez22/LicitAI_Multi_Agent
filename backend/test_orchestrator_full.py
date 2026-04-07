import asyncio
import os
import json

os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/licitaciones"
os.environ["VECTOR_DB_URL"] = "http://localhost:8000"
os.environ["OCR_URL"] = "http://localhost:8082"
os.environ["LLM_URL"] = "http://localhost:11434"
os.environ["MEMORY_BACKEND"] = "postgres"

from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_full_pipeline():
    session_id = "e2e_nativo_vigilancia_20260401_192851"
    company_id = "co_1774288319012" # Hector Alvarez
    
    # Setup context
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    # Instanciar el Orquestador maestro
    orchestrator = OrchestratorAgent(context_manager)
    
    print(f"\n🚀 === INICIANDO PRUEBA DE FUEGO: ORQUESTACIÓN COMPLETA (LicitAI) ===")
    print(f"[*] Sesión: {session_id}")
    print(f"[*] Empresa: Servicios de Tecnologia Integrales\n")
    
    input_data = {
        "company_id": company_id,
        "company_data": {
            "mode": "full", # Ejecutar todo el pasillo de análisis
            "name": "Servicios de Tecnologia Integrales SA de CV"
        }
    }
    
    # Ejecutar el proceso en cascada secuencial
    result = await orchestrator.process(session_id, input_data)
    
    print("\n" + "="*50)
    print("🏁 FINAL DE LA PRUEBA DE FUEGO")
    print(f"STATUS FINAL: {result.get('status')}")
    
    # Analizar la decisión del orquestador
    decision = result.get("orchestrator_decision", {})
    print(f"Resumen: {decision.get('summary')}")
    
    if result.get("status") == "waiting_for_data":
        print("\n🚨 DECISIÓN: DETENIDO POR DATOGAP")
        print(f"Mensaje para Usuario: {result.get('chatbot_message')}")
    
    import time, datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"resultado_e2e_v5_{stamp}.json"
    with open(output_name, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n[+] Reporte completo guardado en '{output_name}'")
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_full_pipeline())
