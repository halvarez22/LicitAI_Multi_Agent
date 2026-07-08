import asyncio
import json
from app.agents.economic import EconomicAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def run_test():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    company_id = "co_1774286420505"
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    context_manager = MCPContextManager(memory)
    
    # 1. PREPARAR EL CATÁLOGO DE LA EMPRESA (MOCK)
    from app.api.v1.routes.sessions import get_repository
    repo = await get_repository()
    company = await repo.get_company(company_id)
    
    if company:
        company["catalog"] = [
            {"item": "Pulidoras Industriales", "unidad": "pza", "precio_unitario": 4500.00},
            {"item": "Detergente Industrial 20L", "unidad": "tambor", "precio_unitario": 850.00},
            {"item": "Personal Operario Limpieza", "unidad": "turno", "precio_unitario": 350.00},
            {"item": "Mantenimiento de Maquinaria", "unidad": "servicio", "precio_unitario": 1200.00}
        ]
        await repo.save_company(company_id, company)
        print("[*] Catálogo de Precios inyectado para la empresa.")

    # 2. LANZAR EL AGENTE ECONÓMICO
    agent = EconomicAgent(context_manager)
    
    print(f"\n🚀 === PRUEBA DE AGENTE ECONÓMICO (LicitAI) ===")
    
    # Simular datos de entrada (mock del orquestador)
    input_data = {
        "company_id": company_id,
        "company_data": company
    }
    
    result = await agent.process(session_id, input_data)
    
    print("\n--- RESULTADO DE LA PROPUESTA ECONÓMICA ---")
    data = result.get("data", {})
    if data:
        print(f"Subtotal Base: {data.get('total_base')} MXN")
        print(f"Margen Sugerido: {data.get('margin_suggested')}")
        print(f"Total Final Licitación: {data.get('grand_total')} MXN")
        
        print("\n[Desglose por Concepto]:")
        for item in data.get("items", []):
            print(f"- {item.get('nombre')}: ${item.get('subtotal', 0)} ({item.get('status')})")
    else:
        print(f"Status: {result.get('status')} | {result.get('message')}")

    await repo.disconnect()
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(run_test())
