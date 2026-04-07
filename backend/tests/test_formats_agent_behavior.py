"""
FormatsAgent: contrato de entrada/salida, sin LLM real ni disco.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager

# Slots obligatorios del piloto Hito 4 (FormatsAgent) además de RFC.
_SLOTS_PILOTO = {
    "domicilio_fiscal": "Av. Reforma 222, Col. Juárez, Ciudad de México",
    "representante_legal": "María Representante Legal",
}


def _memory_stub(tasks: list | None = None):
    mem = AsyncMock()
    sess = {"tasks_completed": tasks or [], "name": "test_sess"}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


def _make_agent(tasks=None):
    ctx = MCPContextManager(_memory_stub(tasks))
    agent = FormatsAgent(ctx)
    agent.llm = AsyncMock()
    agent.llm.generate = AsyncMock(return_value={"response": "Contenido legal mockeado."})
    return agent


@pytest.mark.asyncio
async def test_sin_formatos_devuelve_success_vacio():
    """Sin ítems administrativos/formatos → success con lista vacía, sin llamar al LLM."""
    agent = _make_agent()

    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101AAA",
                **_SLOTS_PILOTO,
            }
        },
        "compliance_master_list": {"administrativo": [], "formatos": []},
    }

    with patch("os.makedirs"):
        out = await agent.process("sess_f1", input_data)

    assert out["status"] == "success"
    assert out["data"]["count"] == 0
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_formatos_llm_invocado_y_success():
    """Con ítems administrativos → LLM invocado una vez por ítem, contrato data.documentos."""
    agent = _make_agent()

    req = {"id": "1.1", "nombre": "Acta Constitutiva", "descripcion": "Copia del acta", "tipo": "administrativo"}
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101BBB",
                "representante_legal": "Ana Test",
                "domicilio_fiscal": _SLOTS_PILOTO["domicilio_fiscal"],
            }
        },
        "compliance_master_list": {"administrativo": [req], "formatos": []},
    }

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process("sess_f2", input_data)

    assert out["status"] == "success"
    assert out["data"]["count"] == 1
    assert len(out["data"]["documentos"]) == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_compliance_desde_results_orquestador():
    """Sin compliance_master_list explícito debe leer de results.compliance.data."""
    agent = _make_agent()

    req = {"id": "1.2", "nombre": "Declaración Fiscal", "descripcion": "Últimas 3 declaraciones", "tipo": "administrativo"}
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Fallback SA",
                "rfc": "FAL010101CCC",
                **_SLOTS_PILOTO,
            }
        },
        "results": {"compliance": {"data": {"administrativo": [req], "formatos": []}}},
    }

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process("sess_f3", input_data)

    assert out["status"] == "success"
    assert out["data"]["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_error_no_genera_archivo_y_sigue():
    """Si el LLM devuelve error, el agente salta el ítem sin romper el proceso."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value={"error": "LLM timeout"})

    req = {"id": "1.3", "nombre": "Carta Bajo Protesta", "tipo": "administrativo"}
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Err SA",
                "rfc": "ERR010101DDD",
                **_SLOTS_PILOTO,
            }
        },
        "compliance_master_list": {"administrativo": [req], "formatos": []},
    }

    with patch("os.makedirs"), patch("app.agents.formats._save_docx") as mock_save:
        out = await agent.process("sess_f4", input_data)

    # LLM fue invocado pero el archivo NO se genera
    agent.llm.generate.assert_awaited_once()
    mock_save.assert_not_called()
    assert out["data"]["count"] == 0


@pytest.mark.asyncio
async def test_item_sin_prefijo_pero_tipo_administrativo_se_incluye():
    """Un ítem con tipo='administrativo' sin prefijo 1_ se debe incluir tras el fix del filtro."""
    agent = _make_agent()

    req = {"id": "admin_003", "nombre": "Declaración de Integridad", "tipo": "administrativo"}
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Tipo SA",
                "rfc": "TIP010101EEE",
                **_SLOTS_PILOTO,
            }
        },
        "compliance_master_list": {"administrativo": [req], "formatos": []},
    }

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process("sess_f5", input_data)

    assert out["data"]["count"] == 1
    agent.llm.generate.assert_awaited_once()
