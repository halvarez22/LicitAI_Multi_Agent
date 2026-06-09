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


def test_compute_totals_obra_publica_aplica_indirectos_y_utilidad():
    engine = EconomicCalculatorEngine()
    items = [{"concepto": "0101", "cantidad": 1, "precio_unitario": 2_446_850, "subtotal": 2_446_850}]
    reglas = {
        "catalogo_obra_footer": (
            "Costos Indirectos (10%) 244,685.00 Utilidad (5%) 134,576.75 "
            "IVA 16% TOTAL $3,278,289.63"
        )
    }
    out = engine.compute_totals(
        proposal_items=items,
        reglas_economicas=reglas,
        session_name="barda_primaria_lopez_rayon",
    )
    assert out["profile_name"] == "perfil_obra_publica_v1"
    assert out["formula_set"] == "obra_publica_v1"
    assert abs(out["costos_directos"] - 2_446_850.0) < 0.02
    assert abs(out["costos_indirectos"] - 244_685.0) < 0.02
    assert abs(out["utilidad"] - 134_576.75) < 0.02
    assert abs(out["subtotal_antes_iva"] - 2_826_111.75) < 0.02
    assert abs(out["grand_total"] - 3_278_289.63) < 0.05
