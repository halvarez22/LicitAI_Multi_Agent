"""Tests de resolución de empresa activa (precedencia UI > sesión)."""

from __future__ import annotations

import pytest

from app.services.chat_expediente_bootstrap_service import collect_expediente_bootstrap_facts
from app.services.company_context_resolver import (
    resolve_active_company_context,
    resolve_company_label_from_state,
)


def test_resolve_company_label_prefers_ui_profile():
    state = {
        "master_profile": {"razon_social": "MANAVIL SA DE CV"},
        "company_id": "legacy-id",
    }
    ui_profile = {"razon_social": "Comercializadora Mayo y Torres"}
    label = resolve_company_label_from_state(state, company_profile=ui_profile)
    assert label == "Comercializadora Mayo y Torres"


def test_collect_bootstrap_facts_company_override():
    state = {
        "name": "ISAPEG Limpieza",
        "master_profile": {"razon_social": "MANAVIL SA DE CV"},
    }
    facts = collect_expediente_bootstrap_facts(
        state,
        company_label_override="Comercializadora Mayo y Torres",
    )
    assert facts.company_label == "Comercializadora Mayo y Torres"


@pytest.mark.asyncio
async def test_resolve_active_company_context_from_memory():
    class _Mem:
        async def get_company(self, company_id: str):
            assert company_id == "mayo-torres-id"
            return {
                "id": company_id,
                "name": "Mayo y Torres",
                "master_profile": {
                    "razon_social": "Comercializadora Mayo y Torres",
                    "rfc": "CMT160107S83",
                },
            }

    state = {"master_profile": {"razon_social": "MANAVIL SA DE CV"}}
    ctx = await resolve_active_company_context(_Mem(), state, "mayo-torres-id")
    assert ctx["company_label"] == "Comercializadora Mayo y Torres"
