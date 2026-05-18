import pytest
from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager

class MockMemory:
    async def get_session(self, session_id): return {}
    async def save_session(self, session_id, data): pass
    async def record_task_completion(self, session_id, task, data): pass

@pytest.mark.asyncio
async def test_compliance_unknown_fallback_to_informative():
    # Setup
    ctx = MCPContextManager(MockMemory())
    agent = ComplianceAgent(ctx)
    
    # Simular ítems ruidosos (sin clasificar por el LLM)
    raw_items = [
        {"nombre": "Regla de prueba 1", "descripcion": "Esta es una regla informativa de longitud suficiente para pasar el filtro", "tipo_accion": "unknown"},
        {"nombre": "Regla de prueba 2", "descripcion": "Otra regla sin accion que tambien tiene longitud suficiente para ser procesada", "tipo_accion": ""},
        {"nombre": "Documento Critico", "descripcion": "Debe ser generado obligatoriamente segun las bases de la licitacion", "tipo_accion": "generar"}
    ]
    
    # Mock de contexto de triage vacío para evitar matches de matriz en este test simple
    triage_context = {"law": "LAASSP", "tender_category": "BIENES"}
    
    # Ejecutar reducción
    # Nota: _reduce_zone_items espera (zone_name, items, full_context, triage_context)
    reduced_items, metrics = agent._reduce_zone_items(
        "TEST_ZONE", 
        raw_items, 
        "Contexto de prueba largo para evitar descartes por longitud...",
        triage_context=triage_context
    )
    
    # Verificaciones
    # Los 2 primeros deben haber pasado a 'informativo'
    # El 3ero debe permanecer como 'generar'
    
    informativos = [it for it in reduced_items if it["tipo_accion"] == "informativo"]
    generar = [it for it in reduced_items if it["tipo_accion"] == "generar"]
    unknowns = [it for it in reduced_items if it["tipo_accion"] == "unknown"]
    
    assert len(informativos) >= 2, f"Se esperaban al menos 2 informativos, se obtuvieron: {len(informativos)}"
    assert len(generar) == 1
    assert len(unknowns) == 0, "No deberían quedar ítems en 'unknown' tras el fallback"
    
    # Verificar trazabilidad
    assert "fallback_to_informative" in informativos[0]["quality_flags"]
    
    print("\n✅ Test de Fallback a Informativo: PASSED")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_compliance_unknown_fallback_to_informative())
