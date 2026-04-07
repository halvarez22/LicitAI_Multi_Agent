from fastapi.testclient import TestClient
from app.main import app
from app.config.settings import settings
import pytest
import uuid

client = TestClient(app)

def test_feedback_api_disabled():
    settings.FEEDBACK_API_ENABLED = False
    response = client.post("/api/v1/feedback", json={
        "session_id": "s1",
        "agent_id": "analyst",
        "pipeline_stage": "analysis",
        "entity_type": "requirement",
        "entity_ref": "REQ-01",
        "was_correct": True
    })
    assert response.status_code == 404

def test_feedback_api_enabled_create_success():
    settings.FEEDBACK_API_ENABLED = True
    # Patch the service to avoid real DB
    with pytest.MonkeyPatch().context() as mp:
        async def mock_submit(self, entry):
            return {"success": True, "message": "OK"}
        
        from app.services.feedback_service import FeedbackService
        mp.setattr(FeedbackService, "submit_feedback", mock_submit)
        
        response = client.post("/api/v1/feedback", json={
            "session_id": "s1",
            "agent_id": "analyst",
            "pipeline_stage": "analysis",
            "entity_type": "requirement",
            "entity_ref": "REQ-01",
            "was_correct": True
        })
        assert response.status_code == 200
        assert response.json()["success"] == True

def test_feedback_api_list_success():
    settings.FEEDBACK_API_ENABLED = True
    with pytest.MonkeyPatch().context() as mp:
        async def mock_list(self, session_id):
            return [{
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "agent_id": "analyst",
                "pipeline_stage": "analysis",
                "entity_type": "requirement",
                "entity_ref": "REQ-01",
                "was_correct": True,
                "created_at": "2026-03-30T13:41:57"
            }]
        
        from app.services.feedback_service import FeedbackService
        mp.setattr(FeedbackService, "list_feedback_for_session", mock_list)
        
        response = client.get("/api/v1/feedback/session/s1")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert len(data["data"]) == 1
