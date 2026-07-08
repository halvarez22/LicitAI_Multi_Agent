import asyncio
import sys
import os
from pathlib import Path

sys.path.append(".")
from app.api.deps import get_connected_memory
from app.services.vector_service import VectorDbServiceClient

async def nuke_session_data(session_id: str):
    print(f"🔥 INICIANDO PURGA TOTAL PARA: {session_id}")
    
    # 1. Limpiar Postgres (Memoria)
    memory = await get_connected_memory()
    session = await memory.get_session(session_id)
    if session:
        print("🧹 Limpiando Postgres: compliance_results y tasks...")
        session["compliance_results"] = {}
        session["tasks_completed"] = []
        session["document_candidates_v1"] = {}
        session["document_candidates_final"] = {}
        if "dictamen" in session:
            session["dictamen"]["fastTrackDocumentCandidates"] = {}
            
        await memory.save_session(session_id, session)
        print("✅ Postgres saneado.")
    else:
        print("⚠️ Sesión no encontrada en Postgres.")
    
    # 2. Limpiar ChromaDB (Vectores)
    print("🧹 Limpiando ChromaDB: eliminando colección...")
    vector_client = VectorDbServiceClient()
    success = vector_client.delete_collection(session_id)
    if success:
        print("✅ Colección ChromaDB eliminada.")
    else:
        print("⚠️ No se pudo eliminar la colección (podría no existir).")
        
    # 3. Limpiar Archivos Globales
    ghost_file = "/app/bases_leibles.txt"
    if os.path.exists(ghost_file):
        print(f"🧹 Eliminando fantasma global: {ghost_file}")
        os.remove(ghost_file)
        print("✅ Archivo global eliminado.")
        
    await memory.disconnect()
    print("\n✨ FASE 1 COMPLETADA: Entorno listo para re-ingesta limpia.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python nuke_session.py SESSION_ID")
        sys.exit(1)
    asyncio.run(nuke_session_data(sys.argv[1]))
