import asyncio
from app.memory.factory import MemoryAdapterFactory

async def seed():
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    mock_requirements = {
        "tecnico": [
            {"nombre": "Servicio de Limpieza en Hospital", "seccion": "Técnica", "literal": "Se requiere personal capacitado para limpieza de quirófanos.", "documento": "BASES"},
            {"nombre": "Equipamiento: Pulidoras de Piso", "seccion": "Anexo 2", "literal": "Uso de pulidoras de alta velocidad para áreas comunes.", "documento": "BASES"},
            {"nombre": "Detergentes Industriales", "seccion": "Especificaciones", "literal": "Uso de detergentes biodegradables grado hospitalario.", "documento": "BASES"}
        ],
        "administrativo": [
            {"nombre": "Acta Constitutiva", "seccion": "Legal", "literal": "Presentar acta original.", "documento": "BASES"}
        ]
    }
    
    # Simular que el ComplianceAgent terminó con éxito
    session = await memory.get_session(session_id)
    if session:
        session["master_compliance_list"] = mock_requirements
        await memory.save_session(session_id, session)
        print("[+] Mock Requirements inyectados en la sesión.")

    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(seed())
