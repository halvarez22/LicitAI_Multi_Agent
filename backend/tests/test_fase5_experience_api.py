import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.v1.routes.experience import get_experience_store
from app.config.settings import settings
from unittest.mock import patch, AsyncMock

client = TestClient(app)

@pytest.fixture
def mock_store():
    store = AsyncMock()
    # Mocking the dependency in FastAPI
    async def override_get_experience_store():
        yield store
    
    app.dependency_overrides[get_experience_store] = override_get_experience_store
    yield store
    app.dependency_overrides.clear()

def test_api_outcome_registration_disabled():
    with patch.multiple(settings, EXPERIENCE_API_ENABLED=False):
        response = client.post("/api/v1/experience/outcome", json={
            "session_id": "s1", "resultado": "ganada"
        })
        assert response.status_code == 404

def test_api_outcome_registration_success(mock_store):
    with patch.multiple(settings, EXPERIENCE_API_ENABLED=True, EXPERIENCE_LAYER_ENABLED=True):
        mock_store.upsert_case_summary.return_value = True
        response = client.post("/api/v1/experience/outcome", json={
            "session_id": "s1", "resultado": "ganada", "sector": "salud"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

def test_api_similar_cases_disabled():
    with patch.multiple(settings, EXPERIENCE_DEBUG=False):
        response = client.get("/api/v1/experience/similar?session_id=s1&query=test")
        assert response.status_code == 404

def test_api_similar_cases_success(mock_store):
    from app.services.experience_store import ExperienceCase
    mock_store.find_similar.return_value = [
        ExperienceCase(session_id="s1", summary="summary", outcome="ganada", score=0.99)
    ]
    with patch.multiple(settings, EXPERIENCE_DEBUG=True, EXPERIENCE_LAYER_ENABLED=True):
        response = client.get("/api/v1/experience/similar?session_id=s1&query=test")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert len(response.json()["data"]) == 1
