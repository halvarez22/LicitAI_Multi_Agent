import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_all_lists():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    state = await m.get_session('vigilancia_issste')
    if not state: return
    
    master_list = state.get('master_compliance_list', {})
    admin = master_list.get('administrativo', [])
    formats = master_list.get('formatos', [])
    tech = master_list.get('tecnico', []) or master_list.get('técnico', [])
    
    print(f"ADMINISTRATIVOS: {len(admin)}")
    print(f"FORMATOS: {len(formats)}")
    print(f"TÉCNICOS: {len(tech)}")
    
    analysis = state.get('analysis_result', {})
    reglas = analysis.get('data', {}).get('reglas_economicas', {})
    print(f"REGLAS ECONÓMICAS EXTRAÍDAS: {len(reglas)}")

if __name__ == "__main__":
    asyncio.run(check_all_lists())
