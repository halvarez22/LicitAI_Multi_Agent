"""
Test suite for enhanced_classifier module.

Validates: Requirements 12.1, 12.2, 12.3, 12.4
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from app.agents.enhanced_classifier import (
    classify_requirement,
    extract_page_from_context,
    extract_clause_from_context,
    RequirementClassifier,
    OBLIGATORY_KEYWORDS,
    DESEABLE_KEYWORDS,
    CONDITIONAL_KEYWORDS,
)


class TestClassifyRequirement:
    """Tests for the classify_requirement function."""

    # Requirement 12.1: Obligatory keywords detection
    def test_debera_presentar_is_obligatorio(self):
        """Test that 'deberá presentar' is classified as obligatorio."""
        result = classify_requirement("deberá presentar")
        assert result == ("obligatorio", False)

    def test_es_obligatorio_is_obligatorio(self):
        """Test that 'es obligatorio' is classified as obligatorio."""
        result = classify_requirement("es obligatorio")
        assert result == ("obligatorio", False)

    def test_es_requisito_is_obligatorio(self):
        """Test that 'es requisito' is classified as obligatorio."""
        result = classify_requirement("es requisito")
        assert result == ("obligatorio", False)

    def test_obligatorio_keyword_is_obligatorio(self):
        """Test that 'obligatorio' keyword is detected."""
        result = classify_requirement("Es obligatorio presentar la documentación")
        assert result == ("obligatorio", False)

    def test_requerido_keyword_is_obligatorio(self):
        """Test that 'requerido' keyword is detected."""
        result = classify_requirement("documento requerido")
        assert result == ("obligatorio", False)

    def test_debera_de_keyword_is_obligatorio(self):
        """Test that 'deberá de' keyword is detected."""
        result = classify_requirement("deberá de cumplir")
        assert result == ("obligatorio", False)

    def test_debera_contar_is_obligatorio(self):
        """Test that 'deberá contar' is classified as obligatorio."""
        result = classify_requirement("deberá contar con")
        assert result == ("obligatorio", False)

    def test_es_obligatorio_presentar_is_obligatorio(self):
        """Test that 'es obligatorio presentar' is classified as obligatorio."""
        result = classify_requirement("es obligatorio presentar")
        assert result == ("obligatorio", False)

    def test_es_requisito_indispensable_is_obligatorio(self):
        """Test that 'es requisito indispensable' is classified as obligatorio."""
        result = classify_requirement("es requisito indispensable")
        assert result == ("obligatorio", False)

    def test_debe_cumplir_is_obligatorio(self):
        """Test that 'debe cumplir' is classified as obligatorio."""
        result = classify_requirement("debe cumplir con")
        assert result == ("obligatorio", False)

    def test_se_requiere_is_obligatorio(self):
        """Test that 'se requiere' is classified as obligatorio."""
        result = classify_requirement("se requiere experiencia")
        assert result == ("obligatorio", False)

    # Requirement 12.2: Desirable keywords detection
    def test_es_deseable_is_deseable(self):
        """Test that 'es deseable' is classified as deseable."""
        result = classify_requirement("es deseable")
        assert result == ("deseable", False)

    def test_se_valorara_is_deseable(self):
        """Test that 'se valorará' is classified as deseable."""
        result = classify_requirement("se valorará")
        assert result == ("deseable", False)

    def test_preferible_is_deseable(self):
        """Test that 'preferible' keyword is detected."""
        result = classify_requirement("es preferible")
        assert result == ("deseable", False)

    def test_deseable_keyword_is_deseable(self):
        """Test that 'deseable' keyword is detected."""
        result = classify_requirement("experiencia deseable")
        assert result == ("deseable", False)

    def test_se_considerara_is_deseable(self):
        """Test that 'se considerará' is classified as deseable."""
        result = classify_requirement("se considerará positivamente")
        assert result == ("deseable", False)

    def test_preferente_is_deseable(self):
        """Test that 'preferente' keyword is detected."""
        result = classify_requirement("experiencia preferente")
        assert result == ("deseable", False)

    # Requirement 12.3: Conditional keywords detection
    def test_cuando_se_cumpla_is_condicional(self):
        """Test that 'cuando se cumpla' is classified as condicional."""
        result = classify_requirement("cuando se cumpla")
        assert result == ("condicional", False)

    def test_en_caso_de_is_condicional(self):
        """Test that 'en caso de' is classified as condicional."""
        result = classify_requirement("en caso de")
        assert result == ("condicional", False)

    def test_si_keyword_is_condicional(self):
        """Test that 'si ' keyword is detected."""
        result = classify_requirement("si el proveedor")
        assert result == ("condicional", False)

    def test_solo_si_is_condicional(self):
        """Test that 'solo si' is classified as condicional."""
        result = classify_requirement("solo si se cumple")
        assert result == ("condicional", False)

    def test_unicamente_cuando_is_condicional(self):
        """Test that 'únicamente cuando' is classified as condicional."""
        result = classify_requirement("únicamente cuando")
        assert result == ("condicional", False)

    def test_en_el_caso_de_que_is_condicional(self):
        """Test that 'en el caso de que' is classified as condicional."""
        result = classify_requirement("en el caso de que")
        assert result == ("condicional", False)

    def test_siempre_que_is_condicional(self):
        """Test that 'siempre que' is classified as condicional."""
        result = classify_requirement("siempre que")
        assert result == ("condicional", False)

    def test_dependiendo_de_is_condicional(self):
        """Test that 'dependiendo de' is classified as condicional."""
        result = classify_requirement("dependiendo de")
        assert result == ("condicional", False)

    # Requirement 12.4: Default fallback behavior
    def test_fallback_obligatorio_with_uncertainty(self):
        """Test that text without keywords defaults to obligatorio with uncertainty."""
        result = classify_requirement("texto sin keywords")
        assert result == ("obligatorio", True)

    def test_empty_text_fallback(self):
        """Test that empty text defaults to obligatorio with uncertainty."""
        result = classify_requirement("")
        assert result == ("obligatorio", True)

    def test_none_text_fallback(self):
        """Test that None text defaults to obligatorio with uncertainty."""
        result = classify_requirement(None)
        assert result == ("obligatorio", True)

    def test_generic_text_fallback(self):
        """Test that generic text without keywords defaults to obligatorio."""
        result = classify_requirement("El licitante entregará sus documentos")
        assert result == ("obligatorio", True)

    # Edge cases
    def test_mixed_case_keywords(self):
        """Test that keywords are detected regardless of case."""
        result = classify_requirement("DEBERÁ PRESENTAR")
        assert result == ("obligatorio", False)

    def test_partial_match_not_triggered(self):
        """Test that partial keyword matches don't trigger false positives."""
        # "deseo" should NOT match "deseable"
        result = classify_requirement("tengo deseo de participar")
        assert result == ("obligatorio", True)

    def test_conditional_takes_precedence_over_obligatory(self):
        """Test that conditional keywords take precedence over obligatory."""
        result = classify_requirement("cuando deberá cumplir")
        assert result == ("condicional", False)

    def test_obligatory_takes_precedence_over_deseable(self):
        """Test that obligatory keywords take precedence over deseable."""
        result = classify_requirement("es obligatorio y deseable")
        assert result == ("obligatorio", False)


class TestExtractPageFromContext:
    """Tests for the extract_page_from_context function."""

    def test_extract_page_numero(self):
        """Test extracting page number with 'página' keyword."""
        result = extract_page_from_context("consultar página 15")
        assert result == "15"

    def test_extract_page_pagina_sin_acento(self):
        """Test extracting page number with 'pagina' keyword."""
        result = extract_page_from_context("consultar pagina 10")
        assert result == "10"

    def test_extract_page_folio(self):
        """Test extracting page number with 'folio' keyword."""
        result = extract_page_from_context("véase folio 23")
        assert result == "23"

    def test_extract_page_no_encontrada(self):
        """Test that missing page returns default."""
        result = extract_page_from_context("sin información de página")
        assert result == "No especificado"

    def test_extract_page_empty_context(self):
        """Test that empty context returns default."""
        result = extract_page_from_context("")
        assert result == "No especificado"


class TestExtractClauseFromContext:
    """Tests for the extract_clause_from_context function."""

    def test_extract_clause_numeral(self):
        """Test extracting clause with 'Cláusula' keyword."""
        result = extract_clause_from_context("según Cláusula 5.2")
        assert result == "5.2"

    def test_extract_clause_inciso(self):
        """Test extracting clause with 'Inciso' keyword."""
        result = extract_clause_from_context("Inciso a)")
        assert result == "a)"

    def test_extract_clause_articulo(self):
        """Test extracting clause with 'Artículo' keyword."""
        result = extract_clause_from_context("Artículo 12")
        assert result == "12"

    def test_extract_clause_no_encontrada(self):
        """Test that missing clause returns default."""
        result = extract_clause_from_context("sin información de cláusula")
        assert result == "No especificado"


class TestRequirementClassifier:
    """Tests for the RequirementClassifier class."""

    def test_classify_method(self):
        """Test the classify method of RequirementClassifier."""
        classifier = RequirementClassifier()
        result = classifier.classify("es obligatorio")
        assert result == ("obligatorio", False)

    def test_classify_with_confidence(self):
        """Test the classify_with_confidence method."""
        classifier = RequirementClassifier()
        result = classifier.classify_with_confidence(
            "es obligatorio",
            context="página 5"
        )
        assert result["clasificación"] == "obligatorio"
        assert result["clasificación_incierta"] is False
        assert result["página"] == "5"

    def test_get_priority(self):
        """Test the get_priority method."""
        classifier = RequirementClassifier()
        assert classifier.get_priority("obligatorio") == 1
        assert classifier.get_priority("deseable") == 2
        assert classifier.get_priority("condicional") == 3

    def test_get_category_priority(self):
        """Test the get_category_priority method."""
        classifier = RequirementClassifier()
        assert classifier.get_category_priority("garantías") == 1
        assert classifier.get_category_priority("documentación_legal") == 2

    def test_calculate_delivery_order(self):
        """Test the calculate_delivery_order method."""
        classifier = RequirementClassifier()
        # obligatorio (1) * 100 + garantías (1) = 101
        order = classifier.calculate_delivery_order("obligatorio", "garantías")
        assert order == 101


class TestKeywordLists:
    """Tests to verify keyword lists are properly defined."""

    def test_obligatory_keywords_not_empty(self):
        """Test that obligatory keywords list is not empty."""
        assert len(OBLIGATORY_KEYWORDS) > 0

    def test_deseable_keywords_not_empty(self):
        """Test that deseable keywords list is not empty."""
        assert len(DESEABLE_KEYWORDS) > 0

        assert len(CONDITIONAL_KEYWORDS) > 0


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis
# ---------------------------------------------------------------------------

def _contains_any_keyword(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    for kw in CONDITIONAL_KEYWORDS + OBLIGATORY_KEYWORDS + DESEABLE_KEYWORDS:
        if kw in text_lower:
            return True
    return False

@settings(max_examples=100)
@given(
    prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
    suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
    keyword=st.sampled_from(OBLIGATORY_KEYWORDS)
)
def test_property_14_requisito_classification_obligatorio(prefix: str, suffix: str, keyword: str) -> None:
    """Property 14: Requisito classification by keyword (obligatorio).
    
    Validates: Requirements 12.1, 12.2
    """
    text = f"{prefix} {keyword} {suffix}"
    # Conditional keywords take precedence, so if we accidentally formed one, skip.
    if any(k in text.lower() for k in CONDITIONAL_KEYWORDS):
        return
    classification, uncertain = classify_requirement(text)
    assert classification == "obligatorio"
    assert uncertain is False

@settings(max_examples=100)
@given(
    prefix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
    suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", max_size=20),
    keyword=st.sampled_from(DESEABLE_KEYWORDS)
)
def test_property_14_requisito_classification_deseable(prefix: str, suffix: str, keyword: str) -> None:
    """Property 14: Requisito classification by keyword (deseable).
    
    Validates: Requirements 12.1, 12.2
    """
    text = f"{prefix} {keyword} {suffix}"
    # Conditional and obligatory take precedence, so if we accidentally formed one, skip.
    text_lower = text.lower()
    if any(k in text_lower for k in CONDITIONAL_KEYWORDS) or any(k in text_lower for k in OBLIGATORY_KEYWORDS):
        return
    classification, uncertain = classify_requirement(text)
    assert classification == "deseable"
    assert uncertain is False

@settings(max_examples=100)
@given(
    text=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=50)
)
def test_property_15_ambiguous_classification_fallback(text: str) -> None:
    """Property 15: Ambiguous classification fallback.
    
    Validates: Requirements 12.4
    """
    if _contains_any_keyword(text):
        return
    
    classification, uncertain = classify_requirement(text)
    assert classification == "obligatorio"
    assert uncertain is True