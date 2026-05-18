"""
test_semantic_file_extractor.py — Tests unitarios y PBT para semantic-file-extractor.

Verifica que:
- DocumentPreprocessor nunca excede el límite de tokens
- NumericValidator nunca lanza excepciones
- Invariante de ajuste proporcional en distribuciones mensuales
- ExtractionResult.confidence siempre en [0.0, 1.0]
- PreprocessResult.reduction_ratio siempre en [0.0, 1.0]
"""
from __future__ import annotations

import math
import sys
import os

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.document_preprocessor import DocumentPreprocessor, PreprocessResult
from app.services.numeric_validator import NumericValidator, ValidationResult, DistributionResult
from app.agents.mission_data_extractor import ExtractionResult
from app.agents.chatbot_rag import ChatbotRAGAgent


# ---------------------------------------------------------------------------
# Tests unitarios — DocumentPreprocessor
# ---------------------------------------------------------------------------

class TestDocumentPreprocessor:
    def setup_method(self):
        self.dp = DocumentPreprocessor()

    def test_empty_text_returns_empty_result(self):
        """test_preprocessor_empty_text"""
        result = self.dp.extract_relevant_sections("", "Capital contable")
        assert result.relevant_text == ""
        assert result.reduction_ratio == 0.0
        assert result.total_chars_original == 0

    def test_whitespace_only_returns_empty(self):
        result = self.dp.extract_relevant_sections("   \n\t  ", "Capital contable")
        assert result.relevant_text == ""

    def test_reduction_ratio_in_range(self):
        """test_preprocessor_reduction_ratio"""
        text = "El capital contable mínimo es de 2 millones de pesos. " * 100
        result = self.dp.extract_relevant_sections(text, "Capital contable mínimo")
        assert 0.0 <= result.reduction_ratio <= 1.0

    def test_max_tokens_respected(self):
        """test_preprocessor_max_tokens_respected"""
        text = "x" * 100_000
        result = self.dp.extract_relevant_sections(text, "dato", max_tokens=500)
        assert len(result.relevant_text) <= 500 * 4

    def test_keywords_scoring_prioritizes_relevant_chunks(self):
        """test_preprocessor_keywords_scoring"""
        # El chunk con "capital contable" debe tener mayor score
        text = (
            "Información irrelevante sobre el clima. " * 20 +
            "El capital contable mínimo requerido es de $2,000,000 MXN. " +
            "Más información irrelevante sobre otros temas. " * 20
        )
        result = self.dp.extract_relevant_sections(text, "Capital contable mínimo")
        assert "capital" in result.relevant_text.lower() or "2,000,000" in result.relevant_text

    def test_returns_preprocess_result_type(self):
        result = self.dp.extract_relevant_sections("texto de prueba", "dato")
        assert isinstance(result, PreprocessResult)

    def test_no_exception_for_none_like_inputs(self):
        """No debe lanzar excepciones con inputs extremos"""
        result = self.dp.extract_relevant_sections("", "")
        assert isinstance(result, PreprocessResult)

    def test_extract_keywords_removes_stopwords(self):
        keywords = self.dp._extract_keywords("Capital contable de la empresa")
        assert "de" not in keywords
        assert "la" not in keywords
        assert "capital" in keywords

    def test_score_chunk_with_keywords(self):
        score = self.dp._score_chunk("El capital contable es de 2 millones", ["capital", "contable"])
        assert score >= 6  # +3 por "capital" + +3 por "contable"

    def test_score_chunk_with_digits(self):
        score_with_digits = self.dp._score_chunk("El valor es 1234567", [])
        score_without_digits = self.dp._score_chunk("El valor es alto", [])
        assert score_with_digits > score_without_digits


# ---------------------------------------------------------------------------
# Tests unitarios — NumericValidator
# ---------------------------------------------------------------------------

class TestNumericValidator:
    def setup_method(self):
        self.v = NumericValidator()

    def test_currency_mx_standard(self):
        """test_numeric_validator_currency_mx"""
        r = self.v.validate_and_normalize("$1,234,567.89", "currency")
        assert r.is_valid
        assert r.numeric_value is not None
        assert abs(r.numeric_value - 1234567.89) < 0.01

    def test_currency_european_format(self):
        r = self.v.validate_and_normalize("1.234.567,89", "currency")
        assert r.is_valid
        assert abs(r.numeric_value - 1234567.89) < 0.01

    def test_currency_plain_number(self):
        r = self.v.validate_and_normalize("2000000", "currency")
        assert r.is_valid
        assert abs(r.numeric_value - 2000000.0) < 0.01

    def test_currency_with_mxn(self):
        r = self.v.validate_and_normalize("MXN 500,000", "currency")
        assert r.is_valid
        assert abs(r.numeric_value - 500000.0) < 0.01

    def test_invalid_currency_no_exception(self):
        """test_numeric_validator_invalid_no_exception"""
        r = self.v.validate_and_normalize("no es un numero", "currency")
        assert not r.is_valid
        assert r.numeric_value is None

    def test_empty_value_no_exception(self):
        r = self.v.validate_and_normalize("", "currency")
        assert not r.is_valid

    def test_none_like_no_exception(self):
        r = self.v.validate_and_normalize("None", "currency")
        assert isinstance(r, ValidationResult)

    def test_text_type_always_valid(self):
        r = self.v.validate_and_normalize("cualquier texto", "text")
        assert r.is_valid
        assert r.normalized_value == "cualquier texto"

    def test_integer_type(self):
        r = self.v.validate_and_normalize("50", "integer")
        assert r.is_valid
        assert r.numeric_value == 50.0

    def test_monthly_distribution_valid(self):
        """test_monthly_distribution_valid"""
        d = self.v.validate_monthly_distribution([100.0, 200.0, 300.0], 600.0)
        assert d.is_valid
        assert not d.adjustment_applied
        assert d.adjusted_values == [100.0, 200.0, 300.0]

    def test_monthly_distribution_adjustment(self):
        """test_monthly_distribution_adjustment"""
        d = self.v.validate_monthly_distribution([100.0, 200.0, 295.0], 600.0)
        assert d.adjustment_applied
        assert abs(sum(d.adjusted_values) - 600.0) <= 0.01

    def test_monthly_distribution_empty_list(self):
        d = self.v.validate_monthly_distribution([], 0.0)
        assert isinstance(d, DistributionResult)

    def test_monthly_distribution_single_value(self):
        d = self.v.validate_monthly_distribution([500.0], 500.0)
        assert d.is_valid
        assert not d.adjustment_applied


# ---------------------------------------------------------------------------
# Tests unitarios — ExtractionResult
# ---------------------------------------------------------------------------

class TestExtractionResult:
    def test_confidence_clamped_above_1(self):
        r = ExtractionResult(value="test", confidence=1.5, source_reference="p1", raw_snippet="x", extraction_status="found")
        assert r.confidence == 1.0

    def test_confidence_clamped_below_0(self):
        r = ExtractionResult(value=None, confidence=-0.5, source_reference="", raw_snippet="", extraction_status="not_found")
        assert r.confidence == 0.0

    def test_invalid_status_normalized(self):
        r = ExtractionResult(value=None, confidence=0.5, source_reference="", raw_snippet="", extraction_status="invalid_status")
        assert r.extraction_status == "not_found"

    def test_valid_statuses_preserved(self):
        for status in ("found", "not_found", "ambiguous"):
            r = ExtractionResult(value="x", confidence=0.5, source_reference="", raw_snippet="", extraction_status=status)
            assert r.extraction_status == status


# ---------------------------------------------------------------------------
# Tests unitarios — ChatbotRAGAgent helpers
# ---------------------------------------------------------------------------

class TestChatbotHelpers:
    def test_classify_confirm(self):
        """test_confirmation_classify_confirm"""
        assert ChatbotRAGAgent._classify_confirmation_response("sí") == "confirm"
        assert ChatbotRAGAgent._classify_confirmation_response("si") == "confirm"
        assert ChatbotRAGAgent._classify_confirmation_response("correcto") == "confirm"
        assert ChatbotRAGAgent._classify_confirmation_response("ok") == "confirm"

    def test_classify_correct(self):
        """test_confirmation_classify_correct"""
        assert ChatbotRAGAgent._classify_confirmation_response("no, es 500000") == "correct"
        assert ChatbotRAGAgent._classify_confirmation_response("no, el valor es 2000000") == "correct"

    def test_classify_reject(self):
        """test_confirmation_classify_reject"""
        assert ChatbotRAGAgent._classify_confirmation_response("no aplica") == "reject"
        assert ChatbotRAGAgent._classify_confirmation_response("no tengo") == "reject"

    def test_infer_field_type_currency(self):
        assert ChatbotRAGAgent._infer_field_type("solvencia_economica.capital_contable") == "currency"
        assert ChatbotRAGAgent._infer_field_type("monto_total") == "currency"

    def test_infer_field_type_integer(self):
        assert ChatbotRAGAgent._infer_field_type("numero_empleados") == "integer"

    def test_infer_field_type_text_default(self):
        assert ChatbotRAGAgent._infer_field_type("solvencia_legal.rfc") == "text"
        assert ChatbotRAGAgent._infer_field_type("") == "text"


# ---------------------------------------------------------------------------
# Tests de propiedades — Hypothesis
# ---------------------------------------------------------------------------

# Feature: semantic-file-extractor, Propiedad 1: DocumentPreprocessor nunca excede el límite de tokens
@given(
    text=st.text(min_size=0, max_size=50000),
    dato=st.text(min_size=1, max_size=100),
    max_tokens=st.integers(min_value=100, max_value=5000),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_1_preprocessor_never_exceeds_token_limit(text, dato, max_tokens):
    """
    Para cualquier texto y dato_solicitado,
    relevant_text tiene ≤ max_tokens * 4 caracteres.

    **Validates: Requirements 1.3**
    """
    dp = DocumentPreprocessor()
    result = dp.extract_relevant_sections(text, dato, max_tokens=max_tokens)
    assert isinstance(result, PreprocessResult)
    assert len(result.relevant_text) <= max_tokens * 4, (
        f"relevant_text ({len(result.relevant_text)}) > max_tokens*4 ({max_tokens * 4})"
    )


# Feature: semantic-file-extractor, Propiedad 2: NumericValidator nunca lanza excepciones
@given(raw_value=st.text(max_size=200))
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_property_2_numeric_validator_never_raises(raw_value):
    """
    Para cualquier string input, validate_and_normalize no lanza excepciones.

    **Validates: Requirements 3.1**
    """
    v = NumericValidator()
    for field_type in ("currency", "integer", "percentage", "text"):
        result = v.validate_and_normalize(raw_value, field_type)
        assert isinstance(result, ValidationResult)


# Feature: semantic-file-extractor, Propiedad 3: Invariante de ajuste proporcional
@given(
    monthly_values=st.lists(
        st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=12,
    ),
    total=st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_3_distribution_adjustment_invariant(monthly_values, total):
    """
    Si adjustment_applied=True, entonces abs(sum(adjusted_values) - total) <= 0.01.

    **Validates: Requirements 3.3**
    """
    v = NumericValidator()
    result = v.validate_monthly_distribution(monthly_values, total)
    assert isinstance(result, DistributionResult)
    if result.adjustment_applied:
        actual_sum = sum(result.adjusted_values)
        assert abs(actual_sum - total) <= 0.01, (
            f"Invariante violada: sum={actual_sum}, total={total}, diff={abs(actual_sum - total)}"
        )


# Feature: semantic-file-extractor, Propiedad 4: reduction_ratio siempre en [0.0, 1.0]
@given(
    text=st.text(min_size=1, max_size=10000),
    dato=st.text(min_size=1, max_size=100),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_4_reduction_ratio_in_range(text, dato):
    """
    Para cualquier texto no vacío, reduction_ratio ∈ [0.0, 1.0].

    **Validates: Requirements 1.4**
    """
    dp = DocumentPreprocessor()
    result = dp.extract_relevant_sections(text, dato)
    assert 0.0 <= result.reduction_ratio <= 1.0, (
        f"reduction_ratio fuera de rango: {result.reduction_ratio}"
    )
