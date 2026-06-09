"""Resolución universal de convocante y destinatario (HRU)."""
from __future__ import annotations

from app.services.convocante_resolver import extract_convocante_from_text
from app.services.administrative_letter_clauses import (
    is_short_acceptance_annex,
    strip_redundant_signature_blocks,
    try_build_clause_markdown,
)
from app.services.document_date_resolver import resolve_addressee_lines
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

BARDA_HEADER = """
H. AYUNTAMIENTO DE LEÓN, GTO.
DIRECCIÓN GENERAL DE OBRA PÚBLICA
BASES Y REQUISITOS
LICITACIÓN PÚBLICA NUM.  D/080/2025
OBRA: CONSTRUCCIÓN DE BARDA PERIMETRAL
"""

UNAQ_COMITE = """
COMITÉ DE ADQUISICIONES DE LA UNIVERSIDAD
LICITACIÓN PÚBLICA NACIONAL LA-123-2026
"""


def test_extract_convocante_ayuntamiento_obra_publica():
    found = extract_convocante_from_text(BARDA_HEADER)
    assert "LEÓN" in found.get("convocante", "").upper()
    assert "OBRA PÚBLICA" in found.get("dependencia", "").upper()
    assert "D/080/2025" in found.get("concurso_label", "")
    dest = found.get("destinatario", "")
    assert "AYUNTAMIENTO" in dest.upper()
    assert "PRESENTE" in dest.upper()


def test_extract_convocante_comite_adquisiciones():
    found = extract_convocante_from_text(UNAQ_COMITE)
    assert "COMITÉ" in found.get("destinatario", "").upper()
    assert "P R E S E N T E" in found.get("destinatario", "")


def test_resolve_addressee_from_session_analysis():
    state = {
        "last_analysis": {
            "convocante": "H. Ayuntamiento de León, Gto. — Dirección General de Obra Pública",
            "destinatario": "H. AYUNTAMIENTO DE LEÓN, GTO.\nDIRECCIÓN GENERAL DE OBRA PÚBLICA\nPRESENTE.-",
        }
    }
    assert "AYUNTAMIENTO" in resolve_addressee_lines(state).upper()


def test_t8_privacidad_dedupe_and_clause():
    key = pliego_format_dedupe_key("Aviso de privacidad (anexo)")
    assert key == "obra|T8_PRIVACIDAD"
    assert pliego_format_dedupe_key("Aviso_de_privacidad_anexo.docx") == "obra|T8_PRIVACIDAD"
    body = try_build_clause_markdown(
        req_label="Aviso de privacidad (anexo)",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "destinatario": "H. AYUNTAMIENTO DE LEÓN, GTO.\nPRESENTE.-",
        },
    )
    assert body
    low = body.lower()
    assert "aviso de privacidad" in low
    assert "acepto" in low
    assert "datos personales que se recaudarán" not in low
    assert "finalidades del tratamiento" not in low


def test_is_short_acceptance_annex_privacidad():
    assert is_short_acceptance_annex(
        "Aviso de privacidad (anexo)",
        "",
        "Anexar el documento debidamente firmado y expresando la aceptación o negativa.",
    )


def test_strip_redundant_signature_blocks():
    raw = (
        "Manifiesto conforme a bases.\n\n"
        "Firma del representante legal\n"
        "Juan Pérez\n"
        "Representante Legal"
    )
    out = strip_redundant_signature_blocks(raw)
    assert "firma del representante" not in out.lower()
    assert "manifiesto conforme" in out.lower()
