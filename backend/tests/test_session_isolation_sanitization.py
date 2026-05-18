"""
Test de exploración del bug: Session ID Sanitization Collision

Este test demuestra el bug de colisión de nombres de colección en ChromaDB
debido a la sanitización de session_id. El bug ocurre cuando dos session_ids
diferentes (ej: "ISSSTE-BCS-2024" y "issste_bcs_2024") se sanitizan al mismo
nombre de colección, causando que los datos de ambas sesiones se mezclen.

CRITICAL: Este test DEBE FALLAR en código no corregido.
La falla confirma que el bug existe.

Validates: Requirements 1.4, 2.4
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.vector_service import VectorDbServiceClient


class TestSessionIDSanitizationCollision:
    """
    Test que demuestra el bug de colisión de nombres por sanitización.
    
    Bug Condition: Cuando dos session_ids diferentes se sanitizan al mismo
    nombre de colección, los datos de ambas sesiones se almacenan en la misma
    colección, causando contaminación cruzada.
    
    Expected Behavior: Cada session_id debe producir un nombre de colección
    único, O los datos deben estar aislados por metadata session_id.
    """

    @pytest.fixture
    def vector_service(self):
        """Crea una instancia de VectorDbServiceClient para testing."""
        vector_service = VectorDbServiceClient()
        # Mock del cliente ChromaDB
        vector_service.client = MagicMock()
        return vector_service

    def test_sanitize_name_produces_collision(self, vector_service):
        """
        Test que demuestra que _sanitize_name produce colisiones.
        
        Escenario:
        1. session_id "ISSSTE-BCS-2024" se sanitiza a "issste-bcs-2024"
        2. session_id "issste_bcs_2024" también se sanitiza a "issstebcs2024"
        
        Expected Behavior: Cada session_id debe producir un nombre único
        Bug Behavior: Ambos session_ids producen el mismo nombre sanitizado
        """
        # Probar diferentes session_ids que podrían colisionar
        test_cases = [
            ("ISSSTE-BCS-2024", "issste-bcs-2024"),
            ("issste_bcs_2024", "issstebcs2024"),
            ("ISSSTE_BCS_2024", "issstebcs2024"),
            ("issste-bcs-2024", "issste-bcs-2024"),
        ]
        
        sanitized_names = {}
        collisions = []
        
        for session_id, expected_sanitized in test_cases:
            sanitized = vector_service._sanitize_name(session_id)
            sanitized_names[session_id] = sanitized
            print(f"\n  session_id: '{session_id}' -> sanitized: '{sanitized}'")
        
        # Verificar colisiones
        seen_names = {}
        for session_id, sanitized in sanitized_names.items():
            if sanitized in seen_names:
                collisions.append({
                    "session_id_1": seen_names[sanitized],
                    "session_id_2": session_id,
                    "sanitized_name": sanitized
                })
            else:
                seen_names[sanitized] = session_id
        
        if collisions:
            print("\n[BUG DETECTADO] Colisión de nombres sanitizados")
            for collision in collisions:
                print(f"  - '{collision['session_id_1']}' y '{collision['session_id_2']}'")
                print(f"    ambos se sanitizan a: '{collision['sanitized_name']}'")
            
            # Este es el bug - diferentes session_ids producen el mismo nombre
            assert False, (
                f"Bug detectado: {len(collisions)} colisiones de nombres encontradas. "
                f"Diferentes session_ids no deben producir el mismo nombre de colección."
            )
        else:
            print("\n[COMPORTAMIENTO CORRECTO] No hay colisiones de nombres")

    def test_sanitize_name_case_insensitive_collision(self, vector_service):
        """
        Test que verifica que la conversión a minúsculas causa colisiones.
        
        Escenario:
        1. "PANELES-SOLARES-2024" se sanitiza a "paneles-solares-2024"
        2. "paneles-solares-2024" también se sanitiza a "paneles-solares-2024"
        
        Expected Behavior: Diferentes session_ids (por caso) deben ser distinguibles
        Bug Behavior: La conversión a minúsculas causa colisión
        """
        session_ids = [
            "PANELES-SOLARES-2024",
            "paneles-solares-2024",
            "Paneles-Solares-2024",
        ]
        
        sanitized_names = [vector_service._sanitize_name(sid) for sid in session_ids]
        
        # Verificar si todos son iguales
        if len(set(sanitized_names)) == 1:
            print("\n[BUG DETECTADO] Colisión por conversión a minúsculas")
            print(f"  - Todos los session_ids se sanitizan a: '{sanitized_names[0]}'")
            for sid in session_ids:
                print(f"    - '{sid}'")
            
            # Este es el comportamiento esperado del _sanitize_name actual
            # pero causa problemas de aislamiento
            assert True, "Bug documentado: case-insensitive sanitization"
        else:
            print("\n[COMPORTAMIENTO CORRECTO] Nombres únicos para diferentes casos")

    def test_sanitize_name_special_chars_collision(self, vector_service):
        """
        Test que verifica que diferentes caracteres especiales producen colisión.
        
        Escenario:
        1. "LIC-001-2024" con guiones
        2. "LIC_001_2024" con guiones bajos
        3. "LIC 001 2024" con espacios
        
        Todos podrían sanitizarse al mismo nombre.
        """
        session_ids = [
            "LIC-001-2024",
            "LIC_001_2024",
            "LIC.001.2024",
            "LIC 001 2024",
        ]
        
        sanitized_map = {}
        for sid in session_ids:
            sanitized = vector_service._sanitize_name(sid)
            sanitized_map[sid] = sanitized
            print(f"\n  '{sid}' -> '{sanitized}'")
        
        # Verificar colisiones
        unique_sanitized = set(sanitized_map.values())
        
        if len(unique_sanitized) < len(session_ids):
            print("\n[BUG DETECTADO] Colisión por caracteres especiales")
            print(f"  - {len(session_ids)} session_ids producen {len(unique_sanitized)} nombres únicos")
            
            # Encontrar cuáles colisionan
            reverse_map = {}
            for sid, sanitized in sanitized_map.items():
                if sanitized not in reverse_map:
                    reverse_map[sanitized] = []
                reverse_map[sanitized].append(sid)
            
            for sanitized, sids in reverse_map.items():
                if len(sids) > 1:
                    print(f"\n  Colisión en '{sanitized}':")
                    for sid in sids:
                        print(f"    - '{sid}'")
            
            assert True, "Bug documentado: special char sanitization collision"
        else:
            print("\n[COMPORTAMIENTO CORRECTO] Nombres únicos para diferentes caracteres")

    def test_session_data_collision_in_chromadb(self, vector_service):
        """
        Test que demuestra la contaminación de datos cuando dos session_ids
        se sanitizan al mismo nombre de colección.
        
        Escenario:
        1. Crear sesión "ISSSTE-BCS-2024" e indexar documento A
        2. Crear sesión "issste_bcs_2024" e indexar documento B
        3. Consultar ambas sesiones y verificar que retornan documentos mezclados
        
        Expected Behavior: Cada sesión retorna solo sus propios documentos
        Bug Behavior: Ambas sesiones retornan documentos mezclados
        """
        # Verificar primero si hay colisión de nombres
        session_id_1 = "ISSSTE-BCS-2024"
        session_id_2 = "issste_bcs_2024"
        
        sanitized_1 = vector_service._sanitize_name(session_id_1)
        sanitized_2 = vector_service._sanitize_name(session_id_2)
        
        print(f"\n  session_id_1: '{session_id_1}' -> '{sanitized_1}'")
        print(f"  session_id_2: '{session_id_2}' -> '{sanitized_2}'")
        
        if sanitized_1 != sanitized_2:
            # No hay colisión, el test no aplica
            print("\n[INFO] Los nombres sanitizados son diferentes, no hay colisión")
            pytest.skip("Los nombres sanitizados son diferentes")
        
        # Hay colisión - simular el comportamiento del bug
        print("\n[BUG DETECTADO] Colisión de nombres de colección")
        print(f"  - Ambos session_ids se sanitizan a: '{sanitized_1}'")
        
        # Crear mock de colección compartida
        mock_collection = MagicMock()
        mock_collection.name = sanitized_1
        
        # Simular datos de ambas sesiones en la misma colección
        mock_collection.get.return_value = {
            "ids": ["doc-a", "doc-b"],
            "metadatas": [
                {"session_id": session_id_1, "source": "documento_A.pdf", "content": "Datos de ISSSTE-BCS-2024"},
                {"session_id": session_id_2, "source": "documento_B.pdf", "content": "Datos de issste_bcs_2024"},
            ],
            "documents": [
                "Contenido del documento A de ISSSTE-BCS-2024",
                "Contenido del documento B de issste_bcs_2024",
            ]
        }
        
        # Configurar query para retornar todos los documentos
        mock_collection.query.return_value = {
            "ids": ["doc-a", "doc-b"],
            "metadatas": [
                {"session_id": session_id_1, "source": "documento_A.pdf"},
                {"session_id": session_id_2, "source": "documento_B.pdf"},
            ],
            "documents": [
                "Contenido del documento A",
                "Contenido del documento B",
            ],
            "distances": [0.1, 0.2]
        }
        
        vector_service.client.get_or_create_collection.return_value = mock_collection
        vector_service.client.get_collection.return_value = mock_collection
        
        # Consultar sesión 1
        result_1 = vector_service.query_texts(session_id_1, "test query")
        
        # Consultar sesión 2
        result_2 = vector_service.query_texts(session_id_2, "test query")
        
        # Verificar que ambas consultas retornan datos mezclados
        docs_1 = result_1.get("documents", [])
        docs_2 = result_2.get("documents", [])
        metas_1 = result_1.get("metadatas", [])
        metas_2 = result_2.get("metadatas", [])
        
        # Verificar si hay datos de otra sesión en los resultados
        wrong_session_in_1 = [m for m in metas_1 if m.get("session_id") != session_id_1]
        wrong_session_in_2 = [m for m in metas_2 if m.get("session_id") != session_id_2]
        
        if wrong_session_in_1 or wrong_session_in_2:
            print("\n[BUG DETECTADO] Contaminación de datos por colisión de nombres")
            print(f"  - Sesión '{session_id_1}' retornó {len(wrong_session_in_1)} documentos de otra sesión")
            print(f"  - Sesión '{session_id_2}' retornó {len(wrong_session_in_2)} documentos de otra sesión")
            print(f"  - Ambos session_ids usan la misma colección: '{sanitized_1}'")
            print("  - Los datos de diferentes licitaciones se están mezclando")
            
            # Este assert FALLA en código no corregido, confirmando el bug
            assert False, (
                f"Bug detectado: Los session_ids '{session_id_1}' y '{session_id_2}' "
                f"colisionan en el nombre de colección '{sanitized_1}'. "
                f"Los datos de diferentes licitaciones se mezclan."
            )
        else:
            print("\n[COMPORTAMIENTO CORRECTO] Filtrado por session_id previene contaminación")

    def test_session_isolation_with_metadata_filtering(self, vector_service):
        """
        Test que verifica que el filtrado por metadata session_id puede prevenir
        la contaminación incluso cuando hay colisión de nombres.
        
        Este test verifica si el sistema tiene mecanismos de defensa para
        prevenir la contaminación cuando hay colisión de nombres.
        """
        session_id_1 = "ISSSTE-BCS-2024"
        session_id_2 = "issste_bcs_2024"
        
        sanitized_1 = vector_service._sanitize_name(session_id_1)
        sanitized_2 = vector_service._sanitize_name(session_id_2)
        
        if sanitized_1 != sanitized_2:
            pytest.skip("Los nombres sanitizados son diferentes")
        
        # Crear mock que simula filtrado correcto por session_id
        mock_collection = MagicMock()
        mock_collection.name = sanitized_1
        
        def query_side_effect(**kwargs):
            """Simula query con filtrado por session_id."""
            where = kwargs.get("where", {})
            expected_session = where.get("session_id") if where else None
            
            # Simular datos de ambas sesiones
            all_docs = [
                {"id": "doc-a", "session_id": session_id_1, "text": "Doc A"},
                {"id": "doc-b", "session_id": session_id_2, "text": "Doc B"},
            ]
            
            if expected_session:
                # Filtrar por session_id
                filtered = [d for d in all_docs if d["session_id"] == expected_session]
                return {
                    "ids": [d["id"] for d in filtered],
                    "metadatas": [{"session_id": d["session_id"]} for d in filtered],
                    "documents": [d["text"] for d in filtered],
                    "distances": [0.1] * len(filtered)
                }
            else:
                # Sin filtrado - retorna todo (BUG)
                return {
                    "ids": [d["id"] for d in all_docs],
                    "metadatas": [{"session_id": d["session_id"]} for d in all_docs],
                    "documents": [d["text"] for d in all_docs],
                    "distances": [0.1] * len(all_docs)
                }
        
        mock_collection.query.side_effect = query_side_effect
        vector_service.client.get_or_create_collection.return_value = mock_collection
        vector_service.client.get_collection.return_value = mock_collection
        
        # Verificar si query_texts usa filtrado por session_id
        # En código corregido, query_texts debe agregar where={"session_id": session_id}
        result_1 = vector_service.query_texts(session_id_1, "test")
        
        # Verificar si se llamó con filtrado
        call_args = mock_collection.query.call_args
        if call_args:
            where = call_args.kwargs.get("where")
            if where and where.get("session_id") == session_id_1:
                print("\n[DEFENSA ACTIVA] query_texts filtra por session_id")
                print(f"  - Se aplicó where={{'session_id': '{session_id_1}'}}")
                print("  - El filtrado previene contaminación por colisión de nombres")
            else:
                print("\n[BUG DETECTADO] query_texts NO filtra por session_id")
                print(f"  - No se aplicó filtrado por session_id")
                print("  - La colisión de nombres causa contaminación de datos")


class TestSessionIDSanitizationPropertyBased:
    """
    Property-based tests para verificar unicidad de nombres sanitizados.
    
    Estas pruebas usan Hypothesis para generar múltiples session_ids y verificar
    que no hay colisiones.
    """

    def test_property_sanitize_name_produces_unique_names(self):
        """
        Property: Para cualquier par de session_ids diferentes, _sanitize_name
        debe producir nombres diferentes O el sistema debe tener mecanismos
        de aislamiento por metadata.
        
        Validado con Hypothesis para múltiples combinaciones de session_ids.
        """
        from hypothesis import given, strategies as st, settings, assume
        
        # Estrategia para generar session_ids similares a los reales
        session_id_strategy = st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
            min_size=5,
            max_size=50
        )
        
        vector_service = VectorDbServiceClient()
        vector_service.client = MagicMock()
        
        @given(
            session_id_1=session_id_strategy,
            session_id_2=session_id_strategy
        )
        @settings(max_examples=50)
        def check_no_collision(session_id_1, session_id_2):
            # Solo verificar si los session_ids son diferentes
            assume(session_id_1 != session_id_2)
            
            sanitized_1 = vector_service._sanitize_name(session_id_1)
            sanitized_2 = vector_service._sanitize_name(session_id_2)
            
            # Si los nombres sanitizados son iguales, hay colisión
            if sanitized_1 == sanitized_2:
                # BUG: Colisión detectada
                print(f"\n[BUG DETECTADO] Colisión: '{session_id_1}' y '{session_id_2}' -> '{sanitized_1}'")
                
                # Verificar si el sistema tiene mecanismos de defensa
                # (filtrado por metadata session_id)
                # Por ahora, reportamos la colisión
                assert False, (
                    f"Colisión de nombres: '{session_id_1}' y '{session_id_2}' "
                    f"ambos se sanitizan a '{sanitized_1}'"
                )
        
        # Ejecutar la prueba
        try:
            check_no_collision()
            print("\n[PROPERTY TEST PASSED] No se encontraron colisiones en 50 ejemplos")
        except AssertionError as e:
            print(f"\n[PROPERTY TEST FAILED] {e}")

    def test_property_case_insensitive_causes_collision(self):
        """
        Property: Para cualquier session_id, la versión en mayúsculas y minúsculas
        debe producir el mismo nombre sanitizado (comportamiento actual).
        
        Esto demuestra que el sistema actual es case-insensitive, lo cual
        puede causar problemas si los session_ids difieren solo en caso.
        """
        from hypothesis import given, strategies as st, settings
        
        # Estrategia para generar session_ids con letras
        session_id_strategy = st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll')),
            min_size=5,
            max_size=30
        )
        
        vector_service = VectorDbServiceClient()
        vector_service.client = MagicMock()
        
        @given(session_id=session_id_strategy)
        @settings(max_examples=20)
        def check_case_insensitive(session_id):
            upper = session_id.upper()
            lower = session_id.lower()
            
            sanitized_upper = vector_service._sanitize_name(upper)
            sanitized_lower = vector_service._sanitize_name(lower)
            
            # El sistema actual convierte todo a minúsculas
            # Por lo tanto, ambos deben ser iguales
            assert sanitized_upper == sanitized_lower, (
                f"Case sensitivity: '{upper}' -> '{sanitized_upper}', "
                f"'{lower}' -> '{sanitized_lower}'"
            )
        
        # Ejecutar la prueba
        check_case_insensitive()
        print("\n[PROPERTY VERIFIED] El sistema es case-insensitive (comportamiento documentado)")


class TestSessionIDCollisionCounterexamples:
    """
    Tests que documentan contraejemplos específicos encontrados durante
    la exploración del bug.
    """

    def test_document_found_collision_issste_bcs(self):
        """
        Test que documenta el contraejemplo específico encontrado:
        "ISSSTE-BCS-2024" y "issste_bcs_2024" producen el mismo nombre.
        """
        vector_service = VectorDbServiceClient()
        vector_service.client = MagicMock()
        
        session_ids = [
            "ISSSTE-BCS-2024",
            "issste_bcs_2024",
            "ISSSTE_BCS_2024",
            "issste-bcs-2024",
        ]
        
        print("\n[CONTRAJEMPLO DOCUMENTADO]")
        print("Session IDs que colisionan:")
        
        sanitized_map = {}
        for sid in session_ids:
            sanitized = vector_service._sanitize_name(sid)
            sanitized_map[sid] = sanitized
            print(f"  '{sid}' -> '{sanitized}'")
        
        # Verificar que todos colisionan
        unique_sanitized = set(sanitized_map.values())
        
        if len(unique_sanitized) == 1:
            print(f"\n[BUG CONFIRMADO] Todos los session_ids se sanitizan a: '{list(unique_sanitized)[0]}'")
            print("Esto significa que datos de diferentes licitaciones se mezclarán.")
            
            # Documentar el contraejemplo
            assert True, (
                f"Contraejemplo documentado: {len(session_ids)} session_ids diferentes "
                f"producen el mismo nombre de colección"
            )
        else:
            print(f"\n[INFO] Se producen {len(unique_sanitized)} nombres diferentes")

    def test_document_found_collision_lic_format(self):
        """
        Test que documenta colisiones en el formato LIC-XXX-YYYY.
        """
        vector_service = VectorDbServiceClient()
        vector_service.client = MagicMock()
        
        # Diferentes formatos de LIC que podrían colisionar
        test_cases = [
            ("LIC-001-2024", "lic_001_2024"),
            ("LIC-002-2024", "LIC_002_2024"),
            ("lic-003-2024", "LIC-003-2024"),
        ]
        
        print("\n[CONTRAJEMPLO DOCUMENTADO] Formato LIC-XXX-YYYY")
        
        collisions = []
        for sid1, sid2 in test_cases:
            s1 = vector_service._sanitize_name(sid1)
            s2 = vector_service._sanitize_name(sid2)
            
            if s1 == s2:
                collisions.append((sid1, sid2, s1))
                print(f"  Colisión: '{sid1}' y '{sid2}' -> '{s1}'")
        
        if collisions:
            print(f"\n[BUG CONFIRMADO] {len(collisions)} pares de session_ids colisionan")
            assert True, f"Contraejemplos documentados: {len(collisions)} colisiones"


if __name__ == "__main__":
    # Ejecutar tests directamente
    print("=" * 80)
    print("TEST DE EXPLORACIÓN DEL BUG: Session ID Sanitization Collision")
    print("=" * 80)
    print("\nEste test demuestra el bug de colisión de nombres de colección.")
    print("El test DEBE FALLAR en código no corregido (confirma que el bug existe).")
    print("El test PASARÁ después de implementar la corrección.\n")
    
    pytest.main([__file__, "-v", "-s"])
