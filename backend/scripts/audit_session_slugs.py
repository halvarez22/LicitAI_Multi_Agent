import os
import sys
import asyncio

# 🚀 CONFIGURACIÓN DE RUTAS (Fiel al Host Windows)
# Agregar la raíz de backend al PYTHONPATH antes de cualquier otro import
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/licitaciones"

from app.memory.factory import MemoryAdapterFactory

async def audit_slugs():
    """
    Lista las sesiones actuales, sus nombres legibles y sus IDs técnicos (Slugs).
    Fundamental para sincronizar el Frontend con las carpetas de salida /data/outputs.
    """
    print("\n📊 [LicitAI QA] AUDITORÍA DE SESIONES Y SLUGS TÉCNICOS\n")
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    try:
        # Obtener sesiones (usando el adaptador inyectado)
        sessions = await memory.list_sessions()
        
        if not sessions:
            print("⚠️  No hay sesiones registradas en la base de datos.")
            return

        print(f"✅ Se encontraron {len(sessions)} sesiones. Generando mapa de rutas...\n")
        print(f"{'NOMBRE (UI)':<45} | {'ID TÉCNICO (SLUG)':<45} | {'ESTADO'}")
        print("-" * 110)
        
        for s in sessions:
            sid = s.get("id")
            state = s.get("state_data", {})
            name = str(state.get("name", "S/N"))[:43]
            status = state.get("status", "unknown")
            
            # Verificación de carpeta de salida física
            output_dir = f"C:/data/outputs/{sid}"
            has_output = "[DIR OK]" if os.path.exists(output_dir) else "[SIN DIR]"
            
            print(f"{name:<45} | {sid:<45} | {status} {has_output}")
            
        print("\n📝 [NOTA]: El Frontend debe enviar el 'ID TÉCNICO' en lugar del 'NOMBRE' para descargar el ZIP.")
        
    except Exception as e:
        print(f"❌ ERROR: Falló la auditoría de BD: {e}")
    finally:
        await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(audit_slugs())
