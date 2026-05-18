from app.services.economic_calculator_engine import EconomicCalculatorEngine


def test_compute_totals_health_profile_fsr_missing_params_marks_blocking():
    engine = EconomicCalculatorEngine()
    out = engine.compute_totals(
        proposal_items=[{"concepto": "A", "cantidad": 1, "precio_unitario": 100, "subtotal": 100}],
        reglas_economicas={},
        session_name="issste_licitacion_test",
    )
    assert out["profile_name"] == "perfil_con_salario_real_v1"
    assert out["formula_set"] == "salario_real_v1"
    assert out["blocking_issues"]
    assert out["fsr"].get("ok") is False


def test_compute_totals_health_profile_with_fsr_params_ok():
    engine = EconomicCalculatorEngine()
    reglas = {
        "otras_reglas_oferta_precio": (
            "imss=0.245 sar=0.02 infonavit=0.05 dias_no_laborados=52 "
            "dias_laborados=365 prima_vacacional=6 aguinaldo_dias=15"
        )
    }
    out = engine.compute_totals(
        proposal_items=[{"concepto": "A", "cantidad": 1, "precio_unitario": 100, "subtotal": 100}],
        reglas_economicas=reglas,
        session_name="issste_licitacion_test",
    )
    assert out["blocking_issues"] == []
    assert out["fsr"].get("ok") is True
    assert out["fsr"].get("fsr") > 1.0
