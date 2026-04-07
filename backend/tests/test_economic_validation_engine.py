from app.economic_validation.engine import validate_economic_proposal


def test_engine_ok_basic():
    out = validate_economic_proposal(
        proposal_items=[
            {"concepto": "A", "cantidad": 2, "precio_unitario": 10.0, "subtotal": 20.0},
            {"concepto": "B", "cantidad": 1, "precio_unitario": 30.0, "subtotal": 30.0},
            {"concepto": "C", "cantidad": 1, "precio_unitario": 35.0, "subtotal": 35.0},
        ],
        currency="MXN",
        total_base=85.0,
        grand_total=98.6,
        reglas_economicas={},
        session_name="licitacion generica",
    )
    assert out.perfil_usado == "generic"
    assert len(out.validations) >= 4
    assert out.blocking_issues == []


def test_engine_blocking_price_and_warn_min_importe():
    out = validate_economic_proposal(
        proposal_items=[
            {"concepto": "A", "cantidad": 1, "precio_unitario": 0.0, "subtotal": 0.0},
        ],
        currency="MXN",
        total_base=0.0,
        grand_total=0.0,
        reglas_economicas={
            "criterio_importe_minimo_o_plazo_inferior": "Importe mínimo 1000 MXN"
        },
        session_name="sesion x",
    )
    assert out.blocking_issues
    assert any("precios_positivos" in b for b in out.blocking_issues)
    assert any(v.regla == "importe_minimo" and v.estado == "warn" for v in out.validations)
