"""
test_go_no_go_endpoint.py — Pruebas de integración del endpoint Go/No-Go.

Verifica:
- POST con user_override=True → job encolado (HTTP 200, success=True)
- stop_reason distinto de GO_NO_GO_PENDING → respuesta con success=False
- session_id inválido → respuesta con success=False (sesión no encontrada)

Requisitos: 3.3, 3.4, 3.5
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers para construir mocks de memoria
# ---------------------------------------------------------------------------

def _make_memory_mock(
    session_state: dict = None,
    session_exists: bool = True,
) -> MagicMock:
    """Construye un mock de MemoryRepository para los tests del endpoint."""
    memory = MagicMock()
    memory.disconnect = AsyncMock(return_value=None)

    if not session_exists:
        memory.get_session = AsyncMock(return_value=None)
    else:
        memory.get_session = AsyncMock(return_value=session_state or {})

    memory.save_session = AsyncMock(return_value=True)
    return memory


def _make_session_go_no_go_pending() -> dict:
    """Estado de sesión con stop_reason=GO_NO_GO_PENDING."""
    return {
        "last_orchestrator_decision": {"stop_reason": "GO_NO_GO_PENDING"},
        "go_no_go_result": {
            "semaforo": "RED",
            "brechas": [{"id": "b1", "is_knockout": True, "descripcion": "Falta ISO 9001"}],
            "total_knockouts": 1,
            "total_brechas": 1,
            "requires_user_decision": True,
            "schema_version": 1,
        },
    }


# ---------------------------------------------------------------------------
# Tests usando la lógica del endpoint directamente (sin servidor HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authorize_endpoint_ok():
    """Req 3.5: POST con user_override=True → job encolado, success=True."""
    from app.api.v1.routes.go_no_go import authorize_go_no_go, AuthorizeRequest

    memory = _make_memory_mock(session_state=_make_session_go_no_go_pending())
    body = AuthorizeRequest(
        user_override=True,
        brechas_autorizadas=["b1"],
        company_id="comp_1",
        company_data={"master_profile": {}},
    )

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_bg = MagicMock()
    mock_bg.add_task = MagicMock()

    with patch("app.api.v1.routes.go_no_go.get_connected_memory", new=AsyncMock(return_value=memory)), \
         patch("app.api.v1.routes.go_no_go.update_job_status"), \
         patch("app.api.v1.routes.agents._run_orchestrator_job", new=AsyncMock(), create=True):
        resp = await authorize_go_no_go(
            session_id="sess_ok",
            body=body,
            request=mock_request,
            background_tasks=mock_bg,
        )

    assert resp.success is True
    assert "job_id" in resp.data
    assert resp.data.get("session_id") == "sess_ok"
    # Verificar que se encoló la tarea de reanudación
    mock_bg.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_authorize_endpoint_estado_incorrecto():
    """Req 3.4: stop_reason distinto de GO_NO_GO_PENDING → success=False con mensaje de estado."""
    from app.api.v1.routes.go_no_go import authorize_go_no_go, AuthorizeRequest

    session_state = {
        "last_orchestrator_decision": {"stop_reason": "WAITING_FOR_DATA"},
        "go_no_go_result": None,
    }
    memory = _make_memory_mock(session_state=session_state)
    body = AuthorizeRequest(
        user_override=True,
        brechas_autorizadas=[],
        company_id="comp_1",
        company_data={},
    )

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("app.api.v1.routes.go_no_go.get_connected_memory", new=AsyncMock(return_value=memory)):
        resp = await authorize_go_no_go(
            session_id="sess_wrong_state",
            body=body,
            request=mock_request,
            background_tasks=MagicMock(),
        )

    assert resp.success is False
    assert "GO_NO_GO_PENDING" in resp.message or "estado" in resp.message.lower()


@pytest.mark.asyncio
async def test_authorize_endpoint_sesion_no_existe():
    """Req 3.3: session_id inválido → success=False con mensaje de sesión no encontrada."""
    from app.api.v1.routes.go_no_go import authorize_go_no_go, AuthorizeRequest

    memory = _make_memory_mock(session_exists=False)
    body = AuthorizeRequest(
        user_override=True,
        brechas_autorizadas=[],
        company_id="comp_1",
        company_data={},
    )

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("app.api.v1.routes.go_no_go.get_connected_memory", new=AsyncMock(return_value=memory)):
        resp = await authorize_go_no_go(
            session_id="sess_inexistente",
            body=body,
            request=mock_request,
            background_tasks=MagicMock(),
        )

    assert resp.success is False
    assert "sesión" in resp.message.lower() or "session" in resp.message.lower()


@pytest.mark.asyncio
async def test_authorize_endpoint_user_override_false_detiene():
    """Req 3.3: user_override=False → pipeline detenido, success=True, sin job encolado."""
    from app.api.v1.routes.go_no_go import authorize_go_no_go, AuthorizeRequest

    memory = _make_memory_mock(session_state=_make_session_go_no_go_pending())
    body = AuthorizeRequest(
        user_override=False,
        brechas_autorizadas=[],
        company_id="comp_1",
        company_data={},
    )

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_bg = MagicMock()
    mock_bg.add_task = MagicMock()

    with patch("app.api.v1.routes.go_no_go.get_connected_memory", new=AsyncMock(return_value=memory)):
        resp = await authorize_go_no_go(
            session_id="sess_stop",
            body=body,
            request=mock_request,
            background_tasks=mock_bg,
        )

    assert resp.success is True
    assert "detenido" in resp.message.lower() or "pipeline" in resp.message.lower()
    # No debe haber encolado ninguna tarea
    mock_bg.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_authorize_endpoint_sin_go_no_go_result():
    """Req 3.4: stop_reason=GO_NO_GO_PENDING pero sin go_no_go_result → success=False."""
    from app.api.v1.routes.go_no_go import authorize_go_no_go, AuthorizeRequest

    session_state = {
        "last_orchestrator_decision": {"stop_reason": "GO_NO_GO_PENDING"},
        "go_no_go_result": None,  # Sin resultado
    }
    memory = _make_memory_mock(session_state=session_state)
    body = AuthorizeRequest(
        user_override=True,
        brechas_autorizadas=[],
        company_id="comp_1",
        company_data={},
    )

    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("app.api.v1.routes.go_no_go.get_connected_memory", new=AsyncMock(return_value=memory)):
        resp = await authorize_go_no_go(
            session_id="sess_no_result",
            body=body,
            request=mock_request,
            background_tasks=MagicMock(),
        )

    assert resp.success is False
    assert "go/no-go" in resp.message.lower() or "resultado" in resp.message.lower()
