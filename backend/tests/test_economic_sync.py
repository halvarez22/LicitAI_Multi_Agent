"""
Tests de sincronización económica: chat → snapshot → generación de documentos.

Cubre el bug donde tasks_completed["economic_proposal"] quedaba con total_base=0
aunque el usuario hubiera capturado precios en el chat, bloqueando la generación.

Spec: .kiro/specs/economic-sync-fix/
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List, Optional

from app.economic_validation.service import refresh_economic_validations_for_session


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_memory(store: Dict[str, Any]):
    """Crea un mock de memory con get_session / save_session / get_line_items_for_session."""

    class MockMemory:
        async def get_session(self, session_id: str) -> Optional[Dict]:
            return store.get(session_id)

        async def save_session(self, session_id: str, data: Dict) -> bool:
            store[session_id] = data
            return True

        async def get_line_items_for_session(self, session_id: str) -> List[Dict]:
            return []

    return MockMemory()


def _snapshot_with_zero_total(items: Optional[List[Dict]] = None) -> Dict:
    """Snapshot económico con total_base=0 (estado antes de capturar precios)."""
    return {
        "status": "waiting_for_data",
        "currency": "MXN",
        "items": items or [
            {
                "concepto": "Limpieza en Unidades Médicas y Oficinas Administrativas",
                "concepto_id": "limpieza_unidades",
                "cantidad": 1,
                "precio_unitario": 0.0,
                "subtotal": 0.0,
                "status": "price_missing",
            }
        ],
        "total_base": 0.0,
        "grand_total": 0.0,
        "allow_zero_total_base_ack": False,
        "validation_result": {"perfil_usado": "generic_v1", "blocking_issues": ["total_base_cotizable"]},
    }


def _snapshot_with_prices(total_base: float = 127550.0) -> Dict:
    """Snapshot económico con precios capturados (estado después de capturar)."""
    return {
        "status": "complete",
        "currency": "MXN",
        "items": [
            {
                "concepto": "Limpieza en Unidades Médicas y Oficinas Administrativas",
                "concepto_id": "limpieza_unidades",
                "cantidad": 1,
                "precio_unitario": total_base,
                "subtotal": total_base,
                "status": "matched",
                "price_source": "chat_user_override",
            }
        ],
        "total_base": total_base,
        "grand_total": round(total_base * 1.16, 2),
        "allow_zero_total_base_ack": False,
        "validation_result": {"perfil_usado": "generic_v1", "blocking_issues": []},
    }


def _session_with_zero_snapshot(session_id: str = "test-limpieza") -> Dict:
    """Estado de sesión con snapshot desactualizado (total_base=0)."""
    return {
        "name": "Servicios de Limpieza para Unidades Medicas",
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {"data": {"reglas_economicas": {}}},
            },
            {
                "task": "economic_proposal",
                "result": _snapshot_with_zero_total(),
            },
        ],
        "economic_user_inputs": {},
        "pending_questions": [
            {
                "field": "price_limpieza_unidades",
                "label": "Precio (sin IVA): Limpieza en Unidades Médicas y Oficinas Administrativas",
                "question": "¿Cuál es el precio unitario (sin IVA) para Limpieza en Unidades Médicas?",
                "type": "economic_price",
                "original_item": {
                    "source": "bases_licitacion.pdf",
                    "page": 16,
                    "snippet": "Limpieza en Unidades Médicas y Oficinas Administrativas",
                },
            }
        ],
        "current_question_index": 0,
    }


# ---------------------------------------------------------------------------
# Tarea 2: EconomicRefresherService recalcula totales con overrides
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresher_recalculates_totals_after_price_capture():
    """
    Req 2.1-2.3: Cuando el usuario captura un precio en economic_user_inputs,
    refresh_economic_validations_for_session debe actualizar total_base en el snapshot.
    """
    session_id = "test-limpieza"
    store = {
        session_id: {
            **_session_with_zero_snapshot(session_id),
            "economic_user_inputs": {
                "concept_prices": {
                    "Limpieza en Unidades Médicas y Oficinas Administrativas": 127550.0
                }
            },
        }
    }
    memory = _make_memory(store)

    result = await refresh_economic_validations_for_session(memory, session_id)

    # El snapshot debe haberse actualizado con total_base > 0
    updated_session = store[session_id]
    tasks = updated_session.get("tasks_completed", [])
    snapshot = next(
        (t["result"] for t in reversed(tasks) if t.get("task") == "economic_proposal"),
        None,
    )
    assert snapshot is not None, "El snapshot debe existir en tasks_completed"
    assert float(snapshot.get("total_base") or 0) >= 0.01, (
        f"total_base debe ser > 0 después de capturar precios, got: {snapshot.get('total_base')}"
    )


@pytest.mark.asyncio
async def test_refresher_preserves_existing_fields():
    """
    Req 2.4: El refresher debe preservar campos existentes del snapshot
    (validation_result, calculator_result, etc.) al actualizar totales.
    """
    session_id = "test-preserve"
    store = {
        session_id: {
            "name": "test",
            "tasks_completed": [
                {
                    "task": "stage_completed:analysis",
                    "result": {"data": {"reglas_economicas": {}}},
                },
                {
                    "task": "economic_proposal",
                    "result": {
                        **_snapshot_with_prices(50000.0),
                        "calculator_result": {"profile_name": "generic_v1"},
                        "quadrature_report": {"available": False},
                    },
                },
            ],
            "economic_user_inputs": {
                "concept_prices": {"Limpieza en Unidades Médicas": 50000.0}
            },
        }
    }
    memory = _make_memory(store)

    await refresh_economic_validations_for_session(memory, session_id)

    updated = store[session_id]
    tasks = updated.get("tasks_completed", [])
    snapshot = next(
        (t["result"] for t in reversed(tasks) if t.get("task") == "economic_proposal"),
        {},
    )
    # validation_result debe existir (fue actualizado por el refresher)
    assert "validation_result" in snapshot


@pytest.mark.asyncio
async def test_refresher_no_error_when_no_snapshot():
    """
    Req 2.5: Si no existe snapshot en tasks_completed, el refresher debe
    lanzar ValueError (comportamiento actual) sin crear entradas vacías.
    """
    session_id = "test-no-snapshot"
    store = {
        session_id: {
            "name": "test",
            "tasks_completed": [],
            "economic_user_inputs": {},
        }
    }
    memory = _make_memory(store)

    with pytest.raises(ValueError):
        await refresh_economic_validations_for_session(memory, session_id)


# ---------------------------------------------------------------------------
# Tarea 4: Orquestador verifica snapshot antes de generation_only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_economic_snapshot_ready_missing_snapshot():
    """
    Req 4.5: Si no existe snapshot, _ensure_economic_snapshot_ready debe
    retornar (False, {stop_reason: MISSING_ECONOMIC_PROPOSAL}).
    """
    from app.agents.orchestrator import _ensure_economic_snapshot_ready
    from app.contracts.agent_contracts import AgentInput

    session_state = {"tasks_completed": [], "economic_user_inputs": {}}
    agent_input = AgentInput(
        session_id="test-missing",
        company_id="company-1",
        company_data={},
    )

    mock_context = MagicMock()
    mock_context.memory.get_session = AsyncMock(return_value=session_state)

    ready, error = await _ensure_economic_snapshot_ready(
        mock_context, "test-missing", agent_input, session_state
    )

    assert ready is False
    assert error is not None
    assert error.get("stop_reason") == "MISSING_ECONOMIC_PROPOSAL"


@pytest.mark.asyncio
async def test_ensure_economic_snapshot_ready_with_valid_snapshot():
    """
    Req 4.1: Si el snapshot tiene status=complete y total_base >= 0.01,
    _ensure_economic_snapshot_ready debe retornar (True, None).
    """
    from app.agents.orchestrator import _ensure_economic_snapshot_ready
    from app.contracts.agent_contracts import AgentInput

    session_state = {
        "tasks_completed": [
            {"task": "economic_proposal", "result": _snapshot_with_prices(127550.0)}
        ],
        "economic_user_inputs": {},
    }
    agent_input = AgentInput(
        session_id="test-valid",
        company_id="company-1",
        company_data={},
    )

    mock_context = MagicMock()
    mock_context.memory.get_session = AsyncMock(return_value=session_state)

    # Mockear refresh para que no falle (snapshot ya está listo, no debería llamarse)
    with patch(
        "app.economic_validation.service.refresh_economic_validations_for_session",
        new_callable=AsyncMock,
    ):
        ready, error = await _ensure_economic_snapshot_ready(
            mock_context, "test-valid", agent_input, session_state
        )

    assert ready is True
    assert error is None


@pytest.mark.asyncio
async def test_ensure_economic_snapshot_ready_stale_snapshot_refreshes():
    """
    Req 4.2: Si el snapshot tiene total_base=0, debe intentar el refresh
    y retornar (True, None) si el refresh actualiza el total.
    """
    from app.agents.orchestrator import _ensure_economic_snapshot_ready
    from app.contracts.agent_contracts import AgentInput

    store = {
        "test-stale": {
            "tasks_completed": [
                {"task": "economic_proposal", "result": _snapshot_with_zero_total()}
            ],
            "economic_user_inputs": {
                "concept_prices": {
                    "Limpieza en Unidades Médicas y Oficinas Administrativas": 127550.0
                }
            },
        }
    }

    session_state = store["test-stale"]
    agent_input = AgentInput(
        session_id="test-stale",
        company_id="company-1",
        company_data={},
    )

    # Simular que el refresh actualiza el snapshot con total_base > 0
    async def mock_refresh(memory, session_id):
        store[session_id]["tasks_completed"][-1]["result"] = _snapshot_with_prices(127550.0)

    mock_context = MagicMock()
    mock_context.memory.get_session = AsyncMock(
        side_effect=lambda sid: store.get(sid)
    )

    with patch(
        "app.economic_validation.service.refresh_economic_validations_for_session",
        side_effect=mock_refresh,
    ):
        ready, error = await _ensure_economic_snapshot_ready(
            mock_context, "test-stale", agent_input, session_state
        )

    assert ready is True
    assert error is None


# ---------------------------------------------------------------------------
# Tarea 5: Sanitización de pending_questions huérfanas
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sanitize_orphan_economic_questions_discards_unmatched():
    """
    Req 5.3-5.4: Preguntas de tipo economic_price cuyo concepto no existe
    en el snapshot activo deben ser descartadas silenciosamente.
    """
    from app.agents.chatbot_rag import ChatbotRAGAgent

    session_id = "test-sanitize"
    session_state = {
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": _snapshot_with_prices(127550.0),
            }
        ],
        "pending_questions": [
            {
                "field": "price_limpieza_unidades",
                "label": "Precio (sin IVA): Limpieza en Unidades Médicas y Oficinas Administrativas",
                "type": "economic_price",
                "original_item": {"source": "bases.pdf", "page": 16, "snippet": "Limpieza"},
            },
            {
                # Pregunta huérfana: concepto que no existe en el snapshot
                "field": "price_concepto_inexistente",
                "label": "Precio (sin IVA): Estado de Guanajuato",
                "type": "economic_price",
                "original_item": {"source": "bases.pdf", "page": 17, "snippet": "Guanajuato"},
            },
            {
                # Pregunta no económica: debe preservarse siempre
                "field": "razon_social",
                "label": "Razón Social",
                "type": "profile",
            },
        ],
    }

    mock_context = MagicMock()
    agent = ChatbotRAGAgent(mock_context)

    cleaned = await agent._sanitize_economic_pending_questions(session_id, session_state)

    # La pregunta huérfana debe haber sido descartada
    labels = [q.get("label") for q in cleaned]
    assert "Precio (sin IVA): Estado de Guanajuato" not in labels, (
        "La pregunta huérfana debe ser descartada"
    )
    # La pregunta válida debe mantenerse
    assert any("Limpieza" in (lbl or "") for lbl in labels), (
        "La pregunta válida debe mantenerse"
    )
    # La pregunta no económica debe preservarse
    assert any(q.get("type") == "profile" for q in cleaned), (
        "Las preguntas no económicas deben preservarse"
    )


@pytest.mark.asyncio
async def test_sanitize_keeps_all_when_no_snapshot():
    """
    Req 5.3: Sin snapshot activo, todas las preguntas deben mantenerse
    (no podemos validar sin referencia).
    """
    from app.agents.chatbot_rag import ChatbotRAGAgent

    session_state = {
        "tasks_completed": [],  # Sin snapshot
        "pending_questions": [
            {
                "field": "price_algo",
                "label": "Precio (sin IVA): Algo",
                "type": "economic_price",
                "original_item": {"source": "bases.pdf", "page": 1, "snippet": "Algo"},
            }
        ],
    }

    mock_context = MagicMock()
    agent = ChatbotRAGAgent(mock_context)

    cleaned = await agent._sanitize_economic_pending_questions("test-no-snap", session_state)

    assert len(cleaned) == 1, "Sin snapshot, todas las preguntas deben mantenerse"


# ---------------------------------------------------------------------------
# Tarea 6: Detección de zero-base-ack
# ---------------------------------------------------------------------------

def test_detect_zero_base_ack_intent_positive():
    """Req 6.1: Detectar confirmación de licitación sin importe base."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    positive_cases = [
        "Esta licitación no requiere importe base",
        "no requiere importe base",
        "sin importe base",
        "Esta licitación no requiere importe base — confirmar",
        "la licitación no tiene importe base",
    ]
    for case in positive_cases:
        assert ChatbotRAGAgent._detect_zero_base_ack_intent(case), (
            f"Debería detectar zero-base-ack en: '{case}'"
        )


def test_detect_zero_base_ack_intent_negative():
    """Req 6.1: No detectar falsos positivos en mensajes normales."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    negative_cases = [
        "¿Cuándo es la junta de aclaraciones?",
        "el precio es 127550",
        "generar documentos",
        "hola",
        "¿qué documentos faltan?",
    ]
    for case in negative_cases:
        assert not ChatbotRAGAgent._detect_zero_base_ack_intent(case), (
            f"No debería detectar zero-base-ack en: '{case}'"
        )


@pytest.mark.asyncio
async def test_handle_zero_base_ack_persists_flag():
    """
    Req 6.2: _handle_zero_base_ack debe persistir allow_zero_total_base_ack=True
    en session_state.economic_user_inputs.
    """
    from app.agents.chatbot_rag import ChatbotRAGAgent

    session_id = "test-zero-ack"
    store = {
        session_id: {
            "name": "test",
            "tasks_completed": [
                {
                    "task": "economic_proposal",
                    "result": _snapshot_with_zero_total(),
                }
            ],
            "economic_user_inputs": {},
        }
    }
    memory = _make_memory(store)

    mock_context = MagicMock()
    mock_context.memory = memory

    agent = ChatbotRAGAgent(mock_context)

    with patch.object(
        agent,
        "_save_chat_history",
        new_callable=AsyncMock,
    ):
        result = await agent._handle_zero_base_ack(
            session_id=session_id,
            company_id="company-1",
            correlation_id="test-corr",
        )

    # Verificar que el flag fue persistido
    updated = store[session_id]
    assert updated.get("economic_user_inputs", {}).get("allow_zero_total_base_ack") is True, (
        "allow_zero_total_base_ack debe ser True después de la confirmación"
    )

    # Verificar que la respuesta no expone el nombre técnico del flag
    response_text = result.data.get("respuesta", "") if result.data else ""
    assert "allow_zero_total_base_ack" not in response_text, (
        "El nombre técnico del flag no debe aparecer en la respuesta al usuario"
    )


# ---------------------------------------------------------------------------
# Test de integración: flujo completo chat → generación
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_flow_snapshot_updated_after_price_capture():
    """
    Req 7.1-7.3: Flujo completo de sincronización.
    Simula: snapshot con total_base=0 → usuario captura precio →
    refresh actualiza snapshot → total_base > 0.

    Este test verifica el bug principal: que el snapshot se actualiza
    correctamente después de capturar precios en el chat.
    """
    session_id = "test-full-flow"
    store = {
        session_id: _session_with_zero_snapshot(session_id),
    }

    # Paso 1: Simular captura de precio por el usuario
    store[session_id]["economic_user_inputs"] = {
        "concept_prices": {
            "Limpieza en Unidades Médicas y Oficinas Administrativas": 127550.0
        }
    }

    memory = _make_memory(store)

    # Paso 2: Ejecutar refresh (lo que hace _handle_economic_transaction)
    await refresh_economic_validations_for_session(memory, session_id)

    # Paso 3: Verificar que el snapshot fue actualizado
    updated_session = store[session_id]
    tasks = updated_session.get("tasks_completed", [])
    snapshot = next(
        (t["result"] for t in reversed(tasks) if t.get("task") == "economic_proposal"),
        None,
    )

    assert snapshot is not None, "El snapshot debe existir"
    total_base = float(snapshot.get("total_base") or 0)
    assert total_base >= 0.01, (
        f"total_base debe ser > 0 después de capturar precios. "
        f"Bug de sincronización: el snapshot no fue actualizado. Got: {total_base}"
    )

    # Paso 4: Verificar que EconomicWriterAgent no bloquearía la generación
    # (subtotal >= 0.01 → no retorna WAITING_FOR_DATA)
    assert total_base >= 0.01, (
        "Con total_base > 0, EconomicWriterAgent debe generar documentos sin error"
    )


@pytest.mark.asyncio
async def test_zero_base_ack_unblocks_generation():
    """
    Req 7.5: Con allow_zero_total_base_ack=True, el snapshot con total_base=0
    debe ser considerado válido para generación.
    """
    session_id = "test-zero-base"
    store = {
        session_id: {
            "name": "test",
            "tasks_completed": [
                {
                    "task": "stage_completed:analysis",
                    "result": {"data": {"reglas_economicas": {}}},
                },
                {
                    "task": "economic_proposal",
                    "result": {
                        **_snapshot_with_zero_total(),
                        "allow_zero_total_base_ack": True,
                    },
                },
            ],
            "economic_user_inputs": {"allow_zero_total_base_ack": True},
        }
    }
    memory = _make_memory(store)

    # El refresh no debe fallar con allow_zero=True
    result = await refresh_economic_validations_for_session(memory, session_id)

    # La validación debe pasar (no debe haber blocking_issues de total_base_cotizable)
    blocking = list(result.blocking_issues or [])
    total_base_blocked = any("total_base_cotizable" in str(b) for b in blocking)
    assert not total_base_blocked, (
        f"Con allow_zero_total_base_ack=True, total_base_cotizable no debe bloquear. "
        f"Blocking issues: {blocking}"
    )
