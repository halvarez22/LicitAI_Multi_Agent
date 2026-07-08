import asyncio
import os
import sys

# Añadir el path actual para que pueda importar app
sys.path.append(os.getcwd())

from app.services.vector_service import VectorDbServiceClient

def test_rag():
    print("Iniciando prueba de RAG...")
    try:
        client = VectorDbServiceClient()
        if not client.client:
            print("Error: No se pudo conectar a ChromaDB (cliente es None)")
            return

        print(f"Conectado a ChromaDB: {client.client.heartbeat()}")
        
        session_id = "test_session_123"
        texts = ["El objeto de esta licitación es el suministro de luminarias LED.", "La vigencia del contrato es de 12 meses."]
        metadatas = [{"source": "bases.pdf", "page": 1}, {"source": "bases.pdf", "page": 2}]
        
        print(f"Añadiendo textos a la colección {session_id}...")
        success = client.add_texts(session_id, texts, metadatas)
        
        if success:
            print("Textos añadidos con éxito.")
            print("Realizando búsqueda...")
            results = client.query_texts(session_id, "¿Cuál es el objeto de la licitación?")
            print("Resultados de búsqueda:")
            for i, doc in enumerate(results.get("documents", [])):
                print(f" - Resultado {i+1}: {doc}")
        else:
            print("Error al añadir textos.")
            
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")

if __name__ == "__main__":
    test_rag()
