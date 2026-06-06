"""Tests de nombres de entrega alineados al convocante."""
from __future__ import annotations

import pytest

from app.services.deliverable_filename_service import (
    _looks_like_convocante_label,
    pick_convocante_label,
    prefer_convocante_filenames,
    refine_convocante_label,
    resolve_deliverable_filename,
)


def test_pick_convocante_label_source_filename_first() -> None:
    doc = {
        "nombre": "Documento genérico",
        "source_filename": "9. Anexo J Datos de Facturación.xlsx",
    }
    label, src = pick_convocante_label(doc)
    assert "Anexo J" in label
    assert src == "source_filename"


def test_resolve_uses_convocante_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"source_filename": "3. Anexo AB Manifiestos.docx", "nombre": "Manifiestos"}
    used: set[str] = set()
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="RFC1",
        licitacion_token="lic",
        sobre_label="SobreComplementaria",
        orden=1,
        ext=".docx",
        used_names=used,
    )
    assert mode.startswith("convocante:")
    assert name == "3. Anexo AB Manifiestos.docx"
    assert "RFC1_lic" not in name


def test_resolve_fallback_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"nombre": "TE-12"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="RFC1",
        licitacion_token="lic",
        sobre_label="SobreTecnica",
        orden=2,
        ext=".docx",
        used_names=set(),
    )
    assert mode == "canonical_fallback"
    assert name == "RFC1_lic_SobreTecnica_02.docx"


def test_resolve_collision_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"source_filename": "10. Anexo K Declaración.docx"}
    used: set[str] = {"10. anexo k declaración.docx"}
    name, _, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreComplementaria",
        orden=1,
        ext=".docx",
        used_names=used,
    )
    assert "(2)" in name


@pytest.mark.parametrize(
    "nombre",
    [
        "Anexo_VI_Carta_Compromiso_de_que_cumplira.docx",
        "Anexo_I_el_modelo_de_como_prodra_presentarla.docx",
        "Anexo_III_que_refiere_a_los_datos_generales.docx",
        "Anexo_IX_Carta_de_aseguramiento.docx",
        "12. Anexo M Declaracion de Integridad.docx",
    ],
)
def test_anexo_romano_con_guion_bajo_es_convocante(nombre: str) -> None:
    assert _looks_like_convocante_label(nombre)


def test_anexo_pipeline_con_prefijo_empaquetador(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {
        "nombre": "07_Anexo_VI_Carta_Compromiso.docx",
        "archivo": "07_Anexo_VI_Carta_Compromiso.docx",
    }
    name, mode, label = resolve_deliverable_filename(
        doc,
        rfc_token="RFCX",
        licitacion_token="sesion_demo",
        sobre_label="SobreComplementaria",
        orden=7,
        ext=".docx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert "Anexo VI" in name
    assert "RFCX_sesion_demo" not in name
    assert "Anexo VI" in label


def test_propuesta_tecnica_y_economica_universal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    cases = (
        ("01_CARTA_PRESENTACION_PROPUESTA_TECNICA.docx", "SobreTecnica", "presentacion"),
        ("02_TE-01_Propuesta_Tecnica.docx", "SobreTecnica", "Propuesta Tecnica"),
        ("ANALISIS_PRECIOS_UNITARIOS.docx", "SobreEconomica", "ANALISIS PRECIOS"),
        ("TABLA_PRECIOS_UNITARIOS.xlsx", "SobreEconomica", "TABLA PRECIOS"),
        ("CARTA_COMPROMISO_PRECIOS.docx", "SobreEconomica", "COMPROMISO PRECIOS"),
    )
    for nombre, sobre, needle in cases:
        name, mode, _ = resolve_deliverable_filename(
            {"nombre": nombre},
            rfc_token="AAA",
            licitacion_token="lic_generica",
            sobre_label=sobre,
            orden=1,
            ext=".docx" if not nombre.endswith(".xlsx") else ".xlsx",
            used_names=set(),
        )
        assert mode.startswith("convocante:"), nombre
        assert needle.lower() in name.lower(), name


def test_otra_licitacion_ad_con_descripcion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Señal universal AD-NN + texto; no mapa fijo por convocante."""
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"nombre": "GYN-051-AD-71_Carta_declaracion_understanding.docx"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="RFCG",
        licitacion_token="gyn_vigilancia_2024",
        sobre_label="SobreComplementaria",
        orden=3,
        ext=".docx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert "AD-71" in name or "declaracion" in name.lower()
    assert "RFCG_gyn" not in name


def test_fo35_modelo_presentacion_es_convocante(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"nombre": "FO-35_Anexo_IV_Modelo_presentacion_Propuesta.docx"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreTecnica",
        orden=3,
        ext=".docx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert "modelo" in name.lower() or "FO-35" in name


@pytest.mark.parametrize(
    "pipeline_name,needle",
    [
        (
            "cat_anexo_k_declaracion_de_intereses_10_Anexo_K_Declaracion_de_interesesdocx",
            "10. Anexo K Declaracion de intereses",
        ),
        (
            "mirror_01_21_Anexo_III-B_Actividades_del_supervisor_de_limp.docx",
            "21. Anexo III-B Actividades del supervisor de limp",
        ),
        (
            "03_Anexo_AB_Manifiestosdocx",
            "3. Anexo AB Manifiestos",
        ),
        (
            "panel_pliego_12_Anexo_M_Declaracion_de_Integridad.docx",
            "12. Anexo M Declaracion de Integridad",
        ),
    ],
)
def test_refine_pipeline_embedded_anexo_label(
    pipeline_name: str, needle: str
) -> None:
    refined = refine_convocante_label(pipeline_name)
    assert needle.lower() in refined.lower()


def test_cat_pipeline_resolves_convocante_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {
        "nombre": (
            "cat_anexo_k_declaracion_de_intereses_10_Anexo_K_Declaracion_de_interesesdocx"
        ),
        "archivo": (
            "cat_anexo_k_declaracion_de_intereses_10_Anexo_K_Declaracion_de_interesesdocx"
        ),
    }
    name, mode, label = resolve_deliverable_filename(
        doc,
        rfc_token="RFCX",
        licitacion_token="sesion_demo",
        sobre_label="SobreComplementaria",
        orden=10,
        ext=".docx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert name == "10. Anexo K Declaracion de intereses.docx"
    assert "cat" not in name.lower()
    assert "RFCX_sesion_demo" not in name
    assert "10. Anexo K" in label


def test_mirror_pipeline_resolves_numbered_anexo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {
        "nombre": "mirror_01_21_Anexo_III-B_Actividades_del_supervisor_de_limp.docx",
    }
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreTecnica",
        orden=1,
        ext=".docx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert "21. Anexo III-B" in name
    assert "mirror" not in name.lower()


def test_econ_pipeline_extracts_anexo_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"nombre": "ECON_01_anexo_iii_p_1_zona_a.xlsx"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreEconomica",
        orden=1,
        ext=".xlsx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert "anexo iii" in name.lower()
    assert "econ" not in name.lower()


def test_clean_source_filename_unchanged_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regresión UNAQ: nombres ya legibles no se degradan."""
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"source_filename": "9. Anexo J Datos de Facturación.xlsx"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreComplementaria",
        orden=9,
        ext=".xlsx",
        used_names=set(),
    )
    assert mode.startswith("convocante:")
    assert name == "9. Anexo J Datos de Facturación.xlsx"
