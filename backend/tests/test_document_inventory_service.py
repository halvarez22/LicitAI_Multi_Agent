"""Tests del servicio de inventario documental (solape Tier A vs heurística)."""

from pathlib import Path

import pytest

from app.contracts.document_inventory import (
    DocumentInventory,
    DocumentEnvelope,
    InventoryItem,
    InventoryItemStatus,
    InventoryTier,
)
from app.services.document_inventory_service import (
    DocumentInventoryService,
    bases_revision_hash,
    paso_a_regex_items,
    paso_b_heuristic_items,
)


def test_heuristic_omits_line_when_title_embeds_tier_a_form():
    chunk = """6.- DOCUMENTACION ADICIONAL FUERA DE SOBRE.
6.1 Esto es una linea de prueba lo suficientemente larga para pasar el umbral
7.15 Programa de materiales (Forma AT-13) otro texto largo para cumplir minimos
"""
    full = "Forma AT-13 aparece en otro fragmento.\n" + chunk
    rev = bases_revision_hash(full)
    tier_a = paso_a_regex_items(full, rev, "test.txt")
    assert any(i.canonical_id == "forma_at_13" for i in tier_a)

    h = paso_b_heuristic_items(chunk, rev, "test.txt", tier_a)
    caps_715 = [i for i in h if "7.15" in i.display_name or "7_15" in i.canonical_id]
    assert caps_715 == []
    assert any("6.1" in i.display_name for i in h)


@pytest.mark.asyncio
async def test_build_from_bases_text_smoke():
    from app.services.document_inventory_service import DocumentInventoryService

    text = "Forma DD-01\n6.- DOCUMENTACION\n6.1 Linea larga de prueba para inventario minimo"
    inv = await DocumentInventoryService.build_from_bases_text(
        text,
        session_id="s_test",
        source_file="inline",
        use_llm=False,
        correlation_id="pytest",
    )
    assert inv.stats.total_detected >= 1
    assert any(i.canonical_id == "forma_dd_01" for i in inv.items)


def test_sync_inventory_status_from_disk_marks_generated(tmp_path: Path):
    root = tmp_path / "out"
    sub = root / "1.propuesta_tecnica"
    sub.mkdir(parents=True)
    (sub / "02_Forma_AT_02_contenido.docx").write_bytes(b"x")

    inv = DocumentInventory(
        session_id="sess_x",
        revision=1,
        items=[
            InventoryItem(
                canonical_id="forma_at_02",
                display_name="AT-02",
                description="test",
                category=DocumentEnvelope.TECHNICAL,
                tier=InventoryTier.TIER_A_ANCHORED,
                status=InventoryItemStatus.PENDING,
                anchors=[],
                bases_revision="rev",
            ),
            InventoryItem(
                canonical_id="forma_dd_99",
                display_name="DD-99",
                description="missing",
                category=DocumentEnvelope.LEGAL,
                tier=InventoryTier.TIER_A_ANCHORED,
                status=InventoryItemStatus.PENDING,
                anchors=[],
                bases_revision="rev",
            ),
        ],
    )
    synced = DocumentInventoryService.sync_inventory_status_from_disk(
        inv, session_id="sess_x", output_root=str(root)
    )
    at = next(i for i in synced.items if i.canonical_id == "forma_at_02")
    dd = next(i for i in synced.items if i.canonical_id == "forma_dd_99")
    assert at.status == InventoryItemStatus.GENERATED
    assert at.relative_output_path == "1.propuesta_tecnica/02_Forma_AT_02_contenido.docx"
    assert dd.status == InventoryItemStatus.PENDING


@pytest.mark.asyncio
async def test_sync_inventory_to_session_memory_persists(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "cap_6_1_algo.docx").write_bytes(b"z")

    class _Mem:
        def __init__(self) -> None:
            self.store: dict = {}

        async def get_session(self, sid: str):
            return dict(self.store.get(sid, {}))

        async def save_session(self, sid: str, data: dict) -> None:
            self.store[sid] = dict(data)

    mem = _Mem()
    payload = DocumentInventory(
        session_id="s1",
        revision=1,
        items=[
            InventoryItem(
                canonical_id="cap_6_1_algo",
                display_name="6.1",
                description="d",
                category=DocumentEnvelope.LEGAL,
                tier=InventoryTier.TIER_B_INFERRED,
                status=InventoryItemStatus.PENDING,
                anchors=[],
                bases_revision="r",
            )
        ],
    ).model_dump(mode="json")

    await mem.save_session("s1", {"tasks_completed": [{"task": "x"}]})
    out = await DocumentInventoryService.sync_inventory_to_session_memory(
        mem, "s1", payload, output_root=str(root)
    )
    assert out.items[0].status == InventoryItemStatus.GENERATED
    fresh = await mem.get_session("s1")
    assert fresh["tasks_completed"] == [{"task": "x"}]
    assert fresh["document_inventory"]["items"][0]["status"] == "generated"
