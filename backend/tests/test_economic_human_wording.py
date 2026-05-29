"""Redacción humana de preguntas económicas y captura precio + esquema de horas."""

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.economic import (
    EconomicAgent,
    _build_structured_price_intro,
    _build_structured_price_question_for_user,
    _is_guard_like_context,
)


def test_guard_like_detection():
    assert _is_guard_like_context("Frecuencias del servicio", {"descripcion": "vigilancia por guardia"}, "")
    assert not _is_guard_like_context("Membretada", {"descripcion": "formato de carátula"}, "")


def test_build_price_question_guard_tone():
    gap = {"concepto_id": "r1", "concepto": "Servicio por guardia"}
    req = [{"id": "r1", "descripcion": "Vigilancia 24 horas"}]
    agent = EconomicAgent.__new__(EconomicAgent)
    q = EconomicAgent._build_economic_price_question_for_user(
        agent, "Servicio por guardia", req, gap
    )
    assert "precio unitario" in q.lower()
    assert "guardia" in q.lower()
    assert "periodos de horas" in q.lower() or "horas de servicio" in q.lower()


def test_build_price_question_generic():
    gap = {"concepto_id": "x", "concepto": "Capacitación en normativa"}
    req = [{"id": "x", "descripcion": "Curso interno"}]
    agent = EconomicAgent.__new__(EconomicAgent)
    q = EconomicAgent._build_economic_price_question_for_user(
        agent, "Capacitación en normativa", req, gap
    )
    assert "precio unitario" in q.lower()
    assert "vigilancia" not in q.lower()


def test_split_economic_price_reply():
    agent = ChatbotRAGAgent.__new__(ChatbotRAGAgent)
    a, b = ChatbotRAGAgent._split_economic_price_reply(agent, "5800; 24x24")
    assert a == "5800"
    assert "24" in b
    a2, b2 = ChatbotRAGAgent._split_economic_price_reply(agent, "6200 12x12")
    assert a2 == "6200"
    assert "12" in b2


def test_attach_guard_schedules_from_session():
    agent = EconomicAgent.__new__(EconomicAgent)  # sin MCP; solo método puro
    draft = [{"concepto_id": "c9", "concepto": "Guardia", "precio_unitario": 1.0}]
    out = EconomicAgent._attach_guard_schedules_from_session(
        agent,
        draft,
        {"concept_guard_schedules": {"c9": "24x24"}},
    )
    assert out[0].get("horario_ofertado_por_guardia") == "24x24"


def test_build_economic_msg_intro_guard():
    agent = EconomicAgent.__new__(EconomicAgent)
    gap = {"concepto_id": "g1", "concepto": "Ronda perimetral"}
    intro = EconomicAgent._build_economic_msg_intro(
        agent, 3, gap, [{"id": "g1", "descripcion": "vigilancia"}]
    )
    assert "precio unitario" in intro.lower()
    assert "esquema de horas" in intro.lower()


def test_build_structured_material_question_mentions_anexo_iii_h():
    slot = {
        "concept_label": "ALCOHOL EN GEL (LITRO)",
        "source_name": "32. Anexo III P1-2 ZA_Propuesta economica.xlsx",
        "sheet_name": "PARTIDA 2 ZONA A",
        "row_index": 39,
        "quantity_total": 129,
        "rows_count": 1,
        "slot_type": "monthly_material_requirement",
        "unit": "LITRO",
        "quantity_support_source_name": "matriz_cantidades_materiales.xlsx",
        "quantity_support_sheet_name": "Hoja 1",
        "quantity_support_row_index": 47,
    }
    q = _build_structured_price_question_for_user(slot)
    assert "matriz_cantidades_materiales.xlsx" in q.lower()
    assert "solo con el precio unitario" in q.lower()
    assert "cantidad total a cotizar" in q.lower()


def test_build_structured_price_intro_mentions_support_source_when_available():
    intro = _build_structured_price_intro(
        [
            {
                "concept_label": "ALCOHOL EN GEL (LITRO)",
                "quantity_support_source_name": "matriz_cantidades_materiales.xlsx",
            }
        ]
    )
    assert "matriz_cantidades_materiales.xlsx" in intro.lower()
    assert "precio" in intro.lower()


def test_bootstrap_proposal_from_tabular_rows_when_proposal_empty():
    agent = EconomicAgent.__new__(EconomicAgent)
    tabular_rows = [
        {
            "id": "li_1",
            "concepto_raw": "Salario mensual",
            "concepto_norm": "salario mensual",
            "precio_unitario": 8451.2,
            "cantidad": None,
            "unidad": None,
        }
    ]
    out = EconomicAgent._bootstrap_proposal_from_tabular_rows(agent, [], tabular_rows)
    assert len(out) == 1
    assert out[0]["concepto"] == "Salario mensual"
    assert out[0]["subtotal"] == 8451.2
    assert out[0]["price_source"] == "session_line_items_bootstrap"


def test_bootstrap_proposal_from_tabular_rows_keeps_positive_proposal():
    agent = EconomicAgent.__new__(EconomicAgent)
    proposal = [{"concepto": "Guardia", "subtotal": 100.0}]
    tabular_rows = [{"concepto_raw": "Salario mensual", "precio_unitario": 8451.2}]
    out = EconomicAgent._bootstrap_proposal_from_tabular_rows(agent, proposal, tabular_rows)
    assert out == proposal


def test_proposal_from_session_line_items_generates_priced_rows():
    agent = EconomicAgent.__new__(EconomicAgent)
    rows = [
        {"id": "a1", "concepto_raw": "Aguinaldo", "precio_unitario": 347.5, "cantidad": None}
    ]
    out = EconomicAgent._proposal_from_session_line_items(agent, rows)
    assert len(out) == 1
    assert out[0]["concepto"] == "Aguinaldo"
    assert out[0]["precio_unitario"] == 347.5
    assert out[0]["price_source"] == "session_line_items_engine_fallback"
