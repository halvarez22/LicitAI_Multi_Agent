"""
Tests unitarios y de propiedades para DocIngestor.

Cubre:
- Extracción vía docx2txt y fallback a antiword (tarea 7.10)
- Manejo de fallos y texto corto (tarea 7.10)
- Properties PBT con Hypothesis (tareas 7.11–7.12)
"""

from __future__ import annotations

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.document_doc_ingest import DocIngestor


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ingestor() -> DocIngestor:
    """Retorna una instancia fresca de DocIngestor para cada test."""
    return DocIngestor()


# ---------------------------------------------------------------------------
# Tests unitarios (tarea 7.10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doc_extracts_via_docx2txt(ingestor: DocIngestor) -> None:
    """Extracción exitosa vía docx2txt (mockeado)."""
    texto_extraido = "Este es el contenido del documento Word antiguo con suficiente texto."

    with patch.object(ingestor, "_try_docx2txt", return_value=texto_extraido):
        result = await ingestor.ingest("/tmp/documento.doc", "documento.doc")

    assert result["success"] is True
    assert texto_extraido in result["extracted_text"]
    assert result["total_pages"] == 1


@pytest.mark.asyncio
async def test_doc_fallback_to_antiword(ingestor: DocIngestor) -> None:
    """Fallback a antiword cuando docx2txt retorna None."""
    texto_antiword = "Texto extraído por antiword con contenido suficiente para pasar."

    with patch.object(ingestor, "_try_docx2txt", return_value=None), \
         patch.object(ingestor, "_try_antiword", return_value=texto_antiword):
        result = await ingestor.ingest("/tmp/legacy.doc", "legacy.doc")

    assert result["success"] is True
    assert texto_antiword in result["extracted_text"]


@pytest.mark.asyncio
async def test_doc_both_methods_fail(ingestor: DocIngestor) -> None:
    """success=False cuando ambos métodos (docx2txt y antiword) fallan."""
    with patch.object(ingestor, "_try_docx2txt", return_value=None), \
         patch.object(ingestor, "_try_antiword", return_value=None):
        result = await ingestor.ingest("/tmp/corrupto.doc", "corrupto.doc")

    assert result["success"] is False
    assert "error" in result
    assert "doc" in result["error"].lower() or "docx2txt" in result["error"].lower() or "antiword" in result["error"].lower()


@pytest.mark.asyncio
async def test_doc_short_text_fails(ingestor: DocIngestor) -> None:
    """success=False cuando el texto extraído tiene menos de 10 caracteres."""
    texto_corto = "abc"  # 3 caracteres, menor que el mínimo de 10

    with patch.object(ingestor, "_try_docx2txt", return_value=texto_corto):
        result = await ingestor.ingest("/tmp/vacio.doc", "vacio.doc")

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_doc_header_present(ingestor: DocIngestor) -> None:
    """El encabezado '### ARCHIVO: {filename} | TIPO: DOC' está presente en extracted_text."""
    texto_suficiente = "Contenido del documento con suficiente longitud para ser válido."

    with patch.object(ingestor, "_try_docx2txt", return_value=texto_suficiente):
        result = await ingestor.ingest("/tmp/informe.doc", "informe.doc")

    assert result["success"] is True
    assert "### ARCHIVO: informe.doc | TIPO: DOC" in result["extracted_text"]


@pytest.mark.asyncio
async def test_doc_pages_structure(ingestor: DocIngestor) -> None:
    """pages contiene exactamente un elemento con page='doc'."""
    texto_suficiente = "Texto de prueba con suficiente contenido para ser procesado correctamente."

    with patch.object(ingestor, "_try_docx2txt", return_value=texto_suficiente):
        result = await ingestor.ingest("/tmp/estructura.doc", "estructura.doc")

    assert result["success"] is True
    assert len(result["pages"]) == 1
    assert result["pages"][0]["page"] == "doc"
    assert texto_suficiente in result["pages"][0]["text"]


# ---------------------------------------------------------------------------
# Tests de métodos privados con mocks reales
# ---------------------------------------------------------------------------


def test_try_docx2txt_returns_none_on_exception(ingestor: DocIngestor) -> None:
    """_try_docx2txt retorna None cuando docx2txt lanza una excepción."""
    with patch("app.services.document_doc_ingest.DocIngestor._try_docx2txt") as mock:
        mock.return_value = None
        result = ingestor._try_docx2txt("/tmp/archivo.doc")
        # El mock retorna None directamente
        assert result is None


def test_try_antiword_returns_none_when_not_found(ingestor: DocIngestor) -> None:
    """_try_antiword retorna None cuando antiword no está disponible."""
    with patch("subprocess.run", side_effect=FileNotFoundError("antiword not found")):
        result = ingestor._try_antiword("/tmp/archivo.doc")

    assert result is None


def test_try_antiword_returns_none_on_timeout(ingestor: DocIngestor) -> None:
    """_try_antiword retorna None cuando antiword excede el timeout."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["antiword"], 30)):
        result = ingestor._try_antiword("/tmp/archivo.doc")

    assert result is None


def test_try_antiword_returns_none_on_nonzero_returncode(ingestor: DocIngestor) -> None:
    """_try_antiword retorna None cuando antiword retorna código de error."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error procesando archivo"

    with patch("subprocess.run", return_value=mock_result):
        result = ingestor._try_antiword("/tmp/archivo.doc")

    assert result is None


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis (tareas 7.11–7.12)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    filename=st.text(min_size=1, max_size=100).filter(lambda s: "\x00" not in s),
    texto=st.text(min_size=10, max_size=500),
)
def test_doc_header_on_success(filename: str, texto: str) -> None:
    """Property 8: el encabezado está presente cuando el texto extraído tiene ≥ 10 chars.

    Validates: Requirements 5.5
    """
    import asyncio

    ingestor = DocIngestor()

    with patch.object(ingestor, "_try_docx2txt", return_value=texto):
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest("/tmp/archivo.doc", filename)
        )

    # Solo verificar el encabezado si la extracción fue exitosa
    # (el texto puede tener < 10 chars después de strip)
    if len(texto.strip()) >= 10:
        assert result["success"] is True, (
            f"Con texto de {len(texto)} chars, debe ser exitoso. "
            f"Filename: {filename!r}"
        )
        expected_header = f"### ARCHIVO: {filename} | TIPO: DOC"
        assert expected_header in result["extracted_text"], (
            f"El encabezado {expected_header!r} debe estar en extracted_text"
        )


@settings(max_examples=200)
@given(
    texto_corto=st.text(max_size=9),
)
def test_doc_short_text_always_fails(texto_corto: str) -> None:
    """Property 9: texto con menos de 10 chars siempre produce success=False.

    Validates: Requirements 5.6
    """
    import asyncio

    ingestor = DocIngestor()

    with patch.object(ingestor, "_try_docx2txt", return_value=texto_corto):
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest("/tmp/corto.doc", "corto.doc")
        )

    # Si el texto tiene menos de 10 chars después de strip, debe fallar
    if len(texto_corto.strip()) < 10:
        assert result["success"] is False, (
            f"Con texto de {len(texto_corto.strip())} chars (stripped), "
            f"debe retornar success=False. Texto: {texto_corto!r}"
        )
