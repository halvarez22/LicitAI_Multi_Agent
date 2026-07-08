"""Gate anti-contaminación del panel Formatos/Anexos (HRU)."""
from __future__ import annotations

from app.services.document_deliverable_filter import (
    is_broken_anexo_inventory_label,
    is_formats_panel_noise,
    passes_formats_panel_bases_gate,
    snippet_has_foreign_licitacion_id,
)
from app.services.formats_panel_hru_service import repair_phantom_anexo_label
from app.services.junta_bases_corpus import BasesCorpus
from app.services.pliego_formats_enrichment_service import extract_pliego_generables_from_bases_corpus

ISAPEG_BASES = """
Licitación pública nacional presencial 40004001-003-24 para la contratación del servicio de limpieza.
Anexo A-I Formato de Acreditación de Personalidad Persona Física
Anexo AB Manifiestos
Anexo F Constancia de Visitas
Anexo M Carta de Declaración de Integridad
Anexo K Carta de Declaración de Intereses
Anexo III Descripción del Servicio de Limpieza
Anexo L Comprobante de entrega de muestra para revisión
Adicionalmente, deberá presentar el D-III Integración del costo del servicio de Limpieza.
Oferta económica presentada por escrito en hoja membretada del licitante.
"""

FOCON_SNIPPET = """
Anexo IV ACREDITAMIENTO DE PERSONALIDAD JURÍDICA PERSONA MORAL
Número LA-07-H0M-007H0M001-N-24-2025
El modelo de contrato así como las condiciones establecidas en el Anexo S Modelo contrato federal.
7.0. puntos Sus ingresos son iguales 20% o hasta 29% del monto total de su oferta económica.
Análisis de Precios Unitarios
"""


def test_broken_anexo_inventory_label_detected():
    assert is_broken_anexo_inventory_label("Anexo V: ), Declaración de Integridad (", "), Declaración")
    assert is_broken_anexo_inventory_label("Anexo VIII: )", "")
    assert not is_broken_anexo_inventory_label("Anexo M Carta de Declaración de Integridad", "Anexo M")


def test_repair_phantom_integridad_to_anexo_m():
    fixed = repair_phantom_anexo_label(
        "Anexo V: ), Declaración de Integridad (",
        "), Declaración de Integridad (",
        ISAPEG_BASES,
    )
    assert "anexo m" in fixed.lower()
    assert "integridad" in fixed.lower()


def test_formats_noise_excludes_federal_and_criteria():
    assert is_formats_panel_noise(
        "Anexo S Modelo contrato federal",
        "",
        "El modelo de contrato así como las condiciones establecidas",
    )
    assert is_formats_panel_noise(
        "7.0. puntos Sus ingresos",
        "",
        "20% del monto total de su oferta económica",
    )
    assert is_formats_panel_noise("Pago de penas convencionales", "", "")
    assert not is_formats_panel_noise("Anexo F Constancia de Visitas", "", "Anexo F Constancia de Visitas")


def test_foreign_lpn_rejected():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[("bases_0001.pdf", ISAPEG_BASES)],
        filenames=["bases_0001.pdf"],
    )
    primary_tokens = {"4000400100324"}
    assert snippet_has_foreign_licitacion_id("LA-07-H0M-007H0M001-N-24-2025", primary_tokens)
    assert not passes_formats_panel_bases_gate(
        "Anexo IV Acreditación PM",
        "Número LA-07-H0M-007H0M001-N-24-2025",
        corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )


def test_extraction_primary_only_ignores_foreign_patterns():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[
            ("bases_0001.pdf", ISAPEG_BASES),
            ("FOCON 04.pdf", FOCON_SNIPPET),
        ],
        filenames=["bases_0001.pdf", "FOCON 04.pdf"],
    )
    rows = extract_pliego_generables_from_bases_corpus(corpus)
    joined = " ".join(r["nombre_canonico"].lower() for r in rows)
    assert "contrato federal" not in joined
    assert "7.0. puntos" not in joined
    assert "007h0m" not in joined
    assert "anexo iii" in joined or "integracion" in joined or "d-iii" in joined


def test_valid_isapeg_format_passes_gate():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[("bases_0001.pdf", ISAPEG_BASES)],
        filenames=["bases_0001.pdf"],
    )
    assert passes_formats_panel_bases_gate(
        "Anexo F Constancia de Visitas",
        "Anexo F Constancia de Visitas",
        corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )
