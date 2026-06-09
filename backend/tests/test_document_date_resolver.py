"""Tests universales de fecha documental (HRU)."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.config.settings import settings as app_settings
from app.services.document_date_resolver import (
    apply_document_date_override_from_chat,
    extract_document_date_user_override,
    normalize_body_spanish_dates,
    normalize_docx_spanish_dates,
    parse_document_date_override_from_chat,
    resolve_document_date,
)
from app.services.document_fill_quality_gate import validate_generated_documents_fill


def test_resolve_document_date_from_submission_checklist():
    state = {
        "submission_checklist": {
            "hitos": [
                {
                    "id": "presentacion_proposiciones",
                    "fecha_texto_raw": "19 de diciembre de 2025, 09:30",
                    "fecha_hora": "2025-12-19T09:30:00",
                }
            ]
        }
    }
    out = resolve_document_date(state)
    assert out["source"].startswith("cronograma")
    assert "2025" in out["fecha_es"]
    assert out["deadline_dt"] is not None
    assert "diciembre" in out["fecha_es"].lower()


def test_user_override_from_session():
    state = {
        "document_date_user_override": "17 de diciembre de 2025",
        "submission_checklist": {
            "hitos": [
                {
                    "id": "presentacion_proposiciones",
                    "fecha_hora": "2025-12-19T09:30:00",
                }
            ]
        },
    }
    assert extract_document_date_user_override(state) == "17 de diciembre de 2025"
    out = resolve_document_date(state)
    assert out["source"] == "user_override"
    assert out["fecha_es"] == "17 de diciembre de 2025"


def test_parse_document_date_from_chat():
    msg = "Fecha de los formatos administrativos: 17 de diciembre de 2025"
    assert parse_document_date_override_from_chat(msg) == "17 de diciembre de 2025"


def test_apply_chat_override_clamps_after_deadline():
    state = {
        "submission_checklist": {
            "hitos": [
                {
                    "id": "presentacion_proposiciones",
                    "fecha_hora": "2025-12-19T09:30:00",
                }
            ]
        }
    }
    hitl = apply_document_date_override_from_chat(
        state,
        "fecha documentos: 8 de junio de 2026",
    )
    assert hitl["applied"] is True
    assert "2025" in str(hitl["fecha_es"])
    assert hitl["session_patch"]["document_date_override_provenance"]["clamped_to_deadline"] is True


def test_normalize_body_spanish_dates_replaces_wrong_dates():
    canon = "17 de diciembre de 2025"
    raw = "Carta-Compromiso en León, a 8 de junio de 2026."
    out = normalize_body_spanish_dates(raw, canon)
    assert "8 de junio" not in out
    assert canon in out


def test_normalize_docx_spanish_dates(tmp_path):
    canon = "17 de diciembre de 2025"
    path = tmp_path / "carta.docx"
    doc = Document()
    doc.add_paragraph("En León, Guanajuato, a 20 de diciembre de 2025.")
    doc.save(path)
    changed = normalize_docx_spanish_dates(str(path), canon)
    assert changed is True
    text = "\n".join(p.text for p in Document(path).paragraphs)
    assert "20 de diciembre" not in text
    assert canon in text


def test_fill_gate_no_date_block_when_canonical_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    monkeypatch.setattr(app_settings, "DOCUMENT_CONTAMINATION_GATE_ENABLED", True)
    f = tmp_path / "carta.docx"
    doc = Document()
    doc.add_paragraph("CONSTRUCTORA SA DE CV")
    doc.add_paragraph("RFC: CIN2506089A3")
    doc.add_paragraph("En León, a 17 de diciembre de 2025.")
    doc.save(f)
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f), "tipo": "administrativo", "template_id": "carta_compromiso"}],
        master_profile={
            "razon_social": "CONSTRUCTORA SA DE CV",
            "rfc": "CIN2506089A3",
            "representante_legal": "Juan Perez",
        },
        provenance_context={
            "source": "formats_writer",
            "confidence": 0.9,
            "fecha_es": "17 de diciembre de 2025",
            "deadline_dt_iso": "2025-12-19T09:30:00",
        },
    )
    date_blocks = [
        i
        for i in out["issues"]
        if i.get("error_type") == "document_date_after_submission_deadline"
    ]
    assert not date_blocks
