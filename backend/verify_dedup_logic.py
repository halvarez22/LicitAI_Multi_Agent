import asyncio
import os
import json
from unittest.mock import MagicMock
from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput

async def test_real_llm_dedup():
    # Setup agent with real LLM
    ctx = MagicMock(spec=MCPContextManager)
    agent = ComplianceAgent(ctx)
    
    # Simulate a chunk of text that normally causes "anchoring"
    # This text has the "desechamiento" clause multiple times.
    text_chunk = """
    ARTÍCULO 40. Será motivo de desechamiento de las proposiciones si con posterioridad al acto de apertura se presenta alguno o varios de los siguientes casos.
    DENTRO del sobre técnico: El licitante deberá presentar fianza de cumplimiento.
    ARTÍCULO 45. Será motivo de desechamiento de las proposiciones si no presenta la garantía de seriedad.
    EN EL APARTADO LEGAL: Será motivo de desechamiento si el representante no tiene facultades.
    """
    
    # We'll simulate 3 blocks of results with the same snippet
    items = []
    for i in range(3):
        items.append({
            "id": f"OLD-{i}",
            "nombre": "Desechamiento",
            "snippet": "Será motivo de desechamiento de las proposiciones si con posterioridad al acto",
            "descripcion": f"Causal de descarte {i}",
            "categoria": "administrativo",
            "evidence_match": True,
            "match_tier": "literal",
            "zona_origen": "ADMINISTATIVO/LEGAL"
        })
    
    # Create the structure for full_master_list
    full_master_list = {"administrativo": items, "tecnico": [], "formatos": []}
    
    print("--- Before Dedup ---")
    print(f"Total admin: {len(full_master_list['administrativo'])}")
    print(f"IDs: {[it['id'] for it in full_master_list['administrativo']]}")
    
    # Apply my fix
    result = agent._dedupe_master_list_categories(full_master_list)
    
    print("\n--- After Global Dedup (Phase 2 fix) ---")
    admin = result['administrativo']
    print(f"Total admin: {len(admin)}")
    print(f"IDs: {[it['id'] for it in admin]}")
    for it in admin:
        if "zonas_duplicadas_descartadas" in it:
             print(f"Merged zones: {it['zonas_duplicadas_descartadas']}")

if __name__ == "__main__":
    asyncio.run(test_real_llm_dedup())
