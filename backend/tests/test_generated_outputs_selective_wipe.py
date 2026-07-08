"""Tests de wipe selectivo (F2.5)."""

from __future__ import annotations

import os

from app.services.generated_outputs_cleanup import wipe_output_directory_selective


def test_selective_wipe_preserves_economic(tmp_path):
    root = tmp_path / "session"
    root.mkdir()
    (root / "1.propuesta tecnica").mkdir()
    (root / "2.propuesta_economica").mkdir()
    (root / "2.propuesta_economica" / "eco.xlsx").write_text("x", encoding="utf-8")
    (root / "3.documentos administrativos").mkdir()
    (root / "3.documentos administrativos" / "admin.docx").write_text("a", encoding="utf-8")

    removed_count, removed = wipe_output_directory_selective(
        str(root),
        preserve_subdirs=["2.propuesta_economica"],
    )
    assert removed_count == 2
    assert "1.propuesta tecnica" in removed
    assert "3.documentos administrativos" in removed
    assert (root / "2.propuesta_economica" / "eco.xlsx").is_file()
    assert not (root / "1.propuesta tecnica").exists()
