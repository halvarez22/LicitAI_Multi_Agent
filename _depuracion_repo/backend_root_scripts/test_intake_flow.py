import asyncio
import os
import json
from app.agents.intake import IntakeAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_test():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    company_id = "co_1774286420505"
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    agent = IntakeAgent(context_manager)
    
    # 🧪 ESCENARIO: El usuario responde al chat
    # Mensaje: "Claro, mi identificación oficial es el folio 334-9988-ABC76"
    test_user_responses = [
        "Claro, mi identificación oficial es el folio 334-9988-ABC76",
        "mi correo es contacto@tecnologia-integrales.com",
        "el sitio web es www.integrales-tech.com.mx"
    ]
    
    print(f"\n🚀 === SIMULACIÓN DE CHAT: AGENTE INTAKE (RECAUDACIÓN) ===")
    
    for resp in test_user_responses:
        print(f"\n💬 Usuario: '{resp}'")
        
        # Ejecutar el procesamiento de la respuesta
        result = await agent.process_user_response(session_id, company_id, resp)
        
        print(f"🤖 LicitAI: {result.get('message')}")
        print(f"📊 Estado: {result.get('status')} | Próximo paso: {result.get('next_step', 'continuar_chat')}")

    # Verificar el perfil final en PostgreSQL
    print("\n--- PERFIL MAESTRO ACTUALIZADO (PROCESADO) ---")
    from app.api.v1.routes.sessions import get_repository
    repo = await get_repository()
    company = await repo.get_company(company_id)
    print(json.dumps(company.get("master_profile", {}), indent=2, ensure_ascii=False))
    
    await repo.disconnect()
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_test())
