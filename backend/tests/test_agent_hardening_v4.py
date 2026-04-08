from app.agents.analyst import AnalystAgent
from app.agents.compliance import ComplianceAgent
from app.agents.economic import EconomicAgent


def test_analyst_fallback_periodo_minimo():
    agent = object.__new__(AnalystAgent)
    out = agent._infer_periodo_minimo_from_context("El importe mínimo será para un periodo base de 12 meses.")
    assert out == "12 meses"


def test_compliance_normalize_item_marcas_causa():
    agent = object.__new__(ComplianceAgent)
    item = agent._normalize_item({"descripcion": "Se desechará la propuesta que incumpla requisitos.", "page": 3})
    assert item["descripcion"].lower().startswith("causa de desechamiento:")


def test_economic_inyecta_supervisor_sin_costo():
    agent = object.__new__(EconomicAgent)
    items = [{"concepto": "Servicio base", "precio_unitario": 1.0, "subtotal": 1.0}]
    alcance = [{"puesto_funcion_o_servicio": "Coordinador de turno en sitio", "texto_literal_fila": ""}]
    out = agent._ensure_supervisor_no_cost_item(items, alcance)
    assert any("sin costo" in str(x.get("concepto", "")).lower() for x in out)
