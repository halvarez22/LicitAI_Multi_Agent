import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def check():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    # Obtener el contexto global que el orquestador usa
    # Buscamos en 'tasks_completed' y datos guardados
    session = await memory.get_session(session_id)
    if not session:
        print("Sesión no encontrada.")
        return
        
    print(f"\n--- CONTEXTO DE SESIÓN: {session_id} ---")
    
    # El ComplianceAgent guarda en 'master_compliance_list'
    # Vamos a buscar en el diccionario de estado guardado
    master_list = session.get("master_compliance_list", {})
    
    print("\n[Master Compliance List]:")
    print(json.dumps(master_list, indent=2, ensure_ascii=False))
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
