"""Tests Hito A1: RequirementGrouper + guardado masivo de InteractionBlock."""
import pytest

from app.config.settings import settings
from app.services.interaction_block_mass_save import mass_save_economic_block
from app.services.requirement_grouper import (
    build_interaction_block,
    select_economic_cluster,
    stable_block_id_for_cluster,
)


def _pending_three(gkey: str = "g1") -> list:
    return [
        {"field": "price_a", "type": "economic_price", "label": "A", "block_group_key": gkey, "block_item_seq": 1},
        {"field": "price_b", "type": "economic_price", "label": "B", "block_group_key": gkey, "block_item_seq": 2},
        {"field": "price_c", "type": "economic_price", "label": "C", "block_group_key": gkey, "block_item_seq": 3},
    ]


def _session_with_analisis(pending: list) -> dict:
    return {
        "pending_questions": pending,
        "current_question_index": 0,
        "tasks_completed": [
            {
                "task": "analisis_bases",
                "result": {"reglas_economicas": {"referencia_partidas_anexos_citados": "Anexo 5 tablas"}},
            }
        ],
    }


def test_build_interaction_block_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BLOCK_RESOLUTION", False)
    s = _session_with_analisis(_pending_three())
    assert build_interaction_block(session_id="s1", session_state=s) is None


def test_build_interaction_block_builds_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BLOCK_RESOLUTION", True)
    monkeypatch.setattr(settings, "BLOCK_RESOLUTION_MIN_ITEMS", 3)
    s = _session_with_analisis(_pending_three())
    block = build_interaction_block(session_id="sess-abc", session_state=s, current_idx=0)
    assert block is not None
    assert len(block.items) == 3
    assert block.anchor.provenance in ("analisis_bases", "pending_only")
    assert block.block_id == stable_block_id_for_cluster("sess-abc", ["price_a", "price_b", "price_c"])


def test_select_economic_cluster_prefers_current_group(monkeypatch):
    monkeypatch.setattr(settings, "BLOCK_RESOLUTION_MIN_ITEMS", 2)
    pending = [
        {"field": "x1", "type": "economic_price", "block_group_key": "ga"},
        {"field": "x2", "type": "economic_price", "block_group_key": "ga"},
        {"field": "y1", "type": "economic_price", "block_group_key": "gb"},
        {"field": "y2", "type": "economic_price", "block_group_key": "gb"},
    ]
    cl = select_economic_cluster(pending, current_idx=2)
    assert cl is not None
    assert {q["field"] for q in cl} == {"y1", "y2"}


class _FakeMem:
    def __init__(self, session_state: dict, company: dict):
        self._session = dict(session_state)
        self._company = dict(company)

    async def get_session(self, session_id: str):
        return dict(self._session)

    async def save_session(self, session_id: str, data: dict) -> bool:
        self._session = dict(data)
        return True

    async def get_company(self, company_id: str):
        return dict(self._company)

    async def save_company(self, company_id: str, data: dict) -> bool:
        self._company = dict(data)
        return True


@pytest.mark.asyncio
async def test_mass_save_rejects_invalid_number(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BLOCK_RESOLUTION", True)
    mem = _FakeMem(
        _session_with_analisis(_pending_three()),
        {"catalog": []},
    )
    out = await mass_save_economic_block(
        mem,
        session_id="s1",
        company_id="c1",
        block_id="blk",
        correlation_id="corr",
        rows=[{"item_id": "price_a", "value": "no-es-numero"}],
    )
    assert out["success_count"] == 0
    assert len(out["failed_items"]) == 1
    assert out["removed_fields"] == []
    st = await mem.get_session("s1")
    assert len(st.get("pending_questions") or []) == 3


@pytest.mark.asyncio
async def test_mass_save_persists_and_trims_pending(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BLOCK_RESOLUTION", True)
    pending = _pending_three()
    mem = _FakeMem(
        {
            **_session_with_analisis(pending),
            "current_question_index": 1,
        },
        {"catalog": []},
    )
    out = await mass_save_economic_block(
        mem,
        session_id="s1",
        company_id="c1",
        block_id="x",
        correlation_id="c",
        rows=[
            {"item_id": "price_a", "value": "100"},
            {"item_id": "price_b", "value": "200"},
        ],
    )
    assert out["success_count"] == 2
    assert set(out["removed_fields"]) == {"price_a", "price_b"}
    st = await mem.get_session("s1")
    assert len(st.get("pending_questions") or []) == 1
    assert st["pending_questions"][0]["field"] == "price_c"
    assert st.get("current_question_index") == 0
    user_inputs = st.get("economic_user_inputs") or {}
    concept_prices = user_inputs.get("concept_prices") or {}
    assert concept_prices["price_a"] == 100.0
    assert concept_prices["price_b"] == 200.0
    assert concept_prices["A"] == 100.0
    assert concept_prices["B"] == 200.0
    overrides = st.get("economic_user_overrides") or []
    assert len(overrides) == 2
    assert overrides[0]["source"] == "chatbot_block"
    co = await mem.get_company("c1")
    cat = co.get("catalog") or []
    assert len(cat) == 2
    audit = st.get("interaction_block_audit") or []
    assert len(audit) == 1
    assert audit[0]["success_count"] == 2
