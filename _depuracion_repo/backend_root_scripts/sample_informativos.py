import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def check():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    session = await m.get_session(session_id)
    v1 = session.get("document_candidates_v1", {})
    candidates = v1.get("candidate_document_list", [])
    
    informativos = [c for c in candidates if c.get("tipo_accion_final") == "informativo"]
    
    print(f"Total Informativvos kept: {len(informativos)}")
    print("Sample Informativos (Top 20):")
    for i, c in enumerate(informativos[:20]):
        print(f" - {c.get('nombre')[:100]}")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
