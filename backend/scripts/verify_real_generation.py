import asyncio
import os
import sys
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Path
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.config.settings import settings

async def verify_real_data():
    conn_str = settings.DATABASE_URL or "postgresql://postgres:postgres@localhost:5432/licitaciones"
    if "postgresql://" in conn_str:
        conn_str = conn_str.replace("postgresql://", "postgresql+asyncpg://")
    
    engine = create_async_engine(conn_str)
    
    sid = "licitacin_pblica_nacional_presencial__40004001-003-24_"
    cid = "co_1774286420505"
    
    print(f"📡 Verificando sesión real: {sid}")
    
    async with engine.connect() as conn:
        # 1. Verificar Sesión
        res = await conn.execute(text("SELECT state_data FROM sessions WHERE id = :sid"), {"sid": sid})
        row = res.fetchone()
        if not row:
            print(f"❌ Sesión {sid} no encontrada.")
            return

        sd = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        tasks = sd.get('tasks_completed', [])
        
        has_compliance = any(t.get('task') == 'stage_completed:compliance' for t in tasks if isinstance(t, dict))
        has_econ = any(t.get('task') == 'economic_proposal' for t in tasks if isinstance(t, dict))
        
        print(f"   - Hito Compliance: {'✅ OK' if has_compliance else '❌ NO'}")
        print(f"   - Hito Economic: {'✅ OK' if has_econ else '❌ NO (Requiere simulación parcial)'}")
        
        # 2. Verificar Empresa
        res = await conn.execute(text("SELECT master_profile FROM companies WHERE id = :cid"), {"cid": cid})
        crow = res.fetchone()
        if crow:
            mp = crow[0] if isinstance(crow[0], dict) else json.loads(crow[0])
            print(f"   - Razón Social: {mp.get('razon_social', 'N/D')}")
            print(f"   - RFC: {mp.get('rfc', 'N/D')}")
        else:
            print(f"❌ Empresa {cid} no encontrada.")

if __name__ == "__main__":
    asyncio.run(verify_real_data())
