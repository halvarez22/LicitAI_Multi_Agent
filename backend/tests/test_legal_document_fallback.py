"""Tests para fallback legal determinístico."""

from app.services.document_body_quality import is_substantive_markdown
from app.services.legal_document_fallback import build_administrative_fallback_markdown


def test_fallback_has_legal_marker_and_substance():
    text = build_administrative_fallback_markdown(
        req_nombre="Carta Declaración de Integridad",
        req_desc="Declaración bajo protesta",
        master_profile={
            "razon_social": "Comercializadora Mayo y Torres SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CMT160107S83",
            "domicilio_fiscal": "Querétaro, Qro.",
        },
        doc_metadata={
            "tender_name": "UNAQ 2026 PANELES SOLARES",
            "fecha": "2 de junio de 2026",
            "destinatario": "UNIVERSIDAD AUTÓNOMA DE QUERÉTARO\nPRESENTE.-",
        },
    )
    assert "bajo protesta de decir verdad" in text.lower()
    assert is_substantive_markdown(text)
