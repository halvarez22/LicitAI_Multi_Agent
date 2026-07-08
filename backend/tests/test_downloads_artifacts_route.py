"""Tests de ruta GET /downloads/artifacts (F5.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _write(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


@pytest.mark.asyncio
async def test_artifacts_route_returns_technical_files(tmp_path: Path) -> None:
    root = tmp_path / "vigilancia_issste"
    _write(root / "1.propuesta tecnica" / "propuesta.docx", b"tech")

    async def _fake_resolve(session_id: str):
        return str(root) if session_id == "vigilancia_issste" else None

    with patch(
        "app.api.v1.routes.downloads.resolve_outputs_root",
        new=AsyncMock(side_effect=_fake_resolve),
    ), patch(
        "app.api.v1.routes.downloads._load_session_state",
        new=AsyncMock(return_value={"generation_state": {"jobs": [{"id": "technical", "status": "done"}]}}),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get(
                "/api/v1/downloads/artifacts",
                params={"session_id": "vigilancia_issste", "scope": "technical"},
            )

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["scope"] == "technical"
    assert data["ready"] is True
    assert data["artifact_count"] == 1
    assert data["artifacts"][0]["filename"] == "propuesta.docx"


@pytest.mark.asyncio
async def test_artifacts_route_empty_session(tmp_path: Path) -> None:
    with patch(
        "app.api.v1.routes.downloads.resolve_outputs_root",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.api.v1.routes.downloads._load_session_state",
        new=AsyncMock(return_value={}),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get(
                "/api/v1/downloads/artifacts",
                params={"session_id": "missing_sess", "scope": "technical"},
            )

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["ready"] is False
    assert data["artifact_count"] == 0
    assert data["empty_reason"] is not None
