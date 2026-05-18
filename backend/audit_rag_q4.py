import sys
import os

sys.path.append(os.getcwd())
from app.services.vector_service import VectorDbServiceClient

def run_audit():
    client = VectorDbServiceClient()
    session_id = "vigilancia_hospital_regional_issste_leon"
    
    q = "¿Cuántos elementos de vigilancia se solicitan en total para el turno de 24 horas en el área específica de Entrada Principal?"
    
    print("=== AUDITORÍA RAG: PREGUNTA 4 (ENTRADA PRINCIPAL) ===")
    print(f"\nQUERY: '{q}'")
    res = client.query_texts(session_id, q, n_results=5)
    
    docs = res.get("documents", [])
    metadatas = res.get("metadatas", [])
    distances = res.get("distances", [])
    
    for i in range(len(docs)):
        dist = distances[i]
        sim_score = (1.0 - (dist / 2.0)) * 100
        meta = metadatas[i]
        src = meta.get("source", "N/A")
        page = meta.get("page", "N/A")
        text = docs[i].replace('\n', ' ')
        print(f"  [Chunk {i+1}] Score: {sim_score:.2f}% (Dist: {dist:.4f}) | Page: {page} | Source: {src}")
        print(f"  Texto: {text[:400]}...\n")

if __name__ == "__main__":
    run_audit()
