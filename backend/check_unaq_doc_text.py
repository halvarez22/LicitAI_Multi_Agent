import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory

async def check_doc_text():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    
    docs = await m.get_documents(session_id)
    for d in docs:
        content = d.get("content", {})
        filename = content.get("filename", "??")
        status = content.get("status", "??")
        text = content.get("extracted_text", "") or ""
        file_path = content.get("file_path", "??")
        
        print(f"ARCHIVO  : {filename}")
        print(f"STATUS   : {status}")
        print(f"RUTA     : {file_path}")
        print(f"TEXTO    : {len(text)} caracteres")
        if text:
            print(f"MUESTRA  : {text[:300]}")
        else:
            print("MUESTRA  : [SIN TEXTO]")
    
    # Tambien verificar el compliance en tasks
    s = await m.get_session(session_id) or {}
    tasks = s.get("tasks_completed", [])
    print(f"\nTARES COMPLETADAS: {len(tasks)}")
    for t in tasks[-5:]:
        task_name = t.get("task", "??")
        result = t.get("result", {})
        status = result.get("status", "??") if isinstance(result, dict) else "??"
        msg = result.get("message", "")[:80] if isinstance(result, dict) else ""
        print(f"  - {task_name} => status={status} | {msg}")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_doc_text())
