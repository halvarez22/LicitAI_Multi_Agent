# Plan de Implementación: Universal Document Ingestion

## Visión general

Implementar los cuatro módulos nuevos y las integraciones necesarias para cerrar los huecos de ingesta en LicitAI. El plan sigue las cinco fases del Migration Plan definido en el diseño: primero se crean los módulos nuevos sin tocar código existente, luego se extiende el extractor digital, después se integra en ambos caminos (A y B), y finalmente se valida con la suite de tests.

El lenguaje de implementación es **Python**, alineado con el stack existente del proyecto.

---

## Tareas

- [x] 1. Fase 1 — Nuevos módulos de ingesta (sin romper nada)
  - [x] 1.1 Crear `backend/app/services/document_txt_ingest.py` con la clase `TxtIngestor`
    - Implementar `TxtIngestor.ingest(file_path, filename) -> Dict[str, Any]`
    - Intentar lectura con `utf-8` primero; reintentar con `latin-1` si falla `UnicodeDecodeError`
    - Si ambos encodings fallan, retornar `ocr_result` con `success=False` y mensaje descriptivo
    - En caso exitoso, construir `extracted_text` con encabezado `### ARCHIVO: {filename} | TIPO: TXT`
    - Retornar `pages=[{"page": "txt", "text": full_text}]` y `total_pages=1`
    - Usar `get_logger(__name__)` para warnings de fallback de encoding
    - Incluir type hints completos y docstrings en español (Google Style)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 1.2 Crear `backend/app/services/document_doc_ingest.py` con la clase `DocIngestor`
    - Implementar `DocIngestor.ingest(file_path, filename) -> Dict[str, Any]`
    - Implementar `_try_docx2txt(file_path) -> str | None` como método privado
    - Implementar `_try_antiword(file_path) -> str | None` como método privado con `subprocess.run` y timeout de 30 s
    - Estrategia: intentar `docx2txt` primero; si retorna `None`, intentar `antiword`; si ambos fallan, retornar `success=False`
    - Si el texto extraído tiene menos de 10 caracteres, retornar `success=False` con mensaje `"Archivo .doc vacío o ilegible"`
    - En caso exitoso, construir `extracted_text` con encabezado `### ARCHIVO: {filename} | TIPO: DOC`
    - Retornar `pages=[{"page": "doc", "text": full_text}]` y `total_pages=1`
    - Incluir type hints completos y docstrings en español (Google Style)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 1.3 Crear `backend/app/services/document_ingestion_router.py` con `DocumentIngestionRouter`
    - Definir la constante `ALLOWED_EXTENSIONS: frozenset[str]` con `{"pdf", "docx", "doc", "xlsx", "xls", "csv", "txt"}`
    - Implementar `_normalize_ocr_result(raw: Dict[str, Any]) -> Dict[str, Any]` como función privada
      - Completar claves faltantes con defaults: `extracted_text=""`, `pages=[]`, `total_pages=0`, `success=False`
      - Forzar `success=False` cuando `extracted_text.strip()` esté vacío
    - Exponer `normalize_ocr_result` como alias público para uso en tests
    - Implementar `DocumentIngestionRouter.ingest(file_path, filename, session_id, doc_id, memory)` como método `async`
      - Extraer extensión en minúsculas con `filename.lower().rsplit(".", 1)[-1]`
      - Delegar a `_delegate()` envuelto en `try/except` que captura cualquier excepción y retorna `success=False`
      - Aplicar `_normalize_ocr_result` al resultado antes de retornar
    - Implementar `DocumentIngestionRouter._delegate(ext, ...)` con el routing completo:
      - `xlsx`/`xls` → `process_excel_document`
      - `csv` → `process_csv_document`
      - `docx` → `process_docx_document`
      - `doc` → `DocIngestor().ingest()`
      - `txt` → `TxtIngestor().ingest()`
      - cualquier otro (incluyendo `pdf`) → `OCRServiceClient().scan_document()`
    - Usar `get_logger(__name__)` para logging de inicio, error y completitud
    - Incluir type hints completos y docstrings en español (Google Style)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 7.1, 7.2, 7.3_

  - [x] 1.4 Agregar `docx2txt==0.8` a `backend/requirements.txt`
    - Añadir la línea `docx2txt==0.8` al archivo `backend/requirements.txt`
    - Verificar que no exista ya una entrada de `docx2txt` con versión diferente
    - _Requirements: 5.1_

- [x] 2. Fase 2 — Extensión de `DigitalExtractorAgent` con extracción de tablas PDF
  - [x] 2.1 Agregar función `_format_table_as_markdown` en `backend/app/agents/extractor_digital.py`
    - Implementar `_format_table_as_markdown(table: Any) -> str` como función de módulo (no método de clase)
    - Iterar `table.extract()` para obtener filas; convertir cada celda a `str` y hacer `.strip()`
    - Construir encabezado markdown + separador `---` + filas del cuerpo
    - Retornar string vacío si no hay filas
    - Incluir type hints y docstring en español
    - _Requirements: 6.2_

  - [x] 2.2 Modificar el bucle de páginas en `DigitalExtractorAgent.extract` para invocar `page.find_tables()`
    - Reemplazar el bucle `for i, page in enumerate(doc):` existente por la versión extendida
    - Antes de `page.get_text()`, invocar `page.find_tables()` y formatear cada tabla con `_format_table_as_markdown`
    - Insertar los bloques de tabla markdown **antes** del texto plano en `page_text`
    - Envolver `page.find_tables()` en `try/except Exception` que registre el error con `logger.warning` y continúe con solo `page.get_text()`
    - Mantener el criterio de éxito existente: `real_text_chars > 100`
    - Mantener el comportamiento existente cuando no hay tablas detectables
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 3. Checkpoint — Verificar módulos nuevos antes de integrar
  - Asegurar que todos los tests de las fases 1 y 2 pasen, preguntar al usuario si hay dudas antes de continuar.

- [x] 4. Fase 3 — Integración en Camino A (`upload.py`)
  - [x] 4.1 Agregar validación HTTP 415 en `POST /upload/document` de `backend/app/api/v1/routes/upload.py`
    - Importar `ALLOWED_EXTENSIONS` desde `app.services.document_ingestion_router`
    - Al inicio del handler `upload_file`, extraer la extensión del `file.filename` en minúsculas
    - Si la extensión no está en `ALLOWED_EXTENSIONS`, lanzar `HTTPException(status_code=415, detail=...)`
    - El mensaje de error debe listar las extensiones aceptadas ordenadas alfabéticamente
    - La validación debe ocurrir **antes** de guardar el archivo en disco
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 4.2 Reemplazar el switch de extensiones en `POST /upload/process/{doc_id}` por `DocumentIngestionRouter`
    - Importar `DocumentIngestionRouter` desde `app.services.document_ingestion_router`
    - Reemplazar el bloque `if ext in ["xlsx", "xls"]: ... elif ext in ["csv"]: ... elif ext in ["docx"]: ... else:` por una única llamada a `DocumentIngestionRouter().ingest(file_path, filename, session_id, doc_id, memory)`
    - Mantener sin cambios el bloque de re-ingesta de `line_items` cuando `status == "ANALYZED"` y `force=False`
    - Mantener sin cambios el flujo de chunking, indexación en ChromaDB y actualización de estado a `ANALYZED`
    - Mantener sin cambios la guarda de seguridad de 100 caracteres para PDFs e imágenes
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 5. Fase 4 — Integración en Camino B (`agents.py` / orquestador background)
  - [x] 5.1 Reemplazar el bloque de auto-ingesta en `_run_orchestrator_job` por `DocumentIngestionRouter`
    - Importar `DocumentIngestionRouter` desde `app.services.document_ingestion_router`
    - Instanciar `_router = DocumentIngestionRouter()` una sola vez antes del bucle `for d in docs:`
    - Reemplazar los tres bloques `if ext in ("xlsx", "xls"):`, `if ext in ("csv",):`, `if ext in ("docx",):` y el fallback OCR por una única llamada a `_router.ingest(file_path, filename, session_id, doc_id, memory)`
    - Mantener la llamada a `update_job_status` con `pct=15` antes de la ingesta
    - Mantener el cálculo de `chunk_size` basado en extensión (4000 para tabulares, 800 para el resto)
    - Mantener el bucle de indexación en ChromaDB con los mismos metadatos (`source`, `session_id`, `page`, `doc_id`)
    - Mantener la actualización de `content["status"] = "ANALYZED"` y `content["extracted_text"]` en caso exitoso
    - _Requirements: 3.1, 3.2_

  - [x] 5.2 Cambiar estado de error de `FAILED_EXTRACTION` a `ERROR` en el Camino B
    - En el bloque `if not ocr_ctx.get("success"):` del nuevo código, usar `content["status"] = "ERROR"` en lugar de `"FAILED_EXTRACTION"`
    - Registrar el error con `logger.error("background_ingestion_failed", ...)` incluyendo `doc_id`, `session_id` y `error`
    - _Requirements: 3.3_

- [x] 6. Checkpoint — Verificar integración completa antes de tests finales
  - Asegurar que los cambios en upload.py y agents.py no rompan el comportamiento existente, preguntar al usuario si hay dudas.

- [x] 7. Fase 5 — Tests y validación
  - [x] 7.1 Crear `backend/tests/test_document_ingestion_router.py` con tests unitarios del router
    - Escribir test unitario: routing a `process_excel_document` para extensiones `.xlsx` y `.xls`
    - Escribir test unitario: routing a `process_csv_document` para extensión `.csv`
    - Escribir test unitario: routing a `process_docx_document` para extensión `.docx`
    - Escribir test unitario: routing a `DocIngestor` para extensión `.doc`
    - Escribir test unitario: routing a `TxtIngestor` para extensión `.txt`
    - Escribir test unitario: routing a `OCRServiceClient` para extensión `.pdf` y extensiones desconocidas
    - Escribir test unitario: captura de excepción del ingestor delegado → `success=False`
    - Usar `unittest.mock.AsyncMock` y `patch` para aislar los ingestores delegados
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9_

  - [ ]* 7.2 Escribir property test — Property 1: el router siempre retorna claves canónicas
    - **Property 1: El router siempre retorna un ocr_result con las claves canónicas**
    - Usar `@given(st.text(), st.booleans())` para generar resultados arbitrarios del ingestor mockeado
    - Verificar que el resultado contiene exactamente `extracted_text` (str), `pages` (list), `total_pages` (int), `success` (bool)
    - **Validates: Requirements 1.1, 7.1**

  - [ ]* 7.3 Escribir property test — Property 2: routing case-insensitive
    - **Property 2: El routing es case-insensitive**
    - Usar `@given(st.sampled_from(["pdf", "docx", "doc", "xlsx", "xls", "csv", "txt"]))` y generar variantes de capitalización
    - Verificar que el ingestor seleccionado es idéntico para `.PDF`, `.pdf` y `.Pdf`
    - **Validates: Requirements 1.8**

  - [ ]* 7.4 Escribir property test — Property 3: el router captura excepciones
    - **Property 3: El router captura excepciones y retorna success=False**
    - Usar `@given(st.text())` para generar mensajes de excepción arbitrarios
    - Mockear el ingestor delegado para que lance `Exception(message)` con el mensaje generado
    - Verificar que el router retorna `success=False` sin propagar la excepción
    - **Validates: Requirements 1.9**

  - [ ]* 7.5 Escribir property test — Property 4: normalización completa claves faltantes
    - **Property 4: La normalización completa claves faltantes con valores por defecto**
    - Usar `@given(st.fixed_dictionaries({...}))` con subconjuntos aleatorios de las claves canónicas
    - Verificar que `_normalize_ocr_result` completa las claves faltantes con sus defaults sin alterar las presentes
    - **Validates: Requirements 7.2**

  - [ ]* 7.6 Escribir property test — Property 5: success=False cuando extracted_text vacío
    - **Property 5: success=False cuando extracted_text está vacío**
    - Usar `@given(st.one_of(st.just(""), st.text(alphabet=" \t\n\r")))` para generar textos vacíos/blancos
    - Verificar que `_normalize_ocr_result` retorna `success=False` independientemente del valor original de `success`
    - **Validates: Requirements 7.3**

  - [x] 7.7 Crear `backend/tests/test_txt_ingest.py` con tests unitarios del TxtIngestor
    - Escribir test unitario: lectura exitosa con UTF-8
    - Escribir test unitario: fallback a Latin-1 cuando UTF-8 falla
    - Escribir test unitario: `success=False` cuando ambos encodings fallan (archivo binario)
    - Escribir test unitario: encabezado `### ARCHIVO: {filename} | TIPO: TXT` presente en `extracted_text`
    - Escribir test unitario: `pages` contiene exactamente un elemento con `page="txt"`
    - Usar `tmp_path` de pytest para crear archivos temporales reales
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 7.8 Escribir property test — Property 6: TxtIngestor round-trip de contenido
    - **Property 6: TxtIngestor — round-trip de contenido**
    - Usar `@given(st.text())` para generar strings arbitrarios (unicode, saltos de línea, caracteres especiales)
    - Escribir el texto en un archivo temporal con UTF-8 y leerlo con `TxtIngestor.ingest()`
    - Verificar que `extracted_text` contiene el texto original como subcadena
    - **Validates: Requirements 4.4**

  - [ ]* 7.9 Escribir property test — Property 7: TxtIngestor encabezado siempre presente
    - **Property 7: TxtIngestor — encabezado siempre presente**
    - Usar `@given(st.text(min_size=1), st.text(min_size=1))` para generar nombre de archivo y contenido arbitrarios
    - Verificar que `extracted_text` comienza con `### ARCHIVO: {filename} | TIPO: TXT`
    - **Validates: Requirements 4.5**

  - [x] 7.10 Crear `backend/tests/test_doc_ingest.py` con tests unitarios del DocIngestor
    - Escribir test unitario: extracción exitosa vía `docx2txt` (mockeado)
    - Escribir test unitario: fallback a `antiword` cuando `docx2txt` retorna `None`
    - Escribir test unitario: `success=False` cuando ambos métodos fallan
    - Escribir test unitario: `success=False` cuando el texto extraído tiene menos de 10 caracteres
    - Escribir test unitario: encabezado `### ARCHIVO: {filename} | TIPO: DOC` presente en `extracted_text`
    - Escribir test unitario: `pages` contiene exactamente un elemento con `page="doc"`
    - Usar `unittest.mock.patch` para aislar `docx2txt` y `subprocess.run`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 7.11 Escribir property test — Property 8: DocIngestor encabezado en extracción exitosa
    - **Property 8: DocIngestor — encabezado siempre presente en extracción exitosa**
    - Usar `@given(st.text(min_size=1), st.text(min_size=10))` para generar nombre de archivo y texto extraído (≥ 10 chars)
    - Mockear `_try_docx2txt` para retornar el texto generado
    - Verificar que `extracted_text` contiene `### ARCHIVO: {filename} | TIPO: DOC` como prefijo
    - **Validates: Requirements 5.5**

  - [ ]* 7.12 Escribir property test — Property 9: DocIngestor texto corto produce success=False
    - **Property 9: DocIngestor — texto corto produce success=False**
    - Usar `@given(st.text(max_size=9))` para generar textos con menos de 10 caracteres
    - Mockear `_try_docx2txt` para retornar el texto generado
    - Verificar que el resultado tiene `success=False`
    - **Validates: Requirements 5.6**

  - [x] 7.13 Crear `backend/tests/test_pdf_table_extractor.py` con tests del extractor de tablas PDF
    - Escribir test unitario: `_format_table_as_markdown` con tabla de 2 filas y 3 columnas
    - Escribir test unitario: `_format_table_as_markdown` con tabla vacía retorna string vacío
    - Escribir test unitario: `_format_table_as_markdown` con celdas `None` las convierte a string vacío
    - Escribir test unitario: cuando `page.find_tables()` lanza excepción, el extractor continúa con `page.get_text()`
    - Usar `unittest.mock.MagicMock` para simular objetos `page` y `table` de PyMuPDF
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [ ]* 7.14 Escribir property test — Property 10: extensiones permitidas no retornan HTTP 415
    - **Property 10: Extensiones permitidas son aceptadas por el endpoint de subida**
    - Usar `@given(st.sampled_from(list(ALLOWED_EXTENSIONS)))` y generar variantes de capitalización
    - Invocar el endpoint `POST /upload/document` con `TestClient` de FastAPI
    - Verificar que el status code no es 415
    - **Validates: Requirements 8.1**

  - [ ]* 7.15 Escribir property test — Property 11: extensiones no permitidas retornan HTTP 415
    - **Property 11: Extensiones no permitidas son rechazadas con HTTP 415**
    - Usar `@given(st.text(alphabet=st.characters(whitelist_categories=("Ll",)), min_size=1, max_size=6).filter(lambda e: e not in ALLOWED_EXTENSIONS))` para generar extensiones inválidas
    - Invocar el endpoint `POST /upload/document` con `TestClient` de FastAPI
    - Verificar que el status code es exactamente 415
    - **Validates: Requirements 8.2**

- [x] 8. Checkpoint final — Ejecutar suite completa y verificar CI gate
  - Ejecutar `ruff check backend/` y corregir cualquier advertencia de linting
  - Ejecutar `mypy backend/app/services/document_txt_ingest.py backend/app/services/document_doc_ingest.py backend/app/services/document_ingestion_router.py backend/app/agents/extractor_digital.py` y corregir errores de tipos
  - Ejecutar `pytest backend/tests/test_document_ingestion_router.py backend/tests/test_txt_ingest.py backend/tests/test_doc_ingest.py backend/tests/test_pdf_table_extractor.py -v` y verificar que todos los tests pasan
  - Asegurar que todos los tests pasan, preguntar al usuario si hay dudas antes de cerrar la feature.

---

## Notas

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido; las propiedades PBT son las más valiosas para validar invariantes universales.
- Cada tarea referencia los requisitos específicos para trazabilidad completa.
- Los módulos nuevos (Fase 1) no modifican ningún archivo existente, lo que permite integrarlos y revertirlos de forma independiente.
- `antiword` es un binario de sistema; su ausencia no rompe el sistema (el `DocIngestor` degrada graciosamente a `success=False`).
- El cambio de estado `FAILED_EXTRACTION` → `ERROR` en el Camino B (tarea 5.2) alinea el vocabulario con `stop_reason` del orquestador definido en `AGENTS_CONTEXT.md`.
- Las propiedades PBT 10 y 11 requieren un `TestClient` de FastAPI; asegurarse de que el fixture de la app esté disponible en el módulo de tests o crearlo como fixture de pytest.
