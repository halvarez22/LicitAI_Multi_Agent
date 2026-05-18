"""Extracción determinista desde texto tipo CIF / constancia SAT."""

from app.services.cif_profile_extract import extract_cif_company_profile_patch
from app.services.legal_representative_parser import is_constancia_cif_text


def test_is_constancia_cif_text_detects_marker():
    t = "CÉDULA DE IDENTIFICACIÓN FISCAL\nNombre, denominación o razón social\nX SA DE CV"
    assert is_constancia_cif_text(t) is True
    assert is_constancia_cif_text("acta constitutiva sin sat") is False


def test_extract_moderno_domicilio_sat():
    blob = """
    CONSTANCIA DE SITUACIÓN FISCAL
    Nombre de vialidad: INSURGENTES SUR
    Número exterior: 1602
    Número interior: Piso 4
    Nombre de la colonia: DEL VALLE
    Código postal: 03940
    Nombre de la localidad: CIUDAD DE MÉXICO
    Nombre del municipio o demarcación territorial: BENITO JUÁREZ
    Nombre de la entidad federativa: CIUDAD DE MÉXICO
    RFC ABC123456XYZ
    """
    out = extract_cif_company_profile_patch(blob, is_fisica=False)
    assert "domicilio_fiscal" in out
    assert "INSURGENTES SUR" in out["domicilio_fiscal"]
    assert "03940" in out["domicilio_fiscal"]


def test_extract_legacy_domicilio_fiscal_bloque():
    blob = """
    Cédula de Identificación Fiscal
    Nombre, denominación o razón social
    EJEMPLO SERVICIOS SA DE CV
    RFC CMT160107S83
    Domicilio fiscal
    Av. Siempre Viva 742, Col. Centro, Monterrey, Nuevo León, C.P. 64000
    Régimen General de Ley Personas Morales
    """
    out = extract_cif_company_profile_patch(blob, is_fisica=False)
    assert out.get("domicilio_fiscal")
    assert "64000" in out["domicilio_fiscal"] or "Siempre Viva" in out["domicilio_fiscal"]
    assert "EJEMPLO" in (out.get("razon_social") or "")


def test_extract_domicilio_persona_fisica_sin_razon_moral():
    blob = """
    Constancia de situación fiscal
    Nombre de vialidad: REFORMA
    Número exterior: 100
    Nombre de la colonia: CENTRO
    Código postal: 06000
    Nombre de la entidad federativa: CIUDAD DE MÉXICO
    """
    out = extract_cif_company_profile_patch(blob, is_fisica=True)
    assert out.get("domicilio_fiscal")
    assert "razon_social" not in out
