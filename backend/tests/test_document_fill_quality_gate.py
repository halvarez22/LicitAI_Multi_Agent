from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook

from app.config.settings import settings as app_settings
from app.services.document_fill_quality_gate import validate_generated_documents_fill


def _make_docx(path: Path, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


def _make_xlsx(path: Path, with_values: bool) -> None:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "SUBTOTAL"
    ws["A2"] = "IVA"
    ws["A3"] = "TOTAL"
    if with_values:
        ws["B1"] = 100.0
        ws["B2"] = 16.0
        ws["B3"] = 116.0
    wb.save(path)


def test_fill_gate_detecta_placeholder_docx(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "x.docx"
    _make_docx(f, ["Representante: [NOMBRE]"])
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f)}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
    )
    assert out["documents_scanned"] == 1
    assert any(i["error_type"] == "placeholder_detected" for i in out["issues"])


def test_fill_gate_xlsx_anchor_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "econ.xlsx"
    _make_xlsx(f, with_values=False)
    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[{"ruta": str(f)}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
    )
    assert out["documents_scanned"] == 1
    assert any(i["error_type"] == "required_field_missing" for i in out["issues"])


def test_fill_gate_policy_registry_y_version(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "ANEXO_AE_PROPUESTA_ECONOMICA.docx"
    _make_docx(
        f,
        [
            "SUBTOTAL: $100.00",
            "IVA (16%): $16.00",
            "TOTAL DE LA PROPUESTA: $116.00",
        ],
    )
    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[{"ruta": str(f), "tipo": "anexo_economico", "template_id": "anexo_economico"}],
        master_profile={"razon_social": "ACME SA DE CV", "rfc": "ACM010101AAA", "representante_legal": "Ana Perez"},
    )
    assert out["policy_version"] == "1.1.0"
    assert out["documents_with_policy"] == 1


def test_fill_gate_confianza_insuficiente_y_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "anexo_7.docx"
    _make_docx(f, ["Documento legal"])
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f), "tipo": "administrativo", "template_id": "anexo_7"}],
        master_profile={"razon_social": "ACME SA DE CV", "rfc": "RFC_MALO", "representante_legal": "Ana"},
        provenance_context={
            "source": "llm_inference",
            "field_provenance": {
                "rfc": {"source": "llm_inference", "confidence": 0.2, "anchor": None},
            },
        },
    )
    error_types = {i["error_type"] for i in out["issues"]}
    assert "source_confidence_insufficient" in error_types
    assert "cross_field_inconsistency" in error_types
