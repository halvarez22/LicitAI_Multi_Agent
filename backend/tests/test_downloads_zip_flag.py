"""Banderas de /downloads/list para habilitar ZIP aunque no haya .docx/.pdf en el árbol UI."""
import os
import tempfile

from app.api.v1.routes.downloads import _has_files_for_zip, _list_response


def test_has_files_for_zip_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert _has_files_for_zip(d) is False


def test_has_files_for_zip_json_counts():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "MANIFIESTO_SHA256.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        assert _has_files_for_zip(d) is True


def test_list_response_zip_available_when_only_non_listed_extensions():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "foo.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        out = _list_response(d)
        assert out["success"] is True
        assert out["output_dir_resolved"] is True
        assert out["zip_available"] is True
        assert out["data"] == []


def test_list_response_no_dir():
    out = _list_response(None)
    assert out["zip_available"] is False
    assert out["output_dir_resolved"] is False
