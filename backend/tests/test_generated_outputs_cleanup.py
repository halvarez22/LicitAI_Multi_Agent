"""Limpieza de expediente generado en disco."""
import os

import pytest

from app.services.generated_outputs_cleanup import (
    reset_session_after_output_wipe,
    wipe_output_directory,
)


def test_wipe_output_directory_removes_all_children(tmp_path):
    root = tmp_path / "isapeg"
    root.mkdir()
    (root / "SOBRE_2_TECNICO").mkdir()
    (root / "SOBRE_2_TECNICO" / "01_dup.docx").write_bytes(b"x")
    (root / "descriptions.json").write_text("{}", encoding="utf-8")

    n, names = wipe_output_directory(str(root))
    assert n == 2
    assert set(names) == {"SOBRE_2_TECNICO", "descriptions.json"}
    assert os.listdir(root) == []


def test_reset_session_clears_generation_flags():
    raw = {
        "generation_state": {"technical": "done"},
        "compranet_packaging": {"validation_passed": True},
        "tasks_completed": [
            {"task": "stage_completed:analysis"},
            {"task": "stage_completed:compranet_pack"},
        ],
    }
    out = reset_session_after_output_wipe(raw)
    assert "generation_state" not in out
    assert "compranet_packaging" not in out
    assert len(out["tasks_completed"]) == 1
    assert out["tasks_completed"][0]["task"] == "stage_completed:analysis"
