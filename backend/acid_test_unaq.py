import asyncio
import sys
sys.path.append(".")
from app.api.deps import get_connected_memory
from app.services.vector_service import VectorDbServiceClient

async def acid_test():
    session_id = "unaq-2026_paneles_solares"
    
    print("="*60)
    print("PRUEBA DE ÁCIDO: UNAQ Paneles Solares")
    print("="*60)
    
    # 1. Prueba de ADN: qué hay en ChromaDB
    v = VectorDbServiceClient()
    coll, _ = v._pick_vector_collection(session_id)
    if coll:
        count = coll.count()
        print(f"\n📊 CHUNKS EN CHROMADB: {count}")
        
        # Muestra 3 fragmentos aleatorios
        sample = coll.get(limit=3, where={"session_id": session_id})
        print("\n🧬 MUESTRA DE ADN (primeros 3 chunks):")
        for i, doc in enumerate(sample.get("documents", [])):
            meta = sample.get("metadatas", [])[i] if sample.get("metadatas") else {}
            print(f"\n  Chunk {i+1} [Página {meta.get('page','?')} | Fuente: {meta.get('source','?')}]:")
            print(f"  {doc[:200]}...")
    else:
        print("❌ Sin colección en ChromaDB")
    
    print("\n" + "="*60)
    
    # 2. Prueba de Compliance: qué detectó el sistema
    m = await get_connected_memory()
    s = await m.get_session(session_id) or {}
    tasks = s.get("tasks_completed", [])
    
    comp_task = next(
        (t for t in reversed(tasks) if t.get("task") == "stage_completed:compliance"),
        None
    )
    
    if comp_task:
        data = comp_task.get("result", {}).get("data", {})
        print("\n📋 COMPLIANCE DETECTADO:")
        total = 0
        for zone in ("administrativo", "tecnico", "formatos", "garantias"):
            items = data.get(zone) or []
            if items:
                print(f"\n  Zona '{zone}' ({len(items)} ítems):")
                for it in items[:5]:
                    name = it.get("nombre", "??")
                    snippet = str(it.get("snippet", ""))[:80]
                    print(f"    - {name}")
                    print(f"      Snippet: {snippet}")
                total += len(items)
        print(f"\n  TOTAL ÍTEMS DETECTADOS: {total}")
        
        print("\n🔍 VERIFICACIÓN DE OPINIÓN ESTATAL Y HEURÍSTICAS:")
        forced_count = 0
        leg_fis_forced = 0
        for zone in ("administrativo", "tecnico", "formatos", "garantias"):
            for it in (data.get(zone) or []):
                nombre = it.get("nombre", "").lower()
                is_forced = it.get("forced_by_must_have", False)
                if is_forced:
                    forced_count += 1
                if "opini" in nombre and ("estatal" in nombre or "querétaro" in nombre or "queretaro" in nombre):
                    print(f"  🎯 ENCONTRADO: {it.get('nombre')} -> Acción: {it.get('tipo_accion')} | Forced: {is_forced}")
                if "leg_" in nombre or "fis_" in nombre:
                    if is_forced and it.get("tipo_accion") == "generar":
                        leg_fis_forced += 1
                        print(f"  ⚠️ ERROR HEURÍSTICA: {it.get('nombre')} forzado a generar.")
        
        print(f"  📈 Total items forced_by_must_have: {forced_count}")
        print(f"  🐛 Total LEG_/FIS_ forzados a generar erróneamente: {leg_fis_forced}")

        # Palabra clave de contaminación
        full_text = str(data).lower()
        contaminated_keywords = ["madera", "chihuahua", "luminaria", "encino", "pino", "aserradero", "municipio de madera"]
        found_contamination = [kw for kw in contaminated_keywords if kw in full_text]
        if found_contamination:
            print(f"\n🚨 CONTAMINACIÓN DETECTADA: {found_contamination}")
        else:
            print("\n✅ SIN CONTAMINACIÓN: No hay rastro de Madera/Chihuahua/Luminarias")
        
        # Palabras clave de UNAQ legítimas
        unaq_keywords = ["unaq", "panel", "solar", "universidad aeronáutica", "querétaro", "fotovoltaico"]
        found_unaq = [kw for kw in unaq_keywords if kw in full_text]
        print(f"🎯 SEÑALES UNAQ ENCONTRADAS: {found_unaq}")
    else:
        print("❌ No se encontró compliance en Postgres")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(acid_test())
