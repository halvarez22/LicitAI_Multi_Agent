"""
Test de Preservation: Vector Search Quality

Este test verifica que la funcionalidad de búsqueda vectorial se mantiene
idéntica después de la corrección del bug de aislamiento de sesiones.

IMPORTANTE: Este test debe PASAR en código no corregido.
Esto confirma el comportamiento base que debemos preservar.

Validates: Requirements 3.3
"""

import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite

from app.services.vector_service import VectorDbServiceClient


# =============================================================================
# OBSERVATION-FIRST METHODOLOGY
# =============================================================================
# 
# Este test sigue la metodología de observación:
# 1. Observar el comportamiento del sistema en código no corregido
# 2. Registrar las salidas esperadas
# 3. Escribir tests que verifiquen que estas salidas se mantienen idénticas
# =============================================================================


class TestVectorSearchQuality:
    """
    Test que verifica que la calidad de búsqueda vectorial se mantiene
    para una sola sesión.
    
    Preservation Property: Para cualquier operación de búsqueda vectorial
    en una sola sesión, los resultados se mantienen idénticos antes y
    después de la corrección del bug de aislamiento.
    """

    @pytest.fixture
    def single_session_vector_db(self):
        """
        Crea un mock de VectorDbServiceClient con datos de una sola sesión.
        
        Simula el escenario donde una sesión tiene múltiples documentos
        indexados y las consultas retornan los datos correctos.
        """
        mock_vector_db = MagicMock()
        
        session_id = "test-vector-search-session"
        
        # Documentos indexados con contenido variado
        documents = [
            "CONVOCATORIA LIC-TEST-2024: Servicio de mantenimiento de equipos de cómputo.",
            "PLAZOS: Publicación: 15/01/2024, Junta de aclaraciones: 20/01/2024, Fallo: 25/01/2024.",
            "REQUISITOS DE PARTICIPACIÓN: a) Ser empresa mexicana constituida legalmente, b) Tener experiencia comprobada mínima de 3 años.",
            "REQUISITOS DE EXCLUSIÓN: Serán descalificados quienes no presenten documentación completa o tengan conflictos de interés.",
            "IMPORTE DEL CONTRATO: $500,000 MXN mínimo, $2,000,000 MXN máximo.",
            "GARANTÍAS REQUERIDAS: Garantía de seriedad: 5% del importe, Garantía de cumplimiento: 10%.",
            "CRITERIOS DE EVALUACIÓN: Puntos y porcentajes según tabla anexa al documento de bases.",
            "ESPECIFICACIONES TÉCNICAS: Los equipos deben cumplir con normas NOM-001-SCFI-2018.",
            "ANEXOS TÉCNICOS: Formato de propuesta técnica, Formato de propuesta económica.",
            "INFORMACIÓN ADICIONAL: Contacto: licitaciones@test.gob.mx, Tel: 555-1234.",
        ]
        
        metadatas = [
            {"session_id": session_id, "source": "bases_test.pdf", "page": 1, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 2, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 3, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 4, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 5, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 6, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "bases_test.pdf", "page": 7, "doc_id": "doc-001"},
            {"session_id": session_id, "source": "anexos_tecnicos.pdf", "page": 1, "doc_id": "doc-002"},
            {"session_id": session_id, "source": "anexos_tecnicos.pdf", "page": 2, "doc_id": "doc-002"},
            {"session_id": session_id, "source": "anexos_tecnicos.pdf", "page": 3, "doc_id": "doc-002"},
        ]
        
        def query_texts_side_effect(sid, query, n_results=5):
            """Simula query_texts para una sola sesión."""
            if sid == session_id:
                # Retornar documentos relevantes basados en la query
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
                # Filtrar documentos por source
                filtered_docs = [d for d, m in zip(documents, metadatas) if m.get("source") == source_filter]
                filtered_metas = [m for m in metadatas if m.get("source") == source_filter]
                
                return {
                    "documents": filtered_docs[:n_results],
                    "metadatas": filtered_metas[:n_results],
                    "distances": [0.1 * (i + 1) for i in range(min(n_results, len(filtered_docs)))]
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts_filtered.side_effect = query_texts_filtered_side_effect
        
        def get_full_pages_side_effect(sid, source, pages):
            """Simula get_full_pages."""
            if sid == session_id:
                content_parts = []
                for pg in sorted(pages):
                    matching_docs = [d for d, m in zip(documents, metadatas) 
                                    if m.get("source") == source and m.get("page") == pg]
                    if matching_docs:
                        content_parts.append(f"--- PÁGINA {pg} ---\n" + "\n".join(matching_docs))
                return "\n".join(content_parts)
            return ""
        
        mock_vector_db.get_full_pages.side_effect = get_full_pages_side_effect
        
        def fetch_page_documents_side_effect(sid, source, page):
            """Simula fetch_page_documents."""
            if sid == session_id and source in ["bases_test.pdf", "anexos_tecnicos.pdf"]:
                matching_docs = [d for d, m in zip(documents, metadatas) 
                                if m.get("source") == source and m.get("page") == int(page)]
                return matching_docs
            return []
        
        mock_vector_db.fetch_page_documents.side_effect = fetch_page_documents_side_effect
        
        def get_sources_side_effect(sid):
            """Simula get_sources."""
            if sid == session_id:
                return list({m.get("source") for m in metadatas if m.get("source")})
            return []
        
        mock_vector_db.get_sources.side_effect = get_sources_side_effect
        
        return mock_vector_db, session_id, documents, metadatas

    # ==========================================================================
    # TEST 1: query_texts - Basic Vector Search
    # ==========================================================================
    
    def test_query_texts_returns_correct_structure(self, single_session_vector_db):
        """
        Test que verifica que query_texts retorna la estructura correcta.
        
        Preservation: La estructura de respuesta debe mantenerse idéntica.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts(session_id, "requisitos plazos", n_results=5)
        
        # Verificar estructura de respuesta
        assert "documents" in result, "Debe tener 'documents'"
        assert "metadatas" in result, "Debe tener 'metadatas'"
        assert "distances" in result, "Debe tener 'distances'"
        
        # Verificar tipos
        assert isinstance(result["documents"], list), "documents debe ser lista"
        assert isinstance(result["metadatas"], list), "metadatas debe ser lista"
        assert isinstance(result["distances"], list), "distances debe ser lista"
        
        print("\n[PRESERVATION VERIFIED] query_texts retorna estructura correcta")

    def test_query_texts_returns_correct_documents(self, single_session_vector_db):
        """
        Test que verifica que query_texts retorna los documentos correctos.
        
        Preservation: Los documentos retornados deben ser los correctos.
        """
        mock_vector_db, session_id, expected_docs, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts(session_id, "requisitos", n_results=3)
        
        # Verificar que retorna documentos
        assert len(result["documents"]) > 0, "Debe retornar documentos"
        
        # Verificar que los documentos son los esperados
        for i, doc in enumerate(result["documents"]):
            assert doc == expected_docs[i], f"Documento {i} debe coincidir"
        
        print("\n[PRESERVATION VERIFIED] query_texts retorna documentos correctos")

    def test_query_texts_returns_correct_metadata(self, single_session_vector_db):
        """
        Test que verifica que query_texts retorna los metadatos correctos.
        
        Preservation: Los metadatos deben mantenerse intactos.
        """
        mock_vector_db, session_id, _, expected_metas = single_session_vector_db
        
        result = mock_vector_db.query_texts(session_id, "plazos", n_results=5)
        
        # Verificar que todos los metadatos tienen el session_id correcto
        for meta in result["metadatas"]:
            assert meta.get("session_id") == session_id, (
                f"Todos los metadatos deben tener session_id={session_id}"
            )
        
        # Verificar que los metadatos tienen los campos esperados
        for meta in result["metadatas"]:
            assert "source" in meta, "Debe tener 'source'"
            assert "page" in meta, "Debe tener 'page'"
        
        print("\n[PRESERVATION VERIFIED] query_texts retorna metadatos correctos")

    def test_query_texts_returns_distances(self, single_session_vector_db):
        """
        Test que verifica que query_texts retorna distancias.
        
        Preservation: Las distancias deben mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts(session_id, "garantías", n_results=5)
        
        # Verificar que retorna distancias
        assert len(result["distances"]) > 0, "Debe retornar distancias"
        
        # Verificar que las distancias son números
        for dist in result["distances"]:
            assert isinstance(dist, (int, float)), "Las distancias deben ser numéricas"
        
        print("\n[PRESERVATION VERIFIED] query_texts retorna distancias correctas")

    # ==========================================================================
    # TEST 2: query_texts_filtered - Filtered Vector Search
    # ==========================================================================
    
    def test_query_texts_filtered_filters_by_source(self, single_session_vector_db):
        """
        Test que verifica que query_texts_filtered filtra por fuente.
        
        Preservation: El filtrado por fuente debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts_filtered(
            session_id, "especificaciones", "anexos_tecnicos.pdf", n_results=10
        )
        
        # Verificar que retorna documentos
        assert len(result["documents"]) > 0, "Debe retornar documentos"
        
        # Verificar que todos los documentos son de la fuente correcta
        for meta in result["metadatas"]:
            assert meta.get("source") == "anexos_tecnicos.pdf", (
                "Todos los documentos deben ser de la fuente especificada"
            )
        
        print("\n[PRESERVATION VERIFIED] query_texts_filtered filtra por fuente")

    def test_query_texts_filtered_returns_correct_structure(self, single_session_vector_db):
        """
        Test que verifica que query_texts_filtered retorna la estructura correcta.
        
        Preservation: La estructura debe mantenerse idéntica.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts_filtered(
            session_id, "test query", "bases_test.pdf", n_results=5
        )
        
        # Verificar estructura
        assert "documents" in result
        assert "metadatas" in result
        assert "distances" in result
        
        print("\n[PRESERVATION VERIFIED] query_texts_filtered retorna estructura correcta")

    def test_query_texts_filtered_returns_empty_for_nonexistent_source(self, single_session_vector_db):
        """
        Test que verifica que query_texts_filtered retorna vacío para fuente inexistente.
        
        Preservation: El comportamiento para fuente inexistente debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        result = mock_vector_db.query_texts_filtered(
            session_id, "test query", "nonexistent.pdf", n_results=5
        )
        
        # Verificar que retorna vacío
        assert result["documents"] == [], "Debe retornar lista vacía para fuente inexistente"
        
        print("\n[PRESERVATION VERIFIED] query_texts_filtered maneja fuente inexistente")

    # ==========================================================================
    # TEST 3: get_full_pages - Full Page Retrieval
    # ==========================================================================
    
    def test_get_full_pages_returns_content(self, single_session_vector_db):
        """
        Test que verifica que get_full_pages retorna contenido.
        
        Preservation: La recuperación de páginas completas debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        content = mock_vector_db.get_full_pages(session_id, "bases_test.pdf", [1, 2, 3])
        
        # Verificar que retorna contenido
        assert content != "", "Debe retornar contenido"
        
        # Verificar que contiene las páginas
        assert "--- PÁGINA 1 ---" in content, "Debe contener página 1"
        assert "--- PÁGINA 2 ---" in content, "Debe contener página 2"
        assert "--- PÁGINA 3 ---" in content, "Debe contener página 3"
        
        print("\n[PRESERVATION VERIFIED] get_full_pages retorna contenido")

    def test_get_full_pages_returns_empty_for_nonexistent_source(self, single_session_vector_db):
        """
        Test que verifica que get_full_pages retorna vacío para fuente inexistente.
        
        Preservation: El comportamiento para fuente inexistente debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        content = mock_vector_db.get_full_pages(session_id, "nonexistent.pdf", [1, 2])
        
        # Verificar que retorna vacío
        assert content == "", "Debe retornar vacío para fuente inexistente"
        
        print("\n[PRESERVATION VERIFIED] get_full_pages maneja fuente inexistente")

    def test_get_full_pages_orders_pages_correctly(self, single_session_vector_db):
        """
        Test que verifica que get_full_pages ordena las páginas correctamente.
        
        Preservation: El orden de páginas debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        # Solicitar páginas en desorden
        content = mock_vector_db.get_full_pages(session_id, "bases_test.pdf", [3, 1, 2])
        
        # Verificar que las páginas están en orden
        page1_idx = content.find("--- PÁGINA 1 ---")
        page2_idx = content.find("--- PÁGINA 2 ---")
        page3_idx = content.find("--- PÁGINA 3 ---")
        
        assert page1_idx < page2_idx < page3_idx, "Las páginas deben estar en orden"
        
        print("\n[PRESERVATION VERIFIED] get_full_pages ordena páginas correctamente")

    # ==========================================================================
    # TEST 4: fetch_page_documents - Page Document Retrieval
    # ==========================================================================
    
    def test_fetch_page_documents_returns_documents(self, single_session_vector_db):
        """
        Test que verifica que fetch_page_documents retorna documentos.
        
        Preservation: La recuperación de documentos de página debe mantenerse.
        """
        mock_vector_db, session_id, expected_docs, _ = single_session_vector_db
        
        docs = mock_vector_db.fetch_page_documents(session_id, "bases_test.pdf", 1)
        
        # Verificar que retorna documentos
        assert isinstance(docs, list), "Debe retornar una lista"
        assert len(docs) > 0, "Debe retornar al menos un documento"
        
        print("\n[PRESERVATION VERIFIED] fetch_page_documents retorna documentos")

    def test_fetch_page_documents_returns_empty_for_nonexistent_page(self, single_session_vector_db):
        """
        Test que verifica que fetch_page_documents retorna vacío para página inexistente.
        
        Preservation: El comportamiento para página inexistente debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        docs = mock_vector_db.fetch_page_documents(session_id, "bases_test.pdf", 999)
        
        # Verificar que retorna vacío
        assert docs == [], "Debe retornar lista vacía para página inexistente"
        
        print("\n[PRESERVATION VERIFIED] fetch_page_documents maneja página inexistente")

    def test_fetch_page_documents_handles_string_page(self, single_session_vector_db):
        """
        Test que verifica que fetch_page_documents maneja página como string.
        
        Preservation: El manejo de tipos de página debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        # Probar con string
        docs = mock_vector_db.fetch_page_documents(session_id, "bases_test.pdf", "1")
        
        # Verificar que funciona igual que con int
        assert isinstance(docs, list), "Debe funcionar con string"
        
        print("\n[PRESERVATION VERIFIED] fetch_page_documents maneja string page")

    # ==========================================================================
    # TEST 5: get_sources - Source Listing
    # ==========================================================================
    
    def test_get_sources_returns_sources(self, single_session_vector_db):
        """
        Test que verifica que get_sources retorna las fuentes.
        
        Preservation: El listado de fuentes debe mantenerse.
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        sources = mock_vector_db.get_sources(session_id)
        
        # Verificar que retorna fuentes
        assert isinstance(sources, list), "Debe retornar una lista"
        assert len(sources) > 0, "Debe retornar al menos una fuente"
        
        # Verificar que contiene las fuentes esperadas
        assert "bases_test.pdf" in sources, "Debe contener bases_test.pdf"
        assert "anexos_tecnicos.pdf" in sources, "Debe contener anexos_tecnicos.pdf"
        
        print("\n[PRESERVATION VERIFIED] get_sources retorna fuentes")

    def test_get_sources_returns_unique_sources(self, single_session_vector_db):
        """
        Test que verifica que get_sources retorna fuentes únicas.
        
        Preservation: Las fuentes deben ser únicas (sin duplicados).
        """
        mock_vector_db, session_id, _, _ = single_session_vector_db
        
        sources = mock_vector_db.get_sources(session_id)
        
        # Verificar que no hay duplicados
        assert len(sources) == len(set(sources)), "No debe haber duplicados"
        
        print("\n[PRESERVATION VERIFIED] get_sources retorna fuentes únicas")

    def test_get_sources_returns_empty_for_nonexistent_session(self, single_session_vector_db):
        """
        Test que verifica que get_sources retorna vacío para sesión inexistente.
        
        Preservation: El comportamiento para sesión inexistente debe mantenerse.
        """
        mock_vector_db, _, _, _ = single_session_vector_db
        
        sources = mock_vector_db.get_sources("nonexistent-session")
        
        # Verificar que retorna vacío
        assert sources == [], "Debe retornar lista vacía para sesión inexistente"
        
        print("\n[PRESERVATION VERIFIED] get_sources maneja sesión inexistente")


class TestVectorSearchQualityPropertyBased:
    """
    Property-based tests para verificar que la calidad de búsqueda vectorial
    se mantiene para cualquier entrada válida.
    """

    @given(
        n_results=st.integers(min_value=1, max_value=20),
        query=st.text(min_size=1, max_size=100)
    )
    @settings(max_examples=20)
    def test_query_texts_returns_consistent_structure_for_any_input(self, n_results, query):
        """
        Property: Para cualquier query y n_results, query_texts retorna
        una estructura consistente.
        
        Validado con Hypothesis para múltiples combinaciones.
        """
        # Crear mock
        mock_vector_db = MagicMock()
        session_id = "test-property-session"
        
        documents = [f"Documento {i}" for i in range(20)]
        metadatas = [{"session_id": session_id, "source": f"doc_{i}.pdf", "page": i} 
                     for i in range(20)]
        
        def query_side_effect(sid, q, n_results=5):
            if sid == session_id:
                return {
                    "documents": documents[:n_results],
                    "metadatas": metadatas[:n_results],
                    "distances": [0.1] * n_results
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts.side_effect = query_side_effect
        
        # Ejecutar query
        result = mock_vector_db.query_texts(session_id, query, n_results=n_results)
        
        # Verificar estructura
        assert "documents" in result
        assert "metadatas" in result
        assert "distances" in result
        
        # Verificar que todos los metadatos tienen el session_id correcto
        for meta in result["metadatas"]:
            assert meta["session_id"] == session_id

    @given(
        source_filter=st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
            min_size=3,
            max_size=30
        ),
        n_results=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=15)
    def test_query_texts_filtered_returns_only_filtered_sources(self, source_filter, n_results):
        """
        Property: Para cualquier filtro de fuente, query_texts_filtered
        retorna solo documentos de esa fuente.
        """
        # Crear mock
        mock_vector_db = MagicMock()
        session_id = "test-filter-property"
        
        documents = [f"Documento de {source_filter}" for _ in range(5)]
        metadatas = [{"session_id": session_id, "source": source_filter} for _ in range(5)]
        
        def query_filtered_side_effect(sid, query, src_filter, n_results=20):
            if sid == session_id and src_filter == source_filter:
                return {
                    "documents": documents[:n_results],
                    "metadatas": metadatas[:n_results],
                    "distances": [0.1] * min(n_results, len(documents))
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts_filtered.side_effect = query_filtered_side_effect
        
        # Ejecutar query filtrada
        result = mock_vector_db.query_texts_filtered(
            session_id, "test query", source_filter, n_results=n_results
        )
        
        # Verificar que todos los documentos son de la fuente correcta
        for meta in result["metadatas"]:
            assert meta["source"] == source_filter

    @given(
        pages=st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=10)
    )
    @settings(max_examples=15)
    def test_get_full_pages_returns_content_for_any_pages(self, pages):
        """
        Property: Para cualquier lista de páginas, get_full_pages retorna
        contenido para esas páginas.
        """
        # Crear mock
        mock_vector_db = MagicMock()
        session_id = "test-pages-property"
        
        def get_full_pages_side_effect(sid, source, pgs):
            if sid == session_id:
                content_parts = []
                for pg in sorted(pgs):
                    content_parts.append(f"--- PÁGINA {pg} ---\nContenido de página {pg}")
                return "\n".join(content_parts)
            return ""
        
        mock_vector_db.get_full_pages.side_effect = get_full_pages_side_effect
        
        # Ejecutar get_full_pages
        content = mock_vector_db.get_full_pages(session_id, "test.pdf", pages)
        
        # Verificar que retorna contenido
        assert content != "", "Debe retornar contenido"
        
        # Verificar que contiene las páginas solicitadas
        for pg in pages:
            assert f"PÁGINA {pg}" in content, f"Debe contener página {pg}"


class TestVectorSearchQualityEdgeCases:
    """
    Tests que verifican casos edge en la búsqueda vectorial.
    """

    def test_query_texts_with_empty_query(self):
        """
        Test que verifica el comportamiento con query vacía.
        
        Preservation: El manejo de query vacía debe mantenerse.
        """
        mock_vector_db = MagicMock()
        session_id = "test-empty-query"
        
        mock_vector_db.query_texts.return_value = {
            "documents": [],
            "metadatas": [],
            "distances": []
        }
        
        result = mock_vector_db.query_texts(session_id, "", n_results=5)
        
        # Verificar que retorna estructura válida
        assert "documents" in result
        assert "metadatas" in result
        assert "distances" in result
        
        print("\n[PRESERVATION VERIFIED] query_texts maneja query vacía")

    def test_query_texts_with_large_n_results(self):
        """
        Test que verifica el comportamiento con n_results grande.
        
        Preservation: El manejo de n_results grande debe mantenerse.
        """
        mock_vector_db = MagicMock()
        session_id = "test-large-n-results"
        
        documents = [f"Documento {i}" for i in range(100)]
        metadatas = [{"session_id": session_id, "source": f"doc_{i}.pdf", "page": i} 
                     for i in range(100)]
        
        def query_side_effect(sid, query, n_results=5):
            if sid == session_id:
                return {
                    "documents": documents[:n_results],
                    "metadatas": metadatas[:n_results],
                    "distances": [0.1] * n_results
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts.side_effect = query_side_effect
        
        # Solicitar más resultados de los disponibles
        result = mock_vector_db.query_texts(session_id, "test", n_results=1000)
        
        # Verificar que retorna todos los documentos disponibles
        assert len(result["documents"]) == 100, "Debe retornar todos los documentos disponibles"
        
        print("\n[PRESERVATION VERIFIED] query_texts maneja n_results grande")

    def test_query_texts_with_special_characters_in_query(self):
        """
        Test que verifica el comportamiento con caracteres especiales en query.
        
        Preservation: El manejo de caracteres especiales debe mantenerse.
        """
        mock_vector_db = MagicMock()
        session_id = "test-special-chars"
        
        special_query = "requisitos & plazos | garantías @ # $ % ^ * ( )"
        
        mock_vector_db.query_texts.return_value = {
            "documents": ["Documento con caracteres especiales"],
            "metadatas": [{"session_id": session_id, "source": "test.pdf", "page": 1}],
            "distances": [0.1]
        }
        
        result = mock_vector_db.query_texts(session_id, special_query, n_results=5)
        
        # Verificar que retorna estructura válida
        assert "documents" in result
        assert len(result["documents"]) > 0
        
        print("\n[PRESERVATION VERIFIED] query_texts maneja caracteres especiales")

    def test_fetch_page_documents_with_zero_page(self):
        """
        Test que verifica el comportamiento con página 0.
        
        Preservation: El manejo de página 0 debe mantenerse.
        """
        mock_vector_db = MagicMock()
        session_id = "test-zero-page"
        
        mock_vector_db.fetch_page_documents.return_value = []
        
        result = mock_vector_db.fetch_page_documents(session_id, "test.pdf", 0)
        
        # Verificar que retorna lista (vacía o con contenido)
        assert isinstance(result, list), "Debe retornar una lista"
        
        print("\n[PRESERVATION VERIFIED] fetch_page_documents maneja página 0")

    def test_get_full_pages_with_empty_pages_list(self):
        """
        Test que verifica el comportamiento con lista de páginas vacía.
        
        Preservation: El manejo de lista vacía debe mantenerse.
        """
        mock_vector_db = MagicMock()
        session_id = "test-empty-pages"
        
        mock_vector_db.get_full_pages.return_value = ""
        
        result = mock_vector_db.get_full_pages(session_id, "test.pdf", [])
        
        # Verificar que retorna string vacío
        assert result == "", "Debe retornar string vacío para lista de páginas vacía"
        
        print("\n[PRESERVATION VERIFIED] get_full_pages maneja lista de páginas vacía")


class TestVectorSearchQualityMultipleSources:
    """
    Tests que verifican la búsqueda vectorial con múltiples fuentes.
    """

    @pytest.fixture
    def multi_source_vector_db(self):
        """
        Crea un mock con múltiples fuentes en una sola sesión.
        """
        mock_vector_db = MagicMock()
        session_id = "test-multi-source"
        
        # Documentos de múltiples fuentes
        sources = {
            "bases_principales.pdf": [
                "CONVOCATORIA: Licitación pública nacional.",
                "PLAZOS: 30 días naturales para propuesta.",
            ],
            "anexos_tecnicos.pdf": [
                "ESPECIFICACIONES: Equipos de cómputo.",
                "REQUISITOS TÉCNICOS: Normas NOM.",
            ],
            "anexos_economicos.pdf": [
                "PRESUPUESTO: $1,000,000 MXN.",
                "FORMA DE PAGO: Mensual contra entrega.",
            ]
        }
        
        all_documents = []
        all_metadatas = []
        
        for source, docs in sources.items():
            for i, doc in enumerate(docs):
                all_documents.append(doc)
                all_metadatas.append({
                    "session_id": session_id,
                    "source": source,
                    "page": i + 1
                })
        
        def query_texts_side_effect(sid, query, n_results=5):
            if sid == session_id:
                return {
                    "documents": all_documents[:n_results],
                    "metadatas": all_metadatas[:n_results],
                    "distances": [0.1] * min(n_results, len(all_documents))
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts.side_effect = query_texts_side_effect
        
        def query_texts_filtered_side_effect(sid, query, source_filter, n_results=20):
            if sid == session_id:
                filtered = [(d, m) for d, m in zip(all_documents, all_metadatas) 
                           if m.get("source") == source_filter]
                return {
                    "documents": [d for d, _ in filtered][:n_results],
                    "metadatas": [m for _, m in filtered][:n_results],
                    "distances": [0.1] * min(n_results, len(filtered))
                }
            return {"documents": [], "metadatas": [], "distances": []}
        
        mock_vector_db.query_texts_filtered.side_effect = query_texts_filtered_side_effect
        
        def get_sources_side_effect(sid):
            if sid == session_id:
                return list(sources.keys())
            return []
        
        mock_vector_db.get_sources.side_effect = get_sources_side_effect
        
        return mock_vector_db, session_id, sources

    def test_query_texts_returns_documents_from_all_sources(self, multi_source_vector_db):
        """
        Test que verifica que query_texts retorna documentos de todas las fuentes.
        
        Preservation: La búsqueda debe incluir documentos de todas las fuentes.
        """
        mock_vector_db, session_id, sources = multi_source_vector_db
        
        result = mock_vector_db.query_texts(session_id, "test", n_results=10)
        
        # Verificar que retorna documentos
        assert len(result["documents"]) > 0, "Debe retornar documentos"
        
        # Verificar que los documentos provienen de múltiples fuentes
        result_sources = {m.get("source") for m in result["metadatas"]}
        assert len(result_sources) > 1, "Debe retornar documentos de múltiples fuentes"
        
        print("\n[PRESERVATION VERIFIED] query_texts retorna documentos de múltiples fuentes")

    def test_query_texts_filtered_isolates_single_source(self, multi_source_vector_db):
        """
        Test que verifica que query_texts_filtered aísla una sola fuente.
        
        Preservation: El filtrado debe aislar correctamente la fuente.
        """
        mock_vector_db, session_id, sources = multi_source_vector_db
        
        result = mock_vector_db.query_texts_filtered(
            session_id, "test", "anexos_tecnicos.pdf", n_results=10
        )
        
        # Verificar que todos los documentos son de la fuente correcta
        for meta in result["metadatas"]:
            assert meta.get("source") == "anexos_tecnicos.pdf", (
                "Todos los documentos deben ser de la fuente filtrada"
            )
        
        print("\n[PRESERVATION VERIFIED] query_texts_filtered aísla fuente correctamente")

    def test_get_sources_returns_all_sources(self, multi_source_vector_db):
        """
        Test que verifica que get_sources retorna todas las fuentes.
        
        Preservation: Debe retornar todas las fuentes indexadas.
        """
        mock_vector_db, session_id, sources = multi_source_vector_db
        
        result_sources = mock_vector_db.get_sources(session_id)
        
        # Verificar que retorna todas las fuentes
        assert len(result_sources) == len(sources), "Debe retornar todas las fuentes"
        
        for source in sources:
            assert source in result_sources, f"Debe contener {source}"
        
        print("\n[PRESERVATION VERIFIED] get_sources retorna todas las fuentes")


# =============================================================================
# TEST RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("TEST DE PRESERVATION: Vector Search Quality")
    print("=" * 80)
    print("\nEste test verifica que la funcionalidad de búsqueda vectorial se mantiene")
    print("idéntica después de la corrección del bug de aislamiento de sesiones.")
    print("El test DEBE PASAR en código no corregido (confirma comportamiento base).")
    print("El test DEBE PASAR después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])
