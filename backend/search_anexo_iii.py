import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.services.vector_service import VectorDbServiceClient

async def search():
    session_id = "unaq-2026_paneles_solares"
    query = "Anexo III"
    client = VectorDbServiceClient()
    
    print(f"Searching for '{query}' in session {session_id}...")
    results = client.query_texts(session_id, query, n_results=10)
    
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    
    if not docs:
        print("No results found in vector store.")
        return
        
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        print(f"--- Match {i+1} (Source: {meta.get('source')}, Page: {meta.get('page')}) ---")
        print(doc[:500])
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(search())
