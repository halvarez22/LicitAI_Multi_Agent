"""HRU: identidad de anexos en chat (extracción determinista desde bases primarias)."""
from __future__ import annotations

from app.services.bases_annex_identity_service import (
    compose_annex_identity_bases_response,
    detect_annex_bases_intent,
    extract_annex_identity_from_bases,
    parse_annex_token_from_query,
)

ISAPEG_ANEXO_K = """
--- PÁGINA 3 (bases_0001.pdf) ---
ANEXO TÍTULO
Anexo J Datos de Facturación
Anexo K Carta de Declaración de Intereses
Anexo L Comprobante de entrega de muestra para revisión
Anexo M Carta de Declaración de Integridad
Anexo N Carta Compromiso Antisoborno
Anexo III-K Contenido Nacional

--- PÁGINA 9 (bases_0001.pdf) ---
IV.1 Documentación legal y de acreditación de personalidad requerida.

4. Carta de Declaración de Intereses en hoja membretada y con firma autógrafa del representante legal acreditado. Anexo K.

--- PÁGINA 15 (bases_0001.pdf) ---
27. Original del Anexo AB (Manifiestos) con todos los puntos solicitados.

28. Carta compromiso antisoborno del licitante en hoja membretada y firmada por el representante o apoderado legal acreditado. (ANEXO K).

29. Oferta Técnica de conformidad con los Anexo III Limpieza (partida 1 y 2).
"""


def test_detect_annex_bases_intent_user_question():
    assert detect_annex_bases_intent("¿De qué va el Anexo K?") is True
    assert detect_annex_bases_intent("¿Hay alusión al Anexo K en p. 15?") is True


def test_parse_annex_token_distinguishes_k_from_iii_k():
    assert parse_annex_token_from_query("¿De qué va el Anexo K?") == "k"
    assert parse_annex_token_from_query("contenido del Anexo III-K") == "iii-k"


def test_extract_anexo_k_index_and_requirements():
    payload = extract_annex_identity_from_bases(ISAPEG_ANEXO_K, "k", source="bases_0001.pdf")
    assert payload["ready"] is True
    assert "Declaración de Intereses" in payload["index_catalog_excerpt"]
    pages = {e.get("pagina") for e in payload["index_entries"]}
    assert 3 in pages
    req_pages = {r.get("pagina") for r in payload["requirements"]}
    assert 9 in req_pages
    assert 15 in req_pages
    assert any(c.get("type") == "cross_reference_mismatch" for c in payload["conflicts"])
    out = compose_annex_identity_bases_response(payload)
    assert "Anexo K" in out
    assert "Declaración de Intereses" in out
    assert "antisoborno" in out.lower()
    assert "Anexo N" in out
    assert "III-K" not in out or "Contenido Nacional" not in out.split("III-K")[0]


def test_extract_anexo_k_page_15_only():
    payload = extract_annex_identity_from_bases(
        ISAPEG_ANEXO_K,
        "k",
        source="bases_0001.pdf",
        page_filter=15,
    )
    assert payload["ready"] is True
    assert len(payload["index_entries"]) == 0
    assert len(payload["requirements"]) == 1
    assert payload["requirements"][0].get("numero") == "28"
    out = compose_annex_identity_bases_response(payload)
    assert "página 15" in out.lower()
    assert "Sí:" in out
    assert "antisoborno" in out.lower()


def test_iii_k_does_not_match_anexo_k():
    payload = extract_annex_identity_from_bases(ISAPEG_ANEXO_K, "k", source="bases_0001.pdf")
    for req in payload["requirements"]:
        assert "III-K" not in req.get("text", "")
    payload_iii = extract_annex_identity_from_bases(
        ISAPEG_ANEXO_K, "iii-k", source="bases_0001.pdf"
    )
    assert payload_iii["ready"] is True
    assert "Contenido Nacional" in payload_iii["index_catalog_excerpt"]
