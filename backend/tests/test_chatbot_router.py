import pytest
from app.agents.chatbot_rag import ChatbotRAGAgent

@pytest.mark.parametrize("query, expected", [
    ("ok, que conceptos son?", True),
    ("no se a que conceptos tecnicos se refiere", True),
    ("¿Aclárame lo que falta?", True),
    ("Repíteme los precios", True),
    ("qué falta", True),
    ("que solvencia piden?", False), # DEBE SER QUERY (PDF)
    ("cuanto cuesta el servicio", False), # DEBE SER QUERY (PDF)
    ("ok cual concepto es", True),
    ("dime los datos que faltan", True),
    ("que significa garantia de cumplimiento", False), # Pregunta técnica (PDF)
])
def test_clarification_intent_routing(query, expected):
    # Probamos la lógica real importada del Agente
    assert ChatbotRAGAgent._evaluate_clarification_intent(query) == expected
