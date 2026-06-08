"""Banderas de /downloads/list para habilitar ZIP (CompraNet validado o entregables)."""
import os
import tempfile

from app.api.v1.routes.downloads import _list_response
from app.services.output_delivery_view import COMPRANET_VALIDATED_DIR, delivery_zip_available


def test_delivery_zip_unavailable_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert delivery_zip_available(d) is False


def test_delivery_zip_available_with_compranet_validated():
    with tempfile.TemporaryDirectory() as d:
        sobre = os.path.join(d, COMPRANET_VALIDATED_DIR, "SobreEconomica")
        os.makedirs(sobre)
        with open(os.path.join(sobre, "propuesta.xlsx"), "w", encoding="utf-8") as f:
            f.write("x")
        assert delivery_zip_available(d) is True


def test_list_response_zip_available_when_compranet_present():
    with tempfile.TemporaryDirectory() as d:
        sobre = os.path.join(d, COMPRANET_VALIDATED_DIR, "SobreEconomica")
        os.makedirs(sobre)
        with open(os.path.join(sobre, "propuesta.xlsx"), "w", encoding="utf-8") as f:
            f.write("x")
        out = _list_response(d)
        assert out["success"] is True
        assert out["output_dir_resolved"] is True
        assert out["zip_available"] is True
        assert len(out["data"]) >= 1


def test_list_response_no_dir():
    out = _list_response(None)
    assert out["zip_available"] is False
    assert out["output_dir_resolved"] is False
