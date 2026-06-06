"""Preferencia de materialización al deduplicar en packager."""
from __future__ import annotations

from app.agents.document_packager import _pick_preferred_doc


def test_pick_preferred_prefers_deterministic_over_larger_shell(tmp_path):
    small = tmp_path / "apu_det.docx"
    large = tmp_path / "apu_shell.docx"
    small.write_bytes(b"x" * 1000)
    large.write_bytes(b"y" * 100000)

    det = {"ruta": str(small), "materialization_route": "deterministic_apu"}
    shell = {"ruta": str(large), "materialization_route": "generate_controlled"}
    picked = _pick_preferred_doc(shell, det)
    assert picked is det
