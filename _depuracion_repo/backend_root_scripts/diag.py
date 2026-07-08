import asyncio
import os
from app.services.ocr_service import OCRServiceClient

async def diag():
    # Buscamos un archivo que ya esté en /data/uploads del backend
    # Según nuestro listado anterior, este existe:
    file_path = "/data/uploads/00165194-7328-4bb5-a235-7f10ce882cf6_bases_servicio_limpieza_2024_issste_bcs.pdf"
    
    if not os.path.exists(file_path):
        print(f"❌ Error: El archivo {file_path} no parece existir en el contenedor backend.")
        return
        
    print(f"[*] Iniciando prueba de Agente Extractor sobre: {file_path}")
    client = OCRServiceClient()
    
    start_time = asyncio.get_event_loop().time()
    result = await client.scan_document(file_path)
    end_time = asyncio.get_event_loop().time()
    
    if "error" in result:
        print(f"❌ ERROR DEL AGENTE: {result['error']}")
    else:
        print(f"✅ ÉXITO DEL AGENTE!")
        print(f" - MÉTODO UTILIZADO: {result.get('method')}")
        print(f" - PÁGINAS: {result.get('total_pages')}")
        print(f" - CARACTERES: {len(result.get('extracted_text', ''))}")
        print(f" - TIEMPO: {end_time - start_time:.2f}s")
        
        # Comparación interna rápida
        print("\nMuestra de texto (Primeros 200 chars):")
        print(result.get('extracted_text', '')[:200].replace('\n', ' '))

if __name__ == "__main__":
    asyncio.run(diag())
