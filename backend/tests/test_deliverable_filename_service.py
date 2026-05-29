"""Tests de nombres de entrega alineados al convocante."""
from __future__ import annotations

import os

import pytest

from app.services.deliverable_filename_service import (
    pick_convocante_label,
    prefer_convocante_filenames,
    resolve_deliverable_filename,
)


def test_pick_convocante_label_source_filename_first() -> None:
    doc = {
        "nombre": "Documento genérico",
        "source_filename": "9. Anexo J Datos de Facturación.xlsx",
    }
    label, src = pick_convocante_label(doc)
    assert "Anexo J" in label
    assert src == "source_filename"


def test_resolve_uses_convocante_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"source_filename": "3. Anexo AB Manifiestos.docx", "nombre": "Manifiestos"}
    used: set[str] = set()
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="RFC1",
        licitacion_token="lic",
        sobre_label="SobreComplementaria",
        orden=1,
        ext=".docx",
        used_names=used,
    )
    assert mode.startswith("convocante:")
    assert name == "3. Anexo AB Manifiestos.docx"
    assert "RFC1_lic" not in name


def test_resolve_fallback_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"nombre": "TE-12 algo técnico"}
    name, mode, _ = resolve_deliverable_filename(
        doc,
        rfc_token="RFC1",
        licitacion_token="lic",
        sobre_label="SobreTecnica",
        orden=2,
        ext=".docx",
        used_names=set(),
    )
    assert mode == "canonical_fallback"
    assert name == "RFC1_lic_SobreTecnica_02.docx"


def test_resolve_collision_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PREFER_CONVOCANTE_FILENAMES", "true")
    doc = {"source_filename": "10. Anexo K Declaración.docx"}
    used: set[str] = {"10. anexo k declaración.docx"}
    name, _, _ = resolve_deliverable_filename(
        doc,
        rfc_token="R",
        licitacion_token="s",
        sobre_label="SobreComplementaria",
        orden=1,
        ext=".docx",
        used_names=used,
    )
    assert "(2)" in name
