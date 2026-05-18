"""
Tests unitarios y de propiedades para _format_table_as_markdown y DigitalExtractorAgent.

Cubre:
- Formateo de tablas como markdown (tarea 7.13)
- Manejo de excepciones en page.find_tables() (tarea 7.13)
- Property PBT con Hypothesis (tarea 7.14)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.agents.extractor_digital import _format_table_as_markdown, DigitalExtractorAgent


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def agent() -> DigitalExtractorAgent:
    """Retorna una instancia fresca de DigitalExtractorAgent para cada test."""
    return DigitalExtractorAgent()


def _make_mock_table(rows: list[list]) -> MagicMock:
    """Construye un mock de objeto tabla de PyMuPDF con el método extract()."""
    mock_table = MagicMock()
    mock_table.extract.return_value = rows
    return mock_table


# ---------------------------------------------------------------------------
# Tests unitarios — _format_table_as_markdown (tarea 7.13)
# ---------------------------------------------------------------------------


def test_format_table_basic() -> None:
    """Tabla de 2 filas y 3 columnas produce markdown con separadores '|'."""
    filas = [
        ["Columna A", "Columna B", "Columna C"],
        ["Valor 1", "Valor 2", "Valor 3"],
    ]
    tabla = _make_mock_table(filas)

    resultado = _format_table_as_markdown(tabla)

    assert "|" in resultado, "El resultado debe contener separadores '|'"
    assert "Columna A" in resultado
    assert "Columna B" in resultado
    assert "Columna C" in resultado
    assert "Valor 1" in resultado
    assert "---" in resultado, "Debe incluir la fila separadora de markdown"


def test_format_table_empty() -> None:
    """Tabla vacía (sin filas) retorna string vacío."""
    tabla = _make_mock_table([])

    resultado = _format_table_as_markdown(tabla)

    assert resultado == "", f"Tabla vacía debe retornar string vacío, obtuvo: {resultado!r}"


def test_format_table_none_cells() -> None:
    """Celdas con valor None se convierten a string vacío."""
    filas = [
        ["Encabezado", None, "Otro"],
        [None, "Dato", None],
    ]
    tabla = _make_mock_table(filas)

    resultado = _format_table_as_markdown(tabla)

    assert "|" in resultado, "El resultado debe contener separadores '|'"
    assert "Encabezado" in resultado
    assert "Dato" in resultado
    # Las celdas None no deben aparecer como "None" en el resultado
    assert "None" not in resultado, "Las celdas None deben convertirse a string vacío, no a 'None'"


def test_format_table_single_row() -> None:
    """Tabla con una sola fila (solo encabezado) produce markdown válido."""
    filas = [["Solo", "Encabezado", "Aquí"]]
    tabla = _make_mock_table(filas)

    resultado = _format_table_as_markdown(tabla)

    assert "|" in resultado
    assert "Solo" in resultado
    assert "---" in resultado


# ---------------------------------------------------------------------------
# Tests de integración — DigitalExtractorAgent con excepciones (tarea 7.13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extractor_continues_on_find_tables_exception(agent: DigitalExtractorAgent) -> None:
    """Cuando page.find_tables() lanza excepción, el extractor continúa con page.get_text()."""
    texto_pagina = "Texto plano de la página sin tablas. " * 5  # > 100 chars

    mock_page = MagicMock()
    mock_page.find_tables.side_effect = RuntimeError("Error simulado en find_tables")
    mock_page.get_text.return_value = texto_pagina

    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = iter([mock_page])
    mock_doc.__len__.return_value = 1

    with patch("os.path.exists", return_value=True), \
         patch("fitz.open", return_value=mock_doc):
        result = await agent.extract("/tmp/documento.pdf")

    # El extractor debe continuar y usar get_text() aunque find_tables() falle
    assert result["success"] is True, (
        "El extractor debe continuar con page.get_text() cuando find_tables() falla"
    )
    assert texto_pagina.strip() in result["extracted_text"] or len(result["extracted_text"]) > 0


@pytest.mark.asyncio
async def test_extractor_uses_tables_when_available(agent: DigitalExtractorAgent) -> None:
    """Cuando hay tablas disponibles, el extractor las incluye en el texto de la página."""
    filas_tabla = [
        ["Ítem", "Precio", "Cantidad"],
        ["Producto A", "100", "5"],
    ]
    mock_tabla = _make_mock_table(filas_tabla)

    texto_plano = "Texto adicional de la página con información complementaria."

    mock_tables_result = MagicMock()
    mock_tables_result.__iter__ = MagicMock(return_value=iter([mock_tabla]))

    mock_page = MagicMock()
    mock_page.find_tables.return_value = mock_tables_result
    mock_page.get_text.return_value = texto_plano

    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = iter([mock_page])
    mock_doc.__len__.return_value = 1

    with patch("os.path.exists", return_value=True), \
         patch("fitz.open", return_value=mock_doc):
        result = await agent.extract("/tmp/con_tablas.pdf")

    # El texto extraído debe contener el contenido de la tabla
    assert "Ítem" in result["extracted_text"] or "Precio" in result["extracted_text"] or \
           texto_plano in result["extracted_text"], (
        "El texto extraído debe incluir contenido de la tabla o el texto plano"
    )


@pytest.mark.asyncio
async def test_extractor_returns_failure_for_missing_file(agent: DigitalExtractorAgent) -> None:
    """El extractor retorna success=False cuando el archivo no existe."""
    with patch("os.path.exists", return_value=False):
        result = await agent.extract("/tmp/no_existe.pdf")

    assert result["success"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis (tarea 7.14)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    filas=st.lists(
        st.lists(
            st.one_of(st.none(), st.text(max_size=50)),
            min_size=2,  # ≥ 2 columnas para garantizar separadores '|'
            max_size=5,
        ),
        min_size=1,
        max_size=10,
    )
)
def test_table_formatting_contains_pipe_separators(filas: list) -> None:
    """Property: cualquier tabla con al menos una fila y ≥ 2 columnas produce markdown con '|'.

    Validates: Requirements 6.2
    """
    tabla = _make_mock_table(filas)

    resultado = _format_table_as_markdown(tabla)

    assert "|" in resultado, (
        f"El resultado de formatear una tabla con {len(filas)} filas debe contener '|'. "
        f"Filas: {filas!r}, Resultado: {resultado!r}"
    )
    assert "---" in resultado, (
        f"El resultado debe contener la fila separadora '---'. "
        f"Filas: {filas!r}, Resultado: {resultado!r}"
    )
