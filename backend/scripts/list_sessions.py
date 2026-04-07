import asyncio
import os
import sys
import json
import io

# Forzar UTF-8 para consola y redirección
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Fallback para versiones de python que no soportan reconfigure
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# Asegurar que el path del backend esté disponible
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.memory.factory import MemoryAdapterFactory
from app.config.settings import settings

async def list_sessions():
    """
    Lista sesiones candidatas para la prueba de generation_only.
    Busca hitos 'stage_completed:*' en tasks_completed.
    """
    print("\n🔍 [LicitAI] Buscando sesiones aptas para generación industrial...\n")
    
    memory = MemoryAdapterFactory.create_adapter()
    if not memory:
        print("❌ Error: No se pudo inicializar el adaptador de memoria.")
        return
        
    await memory.connect()
    
    try:
        # Intentamos obtener sesiones recientes vía Postgres directo para mayor detalle de hitos
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        
        conn_str = settings.DATABASE_URL or "postgresql://postgres:postgres@localhost:5432/licitaciones"
        if not conn_str:
            print("❌ Error: DATABASE_URL no configurada.")
            return
            
        print(f"📡 Conectando a: {conn_str.split('@')[-1]}...")
            
        # Ajuste para asyncpg
        if "postgresql://" in conn_str:
            conn_str = conn_str.replace("postgresql://", "postgresql+asyncpg://")
            
        engine = create_async_engine(conn_str)
        
        async with engine.connect() as conn:
            query = text("""
                SELECT id, state_data, created_at 
                FROM sessions 
                ORDER BY created_at DESC 
                LIMIT 50
            """)
            
            result = await conn.execute(query)
            rows = result.fetchall()
            
            headers = f"{'SESSION_ID':<40} | {'NAME':<20} | {'STAGES':<30}"
            print("-" * len(headers))
            print(headers)
            print("-" * len(headers))
            
            found = False
            for row in rows:
                found = True
                sid, state_data, created = row
                
                # state_data es un dict (JSON column)
                sd = state_data if isinstance(state_data, dict) else (json.loads(state_data) if isinstance(state_data, str) else {})
                tasks = sd.get('tasks_completed', [])
                name = sd.get('name') or str(sid)[:20]
                
                # Filtrar hitos de stage completion
                stages = [t.get('task').replace('stage_completed:', '') 
                         for t in tasks 
                         if isinstance(t, dict) and t.get('task', '').startswith('stage_completed:')]
                
                # También buscar economic_proposal que es crítico para el writer
                has_econ = any(t.get('task') == 'economic_proposal' for t in tasks if isinstance(t, dict))
                
                stage_str = ", ".join(stages) if stages else "none"
                if has_econ: stage_str += " (+ECON)"
                
                print(f"{str(sid):<40} | {str(name)[:30]:<20} | {stage_str:<30}")
            
            if not found:
                print("⚠️ No se encontraron sesiones recientes.")
            else:
                print("\n💡 Tip: Usa una sesión que tenga 'compliance' y '+ECON' para un test óptimo de 'generation_only'.")

    except Exception as e:
        print(f"❌ Error durante la inspección: {e}")
    finally:
        await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(list_sessions())
