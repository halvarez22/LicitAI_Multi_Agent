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
        generated_documents=[{"ruta": str(f), "tipo": "tabla_precios", "template_id": "tabla_precios"}],
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
    assert out["policy_version"] == "1.3.0"
    assert out["documents_with_policy"] == 1


def test_fill_gate_confianza_insuficiente_y_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "anexo_7.docx"
    _make_docx(f, ["ACME SA DE CV", "RFC_MALO", "Ana"])
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


def test_fill_gate_valida_que_el_docx_materializado_contenga_rfc(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "anexo_7.docx"
    _make_docx(f, ["Documento legal sin datos de empresa"])
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f), "tipo": "administrativo", "template_id": "anexo_7"}],
        master_profile={
            "razon_social": "ACME SA DE CV",
            "rfc": "ACM010101AAA",
            "representante_legal": "Ana Perez",
        },
    )
    missing_fields = {i["field_key"] for i in out["issues"] if i["error_type"] == "required_field_missing"}
    assert "rfc" in missing_fields
    assert "razon_social" in missing_fields
    assert "representante_legal" in missing_fields


def test_fill_gate_ignora_separador_pero_detecta_blanco_real(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "blancos.docx"
    _make_docx(
        f,
        [
            "__________________________________________________",
            "Quien suscribe _____________________, bajo protesta de decir verdad manifiesto lo siguiente:",
        ],
    )
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f)}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
    )
    placeholders = [i for i in out["issues"] if i["error_type"] == "placeholder_detected"]
    assert len(placeholders) == 1
    assert "Quien suscribe" in placeholders[0]["detected_value"]


def test_fill_gate_detecta_cross_tender_y_blancos_en_xlsx(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "econ_cross.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A1"] = (
        "SERVICIO INTEGRAL ... PARA LOS SERVICIOS DE SALUD DEL INSTITUTO MEXICANO "
        "DEL SEGURO SOCIAL PARA EL BIENESTAR (IMSS-BIENESTAR)."
    )
    ws["A2"] = (
        "IMSS-BIENESTAR únicamente aceptará cubrir lo manifestado en la propuesta económica."
    )
    ws["A3"] = (
        "Quien suscribe, _______________________, en mi carácter de representante legal "
        "de la empresa ______________________"
    )
    wb.save(f)
    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[{"ruta": str(f)}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
        provenance_context={"source": "economic_writer", "confidence": 0.95, "session_hint": "isapeg ISAPEG"},
    )
    error_types = {i["error_type"] for i in out["issues"]}
    assert "placeholder_detected" in error_types
    assert "cross_tender_reference" in error_types


def test_fill_gate_no_confunde_ellipsis_en_domicilio_xlsx(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "econ_dir.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "DOMICILIO"
    ws["A2"] = (
        "CARRETERA DOLORES HIDALGO-XOCONOXTLE.750...SAN ANTONIO DEL PRETORIO."
        "DOLORES HIDALGO CUNA DE LA INDEPENDENCIA NACIONAL"
    )
    wb.save(f)

    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[{"ruta": str(f), "tipo": "plantilla_economica_espejo"}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
        provenance_context={"source": "economic_writer", "confidence": 0.95, "session_hint": "isapeg ISAPEG"},
    )

    assert not any(i["error_type"] == "placeholder_detected" for i in out["issues"])


def test_fill_gate_no_aplica_totales_a_excel_espejo_solo_por_nombre(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "ECON_09_anexo_iii_p1_2_za_propuesta_economica.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "ANEXO III PARTIDA 2 ZONA A PROPUESTA ECONOMICA"
    ws["B2"] = "Descripción del material"
    ws["E2"] = "Cantidad mensual"
    wb.save(f)

    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[{"ruta": str(f), "tipo": "plantilla_economica_espejo"}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
        provenance_context={"source": "economic_writer", "confidence": 0.95, "session_hint": "isapeg ISAPEG"},
    )

    required_missing = {
        i["field_key"]
        for i in out["issues"]
        if i["error_type"] == "required_field_missing"
    }
    assert "subtotal" not in required_missing
    assert "iva" not in required_missing
    assert "total" not in required_missing


def test_fill_gate_bloquea_excel_espejo_sin_locators_validos(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "econ_skipped.xlsx"
    wb = Workbook()
    wb.save(f)

    out = validate_generated_documents_fill(
        stage="economic",
        generated_documents=[
            {
                "ruta": str(f),
                "tipo": "plantilla_economica_espejo",
                "fill_status": "skipped_missing_locator",
                "valid_locator_count": 0,
            }
        ],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
        provenance_context={"source": "economic_writer", "confidence": 0.95, "session_hint": "isapeg ISAPEG"},
    )

    missing_fields = {
        i["field_key"]
        for i in out["issues"]
        if i["error_type"] == "required_field_missing"
    }
    assert "price_fill" in missing_fields


def test_fill_gate_ignora_placeholders_de_formato_referencia_fianza(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    f = tmp_path / "anexo_g_fianza.docx"
    _make_docx(
        f,
        [
            "AUTORIZACIÓN DEL GOBIERNO FEDERAL PARA OPERAR: ________ (NÚMERO DE OFICIO Y FECHA)",
            "NÚMERO: ____________________. (NÚMERO ASIGNADO POR LA \"AFIANZADORA\")",
            "MONTO AFIANZADO: ____________ (CON LETRA Y NÚMERO, SIN INCLUIR EL IMPUESTO AL VALOR AGREGADO)",
            "FECHA DE EXPEDICIÓN: _____________________.",
            "LA \"AFIANZADORA\" garantiza el cumplimiento del contrato.",
        ],
    )
    out = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(f), "tipo": "administrativo"}],
        master_profile={"razon_social": "ACME", "rfc": "ACM010101AAA", "representante_legal": "Ana"},
    )
    assert not any(i["error_type"] == "placeholder_detected" for i in out["issues"])
