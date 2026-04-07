import pytest
from unittest.mock import AsyncMock
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
async def test_generate_checklist_logic_hito7():
    """Hito 7: Valida la lógica de conciliación entre requisitos y documentos generados."""
    
    mem = AsyncMock()
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    # 1. Datos simulados de requerimientos (Compliance Master List)
    compliance_master = {
        "administrativo": [
            {"id": "1.1", "nombre": "Carta de Confidencialidad", "tipo": "administrativo"},
            {"id": "1.2", "nombre": "Registro Patronal IMSS", "tipo": "administrativo"}
        ],
        "tecnico": [
            {"id": "T1", "nombre": "Propuesta Técnica Detallada", "tipo": "técnico"}
        ]
    }

    # 2. Datos simulados de documentos generados
    gen_docs = {
        "administrativa": [
            {"nombre": "1.1_Carta_Confidencialidad.docx", "ruta": "/tmp/1.1_Carta_Confidencialidad.docx"}
        ],
        "tecnica": [
            {"nombre": "Propuesta_Tecnica_Detallada_Final.docx", "ruta": "/tmp/Propuesta_Tecnica_Detallada_Final.docx"}
        ]
        # Falta el 1.2 Registro Patronal
    }

    # 3. Ejecutar generación de checklist
    checklist = await orch._generate_checklist(
        "sess_check", 
        {"compliance_master_list": compliance_master, "documentos_generados": gen_docs}, 
        {}
    )

    # 4. Validar resultados
    assert len(checklist) == 3
    
    # ID 1.1 -> fulfilled (coincidencia por ID parcial en nombre de archivo)
    c1 = next(c for c in checklist if c["req_id"] == "1.1")
    assert c1["status"] == "fulfilled"
    assert c1["file"] == "1.1_Carta_Confidencialidad.docx"

    # ID 1.2 -> missing (no hay archivo)
    c2 = next(c for c in checklist if c["req_id"] == "1.2")
    assert c2["status"] == "missing"
    assert c2["file"] is None

    # tecnico T1 -> fulfilled (coincidencia por nombre textual parcial)
    c3 = next(c for c in checklist if c["req_id"] == "T1")
    assert c3["status"] == "fulfilled"
    assert "Propuesta" in c3["file"]
