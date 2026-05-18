"""
mission_data_extractor.py — Extractor semántico dirigido por misión activa.

Extrae un dato específico de un fragmento de texto usando el LLM,
guiado por el mission_context activo del ChatbotRAGAgent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractionResult:
    """Resultado de la extracción semántica de un dato."""
    value: Optional[str]            # None si no se encontró
    confidence: float               # 0.0 a 1.0
    source_reference: str           # "Hoja 2, fila 15" o "Página 3, párrafo 2"
    raw_snippet: str                # fragmento exacto del texto donde se encontró
    extraction_status: str          # "found" | "not_found" | "ambiguous"

    def __post_init__(self):
        # Clampear confidence al rango [0.0, 1.0]
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        # Validar extraction_status
        if self.extraction_status not in ("found", "not_found", "ambiguous"):
            self.extraction_status = "not_found"


_NOT_FOUND_RESULT = ExtractionResult(
    value=None,
    confidence=0.0,
    source_reference="",
    raw_snippet="",
    extraction_status="not_found",
)


class MissionDataExtractor:
    """
    Extrae un dato específico de un fragmento de texto usando el LLM,
    guiado por el mission_context activo.

    Usa temperatura baja (0.1) para extracción determinista.
    Nunca lanza excepciones — degrada a not_found en caso de error.
    """

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: Instancia de ResilientLLMClient.
        """
        self.llm = llm_client

    async def extract(
        self,
        relevant_text: str,
        mission_context: Dict[str, Any],
        correlation_id: str = "",
    ) -> ExtractionResult:
        """
        Extrae el dato solicitado del fragmento de texto.

        Args:
            relevant_text: Fragmento de texto ya filtrado por DocumentPreprocessor.
            mission_context: Contexto de misión con dato_solicitado y por_que_importa.

        Returns:
            ExtractionResult con el valor encontrado y metadatos de extracción.
        """
        if not relevant_text or not relevant_text.strip():
            logger.info("mission_extractor_empty_text")
            return _NOT_FOUND_RESULT

        dato_solicitado = str(mission_context.get("dato_solicitado") or "Dato requerido")
        por_que_importa = str(mission_context.get("por_que_importa") or "")

        system_prompt = f"""Eres un extractor de datos para licitaciones públicas mexicanas.
Tu tarea es encontrar UN dato específico en el texto proporcionado.

Dato a buscar: {dato_solicitado}
Contexto: {por_que_importa}

REGLAS:
1. Extrae SOLO el valor del dato solicitado, nada más.
2. Indica en qué parte del texto lo encontraste (referencia de origen: hoja, fila, página, párrafo).
3. Si hay múltiples valores posibles, elige el más reciente o el más específico.
4. Si NO encuentras el dato, responde con extraction_status="not_found" y value=null.
5. Si hay ambigüedad (múltiples valores igualmente válidos), responde con extraction_status="ambiguous" y value con la opción más probable.

Responde SOLO en JSON válido con este esquema exacto:
{{"value": "string o null", "confidence": 0.0, "source_reference": "string", "raw_snippet": "string", "extraction_status": "found|not_found|ambiguous"}}"""

        user_prompt = f"""Texto del documento:
---
{relevant_text[:8000]}
---

Encuentra el valor de: {dato_solicitado}"""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            response = await self.llm.chat(
                messages=messages,
                options={"temperature": 0.1, "num_predict": 300},
                correlation_id=correlation_id,
            )
            if not response.success or not response.response:
                logger.warning(f"mission_extractor_empty_llm_response: {response.error}")
                return _NOT_FOUND_RESULT

            raw_response = response.response.strip()

            # Extraer JSON de la respuesta (puede venir envuelto en markdown)
            json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if not json_match:
                logger.warning("mission_extractor_no_json_in_response", response=raw_response[:100])
                return _NOT_FOUND_RESULT

            parsed = json.loads(json_match.group())

            result = ExtractionResult(
                value=parsed.get("value") or None,
                confidence=float(parsed.get("confidence") or 0.0),
                source_reference=str(parsed.get("source_reference") or ""),
                raw_snippet=str(parsed.get("raw_snippet") or ""),
                extraction_status=str(parsed.get("extraction_status") or "not_found"),
            )

            logger.info(
                "mission_extractor_complete",
                dato_solicitado=dato_solicitado[:50],
                extraction_status=result.extraction_status,
                confidence=result.confidence,
                value_preview=str(result.value or "")[:50],
            )

            return result

        except json.JSONDecodeError as e:
            logger.warning("mission_extractor_json_parse_error", error=str(e)[:80])
            return _NOT_FOUND_RESULT
        except Exception as e:
            logger.warning("mission_extractor_llm_error", error=str(e)[:120])
            return _NOT_FOUND_RESULT
