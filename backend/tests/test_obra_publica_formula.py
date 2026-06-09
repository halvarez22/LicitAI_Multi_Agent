from decimal import Decimal

from app.economic_validation.formulas.obra_publica_v1 import compute_obra_publica_totals


def test_obra_publica_totals_barda_catalog_math():
    out = compute_obra_publica_totals(
        Decimal("2446850.00"),
        indirectos_rate=Decimal("0.10"),
        utilidad_rate=Decimal("0.05"),
        iva_rate=Decimal("0.16"),
    )
    assert out["costos_directos"] == 2_446_850.0
    assert out["costos_indirectos"] == 244_685.0
    assert out["utilidad"] == 134_576.75
    assert out["subtotal_antes_iva"] == 2_826_111.75
    assert out["iva_amount"] == 452_177.88
    assert out["grand_total"] == 3_278_289.63
