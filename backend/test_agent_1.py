import asyncio
import os
import sys
import json

# Añadir el path del backend
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def test_agent_1():
    print("--- INICIANDO PRUEBA DE AGENTE 1 (ANALISTA) ---")
    
    # Configurar memoria y contexto
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    mcp_manager = MCPContextManager(memory_repository=memory)
    agent = AnalystAgent(context_manager=mcp_manager)
    
    session_id = "test_session_opm_001"
    
    # Inicializar la sesión
    await mcp_manager.initialize_session(session_id, {"title": "Licitación Madera"})
    
    # IMPORTANTE: Inyectar datos reales del PDF en ChromaDB para que el agente tenga qué analizar
    from app.services.vector_service import VectorDbServiceClient
    vdb = VectorDbServiceClient()
    
    # Texto real extraído manualmente/vía browser para la prueba
    real_text_fragments = [
        "MUNICIPIO DE MADERA. LICITACIÓN PÚBLICA NACIONAL PRESENCIAL No. OPM-001-2026.",
        "OBJETO: SUMINISTRO E INSTALACIÓN DE 1259 LUMINARIAS LED VIALES DE 40W Y 650 LUMINARIAS LED VIALES DE 100W.",
        "COSTO DE LAS BASES: $2,500.00. NO SE OTORGARÁ ANTICIPO.",
        "JUNTA DE ACLARACIONES: 26 DE ENERO DE 2026 A LAS 16:00 HORAS.",
        "PRESENTACIÓN Y APERTURA DE PROPOSICIONES: 30 DE ENERO DE 2026 A LAS 11:00 A.M.",
        "VISITA AL SITIO: 26 DE ENERO DE 2026 A LAS 10:00 A.M.",
        "GARANTÍA DE SERIEDAD: 5% DEL MONTO DE LA PROPUESTA. GARANTÍA DE CUMPLIMIENTO: 10% DEL CONTRATO.",
        "CRITERIO DE EVALUACIÓN: BINARIO.",
        "REQUISITOS: EXPERIENCIA TÉCNICA Y CAPACIDAD FINANCIERA COMPROBABLE."
    ]
    metadatas = [{"source": "Bases licitacion OPM-001-2026.pdf", "page": 1} for _ in real_text_fragments]
    vdb.add_texts(session_id, real_text_fragments, metadatas)
    
    # 1. Simular que ya se subió el documento y hay texto en el contexto
    input_data = {
        "document_type": "bases",
        "filename": "Bases licitacion OPM-001-2026.pdf"
    }
    
    # Ejecutar el agente
    print(f"Ejecutando {agent.name}...")
    result = await agent.process(session_id, input_data)
    
    print("\n--- RESULTADO DEL AGENTE 1 ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_agent_1())
