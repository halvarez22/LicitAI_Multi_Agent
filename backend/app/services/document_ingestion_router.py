"""
Router canónico de ingesta de documentos para LicitAI.

Consolida toda la lógica de selección de ingestor en un único punto de entrada
que ambos caminos de ingesta (A: upload.py y B: agents.py) deben usar.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging_config import get_logger
from app.memory.repository import MemoryRepository

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes públicas
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "xlsx", "xls", "csv", "txt"}
)

# Claves canónicas y sus valores por defecto
_CANONICAL_DEFAULTS: Dict[str, Any] = {
    "extracted_text": "",
    "pages": [],
    "total_pages": 0,
    "success": False,
}


# ---------------------------------------------------------------------------
# Normalización del resultado canónico
# ---------------------------------------------------------------------------


def _normalize_ocr_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Garantiza que el resultado cumple el contrato canónico ``ocr_result``.

    Completa las claves faltantes con valores por defecto y fuerza
    ``success=False`` cuando ``extracted_text`` está vacío o contiene
    únicamente espacios en blanco tras la normalización.

    Args:
        raw: Diccionario retornado por cualquier ingestor. Puede contener
            un subconjunto de las claves canónicas o claves adicionales.

    Returns:
        Diccionario con las cuatro claves canónicas garantizadas:

        - ``extracted_text`` (str): Texto completo extraído.
        - ``pages`` (list): Lista de páginas con su texto individual.
        - ``total_pages`` (int): Número total de páginas/secciones.
        - ``success`` (bool): ``True`` solo si hay texto significativo.

        Las claves adicionales presentes en ``raw`` se preservan.
    """
    result: Dict[str, Any] = {**_CANONICAL_DEFAULTS, **raw}

    # Asegurar tipos correctos para cada clave canónica
    result["extracted_text"] = str(result.get("extracted_text") or "")
    result["pages"] = list(result.get("pages") or [])
    result["total_pages"] = int(result.get("total_pages") or len(result["pages"]))
    result["success"] = bool(result.get("success", False))

    # Req 7.3: success=False si extracted_text vacío o solo espacios
    if not result["extracted_text"].strip():
        result["success"] = False

    return result


def normalize_ocr_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Alias público de ``_normalize_ocr_result`` para uso en tests.

    Args:
        raw: Diccionario retornado por cualquier ingestor.

    Returns:
        Diccionario con las claves canónicas garantizadas. Ver
        ``_normalize_ocr_result`` para la descripción completa.
    """
    return _normalize_ocr_result(raw)


# ---------------------------------------------------------------------------
# Router principal
# ---------------------------------------------------------------------------


class DocumentIngestionRouter:
    """Router canónico de ingesta de documentos.

    Recibe cualquier documento y delega al ingestor correcto según la
    extensión del archivo. Ambos caminos de ingesta (A: ``upload.py`` y
    B: ``agents.py``) deben usar este componente como único punto de entrada.

    Garantías:
        - El resultado siempre cumple el contrato ``ocr_result`` canónico.
        - Las extensiones se comparan en minúsculas (case-insensitive).
        - Cualquier excepción del ingestor delegado es capturada y retornada
          como ``ocr_result`` con ``success=False``.
    """

    async def ingest(
        self,
        file_path: str,
        filename: str,
        session_id: str,
        doc_id: str,
        memory: MemoryRepository,
    ) -> Dict[str, Any]:
        """Ingesta un documento y retorna un ``ocr_result`` canónico.

        Extrae la extensión del nombre de archivo en minúsculas, delega al
        ingestor correspondiente y normaliza el resultado antes de retornarlo.
        Cualquier excepción lanzada por el ingestor delegado es capturada y
        convertida en un ``ocr_result`` con ``success=False``.

        Args:
            file_path: Ruta absoluta al archivo en disco.
            filename: Nombre original del archivo, usado para determinar la
                extensión y para encabezados de logging.
            session_id: Identificador de la sesión de licitación.
            doc_id: Identificador del documento en la base de datos.
            memory: Repositorio de persistencia de sesiones y documentos.

        Returns:
            Diccionario ``ocr_result`` canónico con las claves:

            - ``extracted_text`` (str): Texto completo extraído.
            - ``pages`` (list): Lista de páginas con su texto individual.
            - ``total_pages`` (int): Número total de páginas/secciones.
            - ``success`` (bool): ``True`` si la extracción fue exitosa.
            - ``error`` (str, opcional): Mensaje de error si ``success=False``.
        """
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        logger.info(
            "document_ingestion_start",
            doc_id=doc_id,
            session_id=session_id,
            filename=filename,
            ext=ext,
        )

        try:
            raw = await self._delegate(
                ext, file_path, filename, session_id, doc_id, memory
            )
        except Exception as exc:
            logger.error(
                "document_ingestion_error",
                doc_id=doc_id,
                session_id=session_id,
                ext=ext,
                error=str(exc),
            )
            raw = {
                "extracted_text": "",
                "pages": [],
                "total_pages": 0,
                "success": False,
                "error": str(exc),
            }

        result = _normalize_ocr_result(raw)

        logger.info(
            "document_ingestion_complete",
            doc_id=doc_id,
            session_id=session_id,
            success=result["success"],
            chars=len(result["extracted_text"]),
        )

        return result

    async def _delegate(
        self,
        ext: str,
        file_path: str,
        filename: str,
        session_id: str,
        doc_id: str,
        memory: MemoryRepository,
    ) -> Dict[str, Any]:
        """Delega al ingestor correcto según la extensión del archivo.

        Las importaciones de los ingestores se realizan de forma diferida
        (dentro del método) para evitar dependencias circulares y reducir
        el tiempo de arranque del módulo.

        Args:
            ext: Extensión del archivo en minúsculas, sin punto (p. ej. ``"pdf"``).
            file_path: Ruta absoluta al archivo en disco.
            filename: Nombre original del archivo.
            session_id: Identificador de la sesión de licitación.
            doc_id: Identificador del documento en la base de datos.
            memory: Repositorio de persistencia de sesiones y documentos.

        Returns:
            Resultado crudo del ingestor delegado. Puede ser un subconjunto
            del contrato canónico; ``_normalize_ocr_result`` se encarga de
            completar las claves faltantes.
        """
        if ext in ("xlsx", "xls"):
            from app.services.document_excel_ingest import process_excel_document

            ocr_result, _ = await process_excel_document(
                memory, session_id, doc_id, file_path, filename
            )
            return ocr_result

        if ext == "csv":
            from app.services.document_csv_ingest import process_csv_document

            ocr_result, _ = await process_csv_document(
                memory, session_id, doc_id, file_path, filename
            )
            return ocr_result

        if ext == "docx":
            from app.services.document_docx_ingest import process_docx_document

            ocr_result, _ = await process_docx_document(
                memory, session_id, doc_id, file_path, filename
            )
            return ocr_result

        if ext == "doc":
            from app.services.document_doc_ingest import DocIngestor

            return await DocIngestor().ingest(file_path, filename)

        if ext == "txt":
            from app.services.document_txt_ingest import TxtIngestor

            return await TxtIngestor().ingest(file_path, filename)

        # .pdf y cualquier extensión no reconocida → pipeline OCR
        from app.services.ocr_service import OCRServiceClient

        return await OCRServiceClient().scan_document(file_path)
