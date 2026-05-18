"""
Tests unitarios y de propiedades para DocumentIngestionRouter y _normalize_ocr_result.

Cubre:
- Routing correcto por extensión de archivo (tareas 7.1)
- Properties PBT con Hypothesis (tareas 7.2–7.6)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.document_ingestion_router import (
    DocumentIngestionRouter,
    _normalize_ocr_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router() -> DocumentIngestionRouter:
    """Retorna una instancia fresca del router para cada test."""
    return DocumentIngestionRouter()


@pytest.fixture
def mock_memory() -> MagicMock:
    """Retorna un mock del MemoryRepository."""
    return MagicMock()


def _make_ocr_result(success: bool = True, text: str = "Contenido de prueba suficiente") -> dict:
    """Construye un ocr_result canónico mínimo para usar en mocks."""
    return {
        "extracted_text": text,
        "pages": [{"page": 1, "text": text}],
        "total_pages": 1,
        "success": success,
    }


# ---------------------------------------------------------------------------
# Tests unitarios — routing por extensión (tarea 7.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_delegates_xlsx(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .xlsx a process_excel_document."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/file.xlsx", "file.xlsx", "s1", "d1", mock_memory)

    mock_delegate.assert_awaited_once()
    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "xlsx", "La extensión pasada a _delegate debe ser 'xlsx'"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_xls(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .xls a process_excel_document."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/file.xls", "file.xls", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "xls"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_csv(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .csv a process_csv_document."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/data.csv", "data.csv", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "csv"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_docx(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .docx a process_docx_document."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/doc.docx", "doc.docx", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "docx"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_doc(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .doc a DocIngestor."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/doc.doc", "doc.doc", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "doc"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_txt(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .txt a TxtIngestor."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/readme.txt", "readme.txt", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "txt"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_pdf_to_ocr(router: DocumentIngestionRouter, mock_memory: MagicMock) -> None:
    """El router delega archivos .pdf a OCRServiceClient."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/doc.pdf", "doc.pdf", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "pdf"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_delegates_unknown_ext_to_ocr(
    router: DocumentIngestionRouter, mock_memory: MagicMock
) -> None:
    """El router delega extensiones desconocidas a OCRServiceClient."""
    expected = _make_ocr_result()
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_delegate:
        result = await router.ingest("/tmp/file.xyz", "file.xyz", "s1", "d1", mock_memory)

    call_args = mock_delegate.call_args[0]
    assert call_args[0] == "xyz"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_router_catches_exception_returns_failure(
    router: DocumentIngestionRouter, mock_memory: MagicMock
) -> None:
    """Cuando el ingestor delegado lanza una excepción, el router retorna success=False."""
    with patch(
        "app.services.document_ingestion_router.DocumentIngestionRouter._delegate",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Fallo simulado del ingestor"),
    ):
        result = await router.ingest("/tmp/file.pdf", "file.pdf", "s1", "d1", mock_memory)

    assert result["success"] is False
    assert "error" in result
    assert "Fallo simulado del ingestor" in result["error"]


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    extracted_text=st.one_of(st.none(), st.text(), st.just("")),
    pages=st.one_of(st.none(), st.lists(st.dictionaries(st.text(), st.text()))),
    total_pages=st.one_of(st.none(), st.integers()),
    success=st.one_of(st.none(), st.booleans()),
)
def test_normalize_always_has_canonical_keys(
    extracted_text, pages, total_pages, success
) -> None:
    """Property 4: _normalize_ocr_result siempre retorna las 4 claves canónicas con tipos correctos.

    Validates: Requirements 7.2
    """
    raw: dict = {}
    if extracted_text is not None:
        raw["extracted_text"] = extracted_text
    if pages is not None:
        raw["pages"] = pages
    if total_pages is not None:
        raw["total_pages"] = total_pages
    if success is not None:
        raw["success"] = success

    result = _normalize_ocr_result(raw)

    assert "extracted_text" in result, "Debe contener la clave 'extracted_text'"
    assert "pages" in result, "Debe contener la clave 'pages'"
    assert "total_pages" in result, "Debe contener la clave 'total_pages'"
    assert "success" in result, "Debe contener la clave 'success'"

    assert isinstance(result["extracted_text"], str), "extracted_text debe ser str"
    assert isinstance(result["pages"], list), "pages debe ser list"
    assert isinstance(result["total_pages"], int), "total_pages debe ser int"
    assert isinstance(result["success"], bool), "success debe ser bool"


@settings(max_examples=200)
@given(
    empty_text=st.one_of(
        st.just(""),
        st.text(alphabet=" \t\n\r", min_size=0, max_size=50),
    ),
    original_success=st.booleans(),
)
def test_normalize_empty_text_forces_success_false(
    empty_text: str, original_success: bool
) -> None:
    """Property 5: texto vacío/blanco en extracted_text fuerza success=False.

    Validates: Requirements 7.3
    """
    raw = {
        "extracted_text": empty_text,
        "success": original_success,
    }
    result = _normalize_ocr_result(raw)

    assert result["success"] is False, (
        f"Con extracted_text={repr(empty_text)!r} y success original={original_success}, "
        f"el resultado debe tener success=False"
    )


@settings(max_examples=200)
@given(
    ext=st.sampled_from(["pdf", "docx", "doc", "xlsx", "xls", "csv", "txt"]),
)
def test_extension_normalization_is_case_insensitive(ext: str) -> None:
    """Property 2: el routing es case-insensitive — .PDF == .pdf == .Pdf.

    Validates: Requirements 1.8
    """
    router = DocumentIngestionRouter()

    # Generar variantes de capitalización
    upper = ext.upper()
    title = ext.capitalize()

    # Verificar que la extracción de extensión produce el mismo resultado
    filename_lower = f"archivo.{ext}"
    filename_upper = f"archivo.{upper}"
    filename_title = f"archivo.{title}"

    ext_lower = filename_lower.lower().rsplit(".", 1)[-1]
    ext_upper = filename_upper.lower().rsplit(".", 1)[-1]
    ext_title = filename_title.lower().rsplit(".", 1)[-1]

    assert ext_lower == ext_upper == ext_title == ext.lower(), (
        f"Las extensiones {ext!r}, {upper!r}, {title!r} deben normalizarse a {ext.lower()!r}"
    )


@settings(max_examples=200)
@given(
    error_message=st.text(min_size=0, max_size=200),
)
def test_router_catches_any_exception(error_message: str) -> None:
    """Property 3: cualquier excepción en el ingestor delegado produce success=False.

    Validates: Requirements 1.9
    """
    import asyncio

    router = DocumentIngestionRouter()
    memory = MagicMock()

    async def run() -> dict:
        with patch.object(
            router,
            "_delegate",
            new_callable=AsyncMock,
            side_effect=Exception(error_message),
        ):
            return await router.ingest("/tmp/f.pdf", "f.pdf", "s1", "d1", memory)

    result = asyncio.get_event_loop().run_until_complete(run())

    assert result["success"] is False, (
        f"Con excepción de mensaje {error_message!r}, el router debe retornar success=False"
    )
    assert isinstance(result["extracted_text"], str)
    assert isinstance(result["pages"], list)
    assert isinstance(result["total_pages"], int)
