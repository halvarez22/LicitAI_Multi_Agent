# 🚜 Fine Tunning: Arquitectura de Doble Agente Extractor - LicitAI

Este documento registra la evolución arquitectónica del sistema de ingestión de LicitAI. Define la solución definitiva para garantizar el **100% de operatividad** extrayendo tanto PDFs de texto nativo como mamotretos escaneados de alta densidad, **respetando siempre el límite de 8GB de VRAM**.

---

## 🛑 1. El Incidente: "El Mazo de los 8GB" (Diagnóstico Forense)

Durante la prueba general con licitaciones escaneadas (ej. `Maderas Chihuahua`), el sistema experimentó un fallo silencioso (Extracción Incompleta / Error 502 Bad Gateway).

*   **Diagnóstico:** El servicio único de OCR intentó cargar las 50 páginas del PDF a la memoria RAM simultáneamente usando `convert_from_bytes()`. Al sumar esto con la carga del modelo GLM en VRAM, el sistema colapsó por **OOM (Out-Of-Memory)** a nivel sistema, matando al contenedor de visión antes de poder empezar.
*   **Problema de Diseño Original:** Faltaba separación de responsabilidades. El mismo servicio intentaba ser rápido y ligero para texto, y pesado y mastodóntico para visión. 

---

## 🏗️ 2. La Solución Arquitectónica: "División del Trabajo"

Siguiendo las mejores prácticas de SQA y los axiomas del *Faro Técnico*, hemos dividido al "Extractor Único" en dos agentes ultra especializados e independientes.

### 🕵️ Agente 1: `DigitalExtractorAgent` (El Bisturí)
*   **Terreno:** PDFs Nativos / Digitales.
*   **Recurso:** 100% CPU.
*   **Mecánica:** Intenta extraer el texto al instante usando `PyMuPDF`.
*   **Criterio de Pista:** Si extrae = > 100 caracteres significativos, declara victoria en 1 segundo y le pasa el testigo al Orquestador. No toca la GPU en absoluto.

### 👁️ Agente 2: `VisionExtractorAgent` (El Tanque Forense)
*   **Terreno:** Escaneos densos, fotos, firmas que no pasaron la prueba del Agente 1.
*   **Recurso:** 99% GPU (Pide Exclusividad de la RTX).
*   **Nuevas Mecánicas de Blindaje (Fine Tunning):**
    1.  **Paginación Directa desde Disco:** Se eliminó la lectura masiva a RAM (`convert_from_bytes`). Ahora se lee el PDF desde el disco duro archivo por archivo usando `convert_from_path(tmp_path)`.
    2.  **Batches a Prueba de Fuego (`Batch Size = 1`):** Convierte una sola página, la envía al VLM, extrae el texto, y **obliga al Garbage Collector de Python a limpiar la RAM (`gc.collect()`)**.
    3.  **Vaciado de VRAM:** Obliga permanentemente a `torch.cuda.empty_cache()` entre iteración e iteración para que la VRAM nunca suba.
    4.  **Resiliencia (Polling):** Aumentado el límite de procesamiento seguro de los 15 minutos estándar a **30 Minutos**, ideal para licitaciones colosales que demoren ~40s por página visual en procesar.

---

## 🚦 3. Flujo Lógico Actualizado

Cuando un usuario sube un documento:

1.  **`upload.py`** recibe el archivo.
2.  Lanza el `DigitalExtractorAgent`.
    *   *Si es un PDF de Word:* Termina en 1 segundo. Éxito.
    *   *Si es un PDF sucio/escaneo:* Devuelve "success": False.
3.  **El sistema reacciona:** *"🚜 Delegando archivo pesado a VisionExtractorAgent..."*
4.  Lanza el `VisionExtractorAgent`.
5.  El contenedor `ocr-vlm` comienza a procesarlo pacíficamente, **con uso de RAM chato y constante**, asegurando que el proceso finalice no importa cuántas páginas tenga el PDF.

## 🏆 Conclusión

LicitAI ya no trata de comerse "la ballena entera". Ahora respeta sus recursos al 100%, operando como un Fórmula 1 para archivos ligeros, y mutando en un vehículo de tracción pesada seguro, imparable y paciente para documentos fotográficos. Operatividad universal asegurada.
