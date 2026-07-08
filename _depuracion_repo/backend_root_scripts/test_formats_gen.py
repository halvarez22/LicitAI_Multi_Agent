import asyncio
import sys
import os
from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory
from app.contracts.agent_contracts import AgentInput

async def test_gen():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    ctx = MCPContextManager(m)
    agent = FormatsAgent(ctx)
    
    # ID de sesión activo de los metadatos
    session_id = '10468fa0-a136-4cde-8c8b-a350376682b1'
    
    # Preparamos el input respetando el contrato estricto de Pydantic
    agent_input = AgentInput(
        session_id=session_id,
        company_id='comp_test_001',
        company_data={'name': 'Empresa de Seguridad S.A. de C.V.'},
        mode='full' # Modo completo para que escanee y genere
    )
    
    print(f'--- INICIANDO SANITY CHECK EN SESIÓN {session_id} ---')
    try:
        result = await agent.process(agent_input)
        print(f'STATUS: {result.status}')
        if result.data:
            files = result.data.get("generated_files", [])
            print(f'TOTAL ARCHIVOS GENERADOS: {len(files)}')
            for f in files:
                print(f'  [OK] {os.path.basename(f.get("file_path"))}')
        else:
            print('RESULTADO: No se generaron archivos (posible bloqueo de Quality Gate o lista vacía)')
            if result.message:
                print(f'MENSAJE: {result.message}')
                
    except Exception as e:
        print(f'ERROR CRITICO DURANTE LA PRUEBA: {e}')

if __name__ == "__main__":
    asyncio.run(test_gen())
