import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory

async def check():
    m = await get_connected_memory()
    
    sessions = [
        "unaq-2026_paneles_solares",
        "licitacion_opm-001-2026_madera_chihuahua",
        "limpieza_isapeg",
        "vigilancia_issste",
    ]
    
    for sid in sessions:
        s = await m.get_session(sid)
        docs = await m.get_documents(sid)
        tasks = (s or {}).get("tasks_completed", [])
        has_compliance = any(
            t.get("task", "").startswith("stage_completed:compliance") for t in tasks
        )
        print(f"\n{'='*60}")
        print(f"SESSION : {sid}")
        print(f"DOCS    : {len(docs)}")
        for d in docs:
            fname = d.get("content", {}).get("filename", "??")
            status = d.get("content", {}).get("status", "??")
            fpath = d.get("content", {}).get("file_path", "??")
            print(f"  - [{status}] {fname}")
            print(f"    Path: {fpath}")
        print(f"COMPLIANCE DONE: {has_compliance}")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
