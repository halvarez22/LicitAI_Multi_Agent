import asyncio
import logging
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory
from app.contracts.agent_contracts import AgentInput

logging.basicConfig(level=logging.INFO)

async def trigger_generation():
    repo = MemoryAdapterFactory.create_adapter()
    await repo.connect()
    ctx = MCPContextManager(repo)
    
    orch = OrchestratorAgent(ctx)
    session_id = 'vigilancia_issste'
    
    state = await ctx.memory.get_session(session_id)
    if not state:
        print("Error: Sesión no encontrada.")
        return
        
    company_data = state.get('company_data', {})
    
    agent_input = AgentInput(
        session_id=session_id,
        job_id='manual_generation_trigger_001',
        mode='generation_only',
        company_data=company_data,
        resume_generation=True
    )
    
    print(f"[*] Disparando Generación (generation_only) para {session_id}...")
    try:
        result = await orch.process(session_id, agent_input.model_dump())
        print(f"[*] Pipeline finalizado con status: {result.get('status')}")
        if result.get('status') == 'error':
            print(f"    - Detalle: {result.get('message')}")
    except Exception as e:
        print(f"Error fatal: {str(e)}")

if __name__ == "__main__":
    asyncio.run(trigger_generation())
