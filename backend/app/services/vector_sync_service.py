"""
VectorSyncService — Servicio de Sincronización y Auto-Curación de Vectores (Hito 11).

Resuelve el desacoplamiento de estado entre PostgreSQL (fuente de verdad del texto extraído)
y ChromaDB (índice de búsqueda semántica).

Garantías:
  - Si Postgres dice ANALYZED pero ChromaDB tiene 0 chunks → re-indexa automáticamente.
  - Idempotente: borra chunks existentes del doc antes de re-indexar (evita duplicados).
  - Silencioso: no interrumpe al usuario ni requiere re-subir el PDF.
  - Universal: aplica a cualquier sesión, no es un parche por licitación.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from app.core.logging_config import get_logger
from app.services.vector_service import VectorDbServiceClient

logger = get_logger(__name__)

# Umbral mínimo de chunks esperados por página de texto.
# Si la colección tiene menos que (total_pages * CHUNKS_PER_PAGE_MIN) chunks,
# se considera desincronizada y se dispara la auto-curación.
CHUNKS_PER_PAGE_MIN: int = 1

# Número mínimo de caracteres de texto para considerar que un doc tiene contenido real.
MIN_TEXT_CHARS: int = 100


def _split_by_page_markers(text: str) -> List[Dict[str, Any]]:
    """
    Divide el texto extraído usando los marcadores de página del DigitalExtractorAgent.

    El DigitalExtractorAgent escribe marcadores con el formato:
        ``--- PÁGINA N ---``

    Args:
        text: Texto completo extraído, con marcadores de página.

    Returns:
        Lista de dicts ``{"page": int, "text": str}`` en orden de página.
        Si no se encuentran marcadores, retorna una sola entrada con page=1 y
        todo el texto (compatibilidad con documentos sin paginación).
    """
    parts = re.split(r"\n?--- PÁGINA (\d+) ---\n?", text)

    # Si no hay marcadores, tratamos el texto completo como página 1
    if len(parts) <= 1:
        stripped = text.strip()
        return [{"page": 1, "text": stripped}] if stripped else []

    pages: List[Dict[str, Any]] = []
    # parts[0] = texto antes del primer marcador (generalmente vacío)
    # Luego alternamos: número de página, texto de página
    for i in range(1, len(parts) - 1, 2):
        try:
            page_num = int(parts[i])
        except (ValueError, IndexError):
            continue
        page_text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if page_text:
            pages.append({"page": page_num, "text": page_text})

    return pages


class VectorSyncService:
    """
    Servicio de sincronización bidireccional entre PostgreSQL y ChromaDB.

    Uso típico (en ChatbotRAGAgent o al iniciar cualquier sesión):

        sync_svc = VectorSyncService()
        result = await sync_svc.ensure_session_indexed(memory, session_id)
        if result["healed"]:
            logger.info("Auto-curación completada: %d páginas re-indexadas", result["pages_indexed"])
    """

    def __init__(self) -> None:
        self._vector_client = VectorDbServiceClient()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def ensure_session_indexed(
        self,
        memory: Any,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Verifica que la sesión tenga vectores coherentes con su estado en Postgres.

        Algoritmo:
        1. Obtiene todos los documentos ANALYZED de la sesión desde Postgres.
        2. Para cada doc, cuenta chunks en ChromaDB filtrando por doc_id.
        3. Si chunks == 0 (y el texto extraído existe), dispara ``_heal_document``.
        4. Retorna un resumen de la operación.

        Args:
            memory: Repositorio de persistencia (MemoryRepository).
            session_id: ID de la sesión de licitación.

        Returns:
            Dict con claves:
            - ``healed`` (bool): True si se re-indexó al menos un documento.
            - ``docs_checked`` (int): Número de documentos revisados.
            - ``docs_healed`` (int): Número de documentos que necesitaron re-indexación.
            - ``pages_indexed`` (int): Total de páginas indexadas en esta operación.
            - ``errors`` (list[str]): Errores no críticos encontrados.
        """
        result: Dict[str, Any] = {
            "healed": False,
            "docs_checked": 0,
            "docs_healed": 0,
            "pages_indexed": 0,
            "errors": [],
        }

        try:
            docs = await memory.get_documents(session_id)
        except Exception as exc:
            logger.error(
                "vector_sync_get_docs_failed",
                session_id=session_id,
                error=str(exc),
            )
            result["errors"].append(f"get_documents: {exc}")
            return result

        analyzed = [
            d for d in (docs or [])
            if d.get("content", {}).get("status") == "ANALYZED"
        ]

        result["docs_checked"] = len(analyzed)

        for doc in analyzed:
            doc_id = str(doc.get("id") or "")
            content = doc.get("content") or {}
            filename = str(content.get("filename") or "desconocido")
            extracted_text = str(content.get("extracted_text") or "")
            total_pages_pg = int(content.get("total_pages") or 0)

            if not doc_id or len(extracted_text) < MIN_TEXT_CHARS:
                logger.debug(
                    "vector_sync_skip_doc",
                    session_id=session_id,
                    doc_id=doc_id,
                    reason="no_text_or_id",
                )
                continue

            # ── Conteo de chunks en ChromaDB para este doc_id ────────────────
            current_chunks = self._count_chunks(session_id, doc_id)
            expected_min = max(1, total_pages_pg) * CHUNKS_PER_PAGE_MIN

            if current_chunks >= expected_min:
                logger.debug(
                    "vector_sync_ok",
                    session_id=session_id,
                    doc_id=doc_id,
                    chunks=current_chunks,
                    expected_min=expected_min,
                )
                continue

            # ── Desincronización detectada → auto-curación ───────────────────
            logger.warning(
                "vector_sync_desync_detected",
                session_id=session_id,
                doc_id=doc_id,
                filename=filename,
                current_chunks=current_chunks,
                expected_min=expected_min,
            )

            try:
                pages_indexed = self._heal_document(
                    session_id=session_id,
                    doc_id=doc_id,
                    filename=filename,
                    extracted_text=extracted_text,
                )
                result["docs_healed"] += 1
                result["pages_indexed"] += pages_indexed
                result["healed"] = True

                logger.info(
                    "vector_sync_healed",
                    session_id=session_id,
                    doc_id=doc_id,
                    filename=filename,
                    pages_indexed=pages_indexed,
                )
            except Exception as exc:
                err_msg = f"heal_document({doc_id}): {exc}"
                logger.error("vector_sync_heal_failed", session_id=session_id, error=err_msg)
                result["errors"].append(err_msg)

        return result

    # ------------------------------------------------------------------
    # Métodos internos
    # ------------------------------------------------------------------

    def _count_chunks(self, session_id: str, doc_id: str) -> int:
        """Retorna el número de chunks en ChromaDB para un doc_id específico."""
        try:
            coll = self._vector_client.get_or_create_collection(session_id)
            if not coll:
                return 0
            res = coll.get(where={"doc_id": doc_id})
            return len(res.get("ids") or [])
        except Exception as exc:
            logger.warning(
                "vector_sync_count_failed",
                session_id=session_id,
                doc_id=doc_id,
                error=str(exc),
            )
            return 0

    def _heal_document(
        self,
        session_id: str,
        doc_id: str,
        filename: str,
        extracted_text: str,
    ) -> int:
        """
        Re-indexa un documento desde el texto almacenado en Postgres.

        Pasos:
        1. Borra TODOS los chunks existentes del doc_id en ChromaDB (idempotencia).
        2. Divide el texto en páginas usando los marcadores del DigitalExtractor.
        3. Indexa cada página como un chunk atómico (misma lógica que upload.py).

        Args:
            session_id: ID de sesión.
            doc_id: ID del documento.
            filename: Nombre del archivo (para metadatos y encabezado del chunk).
            extracted_text: Texto completo extraído guardado en Postgres.

        Returns:
            Número de páginas indexadas exitosamente.
        """
        # ── Paso 1: Purga idempotente ─────────────────────────────────────────
        try:
            self._vector_client.delete_by_doc_id(session_id, doc_id)
            logger.debug(
                "vector_sync_purged",
                session_id=session_id,
                doc_id=doc_id,
            )
        except Exception as exc:
            # La purga es best-effort; si falla, continuamos igual.
            logger.warning(
                "vector_sync_purge_failed",
                session_id=session_id,
                doc_id=doc_id,
                error=str(exc),
            )

        # ── Paso 2: División en páginas ───────────────────────────────────────
        pages = _split_by_page_markers(extracted_text)
        if not pages:
            logger.warning(
                "vector_sync_no_pages",
                session_id=session_id,
                doc_id=doc_id,
                filename=filename,
            )
            return 0

        # ── Paso 3: Re-indexación atómica por página ──────────────────────────
        indexed = 0
        for page in pages:
            p_num = page["page"]
            p_text = page["text"]
            if not p_text:
                continue

            # Mismo formato que upload.py → consistencia total
            header = f"[FUENTE: {filename} | PÁGINA: {p_num}]\n"
            full_chunk = header + p_text

            metadatas = [{
                "source": filename,
                "session_id": session_id,
                "page": p_num,
                "doc_id": doc_id,
                "chunk_type": "page_atomic",
                "reindexed": True,  # Trazabilidad: fue una auto-curación
            }]

            try:
                self._vector_client.add_texts(session_id, [full_chunk], metadatas)
                indexed += 1
            except Exception as exc:
                logger.error(
                    "vector_sync_add_texts_failed",
                    session_id=session_id,
                    doc_id=doc_id,
                    page=p_num,
                    error=str(exc),
                )

        return indexed
