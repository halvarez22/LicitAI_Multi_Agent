import asyncio
from app.memory.factory import MemoryAdapterFactory

async def seed():
    session_id = "VRO-TEST-ECONOMIC-01"
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    mock_requirements = {
        "tecnico": [
            {"nombre": "EQUIPO: PULIDORA", "literal": "Requerimiento de pulidora industrial."},
            {"nombre": "INSUMO: JABON", "literal": "Requerimiento de jabon de manos."}
        ]
    }
    
    # Inicializar sesión completa
    await memory.save_session(session_id, {
        "status": "analysis_COMPLETED",
        "master_compliance_list": mock_requirements,
        "tasks_completed": [
            {"task": "master_compliance_list", "result": mock_requirements}
        ]
    })
    
    print(f"[+] Nueva Sesión {session_id} inicializada para test económico.")
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(seed())
