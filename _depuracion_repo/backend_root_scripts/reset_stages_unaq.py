import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory

async def reset_analysis_stages(session_id: str):
    """Limpia solo los stage_completed fallidos para forzar re-ejecución."""
    m = await get_connected_memory()
    s = await m.get_session(session_id) or {}
    
    tasks = s.get("tasks_completed", [])
    print(f"Tasks antes de limpiar: {len(tasks)}")
    for t in tasks:
        print(f"  - {t.get('task')} => status={t.get('result', {}).get('status', '??') if isinstance(t.get('result'), dict) else '??'}")
    
    # Eliminar SOLO los stage_completed (analysis, compliance) para forzar re-run
    # Conservar master_compliance_list y otros
    stages_to_remove = {"stage_completed:analysis", "stage_completed:compliance"}
    filtered_tasks = [
        t for t in tasks 
        if t.get("task") not in stages_to_remove
    ]
    
    print(f"\nTasks después de limpiar: {len(filtered_tasks)}")
    
    s["tasks_completed"] = filtered_tasks
    await m.save_session(session_id, s)
    print(f"\n✅ Stages fallidos limpiados. El Orquestador re-correrá analysis + compliance.")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(reset_analysis_stages("unaq-2026_paneles_solares"))
