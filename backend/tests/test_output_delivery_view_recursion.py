"""Regresión: listado de entregas no debe recursar (RecursionError en /downloads/list)."""
from pathlib import Path

from app.services.output_delivery_view import (
    build_delivery_structure,
    summarize_delivery_inventory,
)


def test_empty_output_dir_no_recursion(tmp_path: Path) -> None:
    root = tmp_path / "empty_sess"
    root.mkdir()
    structure, inv = build_delivery_structure(str(root))
    assert structure == []
    assert inv["deliverable_files"] == 0
    inv2 = summarize_delivery_inventory(str(root))
    assert inv2["delivery_view"] == "empty"
