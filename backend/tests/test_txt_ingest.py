"""
Tests unitarios y de propiedades para TxtIngestor.

Cubre:
- Lectura exitosa con UTF-8 y fallback a Latin-1 (tarea 7.7)
- Manejo de errores de encoding y archivo no encontrado (tarea 7.7)
- Properties PBT con Hypothesis (tareas 7.8–7.9)
"""

from __future__ import annotations

import pytest
from pathlib import Path  # usado en tests unitarios con tmp_path

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.document_txt_ingest import TxtIngestor


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ingestor() -> TxtIngestor:
    """Retorna una instancia fresca de TxtIngestor para cada test."""
    return TxtIngestor()


# ---------------------------------------------------------------------------
# Tests unitarios (tarea 7.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_txt_reads_utf8_file(ingestor: TxtIngestor, tmp_path: Path) -> None:
    """Lectura exitosa de un archivo codificado en UTF-8."""
    contenido = "Hola mundo con caracteres especiales: áéíóú ñ €"
    archivo = tmp_path / "prueba.txt"
    archivo.write_text(contenido, encoding="utf-8")

    result = await ingestor.ingest(str(archivo), "prueba.txt")

    assert result["success"] is True
    assert contenido in result["extracted_text"]
    assert result["total_pages"] == 1


@pytest.mark.asyncio
async def test_txt_fallback_to_latin1(ingestor: TxtIngestor, tmp_path: Path) -> None:
    """Fallback a Latin-1 cuando el archivo no es válido UTF-8."""
    # Escribir bytes que son válidos en Latin-1 pero no en UTF-8
    contenido_latin1 = "Texto con caracteres Latin-1: \xe9\xe0\xfc"
    archivo = tmp_path / "latin1.txt"
    archivo.write_bytes(contenido_latin1.encode("latin-1"))

    result = await ingestor.ingest(str(archivo), "latin1.txt")

    assert result["success"] is True
    assert result["total_pages"] == 1
    assert len(result["extracted_text"]) > 0


@pytest.mark.asyncio
async def test_txt_both_encodings_fail(ingestor: TxtIngestor, tmp_path: Path) -> None:
    """success=False cuando ambos encodings fallan (archivo binario puro)."""
    # Bytes que no son válidos ni en UTF-8 ni en Latin-1 como texto
    # Latin-1 acepta todos los bytes 0x00-0xFF, así que necesitamos
    # simular el fallo usando un mock de open
    from unittest.mock import patch, mock_open, MagicMock

    archivo = tmp_path / "binario.bin"
    archivo.write_bytes(b"\x00\x01\x02\x03")

    # Parchear open para que ambos encodings lancen UnicodeDecodeError
    original_open = open

    call_count = 0

    def mock_open_func(path, mode="r", encoding=None, **kwargs):
        nonlocal call_count
        if encoding in ("utf-8", "latin-1"):
            call_count += 1
            raise UnicodeDecodeError(encoding or "utf-8", b"", 0, 1, "invalid byte")
        return original_open(path, mode, encoding=encoding, **kwargs)

    with patch("builtins.open", side_effect=mock_open_func):
        result = await ingestor.ingest(str(archivo), "binario.bin")

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_txt_header_present(ingestor: TxtIngestor, tmp_path: Path) -> None:
    """El encabezado '### ARCHIVO: {filename} | TIPO: TXT' está presente en extracted_text."""
    contenido = "Contenido de prueba"
    archivo = tmp_path / "mi_archivo.txt"
    archivo.write_text(contenido, encoding="utf-8")

    result = await ingestor.ingest(str(archivo), "mi_archivo.txt")

    assert result["success"] is True
    assert "### ARCHIVO: mi_archivo.txt | TIPO: TXT" in result["extracted_text"]


@pytest.mark.asyncio
async def test_txt_pages_structure(ingestor: TxtIngestor, tmp_path: Path) -> None:
    """pages contiene exactamente un elemento con page='txt'."""
    contenido = "Texto de prueba para verificar estructura de páginas"
    archivo = tmp_path / "paginas.txt"
    archivo.write_text(contenido, encoding="utf-8")

    result = await ingestor.ingest(str(archivo), "paginas.txt")

    assert result["success"] is True
    assert len(result["pages"]) == 1
    assert result["pages"][0]["page"] == "txt"
    assert contenido in result["pages"][0]["text"]


@pytest.mark.asyncio
async def test_txt_file_not_found(ingestor: TxtIngestor) -> None:
    """success=False cuando el archivo no existe."""
    result = await ingestor.ingest("/ruta/inexistente/archivo.txt", "archivo.txt")

    assert result["success"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis (tareas 7.8–7.9)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(contenido=st.text(min_size=0, max_size=500))
def test_txt_roundtrip(contenido: str) -> None:
    """Property 6: escribir texto en archivo temporal y leerlo produce el texto original como subcadena.

    Nota: Python normaliza saltos de línea al leer en modo texto (\\r → \\n en Windows),
    por lo que la comparación se hace con el contenido normalizado.

    Validates: Requirements 4.4
    """
    import asyncio
    import tempfile
    import os

    ingestor = TxtIngestor()

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as fh:
        fh.write(contenido)
        ruta = fh.name

    try:
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest(ruta, "roundtrip.txt")
        )
    finally:
        os.unlink(ruta)

    assert result["success"] is True, (
        f"La lectura de un archivo UTF-8 válido debe ser exitosa. "
        f"Contenido: {contenido!r}"
    )
    # Python normaliza \r y \r\n a \n al leer en modo texto; comparar con contenido normalizado
    contenido_normalizado = contenido.replace("\r\n", "\n").replace("\r", "\n")
    assert contenido_normalizado in result["extracted_text"], (
        f"El texto original (normalizado) debe estar como subcadena en extracted_text. "
        f"Contenido original: {contenido!r}, Normalizado: {contenido_normalizado!r}"
    )


@settings(max_examples=200)
@given(
    filename=st.text(min_size=1, max_size=100).filter(lambda s: "\x00" not in s),
    contenido=st.text(min_size=0, max_size=200),
)
def test_txt_header_always_present(filename: str, contenido: str) -> None:
    """Property 7: el encabezado siempre está presente para cualquier filename y contenido.

    Validates: Requirements 4.5
    """
    import asyncio
    import tempfile
    import os

    ingestor = TxtIngestor()

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as fh:
        fh.write(contenido)
        ruta = fh.name

    try:
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest(ruta, filename)
        )
    finally:
        os.unlink(ruta)

    assert result["success"] is True
    expected_header = f"### ARCHIVO: {filename} | TIPO: TXT"
    assert expected_header in result["extracted_text"], (
        f"El encabezado {expected_header!r} debe estar en extracted_text. "
        f"Filename: {filename!r}, Contenido: {contenido!r}"
    )
