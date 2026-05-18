# Requirements Document

## Introduction

El sistema LicitAI Multi-Agent necesita ingestar de forma fiable cualquier tipo de documento que un usuario suba a una sesión de licitación. Actualmente existen ingestores para `.xlsx/.xls`, `.csv` y `.docx`, y un pipeline OCR para PDFs. Sin embargo, hay cuatro huecos que provocan fallos silenciosos o pérdida de datos: (1) los archivos `.txt` caen en el pipeline OCR de fitz y pueden fallar; (2) el `OCRServiceClient` (camino B, background) no tiene routing por extensión, por lo que `.docx/.xlsx/.csv` que llegan por ese camino van a fitz y fallan; (3) las tablas en PDFs nativos se extraen como texto plano desordenado porque no se usa `page.find_tables()` de PyMuPDF ≥ 1.23; (4) los archivos `.doc` (Word 97-2003 binario) no tienen ingestor y se rechazan o fallan silenciosamente.

Esta feature cierra los cuatro huecos y consolida el routing de ingesta en un único punto canónico (`DocumentIngestionRouter`) que ambos caminos (A y B) usan, garantizando que todos los tipos de archivo soportados produzcan un payload `ocr_result` estructurado, indexable en ChromaDB y disponible para el RAG.

## Glossary

- **DocumentIngestionRouter**: Componente central nuevo que recibe `(file_path, filename, session_id, doc_id, memory)` y delega al ingestor correcto según la extensión del archivo.
- **Ingestor**: Módulo Python que transforma un archivo en un payload `ocr_result` canónico con claves `extracted_text`, `pages`, `total_pages`, `success`.
- **ocr_result**: Diccionario canónico de salida de cualquier ingestor con claves `extracted_text` (str), `pages` (list[dict]), `total_pages` (int), `success` (bool).
- **Camino A**: Flujo explícito iniciado por el usuario vía `POST /upload/process/{doc_id}`.
- **Camino B**: Flujo background iniciado por el orquestador en `_run_orchestrator_job` antes de lanzar los agentes.
- **TxtIngestor**: Nuevo ingestor para archivos `.txt` con detección de encoding.
- **DocIngestor**: Nuevo ingestor para archivos `.doc` (Word 97-2003 binario) usando `docx2txt` o `antiword` como fallback.
- **PdfTableExtractor**: Extensión del `DigitalExtractorAgent` que usa `page.find_tables()` de PyMuPDF ≥ 1.23 para estructurar tablas en PDFs nativos.
- **OCRServiceClient**: Cliente existente que gestiona la cadena de extracción para PDFs e imágenes (digital → remoto → nativo VLM).
- **ChromaDB**: Base de datos vectorial donde se indexan los fragmentos de texto para búsqueda semántica (RAG).
- **RAG**: Retrieval-Augmented Generation; los agentes consultan ChromaDB para obtener contexto relevante de los documentos.
- **MemoryRepository**: Repositorio de persistencia de sesiones, documentos y partidas económicas.
- **line_items**: Partidas económicas estructuradas extraídas de documentos tabulares (Excel, CSV, DOCX).
- **encoding**: Codificación de caracteres de un archivo de texto (UTF-8, Latin-1, etc.).

## Requirements

### Requirement 1: DocumentIngestionRouter como punto canónico de routing

**User Story:** Como desarrollador del sistema, quiero un único componente de routing de ingesta que ambos caminos (A y B) usen, para que la lógica de selección de ingestor no esté duplicada y cualquier nuevo tipo de archivo se registre en un solo lugar.

#### Acceptance Criteria

1. THE DocumentIngestionRouter SHALL exponer una función asíncrona `ingest(file_path, filename, session_id, doc_id, memory)` que retorne un `ocr_result` canónico.
2. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.xlsx` o `.xls`, THE DocumentIngestionRouter SHALL delegar al ingestor Excel existente (`process_excel_document`).
3. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.csv`, THE DocumentIngestionRouter SHALL delegar al ingestor CSV existente (`process_csv_document`).
4. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.docx`, THE DocumentIngestionRouter SHALL delegar al ingestor DOCX existente (`process_docx_document`).
5. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.doc`, THE DocumentIngestionRouter SHALL delegar al DocIngestor.
6. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.txt`, THE DocumentIngestionRouter SHALL delegar al TxtIngestor.
7. WHEN el DocumentIngestionRouter recibe un archivo con extensión `.pdf` o cualquier extensión no reconocida, THE DocumentIngestionRouter SHALL delegar al `OCRServiceClient`.
8. THE DocumentIngestionRouter SHALL comparar extensiones en minúsculas para que `.PDF`, `.TXT` y `.DOCX` sean tratados igual que sus equivalentes en minúsculas.
9. IF el ingestor delegado lanza una excepción, THEN THE DocumentIngestionRouter SHALL capturarla y retornar un `ocr_result` con `success=False` y el mensaje de error en la clave `error`.

---

### Requirement 2: Integración del DocumentIngestionRouter en el Camino A (upload.py)

**User Story:** Como usuario que sube un documento, quiero que el endpoint `POST /upload/process/{doc_id}` use el router canónico, para que todos los tipos de archivo sean procesados correctamente sin lógica duplicada en la ruta HTTP.

#### Acceptance Criteria

1. WHEN el endpoint `POST /upload/process/{doc_id}` procesa un documento, THE Upload_Route SHALL invocar `DocumentIngestionRouter.ingest()` en lugar del switch por extensión actual.
2. THE Upload_Route SHALL mantener el comportamiento existente de chunking, indexación en ChromaDB y actualización de estado a `ANALYZED` tras una ingesta exitosa.
3. THE Upload_Route SHALL mantener el comportamiento existente de re-ingesta de `line_items` cuando el documento ya está en estado `ANALYZED` y `force=False`.

---

### Requirement 3: Integración del DocumentIngestionRouter en el Camino B (orquestador background)

**User Story:** Como sistema de orquestación, quiero que el job background que auto-ingesta documentos `UPLOADED` use el mismo router canónico que el Camino A, para que `.docx`, `.xlsx`, `.csv`, `.txt` y `.doc` no sean enviados erróneamente al pipeline OCR de fitz.

#### Acceptance Criteria

1. WHEN el orquestador en background encuentra un documento con estado `UPLOADED`, THE Orchestrator SHALL invocar `DocumentIngestionRouter.ingest()` para extraer el texto antes de indexarlo.
2. THE Orchestrator SHALL indexar en ChromaDB el `extracted_text` resultante usando los mismos metadatos (`source`, `session_id`, `page`, `doc_id`) que el Camino A.
3. IF `DocumentIngestionRouter.ingest()` retorna `success=False`, THEN THE Orchestrator SHALL registrar el error en el log y marcar el documento con estado `ERROR` en lugar de continuar con texto vacío.

---

### Requirement 4: TxtIngestor para archivos de texto plano

**User Story:** Como usuario que sube un archivo `.txt`, quiero que el sistema lo lea directamente con detección de encoding, para que el contenido esté disponible para el RAG sin pasar por el pipeline OCR.

#### Acceptance Criteria

1. WHEN el TxtIngestor recibe un archivo `.txt`, THE TxtIngestor SHALL intentar leerlo con encoding `utf-8` primero.
2. IF la lectura con `utf-8` falla por error de decodificación, THEN THE TxtIngestor SHALL reintentar con encoding `latin-1`.
3. IF la lectura con `latin-1` también falla, THEN THE TxtIngestor SHALL retornar un `ocr_result` con `success=False` y un mensaje de error descriptivo.
4. WHEN la lectura es exitosa, THE TxtIngestor SHALL retornar un `ocr_result` con `success=True`, `extracted_text` con el contenido completo, y `pages` con al menos un elemento `{"page": "txt", "text": <contenido>}`.
5. THE TxtIngestor SHALL incluir el nombre del archivo en el encabezado del `extracted_text` con el formato `### ARCHIVO: {filename} | TIPO: TXT`.

---

### Requirement 5: DocIngestor para archivos Word 97-2003 (.doc)

**User Story:** Como usuario que sube un archivo `.doc` antiguo, quiero que el sistema extraiga su texto, para que el contenido esté disponible para el RAG aunque el formato sea binario legacy.

#### Acceptance Criteria

1. WHEN el DocIngestor recibe un archivo `.doc`, THE DocIngestor SHALL intentar extraer el texto usando la librería `docx2txt`.
2. IF `docx2txt` no está disponible o falla, THEN THE DocIngestor SHALL intentar extraer el texto invocando el comando externo `antiword` como fallback.
3. IF tanto `docx2txt` como `antiword` fallan, THEN THE DocIngestor SHALL retornar un `ocr_result` con `success=False` y un mensaje de error que indique que el formato `.doc` no pudo procesarse.
4. WHEN la extracción es exitosa, THE DocIngestor SHALL retornar un `ocr_result` con `success=True`, `extracted_text` con el contenido, y `pages` con al menos un elemento `{"page": "doc", "text": <contenido>}`.
5. THE DocIngestor SHALL incluir el nombre del archivo en el encabezado del `extracted_text` con el formato `### ARCHIVO: {filename} | TIPO: DOC`.
6. IF el texto extraído tiene menos de 10 caracteres, THEN THE DocIngestor SHALL retornar `success=False` con el mensaje `"Archivo .doc vacío o ilegible"`.

---

### Requirement 6: PdfTableExtractor — tablas estructuradas en PDFs nativos

**User Story:** Como agente de análisis, quiero que las tablas de un PDF nativo sean extraídas de forma estructurada, para que los datos tabulares (precios, partidas, especificaciones) sean legibles y consultables en el RAG.

#### Acceptance Criteria

1. WHEN el `DigitalExtractorAgent` procesa una página de PDF y PyMuPDF ≥ 1.23 está disponible, THE DigitalExtractorAgent SHALL invocar `page.find_tables()` para detectar tablas en esa página.
2. WHEN se detectan tablas en una página, THE DigitalExtractorAgent SHALL formatear cada tabla como markdown (filas separadas por `|`) e insertarla en el texto de la página antes del texto plano restante.
3. WHEN una página no contiene tablas detectables, THE DigitalExtractorAgent SHALL extraer únicamente el texto plano con `page.get_text()`, manteniendo el comportamiento actual.
4. THE DigitalExtractorAgent SHALL mantener el criterio de éxito existente: retornar `success=True` solo si el total de caracteres extraídos supera 100.
5. IF `page.find_tables()` lanza una excepción en una página concreta, THEN THE DigitalExtractorAgent SHALL registrar el error en el log, omitir la extracción de tablas para esa página y continuar con `page.get_text()`.

---

### Requirement 7: Contrato canónico del ocr_result

**User Story:** Como desarrollador que consume el resultado de cualquier ingestor, quiero que todos los ingestores retornen exactamente el mismo esquema de diccionario, para que el código de indexación y los agentes no necesiten manejar variaciones por tipo de archivo.

#### Acceptance Criteria

1. THE DocumentIngestionRouter SHALL garantizar que todo `ocr_result` retornado contenga las claves `extracted_text` (str), `pages` (list), `total_pages` (int) y `success` (bool).
2. IF un ingestor retorna un diccionario sin alguna de las claves canónicas, THEN THE DocumentIngestionRouter SHALL completar las claves faltantes con sus valores por defecto: `extracted_text=""`, `pages=[]`, `total_pages=0`, `success=False`.
3. THE DocumentIngestionRouter SHALL retornar `success=False` cuando `extracted_text` esté vacío tras la normalización, independientemente del valor que haya retornado el ingestor delegado.

---

### Requirement 8: Tipos de archivo permitidos en el endpoint de subida

**User Story:** Como usuario, quiero recibir un error claro si subo un tipo de archivo no soportado, para no esperar un procesamiento que nunca tendrá éxito.

#### Acceptance Criteria

1. THE Upload_Route SHALL aceptar archivos con las extensiones: `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.csv`, `.txt`.
2. WHEN un usuario sube un archivo con una extensión no incluida en la lista de extensiones aceptadas, THE Upload_Route SHALL retornar HTTP 415 con un mensaje que indique las extensiones soportadas.
3. THE Upload_Route SHALL realizar la validación de extensión en el endpoint `POST /upload/document` antes de guardar el archivo en disco.
