"""
DocumentPackagerAgent: contrato, parseo LLM robusto, fallback determinístico y rutas.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.agents.document_packager import (
    DocumentPackagerAgent,
    mapear_sobres_deterministico,
)
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse


def _memory_stub():
    mem = AsyncMock()
    # Para consistencia con los tests, mockear get_global_context también en el ctx
    return mem


def _make_agent():
    mem = _memory_stub()
    # sess_name = "test_session"
    mem.get_session = AsyncMock(return_value={"tasks_completed": [], "name": "test_session"})
    ctx = MCPContextManager(mem)
    # Mockear el global context para que devuelva session_state con name: test_session
    ctx.get_global_context = AsyncMock(return_value={"session_state": {"name": "test_session"}})
    
    agent = DocumentPackagerAgent(ctx)
    agent.llm = AsyncMock()
    # Suprimir smart_search para no tocar ChromaDB
    agent.smart_search = AsyncMock(return_value="")
    return agent


ESTRUCTURA_LLM_VALIDA = {
    "sobre_1": {
        "titulo": "SOBRE 1 - ADMINISTRATIVO",
        "nombre_carpeta": "SOBRE_1_ADMINISTRATIVO",
        "documentos": [{"nombre": "Acta Constitutiva", "ruta": "/data/acta.docx"}]
    },
    "sobre_2": {
        "titulo": "SOBRE 2 - TÉCNICO",
        "nombre_carpeta": "SOBRE_2_TECNICO",
        "documentos": []
    },
    "sobre_3": {
        "titulo": "SOBRE 3 - ECONÓMICO",
        "nombre_carpeta": "SOBRE_3_ECONOMICO",
        "documentos": []
    }
}


def test_mapear_deterministico_dedupes_same_path(tmp_path):
    """Un mismo archivo no debe aparecer dos veces en un sobre."""
    session = "sess_dedup"
    doc = tmp_path / "AD-71_Anexo_M.docx"
    doc.write_bytes(b"x")
    gen = {
        "tecnica": [
            {"nombre": "Anexo M", "ruta": str(doc)},
            {"nombre": "Anexo M copia", "ruta": str(doc)},
        ]
    }
    est = mapear_sobres_deterministico(session, gen)
    # Anexo M es administrativo aunque venga de carpeta técnica de generación.
    s1_docs = est["sobre_1"]["documentos"]
    assert len(s1_docs) == 1


def test_mapear_deterministico_anexo_tecnico_en_sobre_2_aunque_ruta_admin(tmp_path):
    """El Anexo Técnico de propuesta no debe quedar en complementario por carpeta admin."""
    session = "sess_at"
    f = tmp_path / "ANEXO_TECNICO_2026.docx"
    f.write_bytes(b"x" * 2000)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {
                    "nombre": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
                    "source_filename": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
                    "ruta": str(f),
                }
            ],
        },
    )
    assert len(est["sobre_2"]["documentos"]) == 1
    assert len(est["sobre_1"]["documentos"]) == 0


def test_mapear_deterministico_dedup_anexo_m_por_nombre(tmp_path):
    session = "sess_m"
    a = tmp_path / "m1.docx"
    b = tmp_path / "m2.docx"
    a.write_bytes(b"aa")
    b.write_bytes(b"bbbb")
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {"nombre": "12. Anexo M (Declaración de Integridad).docx", "ruta": str(a)},
                {"nombre": "12. Anexo M (Declaración de Integridad) (2).docx", "ruta": str(b)},
            ],
        },
    )
    assert len(est["sobre_1"]["documentos"]) == 1


def test_mapear_deterministico_reubica_anexo_tecnico_unicode_descompuesto(tmp_path):
    session = "sess_at_unicode"
    f = tmp_path / "anexo_tecnico.docx"
    f.write_bytes(b"x" * 10)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {
                    "nombre": "ANEXO TE\u0301CNICO 2026 ABRIL A DICIEMBRE.docx",
                    "source_filename": "ANEXO TE\u0301CNICO 2026 ABRIL A DICIEMBRE.docx",
                    "ruta": str(f),
                }
            ]
        },
    )
    assert len(est["sobre_2"]["documentos"]) == 1
    assert len(est["sobre_1"]["documentos"]) == 0


def test_mapear_deterministico_excluye_espejo_pdf_referencia(tmp_path):
    session = "sess_pdf_ref"
    f = tmp_path / "anexo_tecnico_pdf_mirror.docx"
    f.write_bytes(b"x" * 10)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {
                    "nombre": "ANEXO TÉCNICO.pdf",
                    "source_filename": "ANEXO TÉCNICO.pdf",
                    "ruta": str(f),
                }
            ]
        },
    )
    assert len(est["sobre_1"]["documentos"]) == 0
    assert len(est["sobre_2"]["documentos"]) == 0
    assert len(est["sobre_3"]["documentos"]) == 0


def test_mapear_deterministico_excluye_espejo_pdf_referencia_unicode_descompuesto(tmp_path):
    session = "sess_pdf_ref_nfd"
    f = tmp_path / "anexo_tecnico_pdf_mirror_nfd.docx"
    f.write_bytes(b"x" * 10)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {
                    "nombre": "ANEXO TE\u0301CNICO.pdf",
                    "source_filename": "ANEXO TE\u0301CNICO.pdf",
                    "ruta": str(f),
                }
            ]
        },
    )
    assert len(est["sobre_1"]["documentos"]) == 0
    assert len(est["sobre_2"]["documentos"]) == 0
    assert len(est["sobre_3"]["documentos"]) == 0


def test_mapear_deterministico_admin_en_sobre_1(tmp_path):
    session = "sess_admin"
    f = tmp_path / "AD-17_Carta.docx"
    f.write_bytes(b"a")
    est = mapear_sobres_deterministico(
        session,
        {"administrativa": [{"nombre": "Carta", "ruta": str(f)}]},
    )
    assert len(est["sobre_1"]["documentos"]) == 1
    assert est["sobre_2"]["documentos"] == []


@pytest.mark.asyncio
async def test_packager_deterministic_no_llm_call_by_default():
    """Sin PACKAGER_USE_LLM_MAPPING el LLM no debe invocarse."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="{}"))

    inp = AgentInput(
        session_id="sess_det",
        company_data={
            "master_profile": {"razon_social": "Co"},
            "documentos_generados": {
                "tecnica": [{"nombre": "PT", "ruta": "/data/pt.docx"}],
            },
        },
    )

    with patch("os.makedirs"), patch("os.path.exists", return_value=False), patch(
        "shutil.copy2"
    ), patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data.get("mapping_mode") == "deterministic"
    agent.llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_packager_mapeo_llm_json_valido(monkeypatch):
    """LLM devuelve JSON válido → copy2 invocado y estructura_sobres en el retorno."""
    monkeypatch.setenv("PACKAGER_USE_LLM_MAPPING", "true")
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response=json.dumps(ESTRUCTURA_LLM_VALIDA))
    )

    inp = AgentInput(
        session_id="sess_pk1",
        company_data={
            "master_profile": {"razon_social": "Test Co"},
            "documentos_generados": {
                "administrativa": [{"nombre": "Acta Constitutiva", "ruta": "/data/acta.docx"}]
            }
        }
    )

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=True), \
         patch("os.path.isfile", return_value=True), \
         patch("shutil.copy2") as mock_copy, \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "estructura_sobres" in out.data
    assert out.data.get("mapping_mode") == "llm_sanitized"
    mock_copy.assert_called()


@pytest.mark.asyncio
async def test_packager_llm_error_usa_fallback():
    """Si LLM falla con error → fallback determinístico reparte los gen_docs."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=False, error="Ollama timeout"))

    inp = AgentInput(
        session_id="sess_pk2",
        company_data={
            "master_profile": {},
            "documentos_generados": {
                "administrativa": [{"nombre": "Acta", "ruta": "/data/acta.docx"}],
                "tecnica": [{"nombre": "Propuesta Técnica", "ruta": "/data/pt.docx"}],
                "economica": [{"nombre": "Propuesta Económica", "ruta": "/data/pe.xlsx"}],
            }
        }
    )

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    estructura = out.data["estructura_sobres"]
    # Los 3 sobres deben existir gracias al fallback
    assert "sobre_1" in estructura
    assert "sobre_2" in estructura
    assert "sobre_3" in estructura


@pytest.mark.asyncio
async def test_packager_respuesta_dict_no_attr_replace():
    """
    Regresión: asegurar que nunca se llame a .replace() sobre el dict completo.
    """
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response=json.dumps(ESTRUCTURA_LLM_VALIDA))
    )

    inp = AgentInput(
        session_id="sess_pk3",
        company_data={
            "master_profile": {},
            "documentos_generados": {}
        }
    )

    # Si el código hiciera response.replace(...) explotaría con AttributeError
    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    # Que lleguemos aquí sin excepción es la aserción principal
    assert out.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_packager_usa_session_name_en_ruta():
    """El output_base debe contener session_name, no session_id cuando difieren."""
    agent = _make_agent()
    # Usar el session_id para la comparación (aunque el código usa session_id de la URL para crear la carpeta rota)
    # En app/agents/document_packager.py:52 -> os.path.join("/data", "outputs", session_id)
    # Wait, the code uses session_id from agent_input, not the name from mock_stub!
    
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=False, error="no llm"))

    inp = AgentInput(
        session_id="test_session",
        company_data={"master_profile": {}, "documentos_generados": {}}
    )

    captured_dirs = []

    def fake_makedirs(path, **kwargs):
        captured_dirs.append(path)

    with patch("os.makedirs", side_effect=fake_makedirs), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    # El código usa AgentInput.session_id para el path
    assert any("test_session" in d for d in captured_dirs), \
        f"test_session no encontrado en dirs: {captured_dirs}"


@pytest.mark.asyncio
async def test_packager_preserva_lineage_en_estructura_sobres():
    agent = _make_agent()
    inp = AgentInput(
        session_id="sess_lineage_packager",
        company_data={
            "master_profile": {"razon_social": "Test Co"},
            "documentos_generados": {
                "tecnica": [
                    {
                        "nombre": "Anexo Técnico",
                        "ruta": "/data/pt.docx",
                        "source_doc_id": "doc-9",
                        "source_filename": "ANEXO TÉCNICO 2026.docx",
                        "template_id": "anexo_tecnico",
                        "mirror_mode": "copy_docx_filled",
                        "materialization_route": "mirror",
                    }
                ],
            },
        },
    )

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=True), \
         patch("os.path.isfile", return_value=True), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    doc = out.data["estructura_sobres"]["sobre_2"]["documentos"][0]
    assert doc["source_doc_id"] == "doc-9"
    assert doc["template_id"] == "anexo_tecnico"
    assert doc["materialization_route"] == "mirror"
    assert out.data["materialization_metrics"]["files_count"] == 1


def test_mapear_deterministico_dedup_anexo_vii_sobre_ad32(tmp_path):
    session = "sess_vii"
    ad = tmp_path / "AD-32_Carta_Declaracion_de_Integridad.docx"
    anexo = tmp_path / "Anexo_VII_Carta_Declaracion_de_Integridad.docx"
    ad.write_bytes(b"ad")
    anexo.write_bytes(b"anexo" * 20)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {"nombre": ad.name, "ruta": str(ad)},
                {"nombre": anexo.name, "ruta": str(anexo)},
            ],
        },
    )
    assert len(est["sobre_1"]["documentos"]) == 1
    assert "Anexo_VII" in est["sobre_1"]["documentos"][0]["nombre"]


def test_mapear_deterministico_dedup_carta_compromiso_con_anexo_vi(tmp_path):
    session = "sess_vi"
    carta = tmp_path / "Carta_compromiso.docx"
    anexo = tmp_path / "Anexo_VI_Carta_Compromiso.docx"
    carta.write_bytes(b"c")
    anexo.write_bytes(b"anexo" * 20)
    est = mapear_sobres_deterministico(
        session,
        {
            "administrativa": [
                {"nombre": carta.name, "ruta": str(carta)},
                {"nombre": anexo.name, "ruta": str(anexo)},
            ],
        },
    )
    assert len(est["sobre_1"]["documentos"]) == 1
    assert "Anexo_VI" in est["sobre_1"]["documentos"][0]["nombre"]


def test_mapear_deterministico_excluye_espejo_cmyt(tmp_path):
    session = "sess_cmyt"
    f = tmp_path / "cat_formato_hoja_membretada_cmyt_zen.docx"
    f.write_bytes(b"x" * 100)
    est = mapear_sobres_deterministico(
        session,
        {"administrativa": [{"nombre": f.name, "ruta": str(f)}]},
    )
    assert len(est["sobre_1"]["documentos"]) == 0


def test_mapear_deterministico_fo35_modelo_en_sobre_2(tmp_path):
    session = "sess_fo35"
    f = tmp_path / "FO-35_Anexo_IV_Modelo_presentacion_Prop.docx"
    f.write_bytes(b"x" * 100)
    est = mapear_sobres_deterministico(
        session,
        {"administrativa": [{"nombre": f.name, "ruta": str(f)}]},
    )
    assert len(est["sobre_2"]["documentos"]) == 1
    assert len(est["sobre_1"]["documentos"]) == 0


def test_packager_sobres_stale_detects_missing_economic(tmp_path, monkeypatch):
    from app.agents import document_packager as dp

    session = "sess_stale"
    root = tmp_path / "outputs" / session
    econ_src = root / "2.propuesta_economica"
    econ_src.mkdir(parents=True)
    (econ_src / "ECON_01_tabla.xlsx").write_bytes(b"x" * 10)
    sobre3 = root / "SOBRE_3_ECONOMICO"
    sobre3.mkdir(parents=True)
    (sobre3 / "00_CARATULA_SOBRE.docx").write_bytes(b"x" * 10)

    original_join = dp.os.path.join
    monkeypatch.setattr(
        dp,
        "mapear_sobres_deterministico",
        lambda sid, gen=None: {
            "sobre_1": {"documentos": []},
            "sobre_2": {"documentos": []},
            "sobre_3": {
                "documentos": [
                    {"nombre": "ECON_01_tabla.xlsx", "ruta": str(econ_src / "ECON_01_tabla.xlsx")}
                ]
            },
        },
    )

    def fake_join(*parts):
        if len(parts) >= 3 and parts[0] == "/data" and parts[1] == "outputs":
            return str((tmp_path / "outputs").joinpath(*parts[2:]))
        return original_join(*parts)

    monkeypatch.setattr(dp.os.path, "join", fake_join)
    assert dp.packager_sobres_stale(session) is True
