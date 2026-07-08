import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_master_list():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    state = await m.get_session('vigilancia_issste')
    if not state: return
    
    master_list = state.get('master_compliance_list', {})
    tech = master_list.get('tecnico', []) or master_list.get('técnico', [])
    
    print(f"TOTAL ÍTEMS TÉCNICOS CRUDOS: {len(tech)}")
    if len(tech) > 0:
        print("\n--- MUESTRA DE 10 ÍTEMS ---")
        for i, item in enumerate(tech[:10]):
            lbl = item.get('label') or item.get('descripcion') or item.get('titulo') or 'SIN_TITULO'
            print(f"{i+1}. {lbl[:100]}...")

if __name__ == "__main__":
    asyncio.run(check_master_list())
