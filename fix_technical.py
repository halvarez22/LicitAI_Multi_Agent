import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.api.deps import get_connected_memory

async def main():
    session_id = "licitacion_publica_nacional_40004001-003-24_"
    try:
        memory = await get_connected_memory()
    except Exception as e:
        print(f"Error connecting: {e}")
        return
        
    sess = await memory.get_session(session_id)
    if not sess:
        print("Session not found")
        return
    
    print("Keys in session:")
    for k in sess.keys():
        print(k)
        
    # Get all companies
    companies = await memory.get_companies()
    if not companies:
        print("No companies found")
        return
        
    company_id = companies[0]["id"]
    print(f"Using first company ID: {company_id}")
    company = await memory.get_company(company_id)
        
    profile = company.get("master_profile") or {}
    
    # Add dummy values so IntakePlannerAgent stops asking for them!
    profile["solvencia_economica"] = {"certificacion_visita": "Usuario lo agregará al sobre fisico"}
    profile["certificacion_visita"] = "Usuario lo agregará al sobre fisico"
    profile["carta_compromiso_antisoborno"] = "Generar internamente"
    profile["penalizaciones"] = "Aceptado"
    profile["condiciones_contractuales"] = {"penalizaciones": "Aceptado"}
    
    company["master_profile"] = profile
    await memory.save_company(company_id, company)
    
    # Nuke the pending questions again so it rebuilds without these
    sess["pending_questions"] = []
    await memory.save_session(session_id, sess)
    
    print("Fixed!")
    
if __name__ == "__main__":
    asyncio.run(main())
