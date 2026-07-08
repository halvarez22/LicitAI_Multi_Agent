"""Regresión: mensaje Excel como fuente no debe desviarse a INE."""

from __future__ import annotations

from app.agents.chatbot_rag import ChatbotRAGAgent


def test_detect_uploaded_price_source_acknowledgment():
    q = (
        "Los precios están en el Excel que ya subí: CALCULO COSTO ISSSTE VIGILANCIA 2024.xlsx, "
        "según la página 28 de las bases (precio mensual y diario por operario sin IVA)."
    )
    assert ChatbotRAGAgent._detect_uploaded_price_source_acknowledgment(q) is True
    assert ChatbotRAGAgent._detect_uploaded_price_source_acknowledgment("hola") is False


async def test_acknowledge_uploaded_price_source_hitl(monkeypatch):
    from app.services.economic_tabular_ingest_sync import acknowledge_uploaded_price_source_hitl

    saved = {}

    class FakeMemory:
        async def get_session(self, sid):
            return {
                "capture_matrix_blocks": [
                    {"matrix_rows": [{"field": "f1", "label": "A"}]}
                ],
                "economic_user_inputs": {"f1": 100.0},
                "pending_questions": [
                    {
                        "type": "economic_validation_blocking",
                        "field": "economic_price_source",
                        "input_mode": "price_source",
                    },
                    {
                        "type": "profile_field",
                        "field": "ine_representante",
                        "question": "INE?",
                    },
                ],
            }

        async def save_session(self, sid, data):
            saved.update(data)

        async def get_line_items_for_session(self, sid):
            return []

    async def fake_refresh(memory, sid):
        return {}

    monkeypatch.setattr(
        "app.economic_validation.service.refresh_economic_validations_for_session",
        fake_refresh,
    )
    out = await acknowledge_uploaded_price_source_hitl(
        FakeMemory(),
        "sess",
        user_query="precios en excel subido pagina 28",
    )
    assert out["acknowledged"] is True
    assert "economic_price_source_ack_v1" in (saved.get("economic_user_inputs") or {})
    assert len(saved.get("pending_questions") or []) == 1
    assert saved["pending_questions"][0]["field"] == "ine_representante"
