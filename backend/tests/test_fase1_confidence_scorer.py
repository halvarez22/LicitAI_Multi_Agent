"""
tests/test_fase1_confidence_scorer.py
Pruebas unitarias para el motor de confianza (ConfidenceScorer).
"""
import pytest
from app.services.confidence_scorer import ConfidenceScorer, ConfidenceRecommendation

def test_exact_match_high_confidence():
    scorer = ConfidenceScorer()
    context = "El licitante deberá presentar un RFC válido y acta constitutiva."
    extracted = "RFC válido"
    
    score = scorer.calculate_extraction_confidence(
        extracted_text=extracted,
        source_context=context
    )
    
    assert score.overall >= 0.8
    assert score.recommendation == ConfidenceRecommendation.ACCEPT
    assert "literal_evidence" in score.breakdown
    assert score.breakdown["literal_evidence"] == 1.0

def test_uncertain_language_penalty():
    scorer = ConfidenceScorer()
    context = "Documento de ejemplo."
    extracted = "Posiblemente se requiere RFC"
    llm_output = "El documento parece indicar que posiblemente se requiere RFC."
    
    score = scorer.calculate_extraction_confidence(
        extracted_text=extracted,
        source_context=context,
        llm_raw_output=llm_output
    )
    
    # Penalización por lenguaje dudoso
    assert score.breakdown["certainty_language"] < 1.0
    assert score.overall < 0.7
    assert any("incertidumbre" in a.lower() for a in score.ambiguities)

def test_low_context_penalty():
    scorer = ConfidenceScorer()
    context = "Corto." # Contexto muy pobre
    extracted = "Dato extraído"
    
    score = scorer.calculate_extraction_confidence(
        extracted_text=extracted,
        source_context=context
    )
    
    assert score.breakdown["context_richness"] <= 0.4
    assert score.overall < 0.7

def test_critical_threshold_escalates():
    scorer = ConfidenceScorer(threshold_critical=0.90)
    context = "Contexto con algo de duda."
    extracted = "Dato ambiguo"
    
    # Simular score medio (~0.75) que pasaría default (0.70) pero no crítico (0.90)
    score = scorer.calculate_extraction_confidence(
        extracted_text=extracted,
        source_context=context,
        is_critical=True
    )
    
    if score.overall < 0.90:
        assert score.recommendation == ConfidenceRecommendation.ESCALATE
        assert score.threshold_passed is False

def test_overall_score_bounded_0_1():
    scorer = ConfidenceScorer()
    score = scorer.calculate_extraction_confidence("", "")
    assert 0.0 <= score.overall <= 1.0

def test_recommendation_mapping():
    scorer = ConfidenceScorer(threshold_default=0.70)
    
    # Caso ACCEPT
    score_high = scorer.calculate_extraction_confidence("Texto", "Texto " * 50)
    assert score_high.overall >= 0.70
    assert score_high.recommendation == ConfidenceRecommendation.ACCEPT
    
    # Caso REJECT (score muy bajo)
    score_low = scorer.calculate_extraction_confidence("", "")
    assert score_low.overall < 0.55 # 0.70 - 0.15
    assert score_low.recommendation == ConfidenceRecommendation.REJECT
