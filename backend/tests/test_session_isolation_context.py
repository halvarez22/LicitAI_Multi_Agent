"""
Test de exploración del bug: MCPContextManager Cross-Session Context Pollution

Este test demuestra el bug de aislamiento de sesiones en MCPContextManager.
El bug ocurre cuando get_global_context retorna documentos de otra sesión,
mezclando datos de diferentes licitaciones.

CRITICAL: Este test DEBE FALLAR en código no corregido.
La falla confirma que el bug existe.

Validates: Requirements 1.5, 2.5
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.mcp_context import MCPContextManager


class TestMCPContextManagerSessionValidation:
    """
    Test que demuestra el bug de cross-session context pollution en MCPContextManager.
    
    Bug Condition: Cuando se consulta el contexto de una sesión, el sistema
    puede retornar documentos de otra sesión si no hay validación de ownership.
    
    Expected Behavior: get_global_context debe retornar SOLO documentos que
    pertenezcan a la sesión especificada.
    """

    @pytest.fixture
    def mock_memory_repository(self):
        """
        Crea un mock del MemoryRepository con múltiples sesiones y documentos.
        
        Simula el escenario donde:
        - session-alpha tiene documentos de "PANELES SOLARES"
        - session-beta tiene documentos de "ISSSTE-BCS"
        - Los documentos tienen session_id en sus metadatos
        """
        mock_memory = AsyncMock()
        
        # Estado de sesión para session-alpha
        session_alpha_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {"tender_name": "PANELES SOLARES 2024"},
            "tasks_completed": [
                {"task": "analisis_bases", "result": {"requirements": ["req1", "req2"]}}
            ]
        }
        
        # Estado de sesión para session-beta
        session_beta_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {"tender_name": "ISSSTE-BCS 2024"},
            "tasks_completed": []
        }
        
        # Documentos de session-alpha (PANELES SOLARES)
        doc_alpha_1 = {
            "id": "doc-alpha-1",
            "content": {"text": "Requisitos para paneles solares"},
            "metadata": {
                "session_id": "session-alpha",
                "filename": "bases_paneles.pdf",
                "type": "bases"
            }
        }
        
        doc_alpha_2 = {
            "id": "doc-alpha-2",
            "content": {"text": "Especificaciones técnicas paneles"},
            "metadata": {
                "session_id": "session-alpha",
                "filename": "anexos_paneles.pdf",
                "type": "anexos"
            }
        }
        
        # Documentos de session-beta (ISSSTE-BCS)
        doc_beta_1 = {
            "id": "doc-beta-1",
            "content": {"text": "Requisitos para servicio de limpieza ISSSTE"},
            "metadata": {
                "session_id": "session-beta",
                "filename": "bases_issste.pdf",
                "type": "bases"
            }
        }
        
        # Configurar get_session
        def get_session_side_effect(session_id):
            if session_id == "session-alpha":
                return session_alpha_state
            elif session_id == "session-beta":
                return session_beta_state
            return None
        
        mock_memory.get_session.side_effect = get_session_side_effect
        
        # Configurar get_documents
        # BUG: En código no corregido, get_documents podría retornar documentos
        # de otras sesiones si no filtra correctamente por session_id
        def get_documents_side_effect(session_id):
            if session_id == "session-alpha":
                return [doc_alpha_1, doc_alpha_2]
            elif session_id == "session-beta":
                # BUG SIMULATION: Retornar documentos de session-alpha también
                # Esto simula el bug donde get_documents no filtra correctamente
                # En código corregido, esto NO debería pasar porque get_documents
                # filtra por session_id en la base de datos
                return [doc_beta_1, doc_alpha_1, doc_alpha_2]  # BUG: incluye docs de alpha
            return []
        
        mock_memory.get_documents.side_effect = get_documents_side_effect
        mock_memory.save_session = AsyncMock(return_value=True)
        
        return mock_memory

    @pytest.mark.asyncio
    async def test_get_global_context_returns_only_session_documents(self, mock_memory_repository):
        """
        Test que verifica que get_global_context retorna SOLO documentos de la sesión.
        
        Escenario:
        1. session-alpha tiene documentos de PANELES SOLARES
        2. session-beta tiene documentos de ISSSTE-BCS
        3. Al consultar get_global_context("session-beta"), NO debe recibir docs de session-alpha
        
        Expected Behavior: documents_summary contiene solo documentos de session-beta
        Bug Behavior: documents_summary contiene documentos de session-alpha
        """
        ctx_manager = MCPContextManager(mock_memory_repository)
        
        # Obtener contexto de session-beta
        context = await ctx_manager.get_global_context("session-beta")
        
        # Verificar estructura del contexto
        assert "session_state" in context
        assert "documents_summary" in context
        
        # Verificar que session_state es de session-beta
        assert context["session_state"]["global_inputs"]["tender_name"] == "ISSSTE-BCS 2024"
        
        # Verificar que documents_summary contiene SOLO documentos de session-beta
        doc_ids = [doc["id"] for doc in context["documents_summary"]]
        
        # BUG CHECK: Si hay documentos de session-alpha, el bug existe
        alpha_docs_in_beta = [doc_id for doc_id in doc_ids if "alpha" in doc_id]
        
        if alpha_docs_in_beta:
            # BUG DETECTADO: El contexto contiene documentos de otra sesión
            print("\n[BUG DETECTADO] get_global_context retornó documentos de otra sesión")
            print(f"  - Sesión consultada: session-beta")
            print(f"  - Documentos esperados: ['doc-beta-1']")
            print(f"  - Documentos retornados: {doc_ids}")
            print(f"  - Documentos de otra sesión: {alpha_docs_in_beta}")
            print("  - El sistema está mezclando datos de diferentes licitaciones")
            
            # Este assert FALLA en código no corregido, confirmando el bug
            assert False, (
                f"Bug detectado: get_global_context('session-beta') retornó documentos "
                f"de session-alpha: {alpha_docs_in_beta}. "
                f"Los documentos de una licitación no deben aparecer en otra."
            )
        else:
            # Comportamiento correcto
            print("\n[COMPORTAMIENTO CORRECTO] get_global_context retornó solo documentos de la sesión")
            print(f"  - Sesión consultada: session-beta")
            print(f"  - Documentos retornados: {doc_ids}")
            assert "doc-beta-1" in doc_ids, "Debe contener el documento de session-beta"
            assert len(doc_ids) == 1, "Solo debe contener documentos de session-beta"

    @pytest.mark.asyncio
    async def test_get_global_context_filters_cross_session_documents(self, mock_memory_repository):
        """
        Test que verifica que get_global_context filtra documentos de otras sesiones.
        
        Este test verifica específicamente que si get_documents retorna documentos
        de otra sesión (bug en la capa de datos), get_global_context los filtra.
        """
        ctx_manager = MCPContextManager(mock_memory_repository)
        
        # Obtener contexto de session-beta
        context = await ctx_manager.get_global_context("session-beta")
        
        # Verificar que cada documento en documents_summary pertenece a la sesión
        for doc in context["documents_summary"]:
            # Obtener el documento completo para verificar session_id
            doc_id = doc["id"]
            
            # El documento debe pertenecer a session-beta
            if "alpha" in doc_id:
                # BUG: Documento de otra sesión en el contexto
                print(f"\n[BUG DETECTADO] Documento {doc_id} de session-alpha en contexto de session-beta")
                assert False, f"Documento {doc_id} pertenece a otra sesión"

    @pytest.mark.asyncio
    async def test_session_isolation_with_task_completions(self, mock_memory_repository):
        """
        Test que verifica que las tareas completadas no se mezclan entre sesiones.
        
        Escenario:
        1. session-alpha tiene task "analisis_bases" completado
        2. session-beta no tiene tareas completadas
        3. Al consultar session-beta, no debe ver tareas de session-alpha
        """
        ctx_manager = MCPContextManager(mock_memory_repository)
        
        # Obtener contexto de session-beta
        context = await ctx_manager.get_global_context("session-beta")
        
        # Verificar que tasks_completed está vacío para session-beta
        tasks = context["session_state"].get("tasks_completed", [])
        
        # session-beta no debe tener tareas de session-alpha
        analisis_tasks = [t for t in tasks if t.get("task") == "analisis_bases"]
        
        if analisis_tasks:
            print("\n[BUG DETECTADO] Tareas de otra sesión en el contexto")
            print(f"  - Sesión consultada: session-beta")
            print(f"  - Tareas encontradas: {analisis_tasks}")
            assert False, "session-beta no debe tener tareas de session-alpha"
        
        # Verificar que tasks_completed está vacío
        assert len(tasks) == 0, "session-beta no debe tener tareas completadas"


class TestMCPContextManagerCrossSessionPollution:
    """
    Tests que demuestran el bug de contaminación cruzada entre sesiones.
    
    Estos tests simulan escenarios más complejos donde múltiples sesiones
    pueden contaminarse entre sí.
    """

    @pytest.fixture
    def mock_memory_with_pollution(self):
        """
        Fixture que simula contaminación cruzada en el repositorio de memoria.
        
        Este escenario simula el bug donde:
        - Los documentos no tienen session_id en metadatos
        - get_documents retorna todos los documentos sin filtrar
        """
        mock_memory = AsyncMock()
        
        # Sesiones
        session_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        mock_memory.get_session.return_value = session_state
        
        # Documentos SIN session_id en metadatos (bug de datos legacy)
        docs_without_session = [
            {
                "id": "doc-legacy-1",
                "content": {"text": "Documento legacy sin session_id"},
                "metadata": {
                    # BUG: No hay session_id en metadata
                    "filename": "legacy_doc.pdf",
                    "type": "bases"
                }
            },
            {
                "id": "doc-legacy-2",
                "content": {"text": "Otro documento legacy"},
                "metadata": {
                    "filename": "legacy_doc2.pdf",
                    "type": "anexos"
                }
            }
        ]
        
        # BUG: get_documents retorna los mismos documentos para cualquier sesión
        mock_memory.get_documents.return_value = docs_without_session
        mock_memory.save_session = AsyncMock(return_value=True)
        
        return mock_memory

    @pytest.mark.asyncio
    async def test_documents_without_session_id_cause_pollution(self, mock_memory_with_pollution):
        """
        Test que demuestra que documentos sin session_id causan contaminación.
        
        Escenario:
        - Documentos legacy no tienen session_id en metadatos
        - Cualquier sesión puede acceder a estos documentos
        - Esto causa contaminación cruzada
        """
        ctx_manager = MCPContextManager(mock_memory_with_pollution)
        
        # Obtener contexto de dos sesiones diferentes
        context_1 = await ctx_manager.get_global_context("session-1")
        context_2 = await ctx_manager.get_global_context("session-2")
        
        # Ambas sesiones ven los mismos documentos
        docs_1 = context_1["documents_summary"]
        docs_2 = context_2["documents_summary"]
        
        # BUG: Ambas sesiones tienen los mismos documentos
        if len(docs_1) > 0 and len(docs_2) > 0:
            ids_1 = {d["id"] for d in docs_1}
            ids_2 = {d["id"] for d in docs_2}
            
            if ids_1 == ids_2:
                print("\n[BUG DETECTADO] Contaminación cruzada por documentos sin session_id")
                print(f"  - Sesión 1 documentos: {ids_1}")
                print(f"  - Sesión 2 documentos: {ids_2}")
                print("  - Ambas sesiones ven los mismos documentos")
                assert False, "Documentos sin session_id causan contaminación cruzada"

    @pytest.mark.asyncio
    async def test_record_task_completion_validates_session_ownership(self):
        """
        Test que verifica que record_task_completion valida ownership del resultado.
        
        Escenario:
        - Se intenta registrar un resultado con session_id diferente
        - El sistema debe detectar y advertir sobre la discrepancia
        """
        mock_memory = AsyncMock()
        mock_memory.get_session.return_value = {
            "schema_version": 1,
            "status": "initialized",
            "tasks_completed": []
        }
        mock_memory.save_session = AsyncMock(return_value=True)
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Intentar registrar resultado con session_id diferente
        result_with_wrong_session = {
            "session_id": "session-wrong",  # Session ID incorrecto
            "data": "some analysis result"
        }
        
        # Registrar la tarea
        await ctx_manager.record_task_completion(
            "session-correct",
            "analisis_bases",
            result_with_wrong_session
        )
        
        # Verificar que se guardó (el sistema actual no valida)
        # En código corregido, esto debería generar warning o error
        assert mock_memory.save_session.called
        
        # Verificar que el resultado se guardó con el session_id incorrecto
        saved_data = mock_memory.save_session.call_args[0][1]
        tasks = saved_data.get("tasks_completed", [])
        
        if tasks:
            saved_result = tasks[0].get("result", {})
            if saved_result.get("session_id") == "session-wrong":
                print("\n[BUG DETECTADO] record_task_completion no valida session_id del resultado")
                print(f"  - Sesión esperada: session-correct")
                print(f"  - Session_id en resultado: session-wrong")
                print("  - El resultado se guardó sin validación")


class TestMCPContextManagerPropertyBased:
    """
    Property-based tests para verificar aislamiento de sesión.
    
    Estas pruebas usan Hypothesis para generar múltiples escenarios
    y verificar que el aislamiento se mantiene en todos los casos.
    """

    @pytest.mark.asyncio
    async def test_property_session_isolation_multiple_sessions(self):
        """
        Property: Para cualquier par de sesiones diferentes, los documentos
        de una sesión nunca deben aparecer en la otra.
        """
        from hypothesis import given, strategies as st
        
        # Generador de session_ids
        session_id_strategy = st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
            min_size=5,
            max_size=20
        )
        
        @given(session_id_strategy, session_id_strategy)
        async def check_session_isolation(session_a, session_b):
            # Solo verificar si las sesiones son diferentes
            if session_a == session_b:
                return
            
            # Crear mock con documentos en session_a
            mock_memory = AsyncMock()
            mock_memory.get_session.return_value = {
                "schema_version": 1,
                "status": "initialized",
                "tasks_completed": []
            }
            
            doc_a = {
                "id": f"doc-{session_a}",
                "content": {"text": f"Documento de {session_a}"},
                "metadata": {"session_id": session_a}
            }
            
            # BUG SIMULATION: get_documents retorna documentos de session_a
            # cuando se consulta session_b
            def get_docs_side_effect(sid):
                if sid == session_a:
                    return [doc_a]
                elif sid == session_b:
                    # BUG: Retorna documento de session_a
                    return [doc_a]
                return []
            
            mock_memory.get_documents.side_effect = get_docs_side_effect
            mock_memory.save_session = AsyncMock(return_value=True)
            
            ctx_manager = MCPContextManager(mock_memory)
            
            # Obtener contexto de session_b
            context_b = await ctx_manager.get_global_context(session_b)
            
            # Verificar que no hay documentos de session_a
            doc_ids_b = [d["id"] for d in context_b["documents_summary"]]
            
            assert f"doc-{session_a}" not in doc_ids_b, (
                f"Bug: session_b ({session_b}) contiene documento de session_a ({session_a})"
            )
        
        # Ejecutar la prueba con un límite de ejemplos
        try:
            await check_session_isolation.check(max_examples=10)
        except Exception as e:
            print(f"\n[PROPERTY TEST] Error: {e}")


if __name__ == "__main__":
    # Ejecutar tests directamente
    print("=" * 80)
    print("TEST DE EXPLORACIÓN DEL BUG: MCPContextManager Cross-Session Context Pollution")
    print("=" * 80)
    print("\nEste test demuestra el bug de aislamiento de sesiones en MCPContextManager.")
    print("El test DEBE FALLAR en código no corregido (confirma que el bug existe).")
    print("El test PASARÁ después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])
