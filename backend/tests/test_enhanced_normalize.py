"""
Test suite for enhanced_normalize module.

Validates:
- Requirements 1.1-1.5 (experiencia mínima)
- Requirements 3.5 (plantilla fallback)
- Requirements 16.1-16.3 (normalize_solvencia_tecnica)
- Requirements 17.1-17.3 (normalize_condiciones_contractuales)
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typing import Dict, Any

from app.agents.enhanced_normalize import (
    normalize_experiencia_minima,
    normalize_plantilla_personal,
    normalize_solvencia_tecnica,
    normalize_condiciones_contractuales,
    DEFAULT_MISSING
)

# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    anios=st.text(min_size=1, max_size=10),
    monto=st.text(min_size=1, max_size=10),
    num_contratos=st.text(min_size=1, max_size=10),
    moneda=st.text(min_size=1, max_size=10),
)
def test_property_1_experiencia_minima_extraction(anios: str, monto: str, num_contratos: str, moneda: str) -> None:
    """Property 1: Experiencia mínima extraction from different keys.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4
    """
    # Test alternative keys handling
    raw = {
        "anios_experiencia": anios,
        "monto_min": monto,
        "número_contratos": num_contratos,
        "unidad": moneda,
    }
    result = normalize_experiencia_minima(raw)
    
    assert result.años_experiencia == anios
    assert result.monto_minimo == monto
    assert result.numero_contratos == num_contratos
    assert result.unidad_monetaria == moneda


@settings(max_examples=50)
@given(
    missing_key=st.sampled_from(["años_experiencia", "monto_minimo", "numero_contratos", "unidad_monetaria"])
)
def test_property_2_missing_experience_fallback(missing_key: str) -> None:
    """Property 2: Missing experience requirements fallback to 'No especificado'.
    
    Validates: Requirements 1.5
    """
    raw = {}
    result = normalize_experiencia_minima(raw)
    
    # All should be DEFAULT_MISSING if dict is empty
    assert getattr(result, missing_key) == DEFAULT_MISSING


@settings(max_examples=50)
@given(
    flag_key=st.sampled_from(["sin_requisitos_explícitos", "sin_requisitos", "no_requerido"])
)
def test_property_5_empty_plantilla_fallback(flag_key: str) -> None:
    """Property 5: Empty plantilla fallback.
    
    Validates: Requirements 3.5
    """
    raw = [{
        "puesto": "Ingeniero",
        flag_key: True
    }]
    result = normalize_plantilla_personal(raw)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestNormalizeSolvenciaTecnica:
    def test_complete_normalization_flow(self):
        """Test complete flow with valid dict."""
        raw = {
            "experiencia_minima": {"años": "5"},
            "plantilla_personal": [{"puesto": "Gerente"}],
            "normas": [{"norma": "ISO 9001"}]
        }
        result = normalize_solvencia_tecnica(raw)
        
        assert result.experiencia_mínima.años_experiencia == "5"
        assert result.experiencia_mínima.monto_minimo == DEFAULT_MISSING
        assert len(result.plantilla_personal) == 1
        assert result.plantilla_personal[0].puesto == "Gerente"
        assert len(result.normas_certificaciones) == 1
        assert result.normas_certificaciones[0].norma == "ISO 9001"
        
    def test_fallback_values_for_missing_fields(self):
        """Test fallback when given empty dict."""
        result = normalize_solvencia_tecnica({})
        
        assert result.experiencia_mínima.años_experiencia == DEFAULT_MISSING
        assert len(result.plantilla_personal) == 0
        assert result.curriculum.empresa_requerido is False


class TestNormalizeCondicionesContractuales:
    def test_complete_normalization_flow(self):
        raw = {
            "tipo_contrato": {"tipo": "Abierto"},
            "penalizaciones": {"atraso": {"porcentaje": "1%"}},
            "garantia_cumplimiento": {"porcentaje": "10%"}
        }
        result = normalize_condiciones_contractuales(raw)
        
        assert result.tipo_contrato.tipo == "Abierto"
        assert result.penalizaciones.atraso.porcentaje == "1%"
        assert result.garantía_cumplimiento.monto_porcentaje == "10%"
        
    def test_fallback_values_for_missing_fields(self):
        result = normalize_condiciones_contractuales({})
        
        assert result.tipo_contrato.tipo == DEFAULT_MISSING
        assert result.penalizaciones.atraso.porcentaje == DEFAULT_MISSING
        assert result.garantía_cumplimiento.monto_porcentaje == DEFAULT_MISSING
