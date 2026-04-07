import pytest
from unittest.mock import AsyncMock, MagicMock
from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
from app.models.company import Company

@pytest.mark.asyncio
async def test_save_company_persists_catalog():
    """Verifica que el catálogo se persista en save_company usando mock de SQLAlchemy."""
    mock_session_factory = MagicMock()
    mock_db_session = AsyncMock()
    # Simular contexto 'async with self.async_session() as db_session'
    mock_session_factory.return_value.__aenter__.return_value = mock_db_session
    
    adapter = PostgresMemoryAdapter("postgresql://user:pass@localhost/db")
    adapter.async_session = mock_session_factory
    
    # Simular que la empresa no existe aún (UPSERT)
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db_session.execute.return_value = mock_result
    
    data = {
        "name": "Licitadora Mexicana S.A.",
        "catalog": [{"concepto": "Servicio Limpieza", "precio_unitario": 1200.50}]
    }
    
    await adapter.save_company("co_test_123", data)
    
    # Verificar que se añadió el objeto con los datos correctos
    assert mock_db_session.add.called
    db_obj = mock_db_session.add.call_args[0][0]
    assert isinstance(db_obj, Company)
    assert db_obj.id == "co_test_123"
    assert db_obj.catalog == data["catalog"]
    assert mock_db_session.commit.called

@pytest.mark.asyncio
async def test_get_company_returns_catalog_safe():
    """Verifica que get_company retorne el catálogo y use [] si es None."""
    mock_session_factory = MagicMock()
    mock_db_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_db_session
    
    adapter = PostgresMemoryAdapter("postgresql://user:pass@localhost/db")
    adapter.async_session = mock_session_factory
    
    # 1. Caso con catálogo poblado
    mock_company = MagicMock(spec=Company)
    mock_company.id = "co_1"
    mock_company.name = "Empresa A"
    mock_company.catalog = [{"item": "Tinta", "precio": 50}]
    mock_company.type = "moral"
    mock_company.docs = {}
    mock_company.master_profile = {}
    mock_company.created_at = None
    mock_company.updated_at = None
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_company
    mock_db_session.execute.return_value = mock_result
    
    res = await adapter.get_company("co_1")
    assert res["catalog"] == [{"item": "Tinta", "precio": 50}]

    # 2. Caso con catálogo None (debe retornar [])
    mock_company.catalog = None
    res_none = await adapter.get_company("co_1")
    assert res_none["catalog"] == []

@pytest.mark.asyncio
async def test_save_company_merge_logic():
    """Verifica la política de merge: si no viene 'catalog' en data, no se sobrescribe."""
    mock_session_factory = MagicMock()
    mock_db_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_db_session
    
    adapter = PostgresMemoryAdapter("postgresql://user:pass@localhost/db")
    adapter.async_session = mock_session_factory
    
    # Simular objeto existente con catálogo previo
    mock_existing = Company(id="co_old", catalog=[{"existente": True}])
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_existing
    mock_db_session.execute.return_value = mock_result
    
    # Guardar solo el nombre, sin mencionar 'catalog'
    await adapter.save_company("co_old", {"name": "Nuevo Nombre"})
    
    # El objeto NO debe haber perdido su catálogo
    assert mock_existing.catalog == [{"existente": True}]
    assert mock_existing.name == "Nuevo Nombre"
    
    # Ahora guardar con catalog=[], sí debe sobrescribir
    await adapter.save_company("co_old", {"catalog": []})
    assert mock_existing.catalog == []
