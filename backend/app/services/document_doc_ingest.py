"""
Ingestor para archivos Word 97-2003 binarios (.doc) con soporte de docx2txt
y fallback a antiword como comando externo del sistema.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Número mínimo de caracteres (sin espacios) para considerar el texto válido
_MIN_CONTENT_CHARS: int = 10


class DocIngestor:
    """Ingestor para archivos Word 97-2003 binarios (.doc).

    Estrategia de extracción en orden de prioridad:

    1. ``docx2txt`` — librería Python, sin dependencias de sistema.
    2. ``antiword`` — comando externo, fallback para archivos ``.doc`` puros.
    3. Si ambos fallan → ``ocr_result`` con ``success=False``.

    Si el texto extraído tiene menos de ``_MIN_CONTENT_CHARS`` caracteres
    (sin contar espacios), el resultado se considera vacío o ilegible y se
    retorna ``success=False``.

    El resultado siempre cumple el contrato canónico ``ocr_result``:
    ``extracted_text`` (str), ``pages`` (list), ``total_pages`` (int),
    ``success`` (bool).
    """

    async def ingest(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Extrae el texto de un archivo ``.doc``."""
        import asyncio
        loop = asyncio.get_event_loop()
        
        text: str | None = await loop.run_in_executor(None, self._try_docx2txt, file_path)

        if text is None:
            text = await loop.run_in_executor(None, self._try_antiword, file_path)

        if text is None:
            logger.error(
                "doc_ingest_all_methods_failed",
                filename=filename,
                file_path=file_path,
            )
            return {
                "extracted_text": "",
                "pages": [],
                "total_pages": 0,
                "success": False,
                "error": (
                    "No se pudo procesar el archivo .doc: "
                    "docx2txt y antiword fallaron o no están disponibles."
                ),
            }

        if len(text.strip()) < _MIN_CONTENT_CHARS:
            logger.warning(
                "doc_ingest_text_too_short",
                filename=filename,
                chars=len(text.strip()),
            )
            return {
                "extracted_text": "",
                "pages": [],
                "total_pages": 0,
                "success": False,
                "error": "Archivo .doc vacío o ilegible",
            }

        header = f"### ARCHIVO: {filename} | TIPO: DOC"
        full_text = f"{header}\n\n{text.strip()}"

        logger.info(
            "doc_ingest_success",
            filename=filename,
            chars=len(full_text),
        )

        return {
            "extracted_text": full_text,
            "pages": [{"page": "doc", "text": full_text}],
            "total_pages": 1,
            "success": True,
        }

    def _try_docx2txt(self, file_path: str) -> str | None:
        """Intenta extraer texto del archivo ``.doc`` usando ``docx2txt``.

        Importa ``docx2txt`` de forma diferida para que su ausencia no rompa
        el módulo. Si la librería no está instalada o lanza cualquier
        excepción durante el procesamiento, registra un warning y retorna
        ``None``.

        Args:
            file_path: Ruta absoluta al archivo ``.doc``.

        Returns:
            Texto extraído como cadena, o ``None`` si la extracción falla
            o produce un resultado vacío.
        """
        try:
            import docx2txt  # type: ignore[import]

            text: str | None = docx2txt.process(file_path)
            if text:
                return text
            logger.warning(
                "doc_docx2txt_empty_result",
                file_path=file_path,
            )
            return None
        except Exception as exc:
            logger.warning(
                "doc_docx2txt_failed",
                file_path=file_path,
                error=str(exc),
            )
            return None

    def _try_antiword(self, file_path: str) -> str | None:
        """Intenta extraer texto del archivo ``.doc`` usando el comando ``antiword``.

        Invoca ``antiword`` como subproceso con un timeout de 30 segundos.
        Si el comando no está disponible (``FileNotFoundError``), el proceso
        excede el timeout (``subprocess.TimeoutExpired``) o retorna un código
        de error, registra un warning y retorna ``None``.

        Args:
            file_path: Ruta absoluta al archivo ``.doc``.

        Returns:
            Texto extraído como cadena, o ``None`` si ``antiword`` no está
            disponible, falla o produce una salida vacía.
        """
        try:
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            logger.warning(
                "doc_antiword_failed",
                file_path=file_path,
                returncode=result.returncode,
                stderr=result.stderr[:200],
            )
            return None
        except FileNotFoundError as exc:
            logger.warning(
                "doc_antiword_unavailable",
                file_path=file_path,
                error=str(exc),
            )
            return None
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "doc_antiword_timeout",
                file_path=file_path,
                error=str(exc),
            )
            return None
