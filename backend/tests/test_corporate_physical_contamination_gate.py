"""Gate anti-contaminación del panel Documentos empresariales (HRU)."""
from __future__ import annotations

from app.services.corporate_physical_enrichment_service import (
    extract_corporate_physical_from_bases_corpus,
)
from app.services.document_deliverable_filter import (
    is_corporate_physical_panel_noise,
    passes_corporate_physical_bases_gate,
    snippet_contaminated_across_corpus,
)
from app.services.junta_bases_corpus import BasesCorpus, resolve_primary_bases_filename


ISAPEG_BASES = """
IV. REQUISITOS
1.1. Constancia de situación fiscal o cédula del Registro Federal de Contribuyentes.
1.3. Identificación personal oficial vigente en original o copia certificada y copia simple para su cotejo.
1.9. Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT.
1.12. Constancia de no adeudos emitida por INFONAVIT, con vigencia no mayor a treinta días.
23.1. Original o copia certificada para cotejo y copia simple del dictamen de cumplimiento respecto a la NOM-035-STPS-2018.
1.6. Registro en el Padrón de Proveedores del Gobierno del Estado de Guanajuato.
"""

FOCON_FOREIGN = """
A. La oferta que presente el LICITANTE deberá considerar el costo del operario por turno,
de conformidad con las necesidades establecidas por IMSS-BIENESTAR, en el inmueble descrito en el APÉNDICE 1.
D. Presentar escrito en papel membretado manifestando que el personal no actuará como patrón sustituto IMSS-BIENESTAR.
C. Por encontrarse en la lista emitida por el SAT, en estatus de "definitivo" conforme al artículo 69-B del CFF.
"""


def test_resolve_primary_bases_prefers_bases_over_focon():
    sources = ["FOCON 04.pdf", "bases_0001.pdf", "Anexo_A.docx"]
    assert resolve_primary_bases_filename(sources) == "bases_0001.pdf"


def test_snippet_contaminated_when_only_in_foreign_pdf():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[
            ("bases_0001.pdf", ISAPEG_BASES),
            ("FOCON 04.pdf", FOCON_FOREIGN),
        ],
        filenames=["bases_0001.pdf", "FOCON 04.pdf"],
    )
    foreign = (
        "La oferta que presente el LICITANTE deberá considerar el costo del operario por turno, "
        "de conformidad con las necesidades establecidas por IMSS-BIENESTAR"
    )
    assert snippet_contaminated_across_corpus(foreign, corpus) is True
    valid = "1.1. Constancia de situación fiscal o cédula del Registro Federal de Contribuyentes"
    assert snippet_contaminated_across_corpus(valid, corpus) is False


def test_passes_gate_rejects_imss_bienestar_foreign_requirement():
    corpus = BasesCorpus(
        session_id="isapeg_servicios_de_limpieza",
        segments=[
            ("bases_0001.pdf", ISAPEG_BASES),
            ("FOCON 04.pdf", FOCON_FOREIGN),
        ],
        filenames=["bases_0001.pdf", "FOCON 04.pdf"],
    )
    assert not passes_corporate_physical_bases_gate(
        "Costo operario IMSS-BIENESTAR",
        FOCON_FOREIGN[:220],
        corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )
    assert passes_corporate_physical_bases_gate(
        "Constancia de situación fiscal SAT",
        "1.1. Constancia de situación fiscal o cédula del Registro Federal de Contribuyentes",
        corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )
    assert not passes_corporate_physical_bases_gate(
        "SAT artículo 69-B definitivo",
        'Por encontrarse en la lista emitida por el SAT, en estatus de "definitivo" conforme al artículo 69-B',
        corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )


def test_extraction_ignores_foreign_pdf_when_primary_bases_present():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[
            ("bases_0001.pdf", ISAPEG_BASES),
            ("FOCON 04.pdf", FOCON_FOREIGN),
        ],
        filenames=["bases_0001.pdf", "FOCON 04.pdf"],
    )
    rows = extract_corporate_physical_from_bases_corpus(corpus)
    joined = " ".join(r["evidence_snippet"].lower() for r in rows)
    assert "imss-bienestar" not in joined
    assert "operario por turno" not in joined
    assert "69-b" not in joined
    assert "situacion fiscal" in joined or "situación fiscal" in joined or "infonavit" in joined


def test_panel_noise_rejects_header_and_operational_uniform():
    assert is_corporate_physical_panel_noise("IDENTIFICACIÓN Y UNIFORMES", "", "")
    assert is_corporate_physical_panel_noise(
        "Uniformes",
        "",
        "El PRESTADOR DEL SERVICIO queda obligado a garantizar que el personal portará en todo momento el equipo de protección personal como es cubrebocas",
    )
    assert not is_corporate_physical_panel_noise(
        "Constancia de situación fiscal SAT",
        "",
        "Impresión de la Constancia de situación fiscal vigente",
    )
