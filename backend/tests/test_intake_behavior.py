import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.intake import IntakeAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentStatus, AgentInput

# Fixture para evitar que DataGapAgent intente conectarse a ChromaDB durante su instanciación en Intake
@pytest.fixture(autouse=True)
def mock_datagap():
    with patch("app.agents.intake.DataGapAgent") as mock_dg:
        # Hacemos que _is_data_valid funcione básicamente igual para que el test sea coherente
        def mock_valid(field, value):
            if "gmail" in str(value) or "@" in str(value) or "www" in str(value):
                return True
            return len(str(value)) > 5
        
        inst = mock_dg.return_value
        inst._is_data_valid.side_effect = mock_valid
        yield inst

@pytest.fixture
def mock_context():
    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock()
    ctx.memory.get_company = AsyncMock(return_value={"master_profile": {}})
    ctx.memory.save_company = AsyncMock()
    return ctx

@pytest.fixture
def agent(mock_context):
    a = IntakeAgent(mock_context)
    a.llm = AsyncMock()
    a.llm.generate = AsyncMock()
    return a

@pytest.mark.asyncio
async def test_intake_error_si_no_hay_preguntas(agent, mock_context):
    mock_context.memory.get_session.return_value = {"pending_questions": []}
    resp = await agent.process_user_response("s1", "c1", "hola")
    assert resp["status"] == "error"

@pytest.mark.asyncio
async def test_intake_extraccion_exitosa(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {"field": "email", "label": "Correo", "question": "¿Tu mail?"},
            {"field": "tel", "label": "Tel", "question": "¿Tu tel?"}
        ]
    }
    agent.llm.generate.return_value = {"response": "test@gmail.com"}
    
    resp = await agent.process_user_response("s1", "c1", "es test@gmail.com")
    
    assert resp["status"] == "partial"
    assert "Correo" in resp["message"]
    assert "¿Tu tel?" in resp["message"]

@pytest.mark.asyncio
async def test_intake_llm_falla(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"field": "email", "label": "Correo"}]
    }
    agent.llm.generate.return_value = {"response": "NO_PROPORCIONADO"}
    
    resp = await agent.process_user_response("s1", "c1", "no se")
    assert resp["status"] == "ask_again"

@pytest.mark.asyncio
async def test_intake_finalizacion(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"field": "web", "label": "Web", "question": "¿Tu web?"}]
    }
    agent.llm.generate.return_value = {"response": "www.test.com"}
    
    resp = await agent.process_user_response("s1", "c1", "www.test.com")
    assert resp["status"] == "complete"
    assert "expediente completo" in resp["message"].lower()

@pytest.mark.asyncio
async def test_intake_process_interfaz(agent):
    inp = AgentInput(session_id="s", company_id="c1", company_data={})
    out = await agent.process(inp)
    assert out.status == AgentStatus.ERROR
    assert "Use process_user_response_instead" in out.error
