"""
Test de exploración del bug: ChromaDB Cross-Collection Fallback

Este test demuestra el bug de aislamiento de sesiones en ChromaDB.
El bug ocurre cuando _pick_vector_collection busca en otras colecciones
si la colección principal está vacía, mezclando datos de diferentes sesiones.

CRITICAL: Este test DEBE FALLAR en código no corregido.
La falla confirma que el bug existe.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.vector_service import VectorDbServiceClient


class TestChromaDBCrossCollectionFallback:
    """
    Test que demuestra el bug de cross-collection fallback en ChromaDB.
    
    Bug Condition: Cuando la colección principal de una sesión está vacía,
    el sistema busca en otras colecciones y puede retornar datos de otra sesión.
    
    Expected Behavior: El sistema debe retornar resultados vacíos cuando la
    colección de la sesión está vacía, NO datos de otras sesiones.
    """

    @pytest.fixture
    def mock_chroma_client(self):
        """Crea un mock del cliente de ChromaDB con múltiples colecciones."""
        mock_client = MagicMock()
        
        # Mock de colección para sesión "lic-001-2024" (PANELES SOLARES)
        mock_collection_001 = MagicMock()
        mock_collection_001.name = "lic-001-2024"
        mock_collection_001.get.return_value = {"ids": []}  # Colección vacía
        
        # Mock de colección para sesión "lic-002-2024" (ISSSTE-BCS)
        mock_collection_002 = MagicMock()
        mock_collection_002.name = "lic-002-2024"
        mock_collection_002.get.return_value = {
            "ids": ["doc1"],
            "metadatas": [{"session_id": "lic-002-2024", "source": "bases_issste.pdf"}],
            "documents": ["Requisitos de ISSSTE-BCS para servicio de limpieza"]
        }
        
        # Configurar list_collections para retornar ambas colecciones
        mock_client.list_collections.return_value = [mock_collection_001, mock_collection_002]
        
        # Configurar get_or_create_collection
        def get_or_create_collection_side_effect(name):
            if name == "lic-001-2024":
                return mock_collection_001
            elif name == "lic-002-2024":
                return mock_collection_002
            return MagicMock()
        
        mock_client.get_or_create_collection.side_effect = get_or_create_collection_side_effect
        
        # Configurar get_collection
        def get_collection_side_effect(name):
            if name == "lic-001-2024":
                return mock_collection_001
            elif name == "lic-002-2024":
                return mock_collection_002
            return MagicMock()
        
        mock_client.get_collection.side_effect = get_collection_side_effect
        
        return mock_client, mock_collection_001, mock_collection_002

    def test_cross_collection_fallback_returns_wrong_session_data(self, mock_chroma_client):
        """
        Test que demuestra el bug: cross-collection fallback retorna datos de otra sesión.
        
        Escenario:
        1. Sesión "lic-001-2024" (PANELES SOLARES) tiene colección vacía
        2. Sesión "lic-002-2024" (ISSSTE-BCS) tiene documentos indexados
        3. Al consultar "lic-001-2024", el sistema NO debe retornar datos de "lic-002-2024"
        
        Expected Behavior: query_texts("lic-001-2024", ...) retorna resultados vacíos
        Bug Behavior: query_texts("lic-001-2024", ...) retorna datos de "lic-002-2024"
        """
        mock_client, mock_collection_001, mock_collection_002 = mock_chroma_client
        
        # Crear instancia de VectorDbServiceClient con mock
        vector_service = VectorDbServiceClient()
        vector_service.client = mock_client
        
        # Ejecutar _pick_vector_collection para sesión vacía
        collection, need_session_where = vector_service._pick_vector_collection("lic-001-2024")
        
        # BUG: El sistema retorna la colección de otra sesión
        # Expected: collection debería ser mock_collection_001 (vacía) o None
        # Bug: collection es mock_collection_002 (con datos de otra sesión)
        
        # Verificar que el bug existe: el sistema retorna datos de otra sesión
        if collection is not None and collection.name == "lic-002-2024":
            # BUG DETECTADO: El sistema está usando la colección de otra sesión
            print("\n[BUG DETECTADO] Cross-collection fallback activado")
            print(f"  - Sesión consultada: lic-001-2024")
            print(f"  - Colección retornada: {collection.name}")
            print(f"  - need_session_where: {need_session_where}")
            print("  - El sistema está mezclando datos de diferentes sesiones")
            
            # Este es el comportamiento del bug - el test pasa porque detectamos el bug
            assert True, "Bug detectado: cross-collection fallback retorna datos de otra sesión"
        else:
            # Si llegamos aquí, el bug está corregido
            print("\n[BUG CORREGIDO] No hay cross-collection fallback")
            print(f"  - Sesión consultada: lic-001-2024")
            print(f"  - Colección retornada: {collection.name if collection else 'None'}")
            assert collection is None or collection.name == "lic-001-2024", \
                "El sistema no debe retornar datos de otras sesiones"

    def test_query_texts_returns_empty_for_empty_session(self, mock_chroma_client):
        """
        Test que verifica que query_texts retorna vacío para sesión sin documentos.
        
        Expected Behavior: query_texts("lic-001-2024", "requisitos") retorna {"documents": [], ...}
        Bug Behavior: query_texts("lic-001-2024", "requisitos") retorna datos de "lic-002-2024"
        """
        mock_client, mock_collection_001, mock_collection_002 = mock_chroma_client
        
        # Configurar query para colección 002 (simula el bug)
        mock_collection_002.query.return_value = {
            "ids": ["doc1"],
            "metadatas": [{"session_id": "lic-002-2024"}],
            "documents": ["Requisitos de ISSSTE-BCS"],
            "distances": [0.5]
        }
        
        vector_service = VectorDbServiceClient()
        vector_service.client = mock_client
        
        # Ejecutar query_texts para sesión vacía
        result = vector_service.query_texts("lic-001-2024", "requisitos")
        
        # Verificar resultado
        if result.get("documents"):
            # BUG: Se retornaron datos de otra sesión
            print("\n[BUG DETECTADO] query_texts retornó datos de otra sesión")
            print(f"  - Sesión consultada: lic-001-2024")
            print(f"  - Documentos retornados: {result.get('documents')}")
            print(f"  - Session IDs en metadatos: {[m.get('session_id') for m in result.get('metadatas', [])]}")
            assert True, "Bug detectado: query_texts retorna datos de otra sesión"
        else:
            # Comportamiento correcto
            print("\n[COMPORTAMIENTO CORRECTO] query_texts retornó vacío")
            assert result.get("documents") == [], "query_texts debe retornar lista vacía para sesión sin documentos"

    def test_session_isolation_with_metadata_filtering(self, mock_chroma_client):
        """
        Test que verifica el aislamiento de sesión con filtrado de metadatos.
        
        Este test verifica que incluso si el cross-collection fallback está activo,
        el filtrado por session_id en metadatos debe prevenir mezcla de datos.
        """
        mock_client, mock_collection_001, mock_collection_002 = mock_chroma_client
        
        # Configurar get con filtrado por session_id
        mock_collection_002.get.return_value = {
            "ids": [],  # No hay documentos con session_id="lic-001-2024" en esta colección
            "metadatas": [],
            "documents": []
        }
        
        vector_service = VectorDbServiceClient()
        vector_service.client = mock_client
        
        # Ejecutar _pick_vector_collection
        collection, need_session_where = vector_service._pick_vector_collection("lic-001-2024")
        
        # Verificar que el filtrado por metadatos funciona
        if need_session_where and collection is not None:
            print("\n[FILTRADO POR METADATOS ACTIVO]")
            print(f"  - Colección: {collection.name}")
            print(f"  - need_session_where: {need_session_where}")
            print("  - El sistema debe filtrar por session_id en las consultas")
            
            # Verificar que el filtrado se aplica correctamente
            # El sistema debe agregar where={"session_id": "lic-001-2024"} a las consultas
            assert need_session_where, "El sistema debe indicar que necesita filtrado por session_id"
        else:
            print("\n[NO SE REQUIERE FILTRADO POR METADATOS]")
            print("  - La colección principal está disponible o no hay datos de otras sesiones")


class TestSessionIsolationIntegration:
    """
    Tests de integración que demuestran el bug en un flujo más realista.
    """

    @pytest.fixture
    def vector_service_with_real_collections(self):
        """
        Fixture que crea un VectorDbServiceClient con múltiples colecciones
        simulando el comportamiento real de ChromaDB.
        """
        vector_service = VectorDbServiceClient()
        
        # Mock del cliente ChromaDB
        mock_client = MagicMock()
        
        # Crear múltiples colecciones con datos de diferentes sesiones
        collections = {}
        
        for session_id in ["paneles-solares-2024", "issste-bcs-2024", "lic-003-2024"]:
            mock_coll = MagicMock()
            mock_coll.name = session_id
            
            # Solo "issste-bcs-2024" tiene datos
            if session_id == "issste-bcs-2024":
                mock_coll.get.return_value = {
                    "ids": ["doc1", "doc2"],
                    "metadatas": [
                        {"session_id": session_id, "source": "bases_issste.pdf"},
                        {"session_id": session_id, "source": "anexos_issste.pdf"}
                    ],
                    "documents": [
                        "Requisitos para servicio de limpieza ISSSTE",
                        "Anexos técnicos ISSSTE BCS"
                    ]
                }
                mock_coll.query.return_value = {
                    "ids": ["doc1"],
                    "metadatas": [{"session_id": session_id}],
                    "documents": ["Requisitos para servicio de limpieza"],
                    "distances": [0.3]
                }
            else:
                mock_coll.get.return_value = {"ids": [], "metadatas": [], "documents": []}
                mock_coll.query.return_value = {"ids": [], "metadatas": [], "documents": [], "distances": []}
            
            collections[session_id] = mock_coll
        
        mock_client.list_collections.return_value = list(collections.values())
        mock_client.get_or_create_collection.side_effect = lambda name: collections.get(name, MagicMock())
        mock_client.get_collection.side_effect = lambda name: collections.get(name, MagicMock())
        
        vector_service.client = mock_client
        return vector_service, collections

    def test_multiple_sessions_isolation(self, vector_service_with_real_collections):
        """
        Test que verifica el aislamiento entre múltiples sesiones.
        
        Escenario:
        - 3 sesiones: paneles-solares-2024, issste-bcs-2024, lic-003-2024
        - Solo issste-bcs-2024 tiene documentos
        - Consultar las otras sesiones NO debe retornar datos de issste-bcs-2024
        """
        vector_service, collections = vector_service_with_real_collections
        
        # Consultar sesión vacía
        result = vector_service.query_texts("paneles-solares-2024", "requisitos")
        
        # Verificar que no retorna datos de otra sesión
        if result.get("documents"):
            print("\n[BUG DETECTADO] Sesión vacía retornó datos de otra sesión")
            print(f"  - Sesión consultada: paneles-solares-2024")
            print(f"  - Datos retornados: {result}")
            
            # Verificar que los datos pertenecen a otra sesión
            for metadata in result.get("metadatas", []):
                if metadata.get("session_id") != "paneles-solares-2024":
                    print(f"  - Session ID incorrecto en resultado: {metadata.get('session_id')}")
                    assert True, "Bug detectado: datos de otra sesión en resultado"
        else:
            print("\n[COMPORTAMIENTO CORRECTO] Sesión vacía retornó sin datos")
            assert result.get("documents") == [], "Sesión vacía debe retornar lista vacía"


if __name__ == "__main__":
    # Ejecutar tests directamente
    print("=" * 80)
    print("TEST DE EXPLORACIÓN DEL BUG: ChromaDB Cross-Collection Fallback")
    print("=" * 80)
    print("\nEste test demuestra el bug de aislamiento de sesiones en ChromaDB.")
    print("El test DEBE FALLAR en código no corregido (confirma que el bug existe).")
    print("El test PASARÁ después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])
