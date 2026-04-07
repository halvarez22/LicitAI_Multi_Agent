import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.feedback_service import FeedbackService
from app.api.schemas.feedback import FeedbackCreate

@pytest.mark.asyncio
async def test_submit_feedback_valid():
    service = FeedbackService()
    mock_repo = AsyncMock()
    mock_repo.save_feedback.return_value = True
    
    with patch("app.memory.factory.MemoryAdapterFactory.create_adapter", return_value=mock_repo):
        # Entry data follows Pydantic validation
        entry = FeedbackCreate(
            session_id="s1",
            agent_id="analyst",
            pipeline_stage="analysis",
            entity_type="requirement",
            entity_ref="REQ-01",
            was_correct=True
        )
        
        result = await service.submit_feedback(entry)
        assert result["success"] == True
        mock_repo.save_feedback.assert_called_once()

@pytest.mark.asyncio
async def test_submit_feedback_invalid_rejection():
    # Pydantic validation test
    with pytest.raises(ValueError, match="Si la extracción es incorrecta, debe proveer una corrección"):
        FeedbackCreate(
            session_id="s1",
            agent_id="analyst",
            pipeline_stage="analysis",
            entity_type="requirement",
            entity_ref="REQ-01",
            was_correct=False # Fails because no correction or comment
        )

@pytest.mark.asyncio
async def test_list_feedback_service():
    service = FeedbackService()
    mock_repo = AsyncMock()
    mock_repo.get_feedback.return_value = [{"id": "f1", "session_id": "s1"}]
    
    with patch("app.memory.factory.MemoryAdapterFactory.create_adapter", return_value=mock_repo):
        items = await service.list_feedback_for_session("s1")
        assert len(items) == 1
        assert items[0]["id"] == "f1"
