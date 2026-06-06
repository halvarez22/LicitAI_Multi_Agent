"""Anexo AE debe llevar membrete con logo cuando existe en metadata."""
import os
from pathlib import Path

from docx import Document

from app.agents.economic_writer import EconomicWriterAgent
from app.services.economic_document_reapply import build_economic_doc_metadata


def test_anexo_ae_inserts_logo_when_path_exists(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    profile = {
        "razon_social": "Empresa Test",
        "rfc": "TST010101TST",
        "representante_legal": "Rep Legal",
        "logo": str(logo),
    }
    resumen = {"fecha": "23/04/2026", "fecha_es": "23 de abril de 2026", "subtotal": 100.0, "iva": 16.0, "total": 116.0, "moneda": "MXN"}
    meta = build_economic_doc_metadata(
        session_id="test_session",
        session_state={},
        master_profile=profile,
        resumen=resumen,
    )
    out = tmp_path / "anexo_ae.docx"
    agent = EconomicWriterAgent.__new__(EconomicWriterAgent)
    agent._generate_anexo_ae(
        str(out),
        [{"partida": 1, "descripcion": "Partida", "cantidad": 1, "importe": 100.0}],
        resumen,
        profile,
        doc_metadata=meta,
    )
    doc = Document(str(out))
    assert doc.sections[0].header.tables
    assert os.path.isfile(str(out))
