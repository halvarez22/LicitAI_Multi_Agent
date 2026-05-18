# Design Document — Universal Document Ingestion

## Overview

Esta feature cierra cuatro huecos de ingesta en LicitAI y consolida toda la lógica de routing en un único componente canónico: `DocumentIngestionRouter`. El objetivo es garantizar que cualquier tipo de archivo soportado (`.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.csv`, `.txt`) produzca un payload `ocr_result` estructurado, indexable en ChromaDB y disponible para el RAG, independientemente del camino de ingesta (A o B).

### Huecos que se cierran

| # | Problema | Solución |
|---|---|---|
| 1 | `.txt` sin ingestor → fitz falla | Nuevo `TxtIngestor` con detección de encoding |
| 2 | Routing duplicado en Camino A y B | `DocumentIngestionRouter` como punto único canónico |
| 3 | Tablas PDF extraídas como texto plano | `DigitalExtractorAgent` extendido con `page.find_tables()` |
| 4 | `.doc` sin soporte | Nuevo `DocIngestor` con `docx2txt` + fallback `antiword` |

### Principios de diseño

- **Compatibilidad hacia atrás**: los ingestores existentes (`document_excel_ingest.py`, `document_csv_ingest.py`, `document_docx_ingest.py`) no se modifican; el router los envuelve.
- **Contrato canónico único**: todo ingestor produce el mismo esquema `ocr_result` con claves `extracted_text`, `pages`, `total_pages`, `success`.
- **Separación de responsabilidades**: cada ingestor vive en su propio módulo bajo `backend/app/services/`.
- **Degradación graciosa**: cualquier fallo en un ingestor produce un `ocr_result` con `success=False` en lugar de propagar la excepción.

---

## Architecture

### Diagrama de componentes

```mermaid
graph TD
    subgraph "Camino A — Explícito"
        UA[POST /upload/process/{doc_id}]
    end

    subgraph "Camino B — Background"
        OB[_run_orchestrator_job]
    end

    UA --> DIR[DocumentIngestionRouter]
    OB --> DIR

    DIR -->|.xlsx / .xls| EI[process_excel_document]
    DIR -->|.csv| CI[process_csv_document]
    DIR -->|.docx| DXI[process_docx_document]
    DIR -->|.doc| DOI[DocIngestor]
    DIR -->|.txt| TXI[TxtIngestor]
    DIR -->|.pdf / otros| OCR[OCRServiceClient]

    OCR --> DEA[DigitalExtractorAgent]
    DEA -->|page.find_tables| PTE[PdfTableExtractor logic]
    DEA -->|page.get_text| PT[Texto plano]

    DIR --> NORM[_normalize_ocr_result]
    NORM --> CR[ocr_result canónico]

    CR --> VDB[VectorDbServiceClient / ChromaDB]
    CR --> MR[MemoryRepository / PostgreSQL]

    subgraph "Validación de subida"
        UPL[POST /upload/document]
        UPL -->|extensión no permitida| E415[HTTP 415]
        UPL -->|extensión permitida| SAVE[Guardar en disco]
    end
```

### Flujo de datos

```
Archivo subido
    │
    ▼
POST /upload/document
    │  Validar extensión (lista blanca)
    │  Guardar en disco → estado UPLOADED
    ▼
POST /upload/process/{doc_id}  ──OR──  _run_orchestrator_job (background)
    │
    ▼
DocumentIngestionRouter.ingest(file_path, filename, session_id, doc_id, memory)
    │
    ├── .xlsx/.xls  → process_excel_document  → (ocr_result, line_items)
    ├── .csv        → process_csv_document    → (ocr_result, line_items)
    ├── .docx       → process_docx_document   → (ocr_result, line_items)
    ├── .doc        → DocIngestor.ingest       → ocr_result
    ├── .txt        → TxtIngestor.ingest       → ocr_result
    └── .pdf/otros  → OCRServiceClient.scan_document → ocr_result
                              │
                              └── DigitalExtractorAgent.extract
                                        │
                                        ├── page.find_tables() → markdown
                                        └── page.get_text()    → texto plano
    │
    ▼
_normalize_ocr_result(raw_result) → ocr_result canónico garantizado
    │
    ├── VectorDbServiceClient.add_texts(chunks, metadatas)
    └── MemoryRepository.save_document(status=ANALYZED)
```

---

## Components and Interfaces

### 1. DocumentIngestionRouter

**Archivo:** `backend/app/services/document_ingestion_router.py`

Componente central que recibe cualquier documento y delega al ingestor correcto según la extensión. Garantiza que el resultado siempre cumple el contrato canónico `ocr_result`.

```python
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.logging_config import get_logger
from app.memory.repository import MemoryRepository

logger = get_logger(__name__)

# Extensiones soportadas (en minúsculas)
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


def _normalize_ocr_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Garantiza que el resultado cumple el contrato canónico ocr_result.

    Completa claves faltantes con valores por defecto y fuerza success=False
    cuando extracted_text está vacío tras la normalización.

    Args:
        raw: Diccionario retornado por cualquier ingestor.

    Returns:
        Diccionario con las claves canónicas garantizadas.
    """
    result: Dict[str, Any] = {**_CANONICAL_DEFAULTS, **raw}
    # Asegurar tipos correctos
    result["extracted_text"] = str(result.get("extracted_text") or "")
    result["pages"] = list(result.get("pages") or [])
    result["total_pages"] = int(result.get("total_pages") or len(result["pages"]))
    result["success"] = bool(result.get("success", False))
    # Req 7.3: success=False si extracted_text vacío
    if not result["extracted_text"].strip():
        result["success"] = False
    return result


class DocumentIngestionRouter:
    """Router canónico de ingesta de documentos.

    Recibe cualquier documento y delega al ingestor correcto según la extensión
    del archivo. Ambos caminos de ingesta (A: upload.py y B: agents.py) deben
    usar este componente como único punto de entrada.

    Garantías:
    - El resultado siempre cumple el contrato ocr_result canónico.
    - Las extensiones se comparan en minúsculas (case-insensitive).
    - Cualquier excepción del ingestor delegado es capturada y retornada
      como ocr_result con success=False.
    """

    async def ingest(
        self,
        file_path: str,
        filename: str,
        session_id: str,
        doc_id: str,
        memory: MemoryRepository,
    ) -> Dict[str, Any]:
        """Ingesta un documento y retorna un ocr_result canónico.

        Args:
            file_path: Ruta absoluta al archivo en disco.
            filename: Nombre original del archivo (usado para encabezados y logging).
            session_id: ID de la sesión de licitación.
            doc_id: ID del documento en la base de datos.
            memory: Repositorio de persistencia de sesiones y documentos.

        Returns:
            ocr_result canónico con claves: extracted_text (str), pages (list),
            total_pages (int), success (bool).
        """
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        logger.info(
            "document_ingestion_start",
            doc_id=doc_id,
            session_id=session_id,
            ext=ext,
        )
        try:
            raw = await self._delegate(ext, file_path, filename, session_id, doc_id, memory)
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
        """Delega al ingestor correcto según la extensión.

        Args:
            ext: Extensión del archivo en minúsculas (sin punto).
            file_path: Ruta absoluta al archivo.
            filename: Nombre original del archivo.
            session_id: ID de la sesión.
            doc_id: ID del documento.
            memory: Repositorio de persistencia.

        Returns:
            Resultado crudo del ingestor delegado.
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
```

**Función auxiliar de normalización (pública para tests):**

```python
def normalize_ocr_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Alias público de _normalize_ocr_result para uso en tests."""
    return _normalize_ocr_result(raw)
```

---

### 2. TxtIngestor

**Archivo:** `backend/app/services/document_txt_ingest.py`

Ingestor para archivos de texto plano con detección automática de encoding (UTF-8 → Latin-1).

```python
from __future__ import annotations

from typing import Any, Dict

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class TxtIngestor:
    """Ingestor para archivos de texto plano (.txt).

    Intenta leer el archivo con UTF-8 primero; si falla por error de
    decodificación, reintenta con Latin-1. Si ambos fallan, retorna
    ocr_result con success=False.
    """

    async def ingest(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Extrae el contenido de un archivo .txt.

        Args:
            file_path: Ruta absoluta al archivo .txt.
            filename: Nombre original del archivo (para encabezado).

        Returns:
            ocr_result con extracted_text, pages, total_pages, success.
        """
        content: str | None = None
        for encoding in ("utf-8", "latin-1"):
            try:
                with open(file_path, "r", encoding=encoding) as fh:
                    content = fh.read()
                break
            except UnicodeDecodeError:
                logger.warning(
                    "txt_encoding_fallback",
                    filename=filename,
                    encoding=encoding,
                )
                continue
            except OSError as exc:
                logger.error("txt_read_error", filename=filename, error=str(exc))
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
                "error": "No se pudo decodificar el archivo con UTF-8 ni Latin-1.",
            }

        header = f"### ARCHIVO: {filename} | TIPO: TXT"
        full_text = f"{header}\n\n{content}"
        return {
            "extracted_text": full_text,
            "pages": [{"page": "txt", "text": full_text}],
            "total_pages": 1,
            "success": True,
        }
```

---

### 3. DocIngestor

**Archivo:** `backend/app/services/document_doc_ingest.py`

Ingestor para archivos Word 97-2003 binarios (`.doc`) con `docx2txt` como método primario y `antiword` como fallback de sistema.

```python
from __future__ import annotations

import subprocess
from typing import Any, Dict

from app.core.logging_config import get_logger

logger = get_logger(__name__)

_MIN_CONTENT_CHARS = 10


class DocIngestor:
    """Ingestor para archivos Word 97-2003 binarios (.doc).

    Estrategia de extracción:
    1. docx2txt (librería Python, sin dependencias de sistema).
    2. antiword (comando externo, fallback para .doc puros).
    3. Si ambos fallan → ocr_result con success=False.
    """

    async def ingest(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Extrae el texto de un archivo .doc.

        Args:
            file_path: Ruta absoluta al archivo .doc.
            filename: Nombre original del archivo (para encabezado).

        Returns:
            ocr_result con extracted_text, pages, total_pages, success.
        """
        text = self._try_docx2txt(file_path)
        if text is None:
            text = self._try_antiword(file_path)

        if text is None:
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
            return {
                "extracted_text": "",
                "pages": [],
                "total_pages": 0,
                "success": False,
                "error": "Archivo .doc vacío o ilegible.",
            }

        header = f"### ARCHIVO: {filename} | TIPO: DOC"
        full_text = f"{header}\n\n{text.strip()}"
        return {
            "extracted_text": full_text,
            "pages": [{"page": "doc", "text": full_text}],
            "total_pages": 1,
            "success": True,
        }

    def _try_docx2txt(self, file_path: str) -> str | None:
        """Intenta extraer texto con docx2txt.

        Args:
            file_path: Ruta al archivo .doc.

        Returns:
            Texto extraído o None si falla.
        """
        try:
            import docx2txt  # type: ignore[import]
            text = docx2txt.process(file_path)
            return text if text else None
        except Exception as exc:
            logger.warning("doc_docx2txt_failed", file_path=file_path, error=str(exc))
            return None

    def _try_antiword(self, file_path: str) -> str | None:
        """Intenta extraer texto con el comando externo antiword.

        Args:
            file_path: Ruta al archivo .doc.

        Returns:
            Texto extraído o None si antiword no está disponible o falla.
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
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("doc_antiword_unavailable", file_path=file_path, error=str(exc))
            return None
```

---

### 4. DigitalExtractorAgent — extensión PdfTableExtractor

**Archivo a modificar:** `backend/app/agents/extractor_digital.py`

Se extiende el método `extract` para invocar `page.find_tables()` de PyMuPDF ≥ 1.23 antes de `page.get_text()`. Las tablas se formatean como markdown y se insertan al inicio del texto de cada página.

```python
# Fragmento del método extract modificado (reemplaza el bucle de páginas)

def _format_table_as_markdown(table: Any) -> str:
    """Formatea una tabla PyMuPDF como markdown con separadores de columna.

    Args:
        table: Objeto tabla retornado por page.find_tables().

    Returns:
        String con la tabla en formato markdown (filas separadas por |).
    """
    rows: list[str] = []
    for row in table.extract():
        cells = [str(cell or "").strip() for cell in row]
        rows.append(" | ".join(cells))
    if not rows:
        return ""
    # Encabezado + separador markdown
    header = rows[0]
    separator = " | ".join(["---"] * len(rows[0].split(" | ")))
    body = "\n".join(rows[1:]) if len(rows) > 1 else ""
    return f"{header}\n{separator}\n{body}".strip()


# Dentro del bucle for i, page in enumerate(doc):
for i, page in enumerate(doc):
    table_blocks: list[str] = []
    try:
        tables = page.find_tables()
        for tbl in tables:
            md = _format_table_as_markdown(tbl)
            if md:
                table_blocks.append(md)
    except Exception as exc:
        logger.warning(
            "pdf_table_extraction_failed",
            page=i + 1,
            error=str(exc),
        )

    plain_text = page.get_text().strip()
    page_text = "\n\n".join(table_blocks + ([plain_text] if plain_text else ""))
    extracted_pages.append({"page": i + 1, "text": page_text})
    full_text += f"\n--- PÁGINA {i+1} ---\n{page_text}\n"
    real_text_chars += len(page_text)
```

**Decisión de diseño:** Las tablas se insertan *antes* del texto plano de la página para que los fragmentos de mayor densidad informativa aparezcan primero en los chunks de ChromaDB, mejorando la relevancia del RAG.

---

### 5. Modificaciones a upload.py (Camino A)

**Archivo a modificar:** `backend/app/api/v1/routes/upload.py`

#### 5.1 Validación de extensión en POST /upload/document

Se agrega validación de lista blanca antes de guardar el archivo en disco:

```python
from app.services.document_ingestion_router import ALLOWED_EXTENSIONS

@router.post("/document", response_model=GenericResponse)
@router.post("/upload", response_model=GenericResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """Sube un archivo y lo registra como disponible."""
    ext = (file.filename or "").lower().rsplit(".", 1)[-1] if "." in (file.filename or "") else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Tipo de archivo no soportado: .{ext}. "
                f"Extensiones aceptadas: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            ),
        )
    # ... resto del código existente sin cambios
```

#### 5.2 Reemplazo del switch en POST /upload/process/{doc_id}

El bloque `if ext in ["xlsx", "xls"]: ... elif ext in ["csv"]: ... elif ext in ["docx"]: ... else:` se reemplaza por:

```python
from app.services.document_ingestion_router import DocumentIngestionRouter

router_instance = DocumentIngestionRouter()
ocr_result = await router_instance.ingest(
    file_path=file_path,
    filename=filename,
    session_id=session_id,
    doc_id=doc_id,
    memory=memory,
)
```

El resto del flujo (chunking, indexación en ChromaDB, actualización de estado a `ANALYZED`) permanece sin cambios.

---

### 6. Modificaciones a agents.py (Camino B)

**Archivo a modificar:** `backend/app/api/v1/routes/agents.py`

El bloque de auto-ingesta en `_run_orchestrator_job` (los tres bloques `if ext in ("xlsx", "xls"):`, `if ext in ("csv",):`, `if ext in ("docx",):` y el fallback OCR) se reemplaza por:

```python
from app.services.document_ingestion_router import DocumentIngestionRouter

_router = DocumentIngestionRouter()

for d in docs:
    content = d.get("content", {})
    if content.get("status") != "UPLOADED":
        continue

    filename = content.get("filename") or ""
    file_path = content.get("file_path")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    update_job_status(
        job_id,
        "RUNNING",
        {"stage": "ingestion", "pct": 15, "message": f"Procesando: {filename}"},
    )

    ocr_ctx = await _router.ingest(
        file_path=file_path,
        filename=filename,
        session_id=request.session_id,
        doc_id=d["id"],
        memory=memory,
    )

    if not ocr_ctx.get("success"):
        logger.error(
            "background_ingestion_failed",
            doc_id=d["id"],
            session_id=request.session_id,
            error=ocr_ctx.get("error", "unknown"),
        )
        content["status"] = "ERROR"
        await memory.save_document(
            d["id"], request.session_id, content, {"status": "ERROR"}
        )
        continue

    raw_text = ocr_ctx.get("extracted_text", "")
    pages = ocr_ctx.get("pages", [])
    chunk_size = 4000 if ext in ("xlsx", "xls", "csv") else 800
    for page in pages:
        p_text = page.get("text", "")
        if p_text:
            chunks = _chunk_text(p_text, chunk_size=chunk_size, overlap=200)
            metadatas = [
                {
                    "source": filename,
                    "session_id": request.session_id,
                    "page": page.get("page"),
                    "doc_id": d["id"],
                }
                for _ in chunks
            ]
            vector_client.add_texts(request.session_id, chunks, metadatas)

    content["status"] = "ANALYZED"
    content["extracted_text"] = raw_text
    content["total_pages"] = ocr_ctx.get("total_pages", len(pages))
    await memory.save_document(
        d["id"], request.session_id, content, {"status": "ANALYZED"}
    )
```

**Nota:** El estado de error cambia de `FAILED_EXTRACTION` a `ERROR` para alinearse con el Req 3.3 y el vocabulario de `stop_reason` del orquestador.

---

## Data Models

### ocr_result — Contrato canónico

```python
from typing import Any, TypedDict

class OcrPage(TypedDict):
    page: str | int   # Identificador de página (número, nombre de hoja, "txt", "doc", etc.)
    text: str         # Contenido textual de la página

class OcrResult(TypedDict):
    extracted_text: str        # Texto completo concatenado de todas las páginas
    pages: list[OcrPage]       # Lista de páginas con su texto individual
    total_pages: int           # Número total de páginas/secciones
    success: bool              # True si la extracción fue exitosa y hay texto significativo
    # Claves opcionales (presentes en caso de error o en resultados del OCR pipeline):
    # error: str               # Mensaje de error si success=False
    # method: str              # Motor usado (pymupdf_digital, vlm_ocr_remote, etc.)
    # quality_flags: list[str] # Indicadores de calidad del OCR
```

### Tabla de routing por extensión

| Extensión | Ingestor | Retorna line_items | Chunk size |
|---|---|---|---|
| `.xlsx`, `.xls` | `process_excel_document` | Sí | 4000 |
| `.csv` | `process_csv_document` | Sí | 4000 |
| `.docx` | `process_docx_document` | Sí | 4000 |
| `.doc` | `DocIngestor` | No | 800 |
| `.txt` | `TxtIngestor` | No | 800 |
| `.pdf` | `OCRServiceClient` | No | 800 |
| otros | `OCRServiceClient` | No | 800 |

### Dependencias nuevas

```
# backend/requirements.txt — agregar:
docx2txt==0.8
```

`antiword` es un binario de sistema (no Python); se instala vía `apt-get install antiword` en el Dockerfile si se requiere soporte `.doc` en producción. Su ausencia no rompe el sistema (el `DocIngestor` degrada graciosamente).

---

## Correctness Properties

*Una propiedad es una característica o comportamiento que debe ser verdadero en todas las ejecuciones válidas del sistema — esencialmente, una declaración formal sobre lo que el sistema debe hacer. Las propiedades sirven como puente entre especificaciones legibles por humanos y garantías de corrección verificables por máquinas.*

Esta feature es adecuada para property-based testing porque:
- El `DocumentIngestionRouter` es una función pura de routing con lógica de normalización verificable.
- Los ingestores `TxtIngestor` y `DocIngestor` tienen comportamiento de round-trip verificable.
- El contrato canónico `ocr_result` es una invariante universal sobre todos los ingestores.
- La lógica de normalización (`_normalize_ocr_result`) es una función pura.

**Librería PBT:** `hypothesis` (ya incluida en `requirements.txt` como `hypothesis>=6.100.0`).

---

### Property 1: El router siempre retorna un ocr_result con las claves canónicas

*Para cualquier* combinación de extensión de archivo y resultado de ingestor (exitoso o fallido), el `DocumentIngestionRouter` debe retornar un diccionario que contenga exactamente las claves `extracted_text` (str), `pages` (list), `total_pages` (int) y `success` (bool).

**Validates: Requirements 1.1, 7.1**

---

### Property 2: El routing es case-insensitive

*Para cualquier* nombre de archivo con una extensión válida, el ingestor seleccionado por el router debe ser idéntico independientemente de si la extensión está en mayúsculas, minúsculas o mixta (`.PDF` == `.pdf` == `.Pdf`).

**Validates: Requirements 1.8**

---

### Property 3: El router captura excepciones y retorna success=False

*Para cualquier* ingestor que lance cualquier excepción (de cualquier tipo y con cualquier mensaje), el `DocumentIngestionRouter` debe retornar un `ocr_result` con `success=False` y sin propagar la excepción al llamador.

**Validates: Requirements 1.9**

---

### Property 4: La normalización completa claves faltantes con valores por defecto

*Para cualquier* subconjunto de las claves canónicas (`extracted_text`, `pages`, `total_pages`, `success`), `_normalize_ocr_result` debe completar las claves faltantes con sus valores por defecto (`""`, `[]`, `0`, `False`) sin alterar las claves presentes.

**Validates: Requirements 7.2**

---

### Property 5: success=False cuando extracted_text está vacío

*Para cualquier* diccionario donde `extracted_text` sea una cadena vacía o compuesta únicamente de espacios en blanco, `_normalize_ocr_result` debe retornar `success=False`, independientemente del valor original de `success`.

**Validates: Requirements 7.3**

---

### Property 6: TxtIngestor — round-trip de contenido

*Para cualquier* string de texto (incluyendo caracteres unicode, saltos de línea y caracteres especiales), escribirlo en un archivo temporal y leerlo con `TxtIngestor.ingest()` debe producir un `ocr_result` donde `extracted_text` contiene el texto original como subcadena.

**Validates: Requirements 4.4**

---

### Property 7: TxtIngestor — encabezado siempre presente

*Para cualquier* nombre de archivo y cualquier contenido de texto, el `extracted_text` retornado por `TxtIngestor` debe contener la cadena `### ARCHIVO: {filename} | TIPO: TXT` como prefijo.

**Validates: Requirements 4.5**

---

### Property 8: DocIngestor — encabezado siempre presente en extracción exitosa

*Para cualquier* nombre de archivo y cualquier texto extraído exitosamente (longitud ≥ 10 caracteres), el `extracted_text` retornado por `DocIngestor` debe contener la cadena `### ARCHIVO: {filename} | TIPO: DOC` como prefijo.

**Validates: Requirements 5.5**

---

### Property 9: DocIngestor — texto corto produce success=False

*Para cualquier* texto extraído con longitud estrictamente menor a 10 caracteres (incluyendo la cadena vacía y strings de solo espacios), el `DocIngestor` debe retornar `success=False`.

**Validates: Requirements 5.6**

---

### Property 10: Extensiones permitidas son aceptadas por el endpoint de subida

*Para cualquier* extensión en el conjunto `{pdf, docx, doc, xlsx, xls, csv, txt}` (en cualquier capitalización), el endpoint `POST /upload/document` no debe retornar HTTP 415.

**Validates: Requirements 8.1**

---

### Property 11: Extensiones no permitidas son rechazadas con HTTP 415

*Para cualquier* extensión que no pertenezca al conjunto de extensiones permitidas, el endpoint `POST /upload/document` debe retornar HTTP 415.

**Validates: Requirements 8.2**

---

### Reflexión de propiedades — eliminación de redundancias

Tras revisar las 11 propiedades:

- **Properties 1 y 4** son complementarias pero no redundantes: Property 1 verifica el contrato completo del router (incluyendo delegación), mientras Property 4 verifica solo la función de normalización de forma aislada. Se mantienen ambas.
- **Properties 6 y 7** son complementarias: Property 6 verifica el contenido, Property 7 verifica el formato del encabezado. Se mantienen ambas.
- **Properties 8 y 9** son complementarias: Property 8 verifica el formato en caso exitoso, Property 9 verifica el rechazo en caso de texto insuficiente. Se mantienen ambas.
- **Properties 10 y 11** son la imagen especular una de la otra (lista blanca vs. lista negra). Se mantienen ambas porque cubren espacios de entrada disjuntos.
- **Property 2** (case-insensitive) está parcialmente cubierta por Property 1, pero Property 2 verifica específicamente la invarianza de routing, no solo el contrato de salida. Se mantiene.

No se identifican redundancias eliminables. Las 11 propiedades son independientes y cada una aporta valor de verificación único.

---

## Error Handling

### Jerarquía de errores y respuestas

| Escenario | Componente | Comportamiento |
|---|---|---|
| Extensión no soportada en upload | `upload.py` | HTTP 415 con lista de extensiones válidas |
| Archivo no encontrado en disco | `DocumentIngestionRouter` | `ocr_result` con `success=False`, `error="..."` |
| Excepción en ingestor delegado | `DocumentIngestionRouter` | Captura, log de error, `ocr_result` con `success=False` |
| `docx2txt` no disponible | `DocIngestor` | Fallback a `antiword`; si también falla → `success=False` |
| `antiword` no instalado | `DocIngestor` | `FileNotFoundError` capturado → `success=False` |
| Encoding no reconocido en .txt | `TxtIngestor` | Fallback UTF-8 → Latin-1; si ambos fallan → `success=False` |
| `page.find_tables()` lanza excepción | `DigitalExtractorAgent` | Log warning, continúa con `page.get_text()` para esa página |
| `ocr_result.success=False` en Camino B | `_run_orchestrator_job` | Log error, estado del documento → `ERROR`, continúa con otros docs |
| `ocr_result.success=False` en Camino A | `upload.py` | HTTP 502 con detalle del error |

### Logging de auditoría

Todas las operaciones que modifican el estado de un documento en sesión deben registrarse con `get_logger` siguiendo el patrón estructurado:

```python
logger.info(
    "document_ingestion_complete",
    doc_id=doc_id,
    session_id=session_id,  # NUNCA exponer en producción el contenido del doc
    success=result["success"],
    chars=len(result["extracted_text"]),
    ext=ext,
)
```

**Regla de seguridad (ISO/IEC 27034):** Los logs nunca deben contener `file_path`, `extracted_text` ni datos de sesión. Solo IDs, extensiones, métricas de tamaño y flags de éxito/error.

---

## Testing Strategy

### Enfoque dual

La estrategia combina tests unitarios (ejemplos concretos y edge cases) con tests de propiedades (cobertura universal mediante Hypothesis).

### Tests de propiedades (Hypothesis)

Cada propiedad del diseño se implementa como un test de Hypothesis con mínimo 100 iteraciones.

**Archivo:** `backend/tests/test_document_ingestion_router.py`

```python
from hypothesis import given, settings
from hypothesis import strategies as st
from app.services.document_ingestion_router import _normalize_ocr_result, ALLOWED_EXTENSIONS

# Feature: universal-document-ingestion, Property 4: normalización completa claves faltantes
@given(
    extracted_text=st.one_of(st.none(), st.text()),
    pages=st.one_of(st.none(), st.lists(st.dictionaries(st.text(), st.text()))),
    total_pages=st.one_of(st.none(), st.integers()),
    success=st.one_of(st.none(), st.booleans()),
)
@settings(max_examples=200)
def test_normalize_always_has_canonical_keys(extracted_text, pages, total_pages, success):
    """Feature: universal-document-ingestion, Property 4: normalización completa claves faltantes."""
    raw = {}
    if extracted_text is not None:
        raw["extracted_text"] = extracted_text
    if pages is not None:
        raw["pages"] = pages
    if total_pages is not None:
        raw["total_pages"] = total_pages
    if success is not None:
        raw["success"] = success

    result = _normalize_ocr_result(raw)

    assert isinstance(result["extracted_text"], str)
    assert isinstance(result["pages"], list)
    assert isinstance(result["total_pages"], int)
    assert isinstance(result["success"], bool)


# Feature: universal-document-ingestion, Property 5: success=False cuando extracted_text vacío
@given(whitespace=st.text(alphabet=" \t\n\r", min_size=0, max_size=100))
@settings(max_examples=200)
def test_normalize_empty_text_forces_success_false(whitespace):
    """Feature: universal-document-ingestion, Property 5: success=False cuando extracted_text vacío."""
    raw = {"extracted_text": whitespace, "success": True}
    result = _normalize_ocr_result(raw)
    assert result["success"] is False


# Feature: universal-document-ingestion, Property 2: routing case-insensitive
@given(
    base_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    ext=st.sampled_from(list(ALLOWED_EXTENSIONS)),
)
@settings(max_examples=200)
def test_extension_normalization_is_case_insensitive(base_name, ext):
    """Feature: universal-document-ingestion, Property 2: routing case-insensitive."""
    from app.services.document_ingestion_router import DocumentIngestionRouter
    router = DocumentIngestionRouter()
    lower_ext = router._get_extension(f"{base_name}.{ext.lower()}")
    upper_ext = router._get_extension(f"{base_name}.{ext.upper()}")
    assert lower_ext == upper_ext
```

**Archivo:** `backend/tests/test_txt_ingest.py`

```python
import os
import tempfile
from hypothesis import given, settings
from hypothesis import strategies as st
from app.services.document_txt_ingest import TxtIngestor

# Feature: universal-document-ingestion, Property 6: TxtIngestor round-trip de contenido
@given(content=st.text(min_size=1, max_size=5000))
@settings(max_examples=200)
def test_txt_ingestor_roundtrip(content):
    """Feature: universal-document-ingestion, Property 6: TxtIngestor round-trip de contenido."""
    import asyncio
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = asyncio.get_event_loop().run_until_complete(
            TxtIngestor().ingest(path, "test.txt")
        )
        assert result["success"] is True
        assert content in result["extracted_text"]
    finally:
        os.unlink(path)


# Feature: universal-document-ingestion, Property 7: TxtIngestor encabezado siempre presente
@given(
    filename=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))).map(lambda s: s + ".txt"),
    content=st.text(min_size=1, max_size=1000),
)
@settings(max_examples=200)
def test_txt_ingestor_header_present(filename, content):
    """Feature: universal-document-ingestion, Property 7: TxtIngestor encabezado siempre presente."""
    import asyncio
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = asyncio.get_event_loop().run_until_complete(
            TxtIngestor().ingest(path, filename)
        )
        if result["success"]:
            assert f"### ARCHIVO: {filename} | TIPO: TXT" in result["extracted_text"]
    finally:
        os.unlink(path)
```

**Archivo:** `backend/tests/test_doc_ingest.py`

```python
from unittest.mock import patch
from hypothesis import given, settings
from hypothesis import strategies as st
from app.services.document_doc_ingest import DocIngestor

# Feature: universal-document-ingestion, Property 9: DocIngestor texto corto produce success=False
@given(short_text=st.text(max_size=9))
@settings(max_examples=200)
def test_doc_ingestor_short_text_fails(short_text):
    """Feature: universal-document-ingestion, Property 9: DocIngestor texto corto produce success=False."""
    import asyncio
    ingestor = DocIngestor()
    with patch.object(ingestor, "_try_docx2txt", return_value=short_text), \
         patch.object(ingestor, "_try_antiword", return_value=None):
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest("/fake/path.doc", "test.doc")
        )
    assert result["success"] is False


# Feature: universal-document-ingestion, Property 8: DocIngestor encabezado en extracción exitosa
@given(
    filename=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))).map(lambda s: s + ".doc"),
    text=st.text(min_size=10, max_size=1000),
)
@settings(max_examples=200)
def test_doc_ingestor_header_present_on_success(filename, text):
    """Feature: universal-document-ingestion, Property 8: DocIngestor encabezado en extracción exitosa."""
    import asyncio
    ingestor = DocIngestor()
    with patch.object(ingestor, "_try_docx2txt", return_value=text), \
         patch.object(ingestor, "_try_antiword", return_value=None):
        result = asyncio.get_event_loop().run_until_complete(
            ingestor.ingest("/fake/path.doc", filename)
        )
    assert result["success"] is True
    assert f"### ARCHIVO: {filename} | TIPO: DOC" in result["extracted_text"]
```

**Archivo:** `backend/tests/test_pdf_table_extractor.py`

```python
from unittest.mock import MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st

# Feature: universal-document-ingestion, Property 1 (parcial): tablas markdown en texto de página
@given(
    rows=st.lists(
        st.lists(st.text(max_size=20), min_size=1, max_size=5),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=200)
def test_table_formatting_contains_pipe_separators(rows):
    """Feature: universal-document-ingestion, Property 6.2: tablas formateadas como markdown."""
    from app.agents.extractor_digital import _format_table_as_markdown
    mock_table = MagicMock()
    mock_table.extract.return_value = rows
    result = _format_table_as_markdown(mock_table)
    if result:
        assert "|" in result
```

### Tests unitarios (ejemplos y edge cases)

**Archivo:** `backend/tests/test_document_ingestion_router.py` (sección de ejemplos)

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_router_delegates_xlsx_to_excel_ingestor():
    """Req 1.2: .xlsx delega a process_excel_document."""
    with patch("app.services.document_ingestion_router.process_excel_document", new_callable=AsyncMock) as mock:
        mock.return_value = ({"extracted_text": "data", "pages": [], "total_pages": 1, "success": True}, [])
        from app.services.document_ingestion_router import DocumentIngestionRouter
        result = await DocumentIngestionRouter().ingest("/f/test.xlsx", "test.xlsx", "s1", "d1", MagicMock())
        mock.assert_called_once()
        assert result["success"] is True

@pytest.mark.asyncio
async def test_router_catches_exception_and_returns_failure():
    """Req 1.9: excepción en ingestor → success=False."""
    with patch("app.services.document_ingestion_router.TxtIngestor") as MockTxt:
        MockTxt.return_value.ingest = AsyncMock(side_effect=RuntimeError("boom"))
        from app.services.document_ingestion_router import DocumentIngestionRouter
        result = await DocumentIngestionRouter().ingest("/f/test.txt", "test.txt", "s1", "d1", MagicMock())
        assert result["success"] is False
        assert "error" in result
```

**Archivo:** `backend/tests/test_doc_ingest.py` (sección de ejemplos)

```python
@pytest.mark.asyncio
async def test_doc_ingestor_fallback_to_antiword():
    """Req 5.2: si docx2txt falla, usa antiword."""
    ingestor = DocIngestor()
    with patch.object(ingestor, "_try_docx2txt", return_value=None), \
         patch.object(ingestor, "_try_antiword", return_value="Texto extraído con antiword"):
        result = await ingestor.ingest("/fake/test.doc", "test.doc")
    assert result["success"] is True
    assert "antiword" in result["extracted_text"].lower() or "Texto" in result["extracted_text"]

@pytest.mark.asyncio
async def test_doc_ingestor_both_fail_returns_failure():
    """Req 5.3: si docx2txt y antiword fallan → success=False."""
    ingestor = DocIngestor()
    with patch.object(ingestor, "_try_docx2txt", return_value=None), \
         patch.object(ingestor, "_try_antiword", return_value=None):
        result = await ingestor.ingest("/fake/test.doc", "test.doc")
    assert result["success"] is False
```

### Configuración de CI

Los tests de propiedades se ejecutan con el gate de CI existente:

```bash
# Desde backend/
pytest tests/test_document_ingestion_router.py tests/test_txt_ingest.py \
       tests/test_doc_ingest.py tests/test_pdf_table_extractor.py \
       --tb=short -q
```

Hypothesis persiste ejemplos fallidos en `.hypothesis/` (ya en el repo) para reproducibilidad.

---

## Migration Plan

### Fase 1 — Nuevos módulos (sin romper nada)

1. Crear `backend/app/services/document_txt_ingest.py` (nuevo, sin dependencias de código existente).
2. Crear `backend/app/services/document_doc_ingest.py` (nuevo, sin dependencias de código existente).
3. Crear `backend/app/services/document_ingestion_router.py` (nuevo, envuelve ingestores existentes).
4. Agregar `docx2txt==0.8` a `backend/requirements.txt`.
5. Ejecutar tests de los nuevos módulos en aislamiento.

### Fase 2 — Extensión de DigitalExtractorAgent

6. Modificar `backend/app/agents/extractor_digital.py` para agregar `page.find_tables()` con fallback.
7. Ejecutar `backend/tests/test_pdf_table_extractor.py` para verificar no-regresión.
8. Verificar que `OCRServiceClient` sigue funcionando con PDFs existentes.

### Fase 3 — Integración en Camino A (upload.py)

9. Agregar validación de extensión en `POST /upload/document`.
10. Reemplazar el switch de extensiones en `POST /upload/process/{doc_id}` por `DocumentIngestionRouter.ingest()`.
11. Ejecutar tests de integración del endpoint de upload.
12. Verificar que el comportamiento de re-ingesta de `line_items` (force=False + ANALYZED) se mantiene.

### Fase 4 — Integración en Camino B (agents.py)

13. Reemplazar el bloque de auto-ingesta en `_run_orchestrator_job` por `DocumentIngestionRouter.ingest()`.
14. Cambiar estado de error de `FAILED_EXTRACTION` a `ERROR` (alineación con Req 3.3).
15. Ejecutar tests de integración del job background.

### Fase 5 — Validación end-to-end

16. Subir un archivo `.txt` y verificar que aparece en ChromaDB.
17. Subir un archivo `.doc` y verificar extracción (con `docx2txt` disponible).
18. Subir un PDF con tablas y verificar que el texto extraído contiene separadores `|`.
19. Disparar `POST /agents/process` con documentos `.txt` y `.doc` en estado `UPLOADED` y verificar que el Camino B los procesa correctamente.
20. Verificar que subir un `.exe` retorna HTTP 415.

### Compatibilidad hacia atrás

- Los ingestores existentes (`document_excel_ingest.py`, `document_csv_ingest.py`, `document_docx_ingest.py`) **no se modifican**. El router los llama con la misma firma que antes.
- El `OCRServiceClient` y el `DigitalExtractorAgent` mantienen sus interfaces públicas. Solo se extiende el comportamiento interno del `DigitalExtractorAgent`.
- El estado `FAILED_EXTRACTION` que puede existir en documentos ya procesados no se migra; solo los nuevos fallos usarán `ERROR`. Ambos estados son manejados por el orquestador como condiciones de no-procesamiento.
- La función `_normalize_ocr_result` en `ocr_service.py` (existente) no se toca; el router tiene su propia función de normalización con el mismo nombre pero en su propio módulo.
