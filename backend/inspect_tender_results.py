import asyncio
import os
import sys
import json

# Añadir el path del backend para importar los módulos
sys.path.append(r"c:\LicitAI_Multi_Agent\licitaciones-ai\backend")

from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter

async def inspect_tender_results():
    db_url = "postgresql://postgres:postgres@localhost:5432/licitaciones"
    adapter = PostgresMemoryAdapter(connection_string=db_url)
    
    # IMPORTANTE: Conectar antes de usar
    connected = await adapter.connect()
    if not connected:
        print("Error: No se pudo conectar a la base de datos.")
        return
    
    # Obtener todas las sesiones para encontrar la más reciente
    sessions = await adapter.list_sessions()
    if not sessions:
        print("No hay sesiones en la base de datos.")
        return

    # Tomamos la primera (Postgres suele devolver por ID o fecha)
    session_id = sessions[0]["id"]
    print(f"Inspeccionando Sesión: {session_id}")
    
    state = await adapter.get_session(session_id)
    if not state:
        print("No se pudo cargar el estado de la sesión.")
        return

    # 1. Ver la lista de cumplimiento original
    compliance = state.get("master_compliance_list", {})
    if isinstance(compliance, dict) and "data" in compliance:
        compliance = compliance["data"]
        
    counts_raw = {
        "administrativo": len(compliance.get("administrativo", [])),
        "tecnico": len(compliance.get("tecnico", [])),
        "formatos": len(compliance.get("formatos", []))
    }
    print(f"\n--- Resultados RAW (ComplianceAgent) ---")
    print(json.dumps(counts_raw, indent=2))

    # 2. Ver la lista de CANDIDATOS
    from app.services.document_candidate_list_service import build_candidate_document_list
    candidates_data = build_candidate_document_list(compliance)
    candidates = candidates_data.get("candidate_document_list", [])

    print(f"Total Candidatos Filtrados: {len(candidates)}")
    
    generar = [c for c in candidates if c.get("tipo_accion_final") == "generar"]
    fisico = [c for c in candidates if c.get("tipo_accion_final") == "presentar_fisico"]
    informativo = [c for c in candidates if c.get("tipo_accion_final") == "informativo"]
    
    print(f"  - A Generar: {len(generar)}")
    print(f"  - Presentar Físico: {len(fisico)}")
    print(f"  - Informativos: {len(informativo)}")

    print("\n--- DETALLE DE DOCUMENTOS A GENERAR ---")
    for i, doc in enumerate(generar):
        print(f"{i+1}. [{doc.get('document_id')}] {doc.get('nombre')}")
    
    # 3. Datos de la empresa (Domicilio)
    print("\n--- PERFIL DE EMPRESA (DOMICILIO) ---")
    company_id = state.get("company_id")
    if company_id:
        company = await adapter.get_company(company_id)
        if company:
            profile = company.get("master_profile", {})
            print(f"RFC: {profile.get('rfc')}")
            print(f"Domicilio Fiscal: {profile.get('domicilio_fiscal')}")
            print(f"Dirección Estructurada: {json.dumps(profile.get('direccion_estructurada'), indent=2)}")

if __name__ == "__main__":
    asyncio.run(inspect_tender_results())
