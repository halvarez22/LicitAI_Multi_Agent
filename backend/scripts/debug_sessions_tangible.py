
import asyncio
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def debug_tangibility():
    print("\n🔍 [AUDITORÍA DE TANGIBILIDAD] Consultando la Verdad en Postgres...\n")
    
    # URI de conexión directa
    uri = "postgresql+asyncpg://postgres:postgres@localhost:5432/licitaciones"
    engine = create_async_engine(uri)
    
    try:
        async with engine.connect() as conn:
            # Consultar solo los datos vivos en state_data
            query = text("SELECT id, state_data FROM sessions ORDER BY created_at DESC LIMIT 5")
            result = await conn.execute(query)
            rows = result.fetchall()

            if not rows:
                print("⚠️  No hay ninguna sesión en la base de datos.")
                return

            print(f"{'SESSION_ID':<50} | {'HITOS ENCONTRADOS'}")
            print("-" * 100)

            for row in rows:
                sid = row[0]
                data = row[1] if row[1] else {}
                
                # Buscar hitos en tasks_completed o similar dentro del JSON
                tasks = data.get("tasks_completed", [])
                hitos = [t.get("task") for t in tasks if isinstance(t, dict)]
                
                # Buscar rastros de generación exitosa
                if "economic_proposal" in hitos:
                    hitos_str = "✅ ECONÓMICO OK"
                elif "stage_completed:formats" in hitos:
                    hitos_str = "📄 TÉCNICO OK"
                else:
                    hitos_str = f"⏳ En proceso ({len(hitos)} pasos)"
                
                print(f"{str(sid):<50} | {hitos_str}")
                
    except Exception as e:
        print(f"❌ Error de Auditoría: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(debug_tangibility())
