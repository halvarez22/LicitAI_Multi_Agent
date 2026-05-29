from app.services.economic_column_roles import (
    ROLE_UNIT_PRICE_IVA_INCLUDED,
    detect_column_role,
    human_role_label,
)


def test_detect_iva_included_header():
    assert detect_column_role("COSTO POR ELEMENTO I.V.A INCLUIDO") == ROLE_UNIT_PRICE_IVA_INCLUDED


def test_human_label():
    assert "iva" in human_role_label(ROLE_UNIT_PRICE_IVA_INCLUDED).lower()
