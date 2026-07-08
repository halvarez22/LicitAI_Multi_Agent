import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check():
    session_id = "licitacion_opm-001-2026_maderas_chihuahiua"
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    # Obtener documentos indexados
    from app.memory.repository import MemoryRepository
    docs = await memory.get_documents(session_id)
    
    total_chars = sum(len(d.get("content", "")) for d in docs)
    print(f"\n📊 --- REPORTE DE EXTRACCIÓN (OCR-VLM) ---")
    print(f"Total Chunks en VectorDB: {len(docs)}")
    print(f"Total Caracteres: {total_chars}")
    
    if docs:
        print("\n--- MUESTRA DEL TEXTO EXTRAÍDO (PÁGINA 1-2) ---")
        full_text = ""
        for d in docs:
            content = d.get("content", {})
            if isinstance(content, dict):
                # Caso 1: Tiene un campo 'text'
                full_text += content.get("text", "")
                # Caso 2: Tiene un campo 'pages' (lista de dicts con 'text')
                pages = content.get("pages", [])
                for pag in pages:
                    full_text += pag.get("text", "")
            elif isinstance(content, str):
                full_text += content
        
        print(f"Longitud total acumulada: {len(full_text)}")
        print(full_text[:3000])
    else:
        print("❌ No se encontraron documentos en la sesión.")
        
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
