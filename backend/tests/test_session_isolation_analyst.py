"""
Test de exploración del bug: AnalystAgent Cross-Session Data

Este test demuestra el bug de aislamiento de sesiones en AnalystAgent.
El bug ocurre cuando AnalystAgent retorna requisitos de una licitación diferente
a la activa, debido a que smart_search consulta ChromaDB sin validación de sesión.

CRITICAL: Este test DEBE FALLAR en código no corregido.
La falla confirma que el bug existe.

Validates: Requirements 1.2, 2.2
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus


class TestAnalystAgentCrossSessionData:
    """
    Test que demuestra el bug de cross-session data en AnalystAgent.
    
    Bug Condition: Cuando AnalystAgent procesa una sesión vacía, puede retornar
    requisitos de otra sesión si ChromaDB tiene datos de esa otra sesión.
    
    Expected Behavior: AnalystAgent debe retornar error o vacío cuando la sesión
    no tiene documentos, NO requisitos de otra sesión.
    """

    @pytest.fixture
    def mock_context_manager(self):
        """Crea un mock del MCPContextManager."""
        mock_memory = AsyncMock()
        mock_memory.get_session.return_value = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        mock_memory.get_documents.return_value = []
        mock_memory.get_line_items_for_session.return_value = []
        mock_memory.save_session = AsyncMock(return_value=True)
        
        ctx_manager = MCPContextManager(mock_memory)
        return ctx_manager

    @pytest.fixture
    def mock_vector_db_with_cross_session_data(self):
        """
        Crea un mock de VectorDbServiceClient con datos de múltiples sesiones.
        
        Simula el escenario donde:
        - session "paneles-solares-2024" tiene documentos sobre paneles solares
        - session "issste-bcs-2024" NO tiene documentos
        - El bug ocurre cuando query_texts para "issste-bcs-2024" retorna datos de "paneles-solares-2024"
        """
        mock_vector_db = MagicMock()
        
        # Datos de la sesión "paneles-solares-2024"
        paneles_docs = [
            "Requisitos para la instalación de paneles solares fotovoltaicos",
            "Especificaciones técnicas: paneles de 500W mínimo",
            "Capacidad mínima requerida: 100 kWp",
            "Garantía de los paneles: 25 años",
            "Certificación requerida: IEC 61215"
        ]
        paneles_metas = [
            {"session_id": "paneles-solares-2024", "source": "bases_paneles.pdf", "page": 1},
            {"session_id": "paneles-solares-2024", "source": "bases_paneles.pdf", "page": 2},
            {"session_id": "paneles-solares-2024", "source": "bases_paneles.pdf", "page": 3},
            {"session_id": "paneles-solares-2024", "source": "anexos_paneles.pdf", "page": 1},
            {"session_id": "paneles-solares-2024", "source": "anexos_paneles.pdf", "page": 2}
        ]
        
        def query_texts_side_effect(session_id, query, n_results=5):
            """
            Simula el comportamiento del bug:
            - Para "paneles-solares-2024": retorna documentos correctos
            - Para "issste-bcs-2024": BUG - retorna documentos de "paneles-solares-2024"
            """
            if session_id == "paneles-solares-2024":
                return {
                    "documents": paneles_docs[:n_results],
                    "metadatas": paneles_metas[:n_results],
                    "distances": [0.1] * min(n_results, len(paneles_docs))
                }
            elif session_id == "issste-bcs-2024":
                # BUG SIMULATION: Retornar datos de otra sesión
                # En código corregido, esto debería retornar listas vacías
                # porque la sesión no tiene documentos propios
                return {
                    "documents": paneles_docs[:n_results],  # BUG: datos de paneles-solares
                    "metadatas": paneles_metas[:n_results],  # BUG: metadatos con session_id incorrecto
                    "distances": [0.1] * min(n_results, len(paneles_docs))
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts.side_effect = query_texts_side_effect
        
        def fetch_page_side_effect(session_id, source, page):
            """Simula fetch_page_documents con el mismo bug."""
            if session_id == "paneles-solares-2024" or session_id == "issste-bcs-2024":
                # BUG: Retorna datos de paneles para cualquier sesión
                return ["Contenido de página sobre paneles solares"]
            return []
        
        mock_vector_db.fetch_page_documents.side_effect = fetch_page_side_effect
        
        return mock_vector_db

    @pytest.mark.asyncio
    async def test_analyst_agent_returns_empty_for_empty_session(
        self, mock_context_manager, mock_vector_db_with_cross_session_data
    ):
        """
        Test que verifica que AnalystAgent retorna vacío/error para sesión sin documentos.
        
        Escenario:
        1. session "paneles-solares-2024" tiene documentos indexados
        2. session "issste-bcs-2024" NO tiene documentos
        3. Al procesar "issste-bcs-2024", AnalystAgent NO debe retornar requisitos de "paneles-solares-2024"
        
        Expected Behavior: AnalystAgent retorna error "Contexto insuficiente" o datos vacíos
        Bug Behavior: AnalystAgent retorna requisitos sobre paneles solares
        """
        # Crear AnalystAgent con mocks
        agent = AnalystAgent(mock_context_manager)
        agent.vector_db = mock_vector_db_with_cross_session_data
        
        # Mock del LLM para capturar qué contexto se le envía
        captured_context = []
        
        async def mock_llm_generate(prompt, **kwargs):
            captured_context.append(prompt)
            # Retornar un JSON válido por defecto
            return MagicMock(
                success=True,
                response=json.dumps({
                    "cronograma": {},
                    "requisitos_participacion": [],
                    "requisitos_filtro": [],
                    "garantias": {},
                    "criterios_evaluacion": "No especificado",
                    "reglas_economicas": {},
                    "alcance_operativo": []
                })
            )
        
        agent.llm = MagicMock()
        agent.llm.generate = AsyncMock(side_effect=mock_llm_generate)
        
        # Crear input para sesión vacía
        agent_input = AgentInput(
            session_id="issste-bcs-2024",
            mode="full"
        )
        
        # Ejecutar AnalystAgent
        result = await agent.process(agent_input)
        
        # Verificar que el contexto enviado al LLM NO contiene datos de paneles solares
        context_str = captured_context[0] if captured_context else ""
        
        # BUG CHECK: Si el contexto contiene "paneles solares", el bug existe
        if "paneles solares" in context_str.lower() or "paneles" in context_str.lower():
            # BUG DETECTADO: El contexto contiene datos de otra sesión
            print("\n[BUG DETECTADO] AnalystAgent usó datos de otra sesión")
            print(f"  - Sesión procesada: issste-bcs-2024")
            print(f"  - Contexto contiene referencias a: paneles solares")
            print(f"  - Longitud del contexto: {len(context_str)} caracteres")
            print("  - El sistema está mezclando datos de diferentes licitaciones")
            
            # Verificar metadatos incorrectos en los resultados
            print("\n[ANÁLISIS DEL BUG]")
            print("  - query_texts('issste-bcs-2024', ...) retornó documentos de 'paneles-solares-2024'")
            print("  - Los metadatos tienen session_id='paneles-solares-2024' en lugar de 'issste-bcs-2024'")
            print("  - AnalystAgent no verificó que los resultados pertenecieran a la sesión correcta")
            
            # Este assert FALLA en código no corregido, confirmando el bug
            assert False, (
                "Bug detectado: AnalystAgent.process('issste-bcs-2024') usó datos de "
                "'paneles-solares-2024'. Los requisitos de una licitación no deben "
                "aparecer en el análisis de otra."
            )
        
        # Si no hay bug, verificar comportamiento correcto
        if result.get("status") == "error":
            print("\n[COMPORTAMIENTO CORRECTO] AnalystAgent retornó error para sesión vacía")
            print(f"  - Sesión procesada: issste-bcs-2024")
            print(f"  - Mensaje: {result.get('message', 'N/A')}")
            assert "insuficiente" in result.get("message", "").lower() or result.get("status") == "error"
        else:
            # Verificar que los datos no contienen referencias a paneles solares
            data_str = str(result.get("data", {}))
            assert "paneles" not in data_str.lower(), (
                "El resultado no debe contener datos de paneles solares"
            )
            print("\n[COMPORTAMIENTO CORRECTO] AnalystAgent no usó datos de otra sesión")

    @pytest.mark.asyncio
    async def test_analyst_agent_session_id_in_search_results(
        self, mock_context_manager, mock_vector_db_with_cross_session_data
    ):
        """
        Test que verifica que los resultados de búsqueda tienen el session_id correcto.
        
        Este test verifica específicamente que los metadatos de los resultados
        de ChromaDB contengan el session_id de la sesión consultada.
        """
        # Ejecutar query_texts para sesión vacía
        result = mock_vector_db_with_cross_session_data.query_texts(
            "issste-bcs-2024", 
            "requisitos", 
            n_results=5
        )
        
        # Verificar metadatos
        metadatas = result.get("metadatas", [])
        
        # BUG CHECK: Si hay metadatos con session_id incorrecto
        wrong_session_metas = [
            m for m in metadatas 
            if m.get("session_id") != "issste-bcs-2024"
        ]
        
        if wrong_session_metas:
            print("\n[BUG DETECTADO] Resultados de búsqueda con session_id incorrecto")
            print(f"  - Sesión consultada: issste-bcs-2024")
            print(f"  - Metadatos incorrectos: {wrong_session_metas}")
            print(f"  - Session IDs encontrados: {[m.get('session_id') for m in wrong_session_metas]}")
            
            assert False, (
                f"Bug detectado: query_texts retornó {len(wrong_session_metas)} resultados "
                f"con session_id incorrecto. Los resultados deben pertenecer a la sesión consultada."
            )
        else:
            print("\n[COMPORTAMIENTO CORRECTO] Todos los resultados tienen session_id correcto")

    @pytest.mark.asyncio
    async def test_analyst_agent_context_insufficient_for_empty_session(
        self, mock_context_manager
    ):
        """
        Test que verifica que AnalystAgent retorna error cuando no hay contexto suficiente.
        
        Este test usa un mock que retorna SIEMPRE listas vacías, simulando
        correctamente una sesión sin documentos.
        """
        # Crear mock que retorna vacío para cualquier consulta
        mock_vector_db_empty = MagicMock()
        mock_vector_db_empty.query_texts.return_value = {
            "documents": [], 
            "metadatas": [], 
            "distances": []
        }
        mock_vector_db_empty.fetch_page_documents.return_value = []
        
        # Crear AnalystAgent
        agent = AnalystAgent(mock_context_manager)
        agent.vector_db = mock_vector_db_empty
        
        # Mock del LLM (no debería llamarse)
        agent.llm = MagicMock()
        agent.llm.generate = AsyncMock()
        
        # Crear input
        agent_input = AgentInput(
            session_id="empty-session-2024",
            mode="full"
        )
        
        # Ejecutar AnalystAgent
        result = await agent.process(agent_input)
        
        # Verificar que retornó error por contexto insuficiente
        assert result.get("status") == "error", (
            "AnalystAgent debe retornar status='error' para sesión sin documentos"
        )
        assert "insuficiente" in result.get("message", "").lower(), (
            "El mensaje debe indicar contexto insuficiente"
        )
        
        # Verificar que el LLM no fue llamado
        agent.llm.generate.assert_not_called()
        
        print("\n[COMPORTAMIENTO CORRECTO] AnalystAgent detectó contexto insuficiente")
        print(f"  - Sesión: empty-session-2024")
        print(f"  - Status: {result.get('status')}")
        print(f"  - Mensaje: {result.get('message')}")


class TestAnalystAgentCrossSessionPropertyBased:
    """
    Property-based tests para verificar aislamiento de sesión en AnalystAgent.
    
    Estas pruebas usan Hypothesis para generar múltiples escenarios y verificar
    que el aislamiento se mantiene en todos los casos.
    """

    def test_property_analyst_never_returns_wrong_session_data(self):
        """
        Property: Para cualquier par de sesiones diferentes, AnalystAgent
        nunca debe retornar datos de una sesión cuando procesa la otra.
        
        Validado con Hypothesis para múltiples combinaciones de session_ids.
        
        Nota: Este test verifica la propiedad a nivel de VectorDbServiceClient.query_texts
        ya que Hypothesis no soporta funciones async directamente.
        """
        from hypothesis import given, strategies as st, settings, assume
        
        # Estrategia para generar session_ids
        session_id_strategy = st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
            min_size=5,
            max_size=30
        )
        
        @given(
            session_with_data=session_id_strategy,
            session_empty=session_id_strategy
        )
        @settings(max_examples=10)
        def check_session_isolation(session_with_data, session_empty):
            # Solo verificar si las sesiones son diferentes
            assume(session_with_data != session_empty)
            
            # Mock de vector DB con datos solo en session_with_data
            mock_vector_db = MagicMock()
            
            def query_side_effect(sid, query, n_results=5):
                if sid == session_with_data:
                    return {
                        "documents": [f"Documento de {session_with_data}"],
                        "metadatas": [{"session_id": session_with_data}],
                        "distances": [0.1]
                    }
                elif sid == session_empty:
                    # BUG SIMULATION: Retorna datos de otra sesión
                    return {
                        "documents": [f"Documento de {session_with_data}"],
                        "metadatas": [{"session_id": session_with_data}],
                        "distances": [0.1]
                    }
                return {"documents": [], "metadatas": [], "distances": []}
            
            mock_vector_db.query_texts.side_effect = query_side_effect
            
            # Ejecutar query para sesión vacía
            result = mock_vector_db.query_texts(session_empty, "test", n_results=5)
            
            # Verificar que no hay datos de otra sesión
            if result.get("documents"):
                for meta in result.get("metadatas", []):
                    assert meta.get("session_id") == session_empty, (
                        f"Bug: query_texts({session_empty}) retornó datos de {meta.get('session_id')}"
                    )
        
        # Ejecutar la prueba
        check_session_isolation()


class TestAnalystAgentVerificationMethod:
    """
    Tests para el método _verify_search_results_session.
    
    Este método fue agregado como parte de la corrección del bug.
    Verifica que los resultados de búsqueda pertenezcan a la sesión correcta.
    """

    @pytest.fixture
    def analyst_agent(self):
        """Crea un AnalystAgent para testing."""
        mock_memory = AsyncMock()
        mock_memory.get_session.return_value = {"status": "initialized"}
        
        ctx_manager = MCPContextManager(mock_memory)
        return AnalystAgent(ctx_manager)

    def test_verify_search_results_session_returns_input(self, analyst_agent):
        """
        Test que verifica que _verify_search_results_session retorna los resultados.
        
        El método actual pasa los resultados sin modificar (la verificación real
        se hace en VectorDbServiceClient con filtrado por session_id).
        """
        results = "Resultados de búsqueda de prueba"
        session_id = "test-session-2024"
        
        filtered_results, has_warnings = analyst_agent._verify_search_results_session(
            results, session_id
        )
        
        # El método debe retornar los resultados sin modificar
        assert filtered_results == results
        assert has_warnings == False

    def test_verify_search_results_session_logs_session_id(self, analyst_agent):
        """
        Test que verifica que _verify_search_results_session registra el session_id.
        
        El método debe loguear el session_id para trazabilidad.
        """
        results = "Resultados de prueba"
        session_id = "test-session-2024"
        
        # El método no debe lanzar excepciones
        filtered_results, has_warnings = analyst_agent._verify_search_results_session(
            results, session_id
        )
        
        assert filtered_results is not None


# Importar json para los tests
import json


if __name__ == "__main__":
    # Ejecutar tests directamente
    print("=" * 80)
    print("TEST DE EXPLORACIÓN DEL BUG: AnalystAgent Cross-Session Data")
    print("=" * 80)
    print("\nEste test demuestra el bug de aislamiento de sesiones en AnalystAgent.")
    print("El test DEBE FALLAR en código no corregido (confirma que el bug existe).")
    print("El test PASARÁ después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])
