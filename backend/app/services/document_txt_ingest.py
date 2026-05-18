"""
Ingestor para archivos de texto plano (.txt) con detección automática de encoding.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Encodings a intentar en orden de prioridad
_ENCODINGS: tuple[str, ...] = ("utf-8", "latin-1")


class TxtIngestor:
    """Ingestor para archivos de texto plano (.txt).

    Intenta leer el archivo con UTF-8 primero; si falla por error de
    decodificación, reintenta con Latin-1. Si ambos encodings fallan,
    retorna un ``ocr_result`` con ``success=False`` y un mensaje descriptivo.

    El resultado siempre cumple el contrato canónico ``ocr_result``:
    ``extracted_text`` (str), ``pages`` (list), ``total_pages`` (int),
    ``success`` (bool).
    """

    async def ingest(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Extrae el contenido de un archivo .txt con detección de encoding.

        Intenta la lectura con ``utf-8`` primero. Si se produce un
        ``UnicodeDecodeError``, registra un warning y reintenta con
        ``latin-1``. Si ambos encodings fallan, retorna ``success=False``.
        Cualquier error de E/S (``OSError``) se captura y retorna
        inmediatamente con ``success=False``.

        Args:
            file_path: Ruta absoluta al archivo ``.txt`` en disco.
            filename: Nombre original del archivo, usado en el encabezado
                del texto extraído y en los mensajes de log.

        Returns:
            Diccionario ``ocr_result`` con las claves:

            - ``extracted_text`` (str): Texto completo con encabezado
              ``### ARCHIVO: {filename} | TIPO: TXT`` seguido del contenido.
            - ``pages`` (list[dict]): Lista con un único elemento
              ``{"page": "txt", "text": <texto_completo>}``.
            - ``total_pages`` (int): Siempre ``1`` en caso exitoso.
            - ``success`` (bool): ``True`` si la lectura fue exitosa.
            - ``error`` (str, opcional): Mensaje descriptivo si
              ``success=False``.
        """
        content: str | None = None

        for encoding in _ENCODINGS:
            try:
                with open(file_path, "r", encoding=encoding) as fh:
                    content = fh.read()
                # Lectura exitosa: salir del bucle
                break
            except UnicodeDecodeError:
                logger.warning(
                    "txt_encoding_fallback",
                    filename=filename,
                    encoding_failed=encoding,
                )
                continue
            except OSError as exc:
                logger.error(
                    "txt_read_error",
                    filename=filename,
                    file_path=file_path,
                    error=str(exc),
                )
                return {
                    "extracted_text": "",
                    "pages": [],
                    "total_pages": 0,
                    "success": False,
                    "error": f"Error al leer el archivo: {exc}",
                }

        if content is None:
            return {
                "extracted_text": "",
                "pages": [],
                "total_pages": 0,
                "success": False,
                "error": (
                    "No se pudo decodificar el archivo con UTF-8 ni Latin-1."
                ),
            }

        header = f"### ARCHIVO: {filename} | TIPO: TXT"
        full_text = f"{header}\n\n{content}"

        return {
            "extracted_text": full_text,
            "pages": [{"page": "txt", "text": full_text}],
            "total_pages": 1,
            "success": True,
        }
