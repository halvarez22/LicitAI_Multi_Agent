import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.experience_store import ExperienceStore, ExperienceCase
from app.config.settings import settings

@pytest.fixture
def store():
    return ExperienceStore()

@pytest.mark.asyncio
async def test_fingerprint_stability(store):
    reqs1 = ["Requisito A", "Requisito B", "Requisito C"]
    reqs2 = ["Requisito C", "Requisito A", "Requisito B"]
    
    fp1 = store.generate_fingerprint(reqs1)
    fp2 = store.generate_fingerprint(reqs2)
    
    assert fp1 == fp2
    assert len(fp1) == 64 # SHA-256 hex length

@pytest.mark.asyncio
async def test_find_similar_empty_results(store):
    # Mocking vector_db for empty check
    mock_vector = MagicMock()
    mock_vector.get_or_create_collection.return_value = MagicMock()
    mock_vector.get_or_create_collection.return_value.query.return_value = {
        "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]
    }
    
    with patch.object(store, 'vector_db', mock_vector):
        with patch.object(settings, 'EXPERIENCE_LAYER_ENABLED', True):
            cases = await store.find_similar("test query")
            assert len(cases) == 1
            assert cases[0].session_id == "none"
            assert "Baja señal" in cases[0].disclaimer

@pytest.mark.asyncio
async def test_upsert_case_summary_disabled(store):
    with patch.object(settings, 'EXPERIENCE_LAYER_ENABLED', False):
        success = await store.upsert_case_summary("s1", "s", "t", ["r"], "ganada")
        assert success is False
