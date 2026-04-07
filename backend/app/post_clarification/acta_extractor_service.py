from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.agents.extractor_digital import DigitalExtractorAgent
from app.agents.extractor_vision import VisionExtractorAgent

logger = logging.getLogger(__name__)


@dataclass
class ActaExtractionResult:
    text: str
    confidence: float
    method: str
    needs_fallback_template: bool


def _is_acta_filename_hint(filename: str) -> bool:
    low = (filename or "").strip().lower()
    return any(k in low for k in ("acta", "junta", "aclaracion", "aclaraciones"))


def _calc_confidence(text: str, method: str) -> float:
    n = len((text or "").strip())
    if n < 200:
        return 0.2
    if method == "digital":
        if n >= 3500:
            return 0.95
        if n >= 1500:
            return 0.85
        return 0.75
    if method == "vision":
        if n >= 3500:
            return 0.83
        if n >= 1500:
            return 0.74
        return 0.62
    return 0.5


def _sanitize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


async def extract_acta_text(
    *,
    file_path: str,
    filename: str,
    force_vision_on_low_confidence: bool = True,
) -> ActaExtractionResult:
    """
    Extrae texto de acta usando DigitalExtractor primero y VisionExtractor como fallback.
    Devuelve señal explícita de fallback a plantilla cuando confianza < 0.7.
    """
    digital = DigitalExtractorAgent()
    vision = VisionExtractorAgent()

    method = "none"
    text = ""

    dig = await digital.extract(file_path)
    if dig.get("success"):
        text = _sanitize_text(dig.get("extracted_text") or "")
        method = "digital"
    else:
        vis = await vision.extract(file_path)
        if vis.get("success"):
            text = _sanitize_text(vis.get("extracted_text") or "")
            method = "vision"

    if not text:
        return ActaExtractionResult(
            text="",
            confidence=0.0,
            method=method,
            needs_fallback_template=True,
        )

    confidence = _calc_confidence(text, method)
    if force_vision_on_low_confidence and method == "digital" and confidence < 0.7:
        vis = await vision.extract(file_path)
        if vis.get("success"):
            vtext = _sanitize_text(vis.get("extracted_text") or "")
            vconf = _calc_confidence(vtext, "vision")
            if vconf > confidence:
                text = vtext
                confidence = vconf
                method = "vision"

    # Heurística extra: nombre con hint de acta sube un poco la confianza.
    if _is_acta_filename_hint(filename):
        confidence = min(0.99, confidence + 0.03)

    return ActaExtractionResult(
        text=text,
        confidence=round(confidence, 3),
        method=method,
        needs_fallback_template=confidence < 0.7,
    )
