
import os, sys, asyncio, json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Añadir path para importar settings
sys.path.append(os.getcwd())
try:
    from app.core.config import settings
except ImportError:
    # Fallback si no está en el path esperado
    class FakeSettings:
        DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/licitaciones"
    settings = FakeSettings()

async def list_sessions_for_test():
    print("\n🔍 [LicitAI SCANNER] Buscando Sesiones en Postgres...\n")
    
    conn_str = settings.DATABASE_URL
    if not conn_str:
        print("❌ Error: DATABASE_URL no configurada.")
        return
        
    engine = create_async_engine(conn_str.replace("postgresql://", "postgresql+asyncpg://"))
    
    try:
        async with engine.connect() as conn:
            query = text("""
                SELECT id, (state_data->>'name') as name, created_at, tasks_completed 
                FROM sessions 
                ORDER BY created_at DESC 
                LIMIT 10
            """)
            result = await conn.execute(query)
            rows = result.fetchall()

            if not rows:
                print("⚠️ No se encontraron sesiones en la base de datos.")
                return

            print(f"{'SESSION_ID':<50} | {'NAME':<20} | {'STAGES'}")
            print("-" * 100)
            
            for row in rows:
                sid, name, created, tasks_json = row
                tasks = tasks_json if tasks_json else []
                
                # Filtrar hitos de stage completion
                stages = [t.get('task').replace('stage_completed:', '') 
                         for t in tasks 
                         if isinstance(t, dict) and t.get('task', '').startswith('stage_completed:')]
                
                # Buscar economic_proposal
                has_econ = any(t.get('task') == 'economic_proposal' for t in tasks if isinstance(t, dict))
                
                stage_str = ", ".join(stages) if stages else "Análisis Inicial"
                if has_econ: stage_str += " (+ECON)"
                
                print(f"{str(sid):<50} | {str(name or 'S/N')[:20]:<20} | {stage_str}")

    except Exception as e:
        print(f"❌ Error durante el escaneo: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(list_sessions_for_test())
