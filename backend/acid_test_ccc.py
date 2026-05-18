"""
Prueba de Ácido: CCC sobre los 269 ítems reales de UNAQ.
Corre directo contra Postgres — no requiere re-ejecutar el pipeline.
"""
import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory
from app.services.compliance_consolidation_service import ComplianceConsolidator

async def acid_test_ccc():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    s = await m.get_session(session_id) or {}
    tasks = s.get("tasks_completed", [])

    comp_task = next(
        (t for t in reversed(tasks) if t.get("task") == "stage_completed:compliance"),
        None
    )
    if not comp_task:
        print("❌ No hay compliance task en Postgres")
        await m.disconnect()
        return

    raw_data = comp_task.get("result", {}).get("data", {})
    total_raw = sum(len(v) for v in raw_data.values() if isinstance(v, list))
    print(f"📥 Ítems brutos: {total_raw}")

    result = await ComplianceConsolidator().consolidate(raw_items=raw_data, session_id=session_id)
    meta   = result.get("_meta", {})

    print(f"\n{'='*65}")
    print(f"  RESULTADO CCC — {session_id}")
    print(f"{'='*65}")
    print(f"  Raw items       : {meta.get('total_raw_items')}")
    print(f"  Consolidados    : {meta.get('total_consolidados')}")
    print(f"  Con Anexo expl. : {meta.get('items_con_anexo')}")
    print(f"  Agrupados semánt: {meta.get('items_agrupados_semanticamente')}")
    print(f"  Latencia        : {meta.get('latencia_ms')} ms")

    for zone_key in ("sobre_1_tecnico", "sobre_2_economico", "requisitos_legales", "otros_requisitos_criticos"):
        items = result.get(zone_key, [])
        label = zone_key.replace("_", " ").upper()
        print(f"\n  📂 {label} ({len(items)} entregables)")
        for d in items:
            anexo  = f"[{d['numero_anexo']}]" if d.get("numero_anexo") else "[sin #]"
            fused  = d.get("items_fusionados", 1)
            conf   = d.get("confidence", 0)
            evid   = len(d.get("evidencia_original", []))
            print(f"    {anexo:15} {d['nombre_canonico'][:55]:<55} ({fused} fusionados, conf={conf:.2f}, evid={evid})")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(acid_test_ccc())
