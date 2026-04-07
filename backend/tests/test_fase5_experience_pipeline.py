import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.agents.analyst import AnalystAgent
from app.agents.compliance import ComplianceAgent
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.config.settings import settings
from app.services.experience_store import ExperienceCase

@pytest.fixture
def mock_context():
    m = MagicMock()
    m.record_task_completion = AsyncMock()
    m.memory = AsyncMock()
    m.memory.get_documents = AsyncMock(return_value=[])
    m.memory.get_line_items_for_session = AsyncMock(return_value=[])
    return m

_BASES_CHUNK = "algun texto de bases para superar umbral de contexto mínimo del analista. " * 40


@pytest.mark.asyncio
async def test_analyst_injection_off(mock_context):
    agent = AnalystAgent(mock_context)
    agent.smart_search = AsyncMock(return_value=_BASES_CHUNK)
    agent.llm.generate = AsyncMock()
    agent.llm.generate.return_value.success = True
    agent.llm.generate.return_value.response = "{}"
    
    with patch.object(settings, 'EXPERIENCE_LAYER_ENABLED', False):
        await agent.process(AgentInput(session_id="s1"))
        
        call_args = agent.llm.generate.call_args[1]
        assert "CONTEXTO EXPERIENCIA" not in call_args["prompt"]

@pytest.mark.asyncio
async def test_analyst_injection_on(mock_context):
    agent = AnalystAgent(mock_context)
    agent.smart_search = AsyncMock(return_value=_BASES_CHUNK)
    agent.llm.generate = AsyncMock()
    agent.llm.generate.return_value.success = True
    agent.llm.generate.return_value.response = "{}"
    
    # Mock similar cases
    from app.services.experience_store import ExperienceCase
    agent.experience_store.find_similar = AsyncMock(return_value=[
        ExperienceCase(session_id="case-101", sector="Salud", summary="Caso de salud exitoso", outcome="ganada")
    ])
    
    with patch.multiple(settings, EXPERIENCE_LAYER_ENABLED=True, EXPERIENCE_PROMPT_INJECTION=True, EXPERIENCE_SHADOW_MODE=False):
        await agent.process(AgentInput(session_id="s1"))
        
        call_args = agent.llm.generate.call_args[1]
        assert "CONTEXTO EXPERIENCIA" in call_args["prompt"]
        assert "case-101" in call_args["prompt"]

@pytest.mark.asyncio
async def test_compliance_injection_shadow(mock_context):
    agent = ComplianceAgent(mock_context)
    agent.smart_search = AsyncMock(return_value="REQUISITOS")
    agent._map_zone_chunks = AsyncMock(return_value=([], []))
    agent._reduce_zone_items = MagicMock(return_value=([], {}))
    agent.llm.generate = AsyncMock()
    agent.llm.generate.return_value.success = True
    agent.llm.generate.return_value.response = "{}"
    
    # Mock score calculation
    agent.confidence_scorer.calculate_extraction_confidence = MagicMock()
    agent.confidence_scorer.calculate_extraction_confidence.return_value.model_dump.return_value = {}
    
    agent.experience_store.find_similar = AsyncMock(return_value=[
        ExperienceCase(session_id="case-202", summary="Resumen", outcome="ganada")
    ])
    
    with patch.multiple(settings, EXPERIENCE_LAYER_ENABLED=True, EXPERIENCE_PROMPT_INJECTION=True, EXPERIENCE_SHADOW_MODE=True):
        await agent.process(AgentInput(session_id="s1"))
        
        # En Shadow Mode, full_context_str tiene la experiencia, pero no se pasa al prompt del REDUCE
        # (Nota: Compliance Map-Reduce usa prompts por bloque, y solo inyectamos experiencia en el scorer/eval final en esta fase)
        # Vamos a verificar que find_similar se llamó.
        agent.experience_store.find_similar.assert_called()
