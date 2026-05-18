from app.agents.analyst import (
    _build_solvencia_economica_requirements,
    _build_solvencia_legal_requirements,
)


def test_build_solvencia_legal_requirements_detecta_patrones():
    txt = "Se requiere padrón de proveedores vigente y comprobante de domicilio fiscal."
    out = _build_solvencia_legal_requirements(txt)
    titles = {x["titulo"] for x in out}
    assert "Registro en padrón de proveedores" in titles
    assert "Comprobante de domicilio fiscal" in titles


def test_build_solvencia_economica_requirements_detecta_capital():
    txt = "La convocatoria solicita estados financieros auditados y capital mínimo de $500,000."
    out = _build_solvencia_economica_requirements(txt)
    titles = {x["titulo"] for x in out}
    assert "Estados financieros auditados" in titles
    assert "Capital mínimo requerido" in titles
