import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock
from app.agents.extractor_vision import VisionExtractorAgent

@pytest.fixture
def agent():
    return VisionExtractorAgent(ollama_url="http://mock-ollama:11434")

@pytest.mark.asyncio
async def test_vision_path_not_found(agent):
    """Prueba que devuelve error si el archivo no existe."""
    with patch("os.path.exists", return_value=False):
        resp = await agent.extract("missing.pdf")
        assert "error" in resp
        assert resp["success"] is False
        assert "Archivo no encontrado" in resp["error"]

@pytest.mark.asyncio
async def test_vision_extraction_success(agent):
    """Prueba extracción OCR exitosa multicuadro."""
    with patch("os.path.exists", return_value=True), \
         patch("app.agents.extractor_vision.pdfinfo_from_path", return_value={'Pages': '1'}), \
         patch("app.agents.extractor_vision.convert_from_path", return_value=[MagicMock()]), \
         patch("httpx.AsyncClient.post") as mock_post, \
         patch("app.agents.extractor_vision.OllamaGuard") as mock_guard:
        
        # Simular respuesta exitosa de Ollama (GLM-OCR)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Este es un texto extraído quirúrgicamente por GLM-OCR de LicitAI. " * 5 # ~250 chars
        }
        mock_post.return_value = mock_response
        
        # Simular context manager de OllamaGuard
        mock_guard.return_value.__aenter__.return_value = None
        mock_guard.return_value.__aexit__.return_value = None
        
        resp = await agent.extract("scanned.pdf")
        
        assert resp["success"] is True
        assert resp["method"] == "vlm_ocr_vision"
        assert len(resp["pages"]) == 1
        assert resp["stats"]["chars"] > 100
        assert "LicitAI" in resp["extracted_text"]

@pytest.mark.asyncio
async def test_vision_detected_empty(agent):
    """Prueba que captura páginas vacías (sin éxito por umbral caracteres)."""
    with patch("os.path.exists", return_value=True), \
         patch("app.agents.extractor_vision.pdfinfo_from_path", return_value={'Pages': '1'}), \
         patch("app.agents.extractor_vision.convert_from_path", return_value=[MagicMock()]), \
         patch("httpx.AsyncClient.post") as mock_post, \
         patch("app.agents.extractor_vision.OllamaGuard") as mock_guard:
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Breve texto."} # < 100
        mock_post.return_value = mock_response
        
        mock_guard.return_value.__aenter__.return_value = None
        
        resp = await agent.extract("empty.pdf")
        
        assert resp["success"] is False
        assert len(resp["pages"]) == 1
        assert resp["stats"]["chars"] < 100

@pytest.mark.asyncio
async def test_vision_critical_error_before_extraction(agent):
    """Prueba manejo de excepciones antes de extraer paginas."""
    with patch("os.path.exists", return_value=True), \
         patch("app.agents.extractor_vision.pdfinfo_from_path", side_effect=ValueError("Fallo en pdfinfo")):
        
        resp = await agent.extract("broken.pdf")
        
        assert resp["success"] is False
        assert "error" in resp
        assert "pdfinfo" in resp["error"]
