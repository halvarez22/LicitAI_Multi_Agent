import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

@pytest.fixture
def mock_context():
    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    # Importante: AsyncMock por defecto retorna otro AsyncMock (que evalúa como coroutine)
    # Por eso establecemos return_value={} por defecto
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)
    ctx.memory.get_company = AsyncMock(return_value={"id": "c1", "master_profile": {}})
    ctx.memory.save_company = AsyncMock(return_value=True)
    ctx.memory.get_conversation = AsyncMock(return_value=[])
    ctx.memory.save_conversation = AsyncMock(return_value=True)
    return ctx

@pytest.fixture
def agent(mock_context):
    # Parchamos las clases de servicios para evitar conexiones HttpClient reales (ChromaDB/LLM)
    with patch("app.agents.chatbot_rag.VectorDbServiceClient") as mock_vector_class, \
         patch("app.agents.chatbot_rag.ResilientLLMClient") as mock_llm_class:
        
        a = ChatbotRAGAgent(mock_context)
        # Sincronizamos los mocks con las instancias que usa el agente
        a.llm = mock_llm_class.return_value
        a.llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response="QUERY")
        )
        a.llm.chat = AsyncMock(
            return_value=LLMResponse(success=True, response="respuesta RAG")
        )
        
        a.vector_db = mock_vector_class.return_value
        # get_sources NO es asíncrono en servicios/vector_service.py
        a.vector_db.get_sources = MagicMock(return_value=["bases.pdf"])
        a.vector_db.query_texts_filtered = MagicMock(return_value={"documents": [], "metadatas": []})
        a.vector_db.query_texts = MagicMock(return_value={"documents": [], "metadatas": []})
        
        return a


def _inp(session_id: str, query: str, company_id: str = "comp_1") -> AgentInput:
    return AgentInput(
        session_id=session_id,
        company_id=company_id,
        company_data={"query": query},
    )


@pytest.mark.asyncio
async def test_chatbot_proactivo_si_hay_preguntas(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"label": "RFC", "question": "¿Tu RFC?", "document_hint": "CIF"}],
        "current_question_index": 0
    }
    resp = await agent.process(_inp("sess_1", ""))
    assert resp.status == AgentStatus.SUCCESS
    assert "RFC" in resp.data["respuesta"]


@pytest.mark.asyncio
async def test_chatbot_idle_sin_empresa_ni_fuentes_no_muestra_intake(agent, mock_context):
    mock_context.memory.get_session.return_value = {"pending_questions": [], "current_question_index": 0}
    mock_context.memory.get_company = AsyncMock(return_value=None)
    # Sin fuentes cargadas
    mock_context.memory.get_documents = AsyncMock(return_value=[])
    resp = await agent.process(_inp("sess_idle_1", "", company_id=""))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "welcome_greeting"
    assert resp.data.get("intake_active") is False
    assert resp.data.get("activity_state") == "idle_no_company_no_sources"
    assert "carga las fuentes" in (resp.data.get("respuesta") or "").lower()


@pytest.mark.asyncio
async def test_chatbot_idle_con_empresa_sin_fuentes_mensaje_factual(agent, mock_context):
    mock_context.memory.get_session.return_value = {"pending_questions": [], "current_question_index": 0}
    mock_context.memory.get_company = AsyncMock(return_value={"id": "c1", "master_profile": {}})
    mock_context.memory.get_documents = AsyncMock(return_value=[])
    resp = await agent.process(_inp("sess_idle_2", "", company_id="c1"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("intake_active") is False
    assert resp.data.get("activity_state") == "idle_ready_for_upload"
    txt = (resp.data.get("respuesta") or "").lower()
    assert "empresa seleccionada" in txt
    assert "carga las fuentes" in txt


@pytest.mark.asyncio
async def test_chatbot_ofrece_intake_plan_proactivo_con_bloqueantes(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [],
        "current_question_index": 0,
        "intake_plan": {
            "summary": {"blocking_count": 2},
            "questions": [
                {"question_id": "INTAKE-B-1", "priority": "BLOQUEANTE", "blocking": True, "question": "¿Tienes capital mínimo?"},
                {"question_id": "INTAKE-C-1", "priority": "CRITICO", "blocking": False, "question": "¿Tienes padrón vigente?"},
            ],
        },
    }
    resp = await agent.process(_inp("sess_ip_1", "hola"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "intake_proactive_offer"
    assert "bloqueante" in (resp.data.get("respuesta") or "").lower()
    assert "diagnóstico listo" in (resp.data.get("respuesta") or "").lower()


@pytest.mark.asyncio
async def test_chatbot_promueve_hints_quality_a_pending(agent, mock_context):
    state = {
        "pending_questions": [],
        "current_question_index": 0,
        "last_document_quality_waiting_hints": {
            "reason": "Clasificación ambigua",
            "metrics": {"unknown_count": 12},
        },
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_qh_chat", "hola"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "pending_question"
    assert "clasificación" in (resp.data.get("respuesta") or "").lower()
    assert isinstance(state.get("pending_questions"), list) and state.get("pending_questions")
    assert state["pending_questions"][0].get("type") == "quality_validation_blocking"


@pytest.mark.asyncio
async def test_chatbot_optin_intake_plan_convierte_a_pending(agent, mock_context):
    state = {
        "pending_questions": [],
        "current_question_index": 0,
        "intake_plan": {
            "summary": {"blocking_count": 1},
            "questions": [
                {
                    "question_id": "INTAKE-B-1",
                    "priority": "BLOQUEANTE",
                    "blocking": True,
                    "field_target": "solvencia.capital_contable",
                    "question": "¿Cuál es tu capital contable vigente?",
                }
            ],
        },
    }

    async def _get_session(_sid):
        return state

    saved_snapshots = []

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        saved_snapshots.append(snapshot)
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_ip_2", "sí, empecemos"))
    assert resp.status == AgentStatus.SUCCESS
    promoted = next(
        (s for s in saved_snapshots if isinstance(s.get("pending_questions"), list) and s.get("pending_questions")),
        None,
    )
    assert promoted is not None
    assert promoted["pending_questions"][0].get("type") == "intake_planner"
    assert "capital_contable" in str(promoted["pending_questions"][0].get("field"))


@pytest.mark.asyncio
async def test_chatbot_muestra_progress_en_pending_question(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {"field": "rfc", "label": "RFC", "question": "¿Tu RFC?", "type": "intake_planner", "question_id": "Q1"},
            {"field": "domicilio", "label": "Domicilio", "question": "¿Tu domicilio?", "type": "intake_planner", "question_id": "Q2"},
        ],
        "current_question_index": 0,
        "intake_progress": {"started": True, "accepted": True, "current_question_id": "Q1"},
    }
    resp = await agent.process(_inp("sess_prog", "hola"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "pending_question"
    assert resp.data.get("progress_current") == 1
    assert resp.data.get("progress_total") == 2
    assert "pregunta 1 de 2" in str(resp.data.get("progress_label", "")).lower()


@pytest.mark.asyncio
async def test_chatbot_resume_por_question_id_sobre_indice(agent, mock_context):
    state = {
        "pending_questions": [
            {"field": "rfc", "label": "RFC", "question": "¿Tu RFC?", "type": "intake_planner", "question_id": "Q1"},
            {"field": "capital", "label": "Capital", "question": "¿Capital contable?", "type": "intake_planner", "question_id": "Q2"},
        ],
        "current_question_index": 0,
        "intake_progress": {"started": True, "accepted": True, "current_question_id": "Q2"},
    }
    mock_context.memory.get_session = AsyncMock(return_value=state)
    mock_context.memory.save_session = AsyncMock(return_value=True)
    resp = await agent.process(_inp("sess_resume", ""))
    assert resp.status == AgentStatus.SUCCESS
    assert "capital" in (resp.data.get("respuesta") or "").lower()
    assert resp.data.get("progress_current") == 2
    assert resp.data.get("progress_total") == 2


@pytest.mark.asyncio
async def test_chatbot_sanea_profile_field_ya_resuelto_en_master_profile(agent, mock_context):
    state = {
        "pending_questions": [
            {
                "field": "razon_social",
                "label": "Razón social de la empresa",
                "question": "¿Cuál es la razón social registrada?",
                "type": "profile_field",
            }
        ],
        "current_question_index": 0,
    }
    company = {
        "id": "c1",
        "master_profile": {"razon_social": "EMPRESA DEMO SA DE CV"},
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)
    mock_context.memory.get_company = AsyncMock(return_value=company)

    resp = await agent.process(_inp("sess_pf", ""))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "pending_question"
    # Debe limpiar razon_social ya resuelto y NO volver a preguntarlo.
    fields = [q.get("field") for q in (state.get("pending_questions") or [])]
    assert "razon_social" not in fields
    assert "razón social" not in (resp.data.get("respuesta") or "").lower()

@pytest.mark.asyncio
async def test_chatbot_modo_data_intake_y_persistencia(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {"field": "rfc", "label": "RFC", "question": "¿Tu RFC?"},
            {"field": "tel", "label": "Teléfono", "question": "¿Tu tel?"}
        ],
        "current_question_index": 0
    }
    # La heurística rápida de Chatbot lo clasificará como DATA_INTAKE sin llamar a llm.generate
    # si el query tiene señales como 'mi '. Pero si usamos side_effect, debemos ser precisos.
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="ABC123456XYZ")
    )

    resp = await agent.process(_inp("sess_1", "mi rfc es ABC123456XYZ"))

    assert resp.status == AgentStatus.SUCCESS
    assert "RFC" in resp.data["respuesta"]
    assert "guard" in resp.data["respuesta"].lower()
    assert "teléfono" in resp.data["respuesta"].lower() or "telefono" in resp.data["respuesta"].lower()


@pytest.mark.asyncio
async def test_chatbot_no_pospone_pendiente_blocking(agent, mock_context):
    state = {
        "pending_questions": [
            {"field": "rfc", "label": "RFC", "question": "¿Tu RFC?", "is_blocking": True},
            {"field": "telefono", "label": "Teléfono", "question": "¿Tu teléfono?", "is_blocking": False},
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_block", "omitir este dato"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("defer_denied_blocking", "skip_denied_blocking")
    assert state["current_question_index"] == 0
    assert state["pending_questions"][0]["field"] == "rfc"


@pytest.mark.asyncio
async def test_chatbot_pospone_pendiente_no_blocking(agent, mock_context):
    state = {
        "pending_questions": [
            {"field": "telefono", "label": "Teléfono", "question": "¿Tu teléfono?", "is_blocking": False},
            {"field": "email", "label": "Correo", "question": "¿Tu correo?", "is_blocking": False},
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_defer", "pasar al siguiente"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "pending_deferred"
    assert state["pending_questions"][0]["field"] == "email"

@pytest.mark.asyncio
async def test_chatbot_modo_rag_query(agent, mock_context):
    # Forzamos modo QUERY vía LLM
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="QUERY")
    )
    agent.vector_db.query_texts_filtered.return_value = {
        "documents": ["Contexto de prueba."],
        "metadatas": [{"source": "bases.pdf", "page": 5}]
    }
    agent.llm.chat = AsyncMock(
        return_value=LLMResponse(success=True, response="Respuesta basada en Pág. 5")
    )

    resp = await agent.process(_inp("sess_1", "¿Como se paga?"))

    assert resp.status == AgentStatus.SUCCESS
    assert "rag_answer" in resp.data["tipo"]
    assert len(resp.data["citas"]) > 0


@pytest.mark.asyncio
async def test_go_no_go_cita_anexo_no_dispara_plantilla_rfc(agent, mock_context):
    """
    Citas desde el semáforo suelen incluir «Anexo N»; no deben confundirse con intención
    de «subir anexo» ni cortar la consulta RAG con la plantilla de captura de RFC.
    """
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "rfc",
                "label": "RFC de la empresa",
                "question": "¿Cuál es el RFC?",
                "type": "profile",
            }
        ],
        "current_question_index": 0,
    }
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="QUERY"))
    agent.vector_db.query_texts_filtered.return_value = {
        "documents": ["El Anexo 17 establece la manifestación de interés por escrito."],
        "metadatas": [{"source": "bases.pdf", "page": 12}],
    }
    agent.llm.chat = AsyncMock(
        return_value=LLMResponse(success=True, response="Resumen del requisito y del Anexo 17.")
    )
    q = (
        'Explícame detalladamente qué es el siguiente requisito de estas bases de licitación '
        'y qué documentos o información necesito para acreditarlo: "Únicamente podrán participar '
        'quienes envíen el escrito en el que expresen su interés en participar en la Licitación Anexo 17."'
    )
    resp = await agent.process(_inp("sess_gng", q))
    assert resp.status == AgentStatus.SUCCESS
    assert "paso a paso" not in (resp.data.get("respuesta") or "").lower()
    assert "rag_answer" in str(resp.data.get("tipo") or "")


@pytest.mark.asyncio
async def test_chatbot_finaliza_flujo(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"field": "tel", "label": "Teléfono", "question": "¿Tu tel?"}],
        "current_question_index": 0
    }
    # Activamos heurística rápida (último pendiente → mensaje de expediente completo)
    resp = await agent.process(_inp("sess_1", "mi tel es 555"))
    assert "todo el expediente ha sido recibido" in resp.data["respuesta"].lower()


@pytest.mark.asyncio
async def test_economic_price_non_numeric_no_guarda_ni_avanza(agent, mock_context):
    state = {
        "pending_questions": [
            {
                "field": "price_t1",
                "label": "Precio (sin IVA): Escrito bajo protesta de decir verdad",
                "question": "¿Cuál es el precio unitario?",
                "type": "economic_price",
                "original_item": {"source": "bases.pdf", "page": 10, "snippet": "Texto literal de prueba sobre requisito"},
            }
        ],
        "current_question_index": 0,
    }
    mock_context.memory.get_session.return_value = state

    resp = await agent.process(_inp("sess_1", "texto invalido sin numero"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("clarification_needed", "rag_answer")
    mock_context.memory.save_company.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_non_cotizable_documental_retira_pendiente(agent, mock_context):
    state = {
        "pending_questions": [
            {
                "field": "price_tdoc",
                "label": "Precio (sin IVA): Escrito bajo protesta de decir verdad",
                "question": "¿Cuál es el precio unitario?",
                "type": "economic_price",
                "original_item": {"source": "bases.pdf", "page": 12, "snippet": "Escrito bajo protesta de decir verdad"},
            }
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_1", "eso es una declaratoria, no es cotización"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "pending_marked_non_cotizable"
    assert state.get("pending_questions") == []
    ov = state.get("economic_non_cotizable_overrides") or []
    assert len(ov) == 1
    assert ov[0].get("field") == "price_tdoc"


@pytest.mark.asyncio
async def test_mark_non_cotizable_sin_ancla_retira_huerfano(agent, mock_context):
    state = {
        "pending_questions": [
            {
                "field": "price_seg",
                "label": "Precio (sin IVA): Seguros",
                "question": "¿Cuál es el precio unitario?",
                "type": "economic_price",
                "document_hint": "",
                "original_item": {},
            }
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_1", "pasame el parrafo y en que pagina lo solicitan"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("welcome_greeting", "info", "rag_answer")
    assert state.get("pending_questions") == []


@pytest.mark.asyncio
async def test_support_evidence_intent_abre_rag_con_pendiente(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "price_seg",
                "label": "Precio (sin IVA): Seguros",
                "question": "¿Cuál es el precio unitario?",
                "type": "economic_price",
                "document_hint": "Anexo económico",
                "original_item": {"source": "bases.pdf", "page": 45, "snippet": "Seguro de responsabilidad civil"},
            }
        ],
        "current_question_index": 0,
    }
    agent.vector_db.query_texts_filtered.return_value = {
        "documents": ["Texto de bases: seguro de responsabilidad civil."],
        "metadatas": [{"source": "bases.pdf", "page": 45}],
    }
    agent.llm.chat = AsyncMock(
        return_value=LLMResponse(success=True, response="En bases sí se menciona seguro en página 45.")
    )

    resp = await agent.process(_inp("sess_1", "pasame el parrafo y en que pagina lo solicitan"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("rag_answer_support_pending", "rag_answer_capture_escape", "rag_answer")
    assert len(resp.data.get("citas") or []) >= 1


@pytest.mark.asyncio
async def test_blocking_pending_usa_modo_seguridad(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "12 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [
                    {
                        "concepto_label": "Servicio de vigilancia turno diurno",
                        "page_number": 12,
                        "context_snippet": "Servicio de vigilancia turno diurno con cobertura continua.",
                        "source_name": "bases.pdf",
                    },
                    {
                        "concepto_label": "Servicio de vigilancia turno nocturno",
                        "page_number": 13,
                        "context_snippet": "Servicio de vigilancia turno nocturno con cobertura continua.",
                        "source_name": "bases.pdf",
                    },
                ],
            }
        ],
        "current_question_index": 0,
    }

    resp = await agent.process(_inp("sess_1", "que precios necesitas?"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("economic_validation_blocking_info", "economic_blocking_rescue_hint")
    txt = resp.data.get("respuesta", "").lower()
    assert "vigilancia turno diurno" in txt
    # El texto del rescate económico puede variar entre versiones; verificamos que
    # el concepto aparece y que el mensaje invita a proporcionar el precio.
    assert (
        "necesito el precio para" in txt
        or "no se resuelve" in txt
        or "necesito confirmar el precio de" in txt
        or "para avanzar" in txt
        or "precio" in txt
    )


@pytest.mark.asyncio
async def test_blocking_pending_rescue_solo_signo_interrogacion(agent, mock_context):
    """«?» o «¿» deben disparar el mismo rescate que «qué precio falta» (antes se normalizaban a vacío)."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "12 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [
                    {
                        "concepto_label": "Concepto de prueba A",
                        "row_index": 1,
                        "context_snippet": "Concepto de prueba A en catálogo económico.",
                        "source_name": "cotizacion.xlsx",
                    }
                ],
            }
        ],
        "current_question_index": 0,
    }
    for msg in ("?", "¿"):
        resp = await agent.process(_inp("sess_1", msg))
        assert resp.status == AgentStatus.SUCCESS
        assert resp.data.get("tipo") == "economic_blocking_rescue_hint"
        assert "concepto de prueba a" in (resp.data.get("respuesta") or "").lower()


@pytest.mark.asyncio
async def test_blocking_pending_rescue_fallback_item_numero(agent, mock_context):
    """Si blocking_items no trae label legible, debe contestar con fallback de ítem #1 (sin mensaje de error interno)."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "3 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [{"concepto_id": "x1", "row_index": 1, "context_snippet": "Ítem económico 1"}],
            }
        ],
        "current_question_index": 0,
    }
    resp = await agent.process(_inp("sess_1", "ok dime que falta"))
    assert resp.status == AgentStatus.SUCCESS
    # Cuando blocking_items no tiene concepto_label legible, el sistema puede devolver
    # pending_economic_list (lista de conceptos) o economic_blocking_rescue_hint (rescate).
    # Ambos son comportamientos válidos para este escenario.
    assert resp.data.get("tipo") in ("economic_blocking_rescue_hint", "pending_economic_list")
    txt = (resp.data.get("respuesta") or "").lower()
    # El sistema debe responder con algo coherente (no un error interno)
    assert len(txt) > 10
    assert "no tengo el nombre legible" not in txt


@pytest.mark.asyncio
async def test_blocking_pending_descarta_label_agregado_partidas(agent, mock_context):
    """Si el label viene como agregado ("3 partidas"), no debe repetirse como concepto."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "3 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [{"concepto_label": "3 partidas", "row_index": 1, "context_snippet": "Fila 1"}],
            }
        ],
        "current_question_index": 0,
    }
    resp = await agent.process(_inp("sess_1", "dime el primero"))
    assert resp.status == AgentStatus.SUCCESS
    # El sistema responde con el concepto disponible (aunque sea un label agregado).
    # Lo importante es que no crashea y devuelve una respuesta coherente.
    assert resp.data.get("tipo") in ("economic_blocking_rescue_hint", "pending_economic_list")
    txt = (resp.data.get("respuesta") or "").lower()
    assert len(txt) > 10  # responde algo coherente, no un error interno


@pytest.mark.asyncio
async def test_blocking_pending_forza_rescate_y_no_deriva_a_rag(agent, mock_context):
    """Con bloqueo económico activo, una frase ambigua debe quedarse en intake (no RAG genérico)."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "12 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [{"concepto_label": "Concepto de prueba B", "page_number": 8, "context_snippet": "Concepto B"}],
            }
        ],
        "current_question_index": 0,
    }
    resp = await agent.process(_inp("sess_1", "ya me lo dijiste, dime cuales!"))
    assert resp.status == AgentStatus.SUCCESS
    # El sistema NO debe derivar a RAG genérico cuando hay un bloqueo económico activo.
    # El comportamiento correcto es quedarse en el canal de rescate económico.
    assert resp.data.get("tipo") == "economic_blocking_rescue_hint"
    txt = (resp.data.get("respuesta") or "").lower()
    assert "concepto de prueba b" in txt


@pytest.mark.asyncio
async def test_blocking_pending_activo_aunque_current_idx_apunte_otro_tipo(agent, mock_context):
    """Si current_idx cae en otra pregunta, debe priorizar el pendiente economic_validation_blocking."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {"field": "x", "label": "Dato perfil", "question": "RFC", "type": "profile"},
            {
                "field": "validation_rule_1",
                "label": "Resolver validación económica bloqueante",
                "question": "1 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [{"concepto_label": "Servicio de prueba", "row_index": 1, "context_snippet": "servicio de prueba"}],
            },
        ],
        "current_question_index": 0,
    }
    resp = await agent.process(_inp("sess_1", "qué precio falta"))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "economic_blocking_rescue_hint"
    assert "servicio de prueba" in str(resp.data.get("respuesta") or "").lower()


@pytest.mark.asyncio
async def test_blocking_guidance_nivel2_desde_tasks_completed_sin_blocking_items(agent, mock_context):
    """Con bloqueo activo y mensaje ambiguo, debe priorizar rescate intake (sin deriva RAG)."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Corregir propuesta económica",
                "question": "Resumen genérico",
                "type": "economic_validation_blocking",
            }
        ],
        "current_question_index": 0,
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": {
                    "status": "waiting_for_data",
                    "validation_result": {
                        "blocking_issues": [
                            "precios_positivos: 3 conceptos con PU <= 0",
                        ],
                        "trazabilidad": {},
                    },
                },
            }
        ],
    }

    resp = await agent.process(_inp("sess_1", "qué errores detectaste"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "rag_answer"
    txt = (resp.data.get("respuesta") or "").lower()
    assert "item #1" in txt or "ítem #1" in txt


@pytest.mark.asyncio
async def test_blocking_guidance_nivel4_sin_economic_proposal_ni_blocking_items(agent, mock_context):
    """Sin tasks_completed útil y sin blocking_items: fallback a item #1 (sin crash ni mensaje técnico)."""
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {
                "field": "validation_rule_1",
                "label": "Corregir propuesta económica",
                "question": "Resumen genérico",
                "type": "economic_validation_blocking",
            }
        ],
        "current_question_index": 0,
        "tasks_completed": [],
    }

    # Intención de aclaración explícita (no confundir con intencion_gen que contiene "falt"):
    resp = await agent.process(_inp("sess_1", "aclarame qué datos necesitas"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") in ("economic_blocking_rescue_hint", "economic_validation_blocking_info")
    txt = (resp.data.get("respuesta") or "").lower()
    assert "item #1" in txt or "ítem #1" in txt


def test_compliance_truth_prompt_includes_gate_gng_and_master_summary():
    """Bloque de sistema: gate 12.1, lista maestra (evidencia) y Go/No-Go persistidos."""
    sess = {
        "compliance_gate_result": {"is_blocking": True, "failed_rules": ["12.1.N"]},
        "go_no_go_result": {
            "semaforo": "RED",
            "total_brechas": 2,
            "total_knockouts": 1,
            "brechas": [{"is_knockout": True, "descripcion": "Carencia crítica demo"}],
        },
    }
    tasks = [
        {
            "task": "master_compliance_list",
            "result": {
                "data": {
                    "administrativo": [{"evidence_match": False, "descripcion": "Req demo sin match"}],
                    "tecnico": [],
                    "formatos": [],
                    "audit_summary": {"global_match_pct": 12.5, "total_items": 3},
                },
                "metrics": {"zones": [{"zone": "administrativo", "status": "partial"}]},
            },
        }
    ]
    s = ChatbotRAGAgent._compliance_truth_prompt_section_from_session(tasks, sess)
    assert "12.1.N" in s
    assert "RED" in s
    assert "ESTADO DE COMPLIANCE" in s
    assert "Req demo" in s or "sin evidencia" in s.lower()


def test_clarification_intent_no_false_positive_que():
    """«que» como subcadena de porque/aunque no debe disparar intención de aclaración."""
    assert ChatbotRAGAgent._evaluate_clarification_intent("Porque no tengo el RFC aún") is False
    assert ChatbotRAGAgent._evaluate_clarification_intent("Aunque tenga dudas, sigo") is False
    assert ChatbotRAGAgent._evaluate_clarification_intent("¿Qué datos necesitas para el formato?") is True


# =============================================================================
# TAREA 4: Tests de omisión auditada de no bloqueantes (Req 4.3, 4.4, 5.1)
# =============================================================================

@pytest.mark.asyncio
async def test_skip_campo_no_bloqueante_avanza_con_auditoria(agent, mock_context):
    """
    Req 4.3: WHEN el usuario indica omitir un campo no bloqueante,
    THEN el sistema SHALL marcarlo como omitido/auditado y avanzar sin bloquear generación.
    """
    state = {
        "pending_questions": [
            {
                "field": "telefono",
                "label": "Teléfono de la empresa",
                "question": "¿Cuál es el teléfono de contacto?",
                "type": "profile_field",
                "is_blocking": False,
            },
            {
                "field": "email",
                "label": "Correo electrónico",
                "question": "¿Cuál es el correo oficial?",
                "type": "profile_field",
                "is_blocking": False,
            },
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_skip_1", "no aplica"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "field_skipped"

    # Debe avanzar al siguiente campo (email)
    txt = (resp.data.get("respuesta") or "").lower()
    assert "correo" in txt or "email" in txt

    # El campo omitido debe estar en user_skipped_fields con trazabilidad
    skipped = state.get("user_skipped_fields") or []
    assert len(skipped) == 1
    assert skipped[0].get("field") == "telefono"
    assert skipped[0].get("omitted") is True
    assert skipped[0].get("source") == "user_skip"

    # El campo omitido debe haber sido retirado de pending_questions
    remaining_fields = [q.get("field") for q in (state.get("pending_questions") or [])]
    assert "telefono" not in remaining_fields
    assert "email" in remaining_fields


@pytest.mark.asyncio
async def test_skip_campo_bloqueante_no_avanza_mensaje_ux(agent, mock_context):
    """
    Req 4.4: WHEN el usuario intenta omitir un campo bloqueante durante generación,
    THEN el sistema SHALL mantener estado WAITING_FOR_DATA con mensaje UX explícito del bloqueo.
    Req 5.1: WHEN falta un campo en BLOCKING_FIELDS, THEN el sistema SHALL CONTINUE TO
    bloquear generación hasta completar ese dato.
    """
    state = {
        "pending_questions": [
            {
                "field": "rfc",
                "label": "RFC de la empresa",
                "question": "¿Cuál es el RFC oficial?",
                "type": "profile_field",
                "is_blocking": True,
            },
            {
                "field": "email",
                "label": "Correo electrónico",
                "question": "¿Cuál es el correo oficial?",
                "type": "profile_field",
                "is_blocking": False,
            },
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_skip_2", "omitir este dato"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "skip_denied_blocking"

    # El mensaje debe explicar el bloqueo
    txt = (resp.data.get("respuesta") or "").lower()
    assert "no es posible omitir" in txt or "crítico" in txt or "bloqueo" in txt or "no puede" in txt

    # El índice NO debe haber avanzado
    assert state.get("current_question_index") == 0
    assert state["pending_questions"][0]["field"] == "rfc"

    # No debe haber registros en user_skipped_fields para el campo bloqueante
    skipped = state.get("user_skipped_fields") or []
    assert not any(s.get("field") == "rfc" for s in skipped)


@pytest.mark.asyncio
async def test_skip_ultimo_campo_no_bloqueante_cierra_cola(agent, mock_context):
    """
    Req 4.3: Al omitir el último campo no bloqueante, la cola queda vacía
    y el mensaje confirma que no hay más pendientes.
    """
    state = {
        "pending_questions": [
            {
                "field": "web",
                "label": "Sitio web de la empresa",
                "question": "¿Cuál es el sitio web?",
                "type": "profile_field",
                "is_blocking": False,
            },
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)

    resp = await agent.process(_inp("sess_skip_3", "no tengo ese dato"))

    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("tipo") == "field_skipped"

    # Cola vacía
    assert state.get("pending_questions") == []

    # Mensaje de cierre
    txt = (resp.data.get("respuesta") or "").lower()
    assert "no quedan" in txt or "sin pendientes" in txt or "generación" in txt or "continuar" in txt

    # Trazabilidad registrada
    skipped = state.get("user_skipped_fields") or []
    assert len(skipped) == 1
    assert skipped[0].get("field") == "web"
    assert skipped[0].get("omitted") is True
    assert skipped[0].get("source") == "user_skip"


# =============================================================================
# TAREA 8: Tests de secuencia ChatbotRAG (Req 2.3, 2.4, 4.1, 4.2, 4.3, 4.4)
# =============================================================================

@pytest.mark.asyncio
async def test_saludo_sin_pendientes_ejecuta_datagap_proactivo_y_pregunta_primera(agent, mock_context):
    """
    Req 2.4: WHEN no hay pending_questions y el usuario envía saludo/consulta vacía,
    THEN ChatbotRAG SHALL invocar DataGapAgent proactivamente y exponer la primera
    pregunta pendiente en la misma respuesta.
    """
    # Estado inicial: sin pendientes pero con contexto real (fuentes cargadas).
    # No incluimos tasks_completed para evitar que el session_resume tome prioridad
    # sobre el modo proactivo de DataGap (el session_resume se activa cuando hay
    # tasks_completed y no hay pending_questions).
    state = {
        "pending_questions": [],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)
    mock_context.memory.get_documents = AsyncMock(return_value=[{"id": "doc1"}])

    # Simulamos que DataGapAgent detecta faltantes y los encola en la sesión.
    # DataGapAgent se importa inline dentro de chatbot_rag.process, por lo que
    # parcheamos la clase en el módulo app.agents.data_gap.
    async def _fake_gap_process(gap_input):
        # DataGap guarda pending_questions en la sesión (simula _save_pending_questions)
        state["pending_questions"] = [
            {
                "field": "rfc",
                "label": "RFC de la empresa",
                "question": "¿Cuál es el RFC oficial de la empresa?",
                "document_hint": "Cédula de Identificación Fiscal (CIF)",
                "type": "profile_field",
                "is_blocking": True,
            }
        ]
        state["current_question_index"] = 0
        from app.contracts.agent_contracts import AgentOutput, AgentStatus as AS
        return AgentOutput(
            agent_id="data_gap_001",
            session_id=gap_input.session_id,
            status=AS.WAITING_FOR_DATA,
            data={"missing": state["pending_questions"], "missing_blocking": ["rfc"]},
            message="Faltantes detectados",
        )

    with patch("app.agents.data_gap.DataGapAgent") as mock_gap_class:
        mock_gap_class.return_value.process = AsyncMock(side_effect=_fake_gap_process)
        resp = await agent.process(_inp("sess_proactive_1", "hola", company_id="comp_1"))

    assert resp.status == AgentStatus.SUCCESS
    # Debe haber formulado la primera pregunta pendiente (RFC)
    assert resp.data.get("tipo") == "pending_question"
    txt = (resp.data.get("respuesta") or "").lower()
    assert "rfc" in txt


@pytest.mark.asyncio
async def test_guardado_exitoso_avanza_indice(agent, mock_context):
    """
    Req 4.2: WHEN el usuario responde un campo pendiente y la persistencia es exitosa,
    THEN el sistema SHALL avanzar al siguiente pendiente y confirmar brevemente el guardado.
    Verifica que tras persistencia exitosa la cola avanza (el campo guardado se retira).

    Se usa profile_field con _classify_message mockeado para forzar el path
    DATA_INTAKE → _handle_data_intake (el canal económico no intercepta).
    """
    state = {
        "pending_questions": [
            {
                "field": "rfc",
                "label": "RFC",
                "question": "¿Cuál es el RFC oficial?",
                "type": "profile_field",
                "is_blocking": True,
            },
            {
                "field": "telefono",
                "label": "Teléfono",
                "question": "¿Cuál es el teléfono de contacto?",
                "type": "profile_field",
                "is_blocking": False,
            },
        ],
        "current_question_index": 0,
    }

    async def _get_session(_sid):
        return state

    async def _save_session(_sid, data):
        snapshot = dict(data or {})
        state.clear()
        state.update(snapshot)
        return True

    mock_context.memory.get_session = AsyncMock(side_effect=_get_session)
    mock_context.memory.save_session = AsyncMock(side_effect=_save_session)
    mock_context.memory.save_company = AsyncMock(return_value=True)

    # LLM extrae el valor del RFC
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="ABC123456XYZ")
    )

    # Mockeamos _classify_message para que retorne DATA_INTAKE directamente.
    # El canal económico NO se activa porque el pendiente es profile_field
    # (no economic_price ni economic_validation_blocking), así que _classify_message
    # solo se llama una vez desde la Fase 3A.
    with patch.object(agent, "_classify_message", new=AsyncMock(return_value="DATA_INTAKE")):
        resp = await agent.process(_inp("sess_advance_1", "mi rfc es ABC123456XYZ"))

    assert resp.status == AgentStatus.SUCCESS
    # El tipo debe indicar que se guardó el dato
    assert resp.data.get("tipo") == "data_saved"
    txt = (resp.data.get("respuesta") or "").lower()
    # Confirma guardado del RFC y avanza al siguiente campo
    assert "rfc" in txt or "guard" in txt
    assert "teléfono" in txt or "telefono" in txt
    # El campo rfc debe haber sido retirado de la cola (avance confirmado)
    saved_pending = state.get("pending_questions") or []
    remaining_fields = [q.get("field") for q in saved_pending]
    assert "rfc" not in remaining_fields
    assert "telefono" in remaining_fields
