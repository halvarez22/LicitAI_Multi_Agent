import pytest
from unittest.mock import MagicMock, patch
from app.agents.extractor_digital import DigitalExtractorAgent

@pytest.fixture
def agent():
    return DigitalExtractorAgent()

@pytest.mark.asyncio
async def test_digital_path_not_found(agent):
    """Prueba que devuelve error si el archivo no existe."""
    with patch("os.path.exists", return_value=False):
        resp = await agent.extract("missing.pdf")
        assert "error" in resp
        assert resp["success"] is False
        assert "Archivo no encontrado" in resp["error"]

@pytest.mark.asyncio
async def test_digital_extraction_success(agent):
    """Prueba extracción exitosa (más de 100 caracteres)."""
    with patch("os.path.exists", return_value=True), \
         patch("fitz.open") as mock_open:
        
        # Simular documento con 2 páginas
        mock_doc = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Contenido de prueba para la página 1. " * 5 # ~200 chars
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Más contenido real para validar el éxito."
        
        mock_doc.__iter__.return_value = [mock_page1, mock_page2]
        mock_doc.__len__.return_value = 2
        mock_open.return_value = mock_doc
        
        resp = await agent.extract("real.pdf")
        
        assert resp["success"] is True
        assert resp["method"] == "pymupdf_digital"
        assert resp["total_pages"] == 2
        assert len(resp["pages"]) == 2
        assert "Contenido de prueba" in resp["extracted_text"]

@pytest.mark.asyncio
async def test_digital_detected_as_scanned(agent):
    """Prueba que detecta documento como escaneado si tiene poco texto."""
    with patch("os.path.exists", return_value=True), \
         patch("fitz.open") as mock_open:
        
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Poco texto" # < 100
        mock_doc.__iter__.return_value = [mock_page]
        mock_open.return_value = mock_doc
        
        resp = await agent.extract("scanned.pdf")
        
        assert resp["success"] is False
        assert resp["reason"] == "scanned_document"

@pytest.mark.asyncio
async def test_digital_critical_error(agent):
    """Prueba manejo de excepciones durante fitz.open."""
    with patch("os.path.exists", return_value=True), \
         patch("fitz.open", side_effect=ValueError("Corrupción de archivo")):
        
        resp = await agent.extract("broken.pdf")
        
        assert resp["success"] is False
        assert "error" in resp
        assert "Corrupción" in resp["error"]
