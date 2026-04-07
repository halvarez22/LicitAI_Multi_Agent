import pytest
from unittest.mock import AsyncMock, patch
from app.services.slot_inference import SlotInferenceService

@pytest.mark.asyncio
async def test_slot_inference_rules_match():
    """Hito 5: Verifica que las reglas estáticas funcionen (rápido)."""
    service = SlotInferenceService()
    
    # 1. Caso Domicilio y RFC
    text = "Se requiere que el oferente presente su Constancia de Situación Fiscal con RFC y domicilio fiscal vigente de México."
    slots = service.infer_slots_rules(text)
    
    assert "tax_id" in slots
    assert "legal_address" in slots
    
    # 2. Caso Representante
    text2 = "Carta firmada por el representante legal o apoderado de la empresa."
    slots2 = service.infer_slots_rules(text2)
    assert "legal_representative" in slots2

@pytest.mark.asyncio
async def test_slot_inference_llm_hybrid():
    """Hito 5: Verifica que el LLM aporte semántica (lento)."""
    service = SlotInferenceService()
    
    # Mockear LLM para devolver JSON
    with patch.object(service.llm, "generate") as mock_gen:
        mock_gen.return_value = {"response": '["tax_id", "email"]'}
        
        # Un texto muy ambiguo para reglas pero claro para LLM
        text = "Adjuntar CIF y medio de contacto electrónico principal del proveedor."
        slots = await service.infer_all(text)
        
        # 'tax_id' (CIF) via reglas + 'email' via LLM
        assert "tax_id" in slots
        assert "email" in slots
        
@pytest.mark.asyncio
async def test_slot_inference_invalid_vocabulary_excluded():
    """Hito 5: Verifica que slots fuera del vocabulario se descarten."""
    service = SlotInferenceService()
    
    with patch.object(service.llm, "generate") as mock_gen:
        # El LLM inventa un slot "color_favorito"
        mock_gen.return_value = {"response": '["tax_id", "color_favorito"]'}
        
        slots = await service.infer_all("Bases de licitación")
        
        assert "tax_id" in slots
        assert "color_favorito" not in slots
