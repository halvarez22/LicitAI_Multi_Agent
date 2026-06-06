"""Endpoints ligeros P0-02: documentos corporativos y formatos sin dictamen monolítico."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SESSION_ID = "sess_p0_02"


def _memory_with_session() -> MagicMock:
    mem = MagicMock()
    mem.disconnect = AsyncMock(return_value=None)
    mem.get_session = AsyncMock(return_value={"name": "Demo", "compliance_master_list": {}})
    return mem


@pytest.mark.asyncio
async def test_document_candidates_summary_route():
    from app.api.v1.routes.sessions import get_document_candidates_summary

    mem = _memory_with_session()
    corp_payload = {
        "candidate_document_list": [{"nombre": "IMSS", "tipo": "presentar_fisico"}],
        "_meta": {"total": 1},
    }
    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ), patch(
        "app.services.document_candidate_list_service.build_corporate_physical_panel_list",
        new=AsyncMock(return_value=corp_payload),
    ):
        resp = await get_document_candidates_summary(SESSION_ID)

    assert resp.success is True
    assert resp.data["corporate_physical_document_candidates"]["_meta"]["total"] == 1


@pytest.mark.asyncio
async def test_pliego_formats_panel_route():
    from app.api.v1.routes.sessions import get_pliego_formats_panel

    mem = _memory_with_session()
    fmt_payload = {
        "sobre_1_tecnico": [{"nombre": "Anexo 1"}],
        "sobre_2_economico": [],
        "_meta": {"total": 1},
    }
    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ), patch(
        "app.services.document_candidate_list_service.build_formats_panel_consolidated",
        new=AsyncMock(return_value=fmt_payload),
    ):
        resp = await get_pliego_formats_panel(SESSION_ID)

    assert resp.success is True
    assert len(resp.data["pliego_formats_panel"]["sobre_1_tecnico"]) == 1


def test_document_candidates_summary_http_not_found():
    mem = _memory_with_session()
    mem.get_session = AsyncMock(return_value=None)
    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ):
        res = client.get(f"/api/v1/sessions/{SESSION_ID}/document-candidates-summary")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
