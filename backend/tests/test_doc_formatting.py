"""Utilidad de limpieza Markdown → DOCX."""
from app.utils.doc_formatting import strip_markdown_for_docx


def test_strip_bold_and_headings():
    raw = "### Título\nTexto con **negrita** y más.\n---\nOtro **párrafo**."
    out = strip_markdown_for_docx(raw)
    assert "**" not in out
    assert "###" not in out
    assert "Título" in out
    assert "negrita" in out


def test_strip_horizontal_rule_line_removed():
    raw = "Intro\n---\nCierre"
    out = strip_markdown_for_docx(raw)
    assert "Intro" in out
    assert "Cierre" in out
    assert "---" not in out.splitlines()
