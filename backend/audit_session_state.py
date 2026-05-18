import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def audit():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "vigilancia_issste"
    state = await m.get_session(session_id)
    
    if not state:
        print(f"No se encontró la sesión {session_id}")
        return

    # Buscar el resultado económico más reciente
    tasks = state.get("tasks_completed", [])
    economic_data = {}
    for t in reversed(tasks):
        if t.get("task") == "stage_completed:economic":
            economic_data = t.get("result", {}).get("data", {})
            break
    
    # Si no hay en tasks_completed, buscar en el último output guardado
    if not economic_data:
        # Intentar extraer del último resultado del agente si existe
        pass

    items = economic_data.get("items", [])
    gaps = economic_data.get("missing", [])
    
    print(f"--- REPORTE DE AUDITORÍA: {session_id} ---")
    print(f"TOTAL CONCEPTOS DETECTADOS: {len(items) + len(gaps)}")
    print(f"CONCEPTOS CON PRECIO (OK): {len(items)}")
    print(f"CONCEPTOS SIN PRECIO (GAPS): {len(gaps)}")
    
    if items:
        print("\n--- CONCEPTOS YA COTIZADOS ---")
        for it in items[:5]:
            print(f"  [OK] {it.get('concepto')} -> ${it.get('precio_unitario')}")

    if gaps:
        print("\n--- PRIMEROS 15 GAPS (BLOQUEANTES) ---")
        for i, g in enumerate(gaps[:15]):
            print(f"  {i+1}. {g.get('concepto')} (ID: {g.get('concepto_id')})")
            
    # Verificar si hay algo en economic_user_inputs
    user_inputs = state.get("economic_user_inputs", {})
    print(f"\n--- OVERRIDES EN CHAT ({len(user_inputs)}) ---")
    for k, v in user_inputs.items():
        if k == "concept_prices":
            print(f"  Precios manuales: {len(v)}")
        else:
            print(f"  Parámetro: {k} = {v}")

if __name__ == "__main__":
    asyncio.run(audit())
