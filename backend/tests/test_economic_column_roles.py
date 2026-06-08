import pytest

from app.services.economic_column_roles import (
    ROLE_AMOUNT,
    ROLE_LOCATION_LABEL,
    ROLE_QUANTITY,
    ROLE_UNIT_PRICE_EXCL_IVA,
    ROLE_UNIT_PRICE_IVA_INCLUDED,
    detect_column_role,
    human_role_label,
    map_header_row_to_roles,
)


@pytest.mark.parametrize(
    "header,expected",
    [
        ("COSTO POR ELEMENTO I.V.A INCLUIDO", ROLE_UNIT_PRICE_IVA_INCLUDED),
        ("Costo por elemento con IVA incluido", ROLE_UNIT_PRICE_IVA_INCLUDED),
        ("PRECIO UNITARIO IVA INCL", ROLE_UNIT_PRICE_IVA_INCLUDED),
        ("Precio Unitario (sin IVA)", ROLE_UNIT_PRICE_EXCL_IVA),
        ("P.U.", ROLE_UNIT_PRICE_EXCL_IVA),
        ("COSTO UNITARIO", ROLE_UNIT_PRICE_EXCL_IVA),
        ("IMPORTE", ROLE_AMOUNT),
        ("Cantidad mensual", ROLE_QUANTITY),
        ("LOCALIDAD", ROLE_LOCATION_LABEL),
        ("Municipio", ROLE_LOCATION_LABEL),
    ],
)
def test_detect_column_role_variants(header: str, expected: str):
    assert detect_column_role(header) == expected


def test_map_header_row_to_roles():
    roles = map_header_row_to_roles(
        ["LOCALIDAD", "NÚM. ELEMENTOS", "COSTO POR ELEMENTO I.V.A INCLUIDO", "IMPORTE"]
    )
    assert roles[0] == ROLE_LOCATION_LABEL
    assert roles[2] == ROLE_UNIT_PRICE_IVA_INCLUDED
    assert roles[3] == ROLE_AMOUNT


def test_human_label():
    assert "iva" in human_role_label(ROLE_UNIT_PRICE_IVA_INCLUDED).lower()
