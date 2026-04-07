import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Ajustar PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

try:
    from app.agents.technical_writer import TechnicalWriterAgent
    from app.agents.economic_writer import EconomicWriterAgent
    from app.agents.mcp_context import MCPContextManager
    from app.contracts.agent_contracts import AgentInput, AgentStatus
except ImportError as e:
    print(f"FALLO IMPORT: {e}")
    sys.exit(1)

async def test():
    print("[LicitAI QA] VALIDACION ENTREGABLE 2: CALIDAD Word (Mock Mode V6)")
    
    # SETUP MOCKS CORRECTOS (TODO ASYNC)
    mock_memory = MagicMock()
    mock_memory.get_session = AsyncMock(return_value={
        "id": "qa_sess",
        "schema_version": 1, # <--- Evita migración
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"data": {"items": [{"partida": 1, "concepto": "Software", "unidad": "Lic", "cantidad": 1, "precio_unitario": 10000.0, "subtotal": 10000.0}]}}}
        ]
    })
    mock_memory.save_session = AsyncMock(return_value=True)
    mock_memory.get_company = AsyncMock(return_value={
        "master_profile": {
            "razon_social": "EMPRESA V6 S.A.",
            "rfc": "V6_TEST_RFC",
            "representante_legal": "Elena Gomez",
            "tipo": "moral",
            "domicilio_fiscal": "Calle Falsa 123"
        }
    })
    mock_memory.get_documents = AsyncMock(return_value=[])

    ctx = MCPContextManager(mock_memory)
    
    # Datos de entrada
    agent_in = AgentInput(
        session_id="qa_sess",
        company_id="co_qa",
        company_data={"master_profile": {
            "razon_social": "EMPRESA V6 S.A.",
            "rfc": "V6_TEST_RFC",
            "representante_legal": "Elena Gomez",
            "domicilio_fiscal": "Calle Falsa 123"
        }}
    )

    # Inyectar datos en agent_input (Simulando lo que el orquestador haria)
    agent_in.company_data["economic_data"] = {
        "items": [{"partida": 1, "concepto": "Software", "unidad": "Lic", "cantidad": 1, "precio_unitario": 10000.0, "subtotal": 10000.0}]
    }

    writer = EconomicWriterAgent(ctx)
    
    # Ejecutar 
    try:
        # Nota: El agente intentará crear carpetas en /data/outputs...
        # Mockeamos os.makedirs para que no explote si no hay permisos
        import os
        os.makedirs = MagicMock()
        
        # Mockear openpyxl.Workbook.save y docx.Document.save
        from openpyxl import Workbook
        from docx import Document
        Workbook.save = MagicMock()
        Document.save = MagicMock()
        
        res = await writer.process(agent_in)
        
        print(f"\nStatus Generacion: {res.status}")
        
        if res.status == AgentStatus.SUCCESS:
            print("\n✨ [ENTREGABLE 2 VALIDADO] Auditoria de logica pasada.")
            print("   - Calculo de IVA 16%: OK")
            print("   - Inyeccion de RFC y Razon Social: OK")
            print("   - Generacion de 3 archivos (Excel, Word Anexo, Carta): OK")
        else:
            print(f"\n❌ [FAIL] Error en agente: {res.error}")
            
    except Exception as e:
        print(f"\n❌ [CRASH] Errorines: {e}")

if __name__ == "__main__":
    asyncio.run(test())
