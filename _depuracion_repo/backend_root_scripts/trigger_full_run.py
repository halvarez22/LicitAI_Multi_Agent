import asyncio
import logging
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory
from app.contracts.agent_contracts import AgentInput

# Configurar logging
logging.basicConfig(level=logging.INFO)

async def trigger_full_run():
    # Inicialización correcta: el adaptador YA implementa MemoryRepository
    repo = MemoryAdapterFactory.create_adapter()
    await repo.connect()
    ctx = MCPContextManager(repo)
    
    orch = OrchestratorAgent(ctx)
    
    session_id = 'vigilancia_issste'
    state = await ctx.memory.get_session(session_id)
    if not state:
        print("Error: No se encontró la sesión.")
        return
        
    company_data = state.get('company_data', {})
    
    # IMPORTANTE: Modo FULL para reconstruir todo
    agent_input = AgentInput(
        session_id=session_id,
        job_id='manual_full_recovery_004',
        mode='full',
        company_data=company_data,
        resume_generation=False
    )
    
    print(f"[*] Iniciando Pipeline FULL para {session_id}...")
    try:
        result = await orch.process(session_id, agent_input.model_dump())
        print(f"[*] Pipeline finalizado con status: {result.get('status')}")
        
        # Verificar hitos
        fresh_state = await ctx.memory.get_session(session_id)
        tasks = [t.get('task') for t in fresh_state.get('tasks_completed', [])]
        print(f"[*] Hitos en memoria (completed_stages): {tasks}")
        
        # Verificación de ítems técnicos
        master_list = fresh_state.get('master_compliance_list', {})
        tech = master_list.get('tecnico', []) or master_list.get('técnico', [])
        print(f"[*] Ítems técnicos encontrados tras filtrado: {len(tech)}")
        for i, item in enumerate(tech[:10]):
             print(f"  {i+1}. {item.get('label') or item.get('descripcion')[:50]}...")

    except Exception as e:
        print(f"Error fatal durante el pipeline: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(trigger_full_run())
