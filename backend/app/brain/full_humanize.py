
import asyncio
import sys
import json
sys.path.append("/app")
from app.memory.factory import MemoryAdapterFactory

def humanize_recursive(obj):
    robotic = "No cierres la app. Detecté un error de extracción"
    robotic_2 = "hay bloqueos económicos sin ubicación verificable"
    human = "Necesito tu ayuda para completar algunos precios faltantes en tu propuesta económica."
    
    if isinstance(obj, str):
        if robotic in obj or robotic_2 in obj:
            return human
        return obj
    elif isinstance(obj, list):
        return [humanize_recursive(i) for i in obj]
    elif isinstance(obj, dict):
        # Corrección especial: resetear el precio absurdo de 4 millones si existe
        if obj.get("precio_unitario") == 4089000.0:
            print("Reseteando precio erróneo de 4,089,000 a 0.0")
            obj["precio_unitario"] = 0.0
            obj["subtotal"] = 0.0
            obj["status"] = "pending"
            
        return {k: humanize_recursive(v) for k, v in obj.items()}
    return obj

async def full_humanize():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    session_id = "limpieza_isapeg"
    session = await memory.get_session(session_id)
    if not session:
        return

    new_session = humanize_recursive(session)
    
    # Asegurar que el bloqueo económico en pending_questions tenga un mensaje limpio
    pending = new_session.get("pending_questions") or []
    for q in pending:
        if q.get("type") == "economic_validation_blocking":
            q["question"] = "Tu propuesta económica requiere algunos ajustes manuales en los precios para poder continuar."

    await memory.save_session(session_id, new_session)
    print(f"Sesión {session_id} completamente saneada y humanizada.")

if __name__ == "__main__":
    asyncio.run(full_humanize())
