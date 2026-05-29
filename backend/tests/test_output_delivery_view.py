"""Tests de vista de entrega deduplicada y poda post-CompraNet."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.services.output_delivery_view import (
    build_delivery_structure,
    has_compranet_validated,
    iter_delivery_zip_entries,
    prune_duplicate_output_copies,
    summarize_delivery_inventory,
)


def _write(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_prune_keeps_compranet_and_logistics(tmp_path: Path) -> None:
    root = tmp_path / "isapeg"
    validated = root / "_compranet_validated" / "SobreTecnica"
    _write(validated / "doc.docx", b"tech")
    _write(root / "1.propuesta tecnica" / "dup.docx", b"tech")
    _write(root / "SOBRE_2_TECNICO" / "copy.docx", b"tech")
    _write(root / "LOGISTICA_Y_GUIA_DE_ENTREGA.pdf", b"pdf")
    _write(root / "descriptions.json", b"{}")

    res = prune_duplicate_output_copies(str(root))
    assert res["removed_count"] >= 3
    assert not (root / "SOBRE_2_TECNICO").exists()
    assert (validated / "doc.docx").is_file()
    assert (root / "LOGISTICA_Y_GUIA_DE_ENTREGA.pdf").is_file()


def test_delivery_structure_uses_validated_only(tmp_path: Path) -> None:
    root = tmp_path / "sess"
    c1 = b"admin-one"
    c2 = b"tech-one"
    _write(root / "_compranet_validated" / "SobreComplementaria" / "a.docx", c1)
    _write(root / "_compranet_validated" / "SobreTecnica" / "t.docx", c2)
    _write(root / "3.documentos administrativos" / "a.docx", c1)
    _write(root / "SOBRE_1_ADMINISTRATIVO" / "a.docx", c1)

    structure, inv = build_delivery_structure(str(root))
    total_files = sum(len(f["files"]) for f in structure)
    assert total_files == 2
    assert inv["deliverable_files"] == 2
    assert inv["duplicate_extra_files"] == 0
    assert has_compranet_validated(str(root))


def test_zip_entries_exclude_sobre_copies(tmp_path: Path) -> None:
    root = tmp_path / "sess2"
    _write(root / "_compranet_validated" / "SobreTecnica" / "t.docx", b"t")
    _write(root / "SOBRE_2_TECNICO" / "t.docx", b"t")
    entries = iter_delivery_zip_entries(str(root))
    arcs = [a for _f, a in entries]
    assert len(arcs) == 1
    assert arcs[0].startswith("_compranet_validated/")


def test_inventory_physical_vs_deliverable(tmp_path: Path) -> None:
    root = tmp_path / "sess3"
    body = b"same"
    _write(root / "_compranet_validated" / "SobreTecnica" / "t.docx", body)
    _write(root / "1.propuesta tecnica" / "t.docx", body)
    inv = summarize_delivery_inventory(str(root))
    assert inv["total_files_physical"] == 2
    assert inv["deliverable_files"] == 1
    assert inv["unique_sha256"] == 1


def test_delivery_structure_expone_lineage_desde_indice(tmp_path: Path) -> None:
    root = tmp_path / "sess4"
    rel = "_compranet_validated/SobreTecnica/doc.docx"
    _write(root / rel, b"tech-doc")
    _write(
        root / "_compranet_validated" / "INDICE_ENTREGA.json",
        json.dumps(
            {
                "files": [
                    {
                        "path": "SobreTecnica/doc.docx",
                        "source_doc_id": "doc-1",
                        "source_filename": "ANEXO TÉCNICO 2026.docx",
                        "template_id": "anexo_tecnico",
                        "mirror_mode": "copy_docx_filled",
                        "materialization_route": "mirror",
                        "sha256": _sha(b"tech-doc"),
                    }
                ]
            }
        ).encode("utf-8"),
    )
    structure, _inv = build_delivery_structure(str(root))
    file_row = structure[0]["files"][0]
    assert file_row["source_doc_id"] == "doc-1"
    assert file_row["source_filename"] == "ANEXO TÉCNICO 2026.docx"
    assert file_row["materialization_route"] == "mirror"
