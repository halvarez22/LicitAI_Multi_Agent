import os
import sys

# Añadir el path del backend
sys.path.append(r"c:\LicitAI_Multi_Agent\licitaciones-ai\backend")

from app.services.vector_service import VectorDbServiceClient

def fetch_bases_content():
    v = VectorDbServiceClient()
    session_id = 'concurso_por_invitacin_restringida_nmero_001-irunaq2026_primera'
    
    # Buscamos específicamente las secciones de documentación y anexos
    queries = [
        "documentación que integra la propuesta técnica",
        "documentación que integra la propuesta económica",
        "anexos formatos obligatorios",
        "documentación administrativa",
        "lista de anexos"
    ]
    
    all_content = []
    for q in queries:
        res = v.query_texts(session_id, q, n_results=10)
        docs = res.get("documents", [])
        for doc in docs:
            all_content.append(doc)
            
    # Guardar en un archivo para que yo lo lea
    with open("bases_content_raw.txt", "w", encoding="utf-8") as f:
        f.write("\n\n--- NUEVO BLOQUE ---\n\n".join(all_content))
    
    print(f"Contenido extraído: {len(all_content)} fragmentos.")

if __name__ == "__main__":
    fetch_bases_content()
