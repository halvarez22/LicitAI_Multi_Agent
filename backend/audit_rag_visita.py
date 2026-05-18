import sys
import os

# Set up paths
sys.path.append(os.getcwd())

from app.services.vector_service import VectorDbServiceClient

def run_audit():
    client = VectorDbServiceClient()
    session_id = "vigilancia_hospital_regional_issste_leon"
    
    # Let's test a couple of possible queries the user might have asked
    queries = [
        "¿Cuál es la consecuencia si no asiste a la Visita de Instalaciones?",
        "consecuencia si no asiste",
        "Visita de Instalaciones",
        "cláusula 'e' del artículo 7"
    ]
    
    print("=== AUDITORÍA RAG DE CAJA NEGRA ===")
    for q in queries:
        print(f"\nQUERY: '{q}'")
        res = client.query_texts(session_id, q, n_results=5)
        
        docs = res.get("documents", [])
        metadatas = res.get("metadatas", [])
        distances = res.get("distances", [])
        
        for i in range(len(docs)):
            dist = distances[i]
            # Convert cosine distance to a similarity score percentage (approximate)
            # Distance 0 = 100% similar. 
            sim_score = (1.0 - (dist / 2.0)) * 100
            
            meta = metadatas[i]
            src = meta.get("source", "N/A")
            page = meta.get("page", "N/A")
            text = docs[i].replace('\n', ' ')
            print(f"  [Chunk {i+1}] Score: {sim_score:.2f}% (Dist: {dist:.4f}) | Page: {page} | Source: {src}")
            print(f"  Texto: {text[:200]}...")

if __name__ == "__main__":
    run_audit()
