"""
Tests unitarios para _sync_pending_after_analysis (AutoResolveHook).

Cubre:
- Retornos tempranos (company_id ausente, sin pendientes, tipo no-profile, field vacío)
- Timeout de extracción RAG
- Error de persistencia en master_profile
- Avance de cola con lectura atómica fresca
- Log de auditoría en resolución exitosa
- Idempotencia del hook
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.routes.upload import _sync_pending_after_analysis


# ---------------------------------------------------------------------------
# Helpers y fixtures
# ---------------------------------------------------------------------------


def _make_pending(
    field: str = "rfc",
    label: str = "RFC",
    question: str = "¿Cuál es el RFC?",
    type_: str = "profile",
) -> dict:
    """Construye un objeto pending_question mínimo."""
    return {"field": field, "label": label, "question": question, "type": type_}


def _make_memory(
    session_state: dict | None = None,
    company: dict | None = None,
    save_company_raises: Exception | None = None,
    save_session_raises: Exception | None = None,
) -> MagicMock:
    """Construye un mock de MemoryRepository con los métodos async necesarios."""
    mem = MagicMock()
    mem.get_session = AsyncMock(return_value=dict(session_state or {}))
    mem.save_session = AsyncMock(side_effect=save_session_raises)
    mem.get_company = AsyncMock(return_value=dict(company or {"master_profile": {}}))
    mem.save_company = AsyncMock(side_effect=save_company_raises)
    # Flags para verificar ausencia de I/O en retornos tempranos
    mem.save_company_called = property(lambda self: self.save_company.called)
    mem.save_session_called = property(lambda self: self.save_session.called)
    return mem


# ---------------------------------------------------------------------------
# Retornos tempranos — sin I/O
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_company_id_none() -> None:
    """company_id=None → reason='missing_company_id', sin I/O."""
    mem = _make_memory(session_state={"pending_questions": [_make_pending()], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", None)
    assert result["resolved_current_pending"] is False
    assert result["reason"] == "missing_company_id"
    mem.get_session.assert_not_called()
    mem.save_company.assert_not_called()
    mem.save_session.assert_not_called()


@pytest.mark.asyncio
async def test_missing_company_id_empty_string() -> None:
    """company_id='' → reason='missing_company_id', sin I/O."""
    mem = _make_memory()
    result = await _sync_pending_after_analysis(mem, "s1", "")
    assert result["reason"] == "missing_company_id"
    mem.get_session.assert_not_called()


@pytest.mark.asyncio
async def test_missing_company_id_whitespace() -> None:
    """company_id='   ' → reason='missing_company_id', sin I/O."""
    mem = _make_memory()
    result = await _sync_pending_after_analysis(mem, "s1", "   ")
    assert result["reason"] == "missing_company_id"
    mem.get_session.assert_not_called()


@pytest.mark.asyncio
async def test_no_pending_returns_early() -> None:
    """pending_questions vacío → reason='no_pending_questions', sin invocar DataGapAgent."""
    mem = _make_memory(session_state={"pending_questions": [], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["resolved_current_pending"] is False
    assert result["reason"] == "no_pending_questions"
    mem.save_company.assert_not_called()
    mem.save_session.assert_not_called()


@pytest.mark.asyncio
async def test_no_pending_none_returns_early() -> None:
    """pending_questions=None → reason='no_pending_questions'."""
    mem = _make_memory(session_state={"pending_questions": None})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["reason"] == "no_pending_questions"


@pytest.mark.asyncio
async def test_non_profile_type_skipped() -> None:
    """type='economic_price' → reason='current_pending_not_profile', sin DataGapAgent."""
    pending = _make_pending(type_="economic_price")
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["reason"] == "current_pending_not_profile"
    assert result["next_pending_label"] == pending["label"]
    assert result["next_pending_question"] == pending["question"]
    mem.save_company.assert_not_called()


@pytest.mark.asyncio
async def test_arbitrary_non_profile_type_skipped() -> None:
    """Cualquier type distinto de 'profile' → reason='current_pending_not_profile'."""
    for t in ("economic_validation_blocking", "evidence_profile_conflict", "custom_type"):
        pending = _make_pending(type_=t)
        mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")
        assert result["reason"] == "current_pending_not_profile", f"Falló para type={t!r}"


@pytest.mark.asyncio
async def test_empty_field_key_skipped() -> None:
    """field='' → reason='missing_field_key', sin DataGapAgent."""
    pending = _make_pending(field="")
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["reason"] == "missing_field_key"
    mem.save_company.assert_not_called()


@pytest.mark.asyncio
async def test_none_field_key_skipped() -> None:
    """field=None → reason='missing_field_key'."""
    pending = {"field": None, "label": "Campo", "question": "?", "type": "profile"}
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["reason"] == "missing_field_key"


# ---------------------------------------------------------------------------
# Retornos tempranos rellenan next_pending_label/question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_early_returns_fill_next_pending_label() -> None:
    """En retornos tempranos (tipo no-profile), next_pending_label y next_pending_question
    se rellenan con el label/question del pendiente activo para que el endpoint
    pueda construir el mensaje del caso 3."""
    pending = _make_pending(field="rfc", label="RFC de la empresa", question="¿Cuál es el RFC?", type_="economic_price")
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})
    result = await _sync_pending_after_analysis(mem, "s1", "company-1")
    assert result["next_pending_label"] == "RFC de la empresa"
    assert result["next_pending_question"] == "¿Cuál es el RFC?"


# ---------------------------------------------------------------------------
# Timeout de extracción RAG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_gracefully() -> None:
    """DataGapAgent que tarda más de timeout_seconds → reason='timeout', sin persistir."""
    pending = _make_pending()
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})

    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(10)
        return "valor"

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = slow_extract
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(
            mem, "s1", "company-1", timeout_seconds=0.01
        )

    assert result["reason"] == "timeout"
    assert result["resolved_current_pending"] is False
    mem.save_company.assert_not_called()
    mem.save_session.assert_not_called()


# ---------------------------------------------------------------------------
# Valor inválido no persiste
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_value_not_persisted() -> None:
    """Valor que no pasa _is_data_valid → reason='value_not_found_or_invalid', sin I/O."""
    pending = _make_pending()
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="[placeholder]")
    mock_dga._is_data_valid = MagicMock(return_value=False)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["reason"] == "value_not_found_or_invalid"
    mem.save_company.assert_not_called()
    mem.save_session.assert_not_called()


@pytest.mark.asyncio
async def test_none_value_not_persisted() -> None:
    """DataGapAgent retorna None → reason='value_not_found_or_invalid'."""
    pending = _make_pending()
    mem = _make_memory(session_state={"pending_questions": [pending], "current_question_index": 0})

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value=None)
    mock_dga._is_data_valid = MagicMock(return_value=False)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["reason"] == "value_not_found_or_invalid"


# ---------------------------------------------------------------------------
# Error de persistencia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistence_error_no_session_advance() -> None:
    """save_company lanza excepción → reason='persistence_error', session_state sin cambios."""
    pending = _make_pending()
    mem = _make_memory(
        session_state={"pending_questions": [pending], "current_question_index": 0},
        save_company_raises=RuntimeError("DB error"),
    )

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="ABC123456XYZ")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["reason"] == "persistence_error"
    assert result["resolved_current_pending"] is False
    mem.save_session.assert_not_called()


# ---------------------------------------------------------------------------
# Resolución exitosa
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_resolution_single_pending() -> None:
    """Resolución exitosa con un solo pendiente → pending_questions vacío, new_idx=0."""
    pending = _make_pending(field="rfc", label="RFC")
    mem = _make_memory(
        session_state={"pending_questions": [pending], "current_question_index": 0},
        company={"master_profile": {"razon_social": "Empresa SA"}},
    )

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="ABC123456XYZ")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["resolved_current_pending"] is True
    assert result["resolved_field"] == "rfc"
    assert result["resolved_value"] == "ABC123456XYZ"
    assert result["next_pending_label"] == ""
    assert result["next_pending_question"] == ""
    assert result["reason"] == "resolved_and_advanced"

    saved_company = mem.save_company.call_args[0][1]
    assert saved_company["master_profile"]["rfc"] == "ABC123456XYZ"
    assert saved_company["master_profile"]["razon_social"] == "Empresa SA"

    saved_session = mem.save_session.call_args[0][1]
    assert saved_session["pending_questions"] == []
    assert saved_session["current_question_index"] == 0


@pytest.mark.asyncio
async def test_successful_resolution_multiple_pending() -> None:
    """Resolución exitosa con múltiples pendientes → avanza al siguiente."""
    pending_list = [
        _make_pending(field="rfc", label="RFC"),
        _make_pending(field="telefono", label="Teléfono", question="¿Cuál es el teléfono?"),
        _make_pending(field="email", label="Email", question="¿Cuál es el email?"),
    ]
    mem = _make_memory(
        session_state={"pending_questions": pending_list, "current_question_index": 0},
        company={"master_profile": {}},
    )

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="ABC123456XYZ")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["resolved_current_pending"] is True
    assert result["next_pending_label"] == "Teléfono"
    assert result["next_pending_question"] == "¿Cuál es el teléfono?"

    saved_session = mem.save_session.call_args[0][1]
    assert len(saved_session["pending_questions"]) == 2
    assert saved_session["pending_questions"][0]["field"] == "telefono"


@pytest.mark.asyncio
async def test_queue_advance_removes_resolved_item() -> None:
    """Tras resolución, pending_questions tiene N-1 elementos."""
    n = 5
    pending_list = [_make_pending(field=f"campo_{i}", label=f"Campo {i}") for i in range(n)]
    mem = _make_memory(
        session_state={"pending_questions": pending_list, "current_question_index": 2},
        company={"master_profile": {}},
    )

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="valor_valido")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result = await _sync_pending_after_analysis(mem, "s1", "company-1")

    assert result["resolved_current_pending"] is True
    saved_session = mem.save_session.call_args[0][1]
    assert len(saved_session["pending_questions"]) == n - 1
    remaining_fields = [q["field"] for q in saved_session["pending_questions"]]
    assert "campo_2" not in remaining_fields


@pytest.mark.asyncio
async def test_audit_log_on_success(capsys) -> None:
    """Log contiene '[AutoResolve] ✅' con field_key y session_id en resolución exitosa."""
    pending = _make_pending(field="rfc", label="RFC")
    mem = _make_memory(
        session_state={"pending_questions": [pending], "current_question_index": 0},
        company={"master_profile": {}},
    )

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="ABC123456XYZ")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        await _sync_pending_after_analysis(mem, "sesion-test-123", "company-1")

    # El logger usa structlog que escribe a stdout
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "AutoResolve" in output
    assert "rfc" in output
    assert "sesion-test-123" in output


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_idempotent() -> None:
    """Segunda ejecución sobre el mismo estado → reason='no_pending_questions',
    master_profile conserva el valor de la primera ejecución."""
    pending = _make_pending(field="rfc", label="RFC")
    session_state = {"pending_questions": [pending], "current_question_index": 0}
    company_data = {"master_profile": {}}

    class MutableMemory:
        def __init__(self):
            self._session = dict(session_state)
            self._company = dict(company_data)
            self.save_company_count = 0

        async def get_session(self, sid):
            return dict(self._session)

        async def save_session(self, sid, state):
            self._session = dict(state)

        async def get_company(self, cid):
            return dict(self._company)

        async def save_company(self, cid, company):
            self._company = dict(company)
            self.save_company_count += 1

    mem = MutableMemory()

    mock_dga = MagicMock()
    mock_dga.try_extract_field_from_sources = AsyncMock(return_value="ABC123456XYZ")
    mock_dga._is_data_valid = MagicMock(return_value=True)

    with patch("app.agents.data_gap.DataGapAgent", return_value=mock_dga), \
         patch("app.agents.mcp_context.MCPContextManager", return_value=MagicMock()):
        result1 = await _sync_pending_after_analysis(mem, "s1", "company-1")
        assert result1["resolved_current_pending"] is True
        assert mem._company["master_profile"]["rfc"] == "ABC123456XYZ"

        result2 = await _sync_pending_after_analysis(mem, "s1", "company-1")
        assert result2["resolved_current_pending"] is False
        assert result2["reason"] == "no_pending_questions"
        assert mem._company["master_profile"]["rfc"] == "ABC123456XYZ"
        assert mem.save_company_count == 1
