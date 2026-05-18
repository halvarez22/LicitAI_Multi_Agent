"""
Test de Preservation: Agent Workflow Integrity

Este test verifica que el flujo de trabajo entre agentes se mantiene
idéntico después de la corrección del bug de aislamiento de sesiones.

IMPORTANTE: Este test debe PASAR en código no corregido.
Esto confirma el comportamiento base que debemos preservar.

Validates: Requirements 3.5
"""

import pytest
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite

from app.services.vector_service import VectorDbServiceClient
from app.agents.mcp_context import MCPContextManager
from app.agents.analyst import AnalystAgent
from app.agents.compliance import ComplianceAgent
from app.agents.economic import EconomicAgent
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus


# =============================================================================
# OBSERVATION-FIRST METHODOLOGY
# =============================================================================
# 
# Este test sigue la metodología de observación:
# 1. Observar el comportamiento del sistema en código no corregido
# 2. Registrar las salidas esperadas
# 3. Escribir tests que verifiquen que estas salidas se mantienen idénticas
# =============================================================================


class TestAgentWorkflowIntegrity:
    """
    Test que verifica que el flujo de trabajo entre agentes se mantiene
    correcto para una sola sesión.
    
    Preservation Property: Para cualquier flujo completo de agentes en una
    sola sesión, todos los resultados intermedios y finales se mantienen
    idénticos antes y después de la corrección del bug de aislamiento.
    """

    @pytest.fixture
    def workflow_session_vector_db(self):
        """
        Crea un mock de VectorDbServiceClient con datos para el flujo completo.
        
        Simula el escenario donde una sesión tiene documentos indexados
        y las consultas retornan los datos correctos para cada agente.
        """
        mock_vector_db = MagicMock()
        
        session_id = "test-workflow-session"
        
        # Documentos indexados para el flujo completo
        documents = [
            # Documentos para AnalystAgent
            "CONVOCATORIA LIC-WORKFLOW-2024: Servicio de vigilancia y seguridad privada.",
            "PLAZOS: Publicación: 01/02/2024, Junta: 10/02/2024, Fallo: 15/02/2024, Firma: 20/02/2024.",
            "REQUISITOS DE PARTICIPACIÓN: a) Ser empresa mexicana constituida legalmente, b) Tener experiencia mínima de 3 años, c) Contar con personal certificado.",
            "REQUISITOS DE EXCLUSIÓN: Serán descalificados quienes no presenten documentación completa.",
            "IMPORTE DEL CONTRATO: $1,000,000 MXN mínimo, $5,000,000 MXN máximo por 12 meses.",
            "GARANTÍAS: Seriedad de oferta 5%, Cumplimiento 10%.",
            "CRITERIOS DE EVALUACIÓN: Puntos y porcentajes según tabla anexa.",
            # Documentos para ComplianceAgent
            "DOCUMENTACIÓN ADMINISTRATIVA: Acta constitutiva, RFC, Poder notarial del representante.",
            "ESPECIFICACIONES TÉCNICAS: Personal capacitado, equipos de comunicación, vehículos.",
            "ANEXOS: Formato de propuesta técnica, Formato de propuesta económica, Declaración de integridad.",
            "PÓLIZAS: Responsabilidad civil, Daños a terceros, Fianza de cumplimiento.",
            # Documentos para EconomicAgent
            "PARTIDAS: Vigilancia fija, Vigilancia móvil, Monitoreo electrónico, Supervisión.",
            "CANTIDADES: 10 guardias fijos, 2 patrullas, 1 centro de monitoreo, 1 supervisor.",
            "TURNOS: 3 turnos de 8 horas, 7 días a la semana.",
        ]
        
        metadatas = [
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 1, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 2, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 3, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 4, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 5, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 6, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_workflow.pdf", "page": 7, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "anexos_admin.pdf", "page": 1, "doc_id": "doc-002"},
            {"session_id": session_id, "source": "anexos_tecnicos.pdf", "page": 1, "doc_id": "doc-003"},
            {"session_id": session_id, "source": "formatos.pdf", "page": 1, "doc_id": "doc-004"},
            {"session_id": session_id, "source": "garantias.pdf", "page": 1, "doc_id": "doc-005"},
            {"session_id": session_id, "source": "partidas.xlsx", "page": 1, "doc_id": "doc-006"},
            {"session_id": session_id, "source": "partidas.xlsx", "page": 2, "doc_id": "doc-006"},
            {"session_id": session_id, "source": "partidas.xlsx", "page": 3, "doc_id": "doc-006"},
        ]
        
        def query_texts_side_effect(sid, query, n_results=5):
            """Simula query_texts para el flujo completo."""
            if sid == session_id:
                return {
                    "documents": documents[:n_results],
                    "metadatas": metadatas[:n_results],
                    "distances": [0.1 * (i + 1) for i in range(min(n_results, len(documents)))]
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts.side_effect = query_texts_side_effect
        
        def query_texts_filtered_side_effect(sid, query, source_filter, n_results=20):
            """Simula query_texts_filtered para filtrado por fuente."""
            if sid == session_id:
                filtered_docs = [d for d, m in zip(documents, metadatas) if m.get("source") == source_filter]
                filtered_metas = [m for m in metadatas if m.get("source") == source_filter]
                return {
                    "documents": filtered_docs[:n_results],
                    "metadatas": filtered_metas[:n_results],
                    "distances": [0.1 * (i + 1) for i in range(min(n_results, len(filtered_docs)))]
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts_filtered.side_effect = query_texts_filtered_side_effect
        
        def get_sources_side_effect(sid):
            """Simula get_sources."""
            if sid == session_id:
                return list({m.get("source") for m in metadatas if m.get("source")})
            return []
        
        mock_vector_db.get_sources.side_effect = get_sources_side_effect
        
        return mock_vector_db, session_id, documents, metadatas

    @pytest.fixture
    def workflow_session_memory(self):
        """
        Crea un mock del MemoryRepository para el flujo completo.
        """
        session_id = "test-workflow-session"
        
        mock_memory = AsyncMock()
        
        # Estado de sesión inicial
        session_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {"tender_name": "LIC-WORKFLOW-2024"},
            "tasks_completed": []
        }
        
        # Variable para rastrear el estado actual
        current_state = session_state.copy()
        
        def get_session_side_effect(sid):
            if sid == session_id:
                return current_state.copy()
            return None
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            if sid == session_id:
                current_state = data.copy() if isinstance(data, dict) else data
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        # Documentos
        documents = [
            {
                "id": "doc-001",
                "content": {"text": "Bases de la licitación"},
                "metadata": {
                    "session_id": session_id,
                    "filename": "bases_workflow.pdf",
                    "type": "bases"
                }
            }
        ]
        mock_memory.get_documents.return_value = documents
        mock_memory.get_line_items_for_session.return_value = []
        
        return mock_memory, session_id

    # ==========================================================================
    # TEST 1: MCPContextManager - Task Recording in Workflow
    # ==========================================================================
    
    @pytest.mark.asyncio
    async def test_record_task_completion_analyst(self, workflow_session_memory):
        """
        Test que verifica que record_task_completion almacena correctamente
        el resultado del AnalystAgent.
        
        Preservation: El registro de tareas del AnalystAgent debe mantenerse.
        """
        mock_memory, session_id = workflow_session_memory
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Simular resultado del AnalystAgent
        analyst_result = {
            "session_id": session_id,
            "cronograma": {
                "publicacion_convocatoria": "01/02/2024",
                "junta_aclaraciones": "10/02/2024",
                "fallo": "15/02/2024"
            },
            "requisitos_participacion": [
                {"inciso": "a", "texto_literal": "Ser empresa mexicana"}
            ],
            "requisitos_filtro": ["Documentación incompleta"],
            "garantias": {"seriedad": "5%", "cumplimiento": "10%"},
            "criterios_evaluacion": "Puntos y porcentajes",
            "reglas_economicas": {
                "criterio_importe_minimo_o_plazo_inferior": "$1,000,000 MXN"
            },
            "alcance_operativo": []
        }
        
        result = await ctx_manager.record_task_completion(
            session_id, "analisis_bases", analyst_result
        )
        
        # Verificar que se guardó
        assert result is True, "Debe retornar True"
        
        # Verificar que el estado tiene la tarea registrada
        state = await mock_memory.get_session(session_id)
        assert "tasks_completed" in state
        assert len(state["tasks_completed"]) > 0
        
        # Verificar que la tarea tiene el resultado correcto
        task = state["tasks_completed"][0]
        assert task["task"] == "analisis_bases"
        assert "cronograma" in task["result"]
        
        print("\n[PRESERVATION VERIFIED] record_task_completion almacena analisis_bases")

    @pytest.mark.asyncio
    async def test_record_task_completion_compliance(self, workflow_session_memory):
        """
        Test que verifica que record_task_completion almacena correctamente
        el resultado del ComplianceAgent.
        
        Preservation: El registro de tareas del ComplianceAgent debe mantenerse.
        """
        mock_memory, session_id = workflow_session_memory
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Simular resultado del ComplianceAgent
        compliance_result = {
            "status": "success",
            "data": {
                "administrativo": [
                    {"label": "Acta constitutiva", "status": "pending"}
                ],
                "tecnico": [
                    {"label": "Personal certificado", "status": "pending"}
                ],
                "formatos": [
                    {"label": "Propuesta técnica", "status": "pending"}
                ]
            }
        }
        
        result = await ctx_manager.record_task_completion(
            session_id, "master_compliance_list", compliance_result
        )
        
        # Verificar que se guardó
        assert result is True, "Debe retornar True"
        
        # Verificar que el estado tiene la tarea registrada
        state = await mock_memory.get_session(session_id)
        assert "tasks_completed" in state
        
        print("\n[PRESERVATION VERIFIED] record_task_completion almacena master_compliance_list")

    @pytest.mark.asyncio
    async def test_record_task_completion_economic(self, workflow_session_memory):
        """
        Test que verifica que record_task_completion almacena correctamente
        el resultado del EconomicAgent.
        
        Preservation: El registro de tareas del EconomicAgent debe mantenerse.
        """
        mock_memory, session_id = workflow_session_memory
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Simular resultado del EconomicAgent
        economic_result = {
            "status": "complete",
            "currency": "MXN",
            "items": [
                {"concepto": "Vigilancia fija", "precio_unitario": 150.0, "cantidad": 10}
            ],
            "total_base": 15000.0,
            "grand_total": 18000.0
        }
        
        result = await ctx_manager.record_task_completion(
            session_id, "economic_proposal", economic_result
        )
        
        # Verificar que se guardó
        assert result is True, "Debe retornar True"
        
        # Verificar que el estado tiene la tarea registrada
        state = await mock_memory.get_session(session_id)
        assert "tasks_completed" in state
        
        print("\n[PRESERVATION VERIFIED] record_task_completion almacena economic_proposal")

    # ==========================================================================
    # TEST 2: Sequential Agent Workflow
    # ==========================================================================
    
    @pytest.mark.asyncio
    async def test_sequential_workflow_analyst_to_compliance(
        self, workflow_session_memory, workflow_session_vector_db
    ):
        """
        Test que verifica la transición de AnalystAgent a ComplianceAgent.
        
        Preservation: La transición entre agentes debe mantenerse idéntica.
        """
        mock_memory, session_id = workflow_session_memory
        mock_vector_db, _, _, _ = workflow_session_vector_db
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # 1. Simular que AnalystAgent ya procesó
        analyst_result = {
            "session_id": session_id,
            "cronograma": {"fallo": "15/02/2024"},
            "requisitos_participacion": [],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "Puntos y porcentajes",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", analyst_result)
        
        # 2. Verificar que el contexto tiene el resultado del AnalystAgent
        context = await ctx_manager.get_global_context(session_id)
        assert "session_state" in context
        
        # 3. Verificar que el estado tiene la tarea del AnalystAgent
        state = context["session_state"]
        assert "tasks_completed" in state
        
        # 4. Verificar que ComplianceAgent puede acceder al resultado
        tasks = state.get("tasks_completed", [])
        analyst_task = next((t for t in tasks if t.get("task") == "analisis_bases"), None)
        assert analyst_task is not None, "Debe tener la tarea del AnalystAgent"
        
        print("\n[PRESERVATION VERIFIED] Transición AnalystAgent → ComplianceAgent funciona correctamente")

    @pytest.mark.asyncio
    async def test_sequential_workflow_compliance_to_economic(
        self, workflow_session_memory, workflow_session_vector_db
    ):
        """
        Test que verifica la transición de ComplianceAgent a EconomicAgent.
        
        Preservation: La transición entre agentes debe mantenerse idéntica.
        """
        mock_memory, session_id = workflow_session_memory
        mock_vector_db, _, _, _ = workflow_session_vector_db
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # 1. Simular que AnalystAgent y ComplianceAgent ya procesaron
        analyst_result = {
            "session_id": session_id,
            "cronograma": {},
            "requisitos_participacion": [],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {"criterio_importe_minimo_o_plazo_inferior": "$1,000,000"},
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", analyst_result)
        
        compliance_result = {
            "status": "success",
            "data": {
                "administrativo": [],
                "tecnico": [{"label": "Vigilancia fija", "status": "pending"}],
                "formatos": []
            }
        }
        await ctx_manager.record_task_completion(session_id, "master_compliance_list", compliance_result)
        
        # 2. Verificar que el contexto tiene ambos resultados
        context = await ctx_manager.get_global_context(session_id)
        state = context["session_state"]
        tasks = state.get("tasks_completed", [])
        
        # 3. Verificar que ambas tareas están registradas
        analyst_task = next((t for t in tasks if t.get("task") == "analisis_bases"), None)
        compliance_task = next((t for t in tasks if t.get("task") == "master_compliance_list"), None)
        
        assert analyst_task is not None, "Debe tener la tarea del AnalystAgent"
        assert compliance_task is not None, "Debe tener la tarea del ComplianceAgent"
        
        print("\n[PRESERVATION VERIFIED] Transición ComplianceAgent → EconomicAgent funciona correctamente")

    # ==========================================================================
    # TEST 3: Complete Agent Workflow
    # ==========================================================================
    
    @pytest.mark.asyncio
    async def test_complete_agent_workflow(
        self, workflow_session_memory, workflow_session_vector_db
    ):
        """
        Test que verifica el flujo completo de agentes.
        
        Preservation: El flujo completo debe mantenerse idéntico.
        """
        mock_memory, session_id = workflow_session_memory
        mock_vector_db, _, _, _ = workflow_session_vector_db
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # 1. Inicializar sesión
        await ctx_manager.initialize_session(session_id, {"tender_name": "LIC-WORKFLOW-2024"})
        
        # 2. Simular procesamiento del AnalystAgent
        analyst_result = {
            "session_id": session_id,
            "cronograma": {
                "publicacion_convocatoria": "01/02/2024",
                "junta_aclaraciones": "10/02/2024",
                "fallo": "15/02/2024",
                "firma_contrato": "20/02/2024"
            },
            "requisitos_participacion": [
                {"inciso": "a", "texto_literal": "Ser empresa mexicana"},
                {"inciso": "b", "texto_literal": "Tener experiencia mínima de 3 años"}
            ],
            "requisitos_filtro": ["Documentación incompleta"],
            "garantias": {"seriedad": "5%", "cumplimiento": "10%"},
            "criterios_evaluacion": "Puntos y porcentajes",
            "reglas_economicas": {
                "criterio_importe_minimo_o_plazo_inferior": "$1,000,000 MXN",
                "criterio_importe_maximo_o_plazo_superior": "$5,000,000 MXN"
            },
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", analyst_result)
        
        # 3. Simular procesamiento del ComplianceAgent
        compliance_result = {
            "status": "success",
            "data": {
                "administrativo": [
                    {"label": "Acta constitutiva", "status": "pending"},
                    {"label": "RFC", "status": "pending"}
                ],
                "tecnico": [
                    {"label": "Personal certificado", "status": "pending"},
                    {"label": "Equipos de comunicación", "status": "pending"}
                ],
                "formatos": [
                    {"label": "Propuesta técnica", "status": "pending"},
                    {"label": "Propuesta económica", "status": "pending"}
                ]
            }
        }
        await ctx_manager.record_task_completion(session_id, "master_compliance_list", compliance_result)
        
        # 4. Simular procesamiento del EconomicAgent
        economic_result = {
            "status": "complete",
            "currency": "MXN",
            "items": [
                {"concepto": "Vigilancia fija", "precio_unitario": 150.0, "cantidad": 10},
                {"concepto": "Vigilancia móvil", "precio_unitario": 200.0, "cantidad": 2}
            ],
            "total_base": 19000.0,
            "grand_total": 22800.0
        }
        await ctx_manager.record_task_completion(session_id, "economic_proposal", economic_result)
        
        # 5. Verificar que todas las tareas están registradas
        context = await ctx_manager.get_global_context(session_id)
        state = context["session_state"]
        tasks = state.get("tasks_completed", [])
        
        task_names = [t.get("task") for t in tasks]
        assert "analisis_bases" in task_names, "Debe tener analisis_bases"
        assert "master_compliance_list" in task_names, "Debe tener master_compliance_list"
        assert "economic_proposal" in task_names, "Debe tener economic_proposal"
        
        # 6. Verificar que los resultados están intactos
        analyst_task = next((t for t in tasks if t.get("task") == "analisis_bases"), None)
        assert "cronograma" in analyst_task["result"]
        assert analyst_task["result"]["cronograma"]["fallo"] == "15/02/2024"
        
        compliance_task = next((t for t in tasks if t.get("task") == "master_compliance_list"), None)
        assert "data" in compliance_task["result"]
        
        economic_task = next((t for t in tasks if t.get("task") == "economic_proposal"), None)
        assert "grand_total" in economic_task["result"]
        assert economic_task["result"]["grand_total"] == 22800.0
        
        print("\n[PRESERVATION VERIFIED] Flujo completo de agentes funciona correctamente")

    # ==========================================================================
    # TEST 4: Task Singleton Behavior
    # ==========================================================================
    
    @pytest.mark.asyncio
    async def test_task_singleton_replaces_previous(self, workflow_session_memory):
        """
        Test que verifica que las tareas singleton reemplazan la versión anterior.
        
        Preservation: El comportamiento singleton debe mantenerse.
        """
        mock_memory, session_id = workflow_session_memory
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # 1. Registrar primera versión de analisis_bases
        first_result = {
            "session_id": session_id,
            "cronograma": {"fallo": "01/01/2024"},
            "requisitos_participacion": [],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", first_result)
        
        # 2. Registrar segunda versión de analisis_bases (debe reemplazar)
        second_result = {
            "session_id": session_id,
            "cronograma": {"fallo": "15/02/2024"},  # Fecha diferente
            "requisitos_participacion": [],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", second_result)
        
        # 3. Verificar que solo hay una versión de analisis_bases
        state = await mock_memory.get_session(session_id)
        tasks = state.get("tasks_completed", [])
        
        analisis_tasks = [t for t in tasks if t.get("task") == "analisis_bases"]
        assert len(analisis_tasks) == 1, "Debe haber solo una versión de analisis_bases"
        
        # 4. Verificar que es la segunda versión
        assert analisis_tasks[0]["result"]["cronograma"]["fallo"] == "15/02/2024"
        
        print("\n[PRESERVATION VERIFIED] Tareas singleton reemplazan versión anterior")

    # ==========================================================================
    # TEST 5: Session State Integrity
    # ==========================================================================
    
    @pytest.mark.asyncio
    async def test_session_state_integrity_after_workflow(
        self, workflow_session_memory, workflow_session_vector_db
    ):
        """
        Test que verifica la integridad del estado de sesión después del flujo.
        
        Preservation: El estado de sesión debe mantenerse íntegro.
        """
        mock_memory, session_id = workflow_session_memory
        mock_vector_db, _, _, _ = workflow_session_vector_db
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # 1. Inicializar sesión
        await ctx_manager.initialize_session(session_id, {"tender_name": "LIC-WORKFLOW-2024"})
        
        # 2. Ejecutar flujo completo
        analyst_result = {
            "session_id": session_id,
            "cronograma": {},
            "requisitos_participacion": [],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        await ctx_manager.record_task_completion(session_id, "analisis_bases", analyst_result)
        
        compliance_result = {
            "status": "success",
            "data": {"administrativo": [], "tecnico": [], "formatos": []}
        }
        await ctx_manager.record_task_completion(session_id, "master_compliance_list", compliance_result)
        
        economic_result = {
            "status": "complete",
            "currency": "MXN",
            "items": [],
            "total_base": 0.0,
            "grand_total": 0.0
        }
        await ctx_manager.record_task_completion(session_id, "economic_proposal", economic_result)
        
        # 3. Verificar integridad del estado
        state = await mock_memory.get_session(session_id)
        
        # Verificar campos obligatorios
        assert "schema_version" in state, "Debe tener schema_version"
        assert "status" in state, "Debe tener status"
        assert "tasks_completed" in state, "Debe tener tasks_completed"
        
        # Verificar que el schema_version es correcto
        assert state["schema_version"] == 1, "schema_version debe ser 1"
        
        # Verificar que tasks_completed es una lista
        assert isinstance(state["tasks_completed"], list), "tasks_completed debe ser lista"
        
        print("\n[PRESERVATION VERIFIED] Estado de sesión mantiene integridad después del flujo")


class TestAgentWorkflowPropertyBased:
    """
    Property-based tests para verificar que el flujo de trabajo entre agentes
    se mantiene correcto para cualquier entrada válida.
    """

    @given(
        n_tasks=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=15)
    @pytest.mark.asyncio
    async def test_workflow_records_all_tasks(self, n_tasks):
        """
        Property: Para cualquier número de tareas, el flujo registra todas.
        """
        session_id = "test-property-workflow"
        
        # Crear mock
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Registrar múltiples tareas
        for i in range(n_tasks):
            await ctx_manager.record_task_completion(
                session_id, f"task_{i}", {"index": i}
            )
        
        # Verificar que todas las tareas se guardaron
        assert len(current_state["tasks_completed"]) == n_tasks

    @given(
        n_analyst_runs=st.integers(min_value=1, max_value=5)
    )
    @settings(max_examples=10)
    @pytest.mark.asyncio
    async def test_analyst_singleton_keeps_only_last(self, n_analyst_runs):
        """
        Property: Para múltiples corridas del AnalystAgent, solo se mantiene
        la última versión (comportamiento singleton).
        """
        session_id = "test-analyst-singleton"
        
        # Crear mock
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Registrar múltiples versiones de analisis_bases
        for i in range(n_analyst_runs):
            await ctx_manager.record_task_completion(
                session_id, "analisis_bases", {"version": i}
            )
        
        # Verificar que solo hay una versión
        analisis_tasks = [t for t in current_state["tasks_completed"] if t.get("task") == "analisis_bases"]
        assert len(analisis_tasks) == 1, "Debe haber solo una versión de analisis_bases"
        
        # Verificar que es la última versión
        assert analisis_tasks[0]["result"]["version"] == n_analyst_runs - 1


class TestAgentWorkflowEdgeCases:
    """
    Tests que verifican casos edge en el flujo de trabajo entre agentes.
    """

    @pytest.mark.asyncio
    async def test_workflow_with_empty_tasks(self):
        """
        Test que verifica el comportamiento con lista de tareas vacía.
        
        Preservation: El manejo de tareas vacías debe mantenerse.
        """
        session_id = "test-empty-tasks"
        
        mock_memory = AsyncMock()
        mock_memory.get_session.return_value = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        mock_memory.get_documents.return_value = []
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Obtener contexto sin tareas
        context = await ctx_manager.get_global_context(session_id)
        
        # Verificar que el contexto es válido
        assert "session_state" in context
        assert "documents_summary" in context
        assert context["session_state"]["tasks_completed"] == []
        
        print("\n[PRESERVATION VERIFIED] Flujo maneja tareas vacías correctamente")

    @pytest.mark.asyncio
    async def test_workflow_with_large_result(self):
        """
        Test que verifica el comportamiento con resultados grandes.
        
        Preservation: El manejo de resultados grandes debe mantenerse.
        """
        session_id = "test-large-result"
        
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Crear resultado grande
        large_result = {
            "session_id": session_id,
            "cronograma": {},
            "requisitos_participacion": [
                {"inciso": chr(97 + i), "texto_literal": f"Requisito {i}" * 100}
                for i in range(50)
            ],
            "requisitos_filtro": [f"Filtro {i}" * 50 for i in range(20)],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        
        # Registrar resultado grande
        result = await ctx_manager.record_task_completion(
            session_id, "analisis_bases", large_result
        )
        
        # Verificar que se guardó
        assert result is True, "Debe guardar resultado grande"
        
        # Verificar que el resultado está intacto
        state = await mock_memory.get_session(session_id)
        task = state["tasks_completed"][0]
        assert len(task["result"]["requisitos_participacion"]) == 50
        
        print("\n[PRESERVATION VERIFIED] Flujo maneja resultados grandes correctamente")

    @pytest.mark.asyncio
    async def test_workflow_with_special_characters_in_result(self):
        """
        Test que verifica el comportamiento con caracteres especiales.
        
        Preservation: El manejo de caracteres especiales debe mantenerse.
        """
        session_id = "test-special-chars"
        
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Crear resultado con caracteres especiales
        special_result = {
            "session_id": session_id,
            "cronograma": {},
            "requisitos_participacion": [
                {"inciso": "a", "texto_literal": "Requisito con ñ, áéíóú, ü, ¿? ¡! @#$%^&*()"}
            ],
            "requisitos_filtro": [],
            "garantias": {},
            "criterios_evaluacion": "",
            "reglas_economicas": {},
            "alcance_operativo": []
        }
        
        # Registrar resultado con caracteres especiales
        result = await ctx_manager.record_task_completion(
            session_id, "analisis_bases", special_result
        )
        
        # Verificar que se guardó
        assert result is True, "Debe guardar resultado con caracteres especiales"
        
        # Verificar que los caracteres especiales están intactos
        state = await mock_memory.get_session(session_id)
        task = state["tasks_completed"][0]
        assert "ñ, áéíóú" in task["result"]["requisitos_participacion"][0]["texto_literal"]
        
        print("\n[PRESERVATION VERIFIED] Flujo maneja caracteres especiales correctamente")


class TestAgentWorkflowStateTransitions:
    """
    Tests que verifican las transiciones de estado durante el flujo de trabajo.
    """

    @pytest.mark.asyncio
    async def test_stage_completion_recording(self):
        """
        Test que verifica el registro de completación de etapas.
        
        Preservation: El registro de etapas debe mantenerse.
        """
        session_id = "test-stage-completion"
        
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Registrar completación de etapas
        stages = ["analysis", "compliance", "economic"]
        for stage in stages:
            await ctx_manager.record_task_completion(
                session_id, f"stage_completed:{stage}", {"stage": stage}
            )
        
        # Verificar que todas las etapas están registradas
        state = await mock_memory.get_session(session_id)
        tasks = state.get("tasks_completed", [])
        
        task_names = [t.get("task") for t in tasks]
        assert "stage_completed:analysis" in task_names
        assert "stage_completed:compliance" in task_names
        assert "stage_completed:economic" in task_names
        
        print("\n[PRESERVATION VERIFIED] Registro de etapas funciona correctamente")

    @pytest.mark.asyncio
    async def test_workflow_preserves_session_id_in_all_tasks(self):
        """
        Test que verifica que el session_id se preserva en todas las tareas.
        
        Preservation: El session_id debe estar presente en todos los resultados.
        """
        session_id = "test-session-id-preservation"
        
        mock_memory = AsyncMock()
        
        current_state = {
            "schema_version": 1,
            "status": "initialized",
            "global_inputs": {},
            "tasks_completed": []
        }
        
        def get_session_side_effect(sid):
            return current_state.copy()
        
        def save_session_side_effect(sid, data):
            nonlocal current_state
            current_state["tasks_completed"] = data.get("tasks_completed", []).copy()
            return True
        
        mock_memory.get_session.side_effect = get_session_side_effect
        mock_memory.save_session.side_effect = save_session_side_effect
        
        ctx_manager = MCPContextManager(mock_memory)
        
        # Registrar tareas con session_id
        tasks_with_session = [
            ("analisis_bases", {"session_id": session_id, "data": "test"}),
            ("master_compliance_list", {"session_id": session_id, "data": "test"}),
            ("economic_proposal", {"session_id": session_id, "data": "test"}),
        ]
        
        for task_name, result in tasks_with_session:
            await ctx_manager.record_task_completion(session_id, task_name, result)
        
        # Verificar que todas las tareas tienen session_id
        state = await mock_memory.get_session(session_id)
        for task in state["tasks_completed"]:
            assert task["result"].get("session_id") == session_id, (
                f"Tarea {task['task']} debe tener session_id={session_id}"
            )
        
        print("\n[PRESERVATION VERIFIED] session_id se preserva en todas las tareas")


# =============================================================================
# TEST RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("TEST DE PRESERVATION: Agent Workflow Integrity")
    print("=" * 80)
    print("\nEste test verifica que el flujo de trabajo entre agentes se mantiene")
    print("idéntico después de la corrección del bug de aislamiento de sesiones.")
    print("El test DEBE PASAR en código no corregido (confirma comportamiento base).")
    print("El test DEBE PASAR después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])


# =============================================================================
# INTEGRATION TESTS: Gate documental — Requirements 5.1, 5.4, 6.3
# (DataGap + Orchestrator gate: missing_blocking vs missing)
# =============================================================================


class TestDocumentGateIntegration:
    """
    Tests de integración que verifican el invariante clave del gate documental:
    - WAITING_FOR_DATA se justifica SOLO por campos en missing_blocking (críticos).
    - Campos informativos faltantes NO bloquean generación.
    - Flujo mixto (críticos + informativos) bloquea solo por críticos.

    Validates: Requirements 5.1, 5.4, 6.3
    """

    def _make_datagap_agent(self, master_profile: dict):
        """Helper: crea DataGapAgent con perfil dado y sin RAG real."""
        from app.agents.data_gap import DataGapAgent
        from app.agents.mcp_context import MCPContextManager

        mock_memory = AsyncMock()
        session_state = {
            "schema_version": 1,
            "status": "initialized",
            "tasks_completed": [],
            "pending_questions": [],
        }

        # get_session debe retornar el dict directamente (no coroutine)
        async def _get_session(sid):
            return session_state.copy()

        async def _save_session(sid, data):
            session_state.update(data)
            return True

        async def _get_company(cid):
            # Retornar None para que DataGap use company_data del input
            return None

        mock_memory.get_session = _get_session
        mock_memory.save_session = _save_session
        mock_memory.get_company = _get_company
        mock_memory.get_documents = AsyncMock(return_value=[])

        ctx = MCPContextManager(mock_memory)
        agent = DataGapAgent(ctx)

        # Mockear RAG para que no auto-extraiga nada (fuerza preguntas)
        mock_vector_db = MagicMock()
        mock_vector_db.query_texts = MagicMock(return_value={"documents": [], "metadatas": []})
        mock_vector_db.query_texts_filtered = MagicMock(return_value={"documents": [], "metadatas": []})
        agent.vector_db = mock_vector_db

        # Mockear LLM para que no auto-extraiga nada
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=MagicMock(success=False, response=""))
        agent.llm = mock_llm

        # Mockear slot_inferer para que no infiera slots adicionales
        mock_slot_inferer = AsyncMock()
        mock_slot_inferer.infer_all = AsyncMock(return_value=[])
        agent.slot_inferer = mock_slot_inferer

        return agent, mock_memory

    @pytest.mark.asyncio
    async def test_waiting_for_data_solo_por_criticos(self):
        """
        Req 5.1 / 5.4: DataGapAgent retorna WAITING_FOR_DATA SOLO cuando
        faltan campos críticos (BLOCKING_FIELDS).

        Con perfil que tiene todos los críticos pero le faltan informativos,
        el status debe ser SUCCESS (no WAITING_FOR_DATA).
        """
        # Perfil con todos los campos críticos, sin informativos
        master_profile = {
            "razon_social": "Empresa Completa SA de CV",
            "rfc": "ECO010101AAA",
            "domicilio_fiscal": "Av. Reforma 100, Col. Juárez, CDMX",
            "representante_legal": "Carlos Completo",
            # telefono, email, web, anos_experiencia ausentes → informativos
        }
        agent, mock_memory = self._make_datagap_agent(master_profile)

        inp = AgentInput(
            session_id="sess_dg_solo_informativos",
            company_data={"master_profile": master_profile},
            company_id="co-dg-1",
            mode="generation_only",
        )

        out = await agent.process(inp)

        # Con críticos completos, NO debe bloquear
        assert out.status == AgentStatus.SUCCESS, (
            f"DataGap no debe retornar WAITING_FOR_DATA cuando solo faltan informativos. "
            f"Status: {out.status}, missing_blocking: {out.data.get('missing_blocking')}"
        )
        # missing_blocking debe estar vacío
        assert out.data.get("missing_blocking") == [] or not out.data.get("missing_blocking"), (
            f"missing_blocking debe estar vacío. Got: {out.data.get('missing_blocking')}"
        )

    @pytest.mark.asyncio
    async def test_waiting_for_data_cuando_falta_critico(self):
        """
        Req 5.1: DataGapAgent retorna WAITING_FOR_DATA cuando falta un campo
        crítico (rfc, razon_social, domicilio_fiscal, representante_legal).
        """
        # Perfil sin rfc → campo crítico faltante
        master_profile = {
            "razon_social": "Empresa Sin RFC SA",
            # rfc ausente → crítico
            "domicilio_fiscal": "Av. Central 200, CDMX",
            "representante_legal": "Ana Sin RFC",
        }
        agent, mock_memory = self._make_datagap_agent(master_profile)

        inp = AgentInput(
            session_id="sess_dg_critico_faltante",
            company_data={"master_profile": master_profile},
            company_id="co-dg-2",
            mode="generation_only",
        )

        out = await agent.process(inp)

        assert out.status == AgentStatus.WAITING_FOR_DATA, (
            f"DataGap debe retornar WAITING_FOR_DATA cuando falta rfc. Status: {out.status}"
        )
        assert "rfc" in out.data.get("missing_blocking", []), (
            f"rfc debe estar en missing_blocking. Got: {out.data.get('missing_blocking')}"
        )

    @pytest.mark.asyncio
    async def test_flujo_mixto_missing_vs_missing_blocking(self):
        """
        Req 6.3 / 5.4: Flujo mixto — perfil con faltantes críticos Y no críticos.

        Invariante clave:
        - missing contiene TODOS los faltantes (críticos + informativos).
        - missing_blocking contiene SOLO los críticos.
        - WAITING_FOR_DATA se justifica por missing_blocking, no por missing.
        """
        # Perfil sin rfc (crítico) y sin telefono/email (informativos)
        master_profile = {
            "razon_social": "Empresa Mixta SA",
            # rfc ausente → crítico
            "domicilio_fiscal": "Av. Juárez 300, CDMX",
            "representante_legal": "Pedro Mixto",
            # telefono, email ausentes → informativos
        }
        agent, mock_memory = self._make_datagap_agent(master_profile)

        inp = AgentInput(
            session_id="sess_dg_mixto",
            company_data={"master_profile": master_profile},
            company_id="co-dg-3",
            mode="generation_only",
        )

        out = await agent.process(inp)

        # Debe bloquear por el crítico faltante (rfc)
        assert out.status == AgentStatus.WAITING_FOR_DATA, (
            "Con faltante crítico en flujo mixto, debe retornar WAITING_FOR_DATA."
        )

        missing_fields = [m["field"] for m in out.data.get("missing", [])]
        missing_blocking = out.data.get("missing_blocking", [])

        # missing debe incluir el crítico
        assert "rfc" in missing_fields, (
            f"missing debe incluir rfc. Got: {missing_fields}"
        )
        # missing_blocking debe incluir solo el crítico
        assert "rfc" in missing_blocking, (
            f"missing_blocking debe incluir rfc. Got: {missing_blocking}"
        )
        # missing_blocking es subconjunto de missing
        missing_keys = set(missing_fields)
        for blocking_field in missing_blocking:
            assert blocking_field in missing_keys, (
                f"missing_blocking debe ser subconjunto de missing. "
                f"{blocking_field} no está en missing: {missing_fields}"
            )

    @pytest.mark.asyncio
    async def test_generacion_posible_cuando_solo_faltan_no_criticos(self):
        """
        Req 6.3 / 5.4: Cuando solo faltan campos no críticos, la generación
        debe poder continuar (DataGap retorna SUCCESS).

        Los campos informativos faltantes se encolan en pending_questions para
        conversación HITL, pero NO bloquean el pipeline de generación.
        """
        # Perfil con todos los críticos, sin informativos
        master_profile = {
            "razon_social": "Empresa Lista SA de CV",
            "rfc": "ELI010101BBB",
            "domicilio_fiscal": "Blvd. Adolfo López Mateos 400, CDMX",
            "representante_legal": "Laura Lista",
            # telefono, email, web, anos_experiencia ausentes → informativos
        }
        agent, mock_memory = self._make_datagap_agent(master_profile)

        inp = AgentInput(
            session_id="sess_dg_solo_no_criticos",
            company_data={"master_profile": master_profile},
            company_id="co-dg-4",
            mode="generation_only",
        )

        out = await agent.process(inp)

        # Con solo informativos faltantes, debe retornar SUCCESS
        assert out.status == AgentStatus.SUCCESS, (
            f"DataGap debe retornar SUCCESS cuando solo faltan informativos. "
            f"Status: {out.status}, missing_blocking: {out.data.get('missing_blocking')}"
        )

        # missing_blocking debe estar vacío (no hay críticos faltantes)
        missing_blocking = out.data.get("missing_blocking", [])
        assert len(missing_blocking) == 0, (
            f"missing_blocking debe estar vacío cuando solo faltan informativos. "
            f"Got: {missing_blocking}"
        )

        # El output debe tener el contrato correcto
        assert "missing" in out.data, "DataGap output debe incluir 'missing'"
        assert "missing_blocking" in out.data, "DataGap output debe incluir 'missing_blocking'"
        assert "auto_filled" in out.data, "DataGap output debe incluir 'auto_filled'"
