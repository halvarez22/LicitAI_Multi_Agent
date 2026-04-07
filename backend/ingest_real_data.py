import sys
import os
import re

sys.path.append("/app")
from app.services.vector_service import VectorDbServiceClient

def ingest_real_data():
    txt_path = "/app/bases_leibles.txt"
    session_id = "sesion-experto-madera"
    
    if not os.path.exists(txt_path):
        print(f"Error: No se encuentra {txt_path}")
        return

    with open(txt_path, "rb") as f:
        content_bytes = f.read()
        # Probar varias decodificaciones comunes en OCR
        try:
            content = content_bytes.decode('utf-8')
        except:
            content = content_bytes.decode('latin-1', errors='ignore')

    # Regex súper permisiva: tres iguales, cualquier cosa, GINA, espacio, número, tres iguales
    # Capturamos el número
    # r'={3}.*?GINA\s+(\d+)\s+={3}'
    parts = re.split(r'={3}.*?GINA\s+(\d+)\s+={3}', content)
    
    vector_client = VectorDbServiceClient()
    total_chunks = 0
    
    # La estructura de parts tras re.split con captura es:
    # [antes_p1, num1, texto1, num2, texto2...]
    
    if len(parts) < 3:
        print("Error: No se detectaron marcadores de página con el regex.")
        return

    for i in range(1, len(parts), 2):
        page_num = parts[i]
        body = parts[i+1]
        
        # Limpieza básica
        body = body.strip()
        if not body: continue

        # Chunks de 1000 con solape de 200
        size = 1000
        step = 800
        
        for start in range(0, len(body), step):
            chunk = body[start:start+size].strip()
            if len(chunk) > 40:
                vector_client.add_texts(session_id, [chunk], [{
                    "source": "Bases_Madera.pdf",
                    "session_id": session_id,
                    "page": page_num,
                    "doc_id": "doc_madera_master"
                }])
                total_chunks += 1
        
        if int(page_num) % 10 == 0 or int(page_num) == 1:
            print(f"Indexada Página {page_num}...")

    print(f"\n✅ CONOCIMIENTO INYECTADO: {total_chunks} fragmentos de las 53 páginas reales.")

if __name__ == "__main__":
    ingest_real_data()
