"""Tests de normalización OCR para machotes oficiales."""
from app.services.official_format_text import (
    is_boilerplate_obra_capture,
    normalize_official_template_text,
)


def test_normalize_joins_single_word_lines():
    raw = "CONTRATO\nRELATIVO\nA\nLA\nREALIZACIÓN\nDE\nLA\nOBRA:"
    out = normalize_official_template_text(raw)
    assert "CONTRATO RELATIVO A LA REALIZACIÓN DE LA OBRA" in out
    assert "\nRELATIVO\n" not in out


def test_boilerplate_obra_rejected():
    assert is_boilerplate_obra_capture("SE SUJETARÁN A LO DISPUESTO EN LA LEY DE OBRA PÚBLICA")
