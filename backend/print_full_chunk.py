import sys
import os

sys.path.append(os.getcwd())
from app.services.vector_service import VectorDbServiceClient

client = VectorDbServiceClient()
session_id = "vigilancia_hospital_regional_issste_leon"
q = "¿Cuál es la consecuencia si no asiste a la Visita de Instalaciones?"
res = client.query_texts(session_id, q, n_results=1)

print("--- FULL CHUNK TEXT ---")
print(res.get("documents", [])[0])
print("--- END CHUNK TEXT ---")
