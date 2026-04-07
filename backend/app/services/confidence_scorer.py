"""
confidence_scorer.py — Fase 1 Confianza
Motor de cálculo de certidumbre para extracciones de agentes.
Implementa heurísticas transparentes y auditables para detectar alucinaciones o datos débiles.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ConfidenceRecommendation(str, Enum):
    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"
    ESCALATE = "escalate"


class ConfidenceScore(BaseModel):
    """
    Schema del puntaje de confianza.
    """
    overall: float = Field(..., ge=0.0, le=1.0)
    breakdown: Dict[str, float] = Field(default_factory=dict)
    threshold_passed: bool
    recommendation: ConfidenceRecommendation
    unknowns: List[str] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)


class ConfidenceScorer:
    """
    Calculador de confianza basado en señales heurísticas.
    """

    def __init__(
        self,
        threshold_default: float = 0.70,
        threshold_critical: float = 0.80
    ):
        self.threshold_default = threshold_default
        self.threshold_critical = threshold_critical

    def calculate_extraction_confidence(
        self,
        extracted_text: str,
        source_context: str,
        llm_raw_output: str = "",
        extraction_method: str = "llm_extraction",
        is_critical: bool = False
    ) -> ConfidenceScore:
        """
        Calcula el score de confianza basado en múltiples señales.
        """
        signals = {}
        unknowns = []
        ambiguities = []

        # 1. Señal: Evidencia Literal (Similitud/Substring)
        # Si la extracción está presente literalmente en la fuente, es una señal fuerte.
        if extracted_text and extracted_text.strip() in source_context:
            signals["literal_evidence"] = 1.0
        elif extracted_text:
            # Búsqueda parcial o fuzzy simple (case-insensitive)
            if extracted_text.lower() in source_context.lower():
                signals["literal_evidence"] = 0.8
            else:
                signals["literal_evidence"] = 0.3
        else:
            signals["literal_evidence"] = 0.0

        # 2. Señal: Cobertura de Contexto
        # Penaliza si el contexto fuente es sospechosamente corto (< 50 caracteres).
        context_len = len(source_context)
        if context_len > 500:
            signals["context_richness"] = 1.0
        elif context_len > 100:
            signals["context_richness"] = 0.7
        else:
            signals["context_richness"] = 0.4

        # 3. Señal: Lenguaje de Incertidumbre
        # Detecta palabras que indican duda en el LLM.
        uncertainty_terms = [
            r"posiblemente", r"quizá", r"tal vez", r"no está claro", 
            r"probablemente", r"podría ser", r"no se especifica con certeza",
            r"parece indicar", r"supuestamente"
        ]
        found_uncertainty = False
        penalty = 0.0
        for term in uncertainty_terms:
            if re.search(term, llm_raw_output.lower()) or re.search(term, extracted_text.lower()):
                found_uncertainty = True
                penalty += 0.2
                ambiguities.append(f"Término de incertidumbre detectado: {term}")
        
        signals["certainty_language"] = max(0.0, 1.0 - penalty)

        # 4. Señal: Consistencia Estructural
        # Si la extracción es vacía o muy genérica, penaliza.
        if not extracted_text or extracted_text.strip() == "":
            signals["structural_consistency"] = 0.0
            unknowns.append("No se encontró texto extraído")
        elif len(extracted_text) < 3:
            signals["structural_consistency"] = 0.5
            ambiguities.append("Extracción sospechosamente corta")
        else:
            signals["structural_consistency"] = 1.0

        # --- Cálculo del Score Final (Promedio ponderado) ---
        # Pesos: Evidencia (40%), Incertidumbre (30%), Contexto (15%), Estructura (15%)
        weights = {
            "literal_evidence": 0.4,
            "certainty_language": 0.3,
            "context_richness": 0.15,
            "structural_consistency": 0.15
        }
        
        overall = sum(signals[k] * weights[k] for k in weights if k in signals)
        
        # --- Umbrales y Recomendación ---
        threshold = self.threshold_critical if is_critical else self.threshold_default
        threshold_passed = overall >= threshold

        recommendation = ConfidenceRecommendation.ACCEPT
        if overall < (threshold - 0.15):
            recommendation = ConfidenceRecommendation.REJECT
        elif overall < threshold:
            recommendation = ConfidenceRecommendation.REVIEW
        
        # Escalado si es crítico y bajo umbral
        if is_critical and overall < threshold:
            recommendation = ConfidenceRecommendation.ESCALATE

        return ConfidenceScore(
            overall=round(overall, 2),
            breakdown=signals,
            threshold_passed=threshold_passed,
            recommendation=recommendation,
            unknowns=unknowns,
            ambiguities=ambiguities
        )
