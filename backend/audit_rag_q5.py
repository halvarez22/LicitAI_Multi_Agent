import sys
import os

sys.path.append(os.getcwd())
from app.services.vector_service import VectorDbServiceClient

def run_audit():
    client = VectorDbServiceClient()
    session_id = "vigilancia_hospital_regional_issste_leon"
    
    queries = [
        "6.1 REQUISITOS TÉCNICOS",
        "6.1 DOCUMENTACIÓN COMPLEMENTARIA",
        "REPSE",
        "Acreditación de Seguridad",
        "Registro de Prestadoras de Servicios Especializados"
    ]
    
    print("=== AUDITORÍA RAG: PREGUNTA 5 (REPSE / 6.1) ===")
    for q in queries:
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
            print(f"  Texto: {text[:250]}...")

if __name__ == "__main__":
    run_audit()
