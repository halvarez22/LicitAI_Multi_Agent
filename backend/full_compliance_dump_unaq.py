import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory

async def full_compliance_dump():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    s = await m.get_session(session_id) or {}
    tasks = s.get("tasks_completed", [])
    
    comp_task = next(
        (t for t in reversed(tasks) if t.get("task") == "stage_completed:compliance"),
        None
    )
    
    if not comp_task:
        print("❌ No hay compliance task")
        await m.disconnect()
        return
    
    data = comp_task.get("result", {}).get("data", {})
    
    print("=" * 70)
    print("REPORTE COMPLETO DE COMPLIANCE - UNAQ 001-IR/UNAQ/2026")
    print("=" * 70)
    
    grand_total = 0
    for zone in ("administrativo", "tecnico", "formatos", "garantias"):
        items = data.get(zone) or []
        if not items:
            print(f"\n--- ZONA: {zone.upper()} (0 ítems) ---")
            continue
        
        print(f"\n--- ZONA: {zone.upper()} ({len(items)} ítems) ---")
        for i, it in enumerate(items, 1):
            nombre = it.get("nombre", "??")
            snippet = str(it.get("snippet", ""))[:100]
            tipo = it.get("tipo_item", it.get("tipo", ""))
            confidence = it.get("confidence", it.get("confianza", ""))
            print(f"  {i:>3}. [{tipo}] {nombre}")
            if snippet:
                print(f"       Snippet: {snippet}")
        grand_total += len(items)
    
    print(f"\n{'='*70}")
    print(f"TOTAL GENERAL: {grand_total} ítems")
    print(f"{'='*70}")
    
    # También verificar document_candidates
    candidates = s.get("document_candidates_v1") or s.get("document_candidates_final") or {}
    print(f"\n📋 DOCUMENT CANDIDATES (UI) - {len(candidates)} zonas")
    for zone, items in candidates.items():
        if isinstance(items, list):
            print(f"  {zone}: {len(items)} candidatos")
            for it in items[:5]:
                nombre = it.get("nombre", "??") if isinstance(it, dict) else str(it)
                print(f"    - {nombre}")
            if len(items) > 5:
                print(f"    ... y {len(items)-5} más")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(full_compliance_dump())
