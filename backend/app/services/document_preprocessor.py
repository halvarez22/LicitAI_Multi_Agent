"""
document_preprocessor.py — Pre-procesador de documentos para extracción semántica dirigida.

Filtra un texto largo para extraer solo las secciones relevantes para un dato específico,
sin usar el LLM. Reduce el costo de API hasta un 90% al enviar solo el fragmento relevante.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Palabras de contexto de licitación que aumentan el score de relevancia
_LICITACION_CONTEXT_WORDS = frozenset({
    "monto", "precio", "capital", "contable", "facturación", "facturacion",
    "patrimonio", "solvencia", "económica", "economica", "legal", "técnica",
    "tecnica", "requisito", "acreditar", "documento", "anexo", "contrato",
    "licitación", "licitacion", "propuesta", "empresa", "rfc", "imss",
    "registro", "representante", "domicilio", "fiscal", "constitutiva",
    "experiencia", "años", "anios", "empleados", "plantilla", "garantía",
    "garantia", "penalización", "penalizacion", "pago", "condición", "condicion",
    "total", "suma", "importe", "valor", "cantidad", "número", "numero",
    "mes", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
})

# Stopwords en español para limpiar keywords
_STOPWORDS = frozenset({
    "de", "la", "el", "en", "y", "a", "los", "las", "del", "al",
    "un", "una", "por", "con", "para", "es", "se", "que", "su",
    "lo", "le", "no", "si", "o", "e", "u", "ni", "pero", "más",
    "mas", "como", "este", "esta", "estos", "estas", "ese", "esa",
    "mi", "tu", "su", "nos", "les", "me", "te", "mínimo", "minimo",
})


@dataclass
class PreprocessResult:
    """Resultado del pre-procesamiento de un documento."""
    relevant_text: str
    total_chars_original: int
    total_chars_filtered: int
    reduction_ratio: float          # 0.0 a 1.0
    keywords_found: List[str] = field(default_factory=list)


class DocumentPreprocessor:
    """
    Pre-procesa un archivo para extraer solo las secciones relevantes
    para un dato específico, sin usar el LLM.

    Estrategia de scoring por chunk:
    - +3 puntos por cada keyword del dato_solicitado encontrada (case-insensitive)
    - +2 puntos si el chunk contiene dígitos
    - +1 punto por palabras de contexto de licitación
    """

    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K_CHUNKS: int = 6

    def extract_relevant_sections(
        self,
        extracted_text: str,
        dato_solicitado: str,
        max_tokens: int = 3000,
    ) -> PreprocessResult:
        """
        Extrae las secciones más relevantes del texto para el dato solicitado.

        Args:
            extracted_text: Texto completo del documento (del DocumentIngestionRouter).
            dato_solicitado: Label legible del dato que se busca (ej: "Capital contable mínimo").
            max_tokens: Límite de tokens aproximado para el output (1 token ≈ 4 chars).

        Returns:
            PreprocessResult con el fragmento relevante y métricas de reducción.
        """
        try:
            if not extracted_text or not extracted_text.strip():
                return PreprocessResult(
                    relevant_text="",
                    total_chars_original=0,
                    total_chars_filtered=0,
                    reduction_ratio=0.0,
                    keywords_found=[],
                )

            total_chars_original = len(extracted_text)
            keywords = self._extract_keywords(dato_solicitado)

            chunks = self._split_into_chunks(extracted_text)
            if not chunks:
                return PreprocessResult(
                    relevant_text=extracted_text[:max_tokens * 4],
                    total_chars_original=total_chars_original,
                    total_chars_filtered=min(total_chars_original, max_tokens * 4),
                    reduction_ratio=0.0,
                    keywords_found=keywords,
                )

            # Calcular scores y seleccionar top-K
            scored = [(self._score_chunk(chunk, keywords), chunk) for chunk in chunks]
            scored.sort(key=lambda x: x[0], reverse=True)
            top_chunks = [chunk for _, chunk in scored[:self.TOP_K_CHUNKS]]

            # Concatenar con separador y truncar
            relevant_text = "\n---\n".join(top_chunks)
            max_chars = max_tokens * 4
            if len(relevant_text) > max_chars:
                relevant_text = relevant_text[:max_chars]

            total_chars_filtered = len(relevant_text)
            reduction_ratio = max(0.0, min(1.0, 1.0 - (total_chars_filtered / total_chars_original)))

            # Detectar qué keywords se encontraron realmente
            text_lower = extracted_text.lower()
            keywords_found = [kw for kw in keywords if kw.lower() in text_lower]

            logger.info(
                "document_preprocessor_complete",
                original_chars=total_chars_original,
                filtered_chars=total_chars_filtered,
                reduction_ratio=round(reduction_ratio, 3),
                keywords_found=keywords_found[:5],
            )

            return PreprocessResult(
                relevant_text=relevant_text,
                total_chars_original=total_chars_original,
                total_chars_filtered=total_chars_filtered,
                reduction_ratio=reduction_ratio,
                keywords_found=keywords_found,
            )

        except Exception as e:
            logger.warning("document_preprocessor_error", error=str(e)[:120])
            # Fallback: retornar el inicio del texto truncado
            safe_text = str(extracted_text or "")[:max_tokens * 4] if extracted_text else ""
            return PreprocessResult(
                relevant_text=safe_text,
                total_chars_original=len(extracted_text) if extracted_text else 0,
                total_chars_filtered=len(safe_text),
                reduction_ratio=0.0,
                keywords_found=[],
            )

    def _extract_keywords(self, dato_solicitado: str) -> List[str]:
        """
        Extrae keywords significativas del dato_solicitado, eliminando stopwords.

        Args:
            dato_solicitado: Label legible del dato (ej: "Capital contable mínimo").

        Returns:
            Lista de keywords en minúsculas.
        """
        if not dato_solicitado:
            return []

        # Tokenizar: dividir por espacios, comas, puntos, guiones
        tokens = re.split(r"[\s,.:;()\-/]+", dato_solicitado.lower())
        keywords = [
            t.strip()
            for t in tokens
            if t.strip() and len(t.strip()) > 2 and t.strip() not in _STOPWORDS
        ]
        return list(dict.fromkeys(keywords))  # deduplicar preservando orden

    def _score_chunk(self, chunk: str, keywords: List[str]) -> int:
        """
        Calcula el score de relevancia de un chunk.

        Scoring:
        - +3 por cada keyword del dato_solicitado encontrada
        - +2 si el chunk contiene dígitos
        - +1 por palabras de contexto de licitación

        Args:
            chunk: Fragmento de texto a evaluar.
            keywords: Keywords del dato_solicitado.

        Returns:
            Score de relevancia (entero ≥ 0).
        """
        score = 0
        chunk_lower = chunk.lower()

        # +3 por cada keyword del dato solicitado
        for kw in keywords:
            if kw in chunk_lower:
                score += 3

        # +2 si contiene dígitos (datos numéricos)
        if re.search(r"\d", chunk):
            score += 2

        # +1 por palabras de contexto de licitación
        for word in _LICITACION_CONTEXT_WORDS:
            if word in chunk_lower:
                score += 1
                break  # solo +1 aunque haya múltiples palabras de contexto

        return score

    def _split_into_chunks(self, text: str) -> List[str]:
        """
        Divide el texto en chunks de CHUNK_SIZE caracteres con overlap de CHUNK_OVERLAP.

        Args:
            text: Texto a dividir.

        Returns:
            Lista de chunks.
        """
        if not text:
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + self.CHUNK_SIZE, text_len)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += self.CHUNK_SIZE - self.CHUNK_OVERLAP

        return chunks
