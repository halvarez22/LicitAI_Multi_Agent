import sys
import os

sys.path.append(os.getcwd())
from app.services.vector_service import VectorDbServiceClient

client = VectorDbServiceClient()
session_id = "vigilancia_hospital_regional_issste_leon"

queries = [
    "¿Qué moneda y qué formato de precios son de cumplimiento obligatorio para presentar nuestra propuesta económica?",
    "truncamiento redondeo decimales",
    "precios fijos",
    "Cédula de la Propuesta Económica"
]

print("=== AUDITORÍA RAG: PREGUNTA 3 (MONEDA Y FORMATO) ===")
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
