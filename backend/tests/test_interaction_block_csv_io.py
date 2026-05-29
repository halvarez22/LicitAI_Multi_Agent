from pathlib import Path

from app.contracts.interaction_block import (
    BlockAnchor,
    InteractionBlock,
    InteractionBlockItem,
    InteractionBlockMetadata,
)
from app.services.interaction_block_csv_io import (
    interaction_block_to_csv_rows,
    read_mass_save_rows,
    write_interaction_block_csv,
)


def _sample_block() -> InteractionBlock:
    return InteractionBlock(
        block_id="blk_1",
        anchor=BlockAnchor(title="Bases", page=12, legal_reference="Referencia"),
        items=[
            InteractionBlockItem(
                item_id="price_a",
                label="Zona A | costo por elemento",
                unit="elemento",
                suggested_value=123.45,
                block_item_seq=1,
            ),
            InteractionBlockItem(
                item_id="price_b",
                label="ALCOHOL EN GEL (LITRO)",
                unit="litro",
                suggested_value=None,
                block_item_seq=2,
            ),
        ],
        metadata=InteractionBlockMetadata(total_items=2),
    )


def test_interaction_block_to_csv_rows_formats_suggested_value():
    rows = interaction_block_to_csv_rows(_sample_block())
    assert rows[0]["item_id"] == "price_a"
    assert rows[0]["suggested_value"] == "123.45"
    assert rows[0]["value"] == ""
    assert rows[1]["suggested_value"] == ""


def test_read_mass_save_rows_ignores_blank_values(tmp_path: Path):
    csv_path = tmp_path / "prices.csv"
    write_interaction_block_csv(_sample_block(), csv_path)
    content = csv_path.read_text(encoding="utf-8-sig")
    content = content.replace("price_a,Zona A | costo por elemento,elemento,123.45,,must_be_finite_number,", "price_a,Zona A | costo por elemento,elemento,123.45,456.78,must_be_finite_number,")
    csv_path.write_text(content, encoding="utf-8-sig")
    rows = read_mass_save_rows(csv_path)
    assert rows == [{"item_id": "price_a", "value": "456.78"}]


def test_read_mass_save_rows_accepts_valor_alias(tmp_path: Path):
    csv_path = tmp_path / "prices_alias.csv"
    csv_path.write_text(
        "item_id,label,valor\nprice_x,Concepto X,88.5\nprice_y,Concepto Y,\n",
        encoding="utf-8-sig",
    )
    rows = read_mass_save_rows(csv_path)
    assert rows == [{"item_id": "price_x", "value": "88.5"}]
