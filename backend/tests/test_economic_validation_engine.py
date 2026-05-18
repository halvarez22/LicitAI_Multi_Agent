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


def test_engine_supervisor_sin_costo_no_bloquea_precios_positivos():
    out = validate_economic_proposal(
        proposal_items=[
            {
                "concepto": "Supervisor General (Sin costo)",
                "cantidad": 1,
                "precio_unitario": 0.0,
                "subtotal": 0.0,
                "supervisor_sin_costo": True,
            },
            {"concepto": "Guardia", "cantidad": 10, "precio_unitario": 100.0, "subtotal": 1000.0},
        ],
        currency="MXN",
        total_base=1000.0,
        grand_total=1160.0,
        reglas_economicas={},
        session_name="licitacion generica",
    )
    assert not any("precios_positivos" in b for b in out.blocking_issues)
    assert any(v.regla == "precios_positivos" and v.estado == "ok" for v in out.validations)


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
    assert any("total_base_cotizable" in b for b in out.blocking_issues)
    assert any(v.regla == "importe_minimo" and v.estado == "warn" for v in out.validations)


def test_engine_supervisor_only_blocks_total_base_cotizable():
    """Solo renglón exento (supervisor): precios_positivos ok pero subtotal base inválido sin HITL."""
    out = validate_economic_proposal(
        proposal_items=[
            {
                "concepto": "Supervisor General (Sin costo)",
                "cantidad": 1,
                "precio_unitario": 0.0,
                "subtotal": 0.0,
                "supervisor_sin_costo": True,
            },
        ],
        currency="MXN",
        total_base=0.0,
        grand_total=0.0,
        reglas_economicas={},
        session_name="licitacion generica",
    )
    assert not any("precios_positivos" in b for b in out.blocking_issues)
    assert any("total_base_cotizable" in b for b in out.blocking_issues)


def test_engine_allow_zero_total_base_supervisor_ok():
    out = validate_economic_proposal(
        proposal_items=[
            {
                "concepto": "Supervisor General (Sin costo)",
                "cantidad": 1,
                "precio_unitario": 0.0,
                "subtotal": 0.0,
                "supervisor_sin_costo": True,
            },
        ],
        currency="MXN",
        total_base=0.0,
        grand_total=0.0,
        reglas_economicas={},
        session_name="licitacion generica",
        allow_zero_total_base=True,
    )
    assert out.blocking_issues == []
    assert any(v.regla == "total_base_cotizable" and v.estado == "ok" for v in out.validations)
