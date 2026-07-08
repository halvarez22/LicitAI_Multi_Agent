# 🗼 Tunning Perfecto del Proceso de Extracción de Datos - LicitAI

Este documento sirve como **Faro y Guía Técnica** para la arquitectura de extracción de datos de LicitAI. Define los estándares de oro para garantizar que los agentes de análisis nunca estén "ciegos" y que el sistema sea eficiente en hardware de consumo (RTX 4060 8GB).

---

## 🏗️ 1. Arquitectura de "Doble Motor" (Smart Fallback)

La regla de oro es: **"Usa el bisturí antes que el mazo"**. No todos los PDFs necesitan IA de visión.

### 🚤 Vía Rápida: Extracción Digital (PyMuPDF / FIT-Z)
*   **Cuándo:** Siempre que el PDF sea nativo (exportado de Word/Excel) y contenga capas de texto.
*   **Ventaja:** Velocidad instantánea (0.01s por página) y precisión literal del 100%.
*   **Implementación:** Se ejecuta directamente en el **Backend** para evitar latencia de red y consumo de VRAM innecesario.
*   **Criterio de Éxito:** Si el archivo es `.pdf` y genera más de 100 caracteres significativos en el primer intento, se aborta el uso de OCR pesado.

### 👁️ Vía de Visión: GLM-OCR VLM (Vision-Language Model)
*   **Cuándo:** PDFs escaneados, fotos, documentos firmados o con tablas complejas no leíbles.
*   **Motor:** `zai-org/GLM-OCR` (0.9B Parameters).
*   **Ventaja:** Capacidad de razonamiento visual. Entiende contexto, sellos y tablas.
*   **Ubicación:** Contenedor especializado `ocr-vlm`.

---

## ⚙️ 2. Optimización de Hardware (El Límite de los 8GB VRAM)

Para correr **Ollama (Llama 3.1)** y **GLM-OCR** simultáneamente en una sola GPU, es IMPERATIVO:

1.  **DType float16:** Cargar el VLM en media precisión (`torch.float16`). Reduce el uso de VRAM a la mitad (~2.2GB vs ~4.5GB).
2.  **Eliminación de Motores Redundantes:** Nunca inicializar un segundo motor (como EasyOCR) mientras el VLM está cargado. Cada megabyte cuenta.
3.  **VRAM Cleaning:** Ejecutar `torch.cuda.empty_cache()` después de procesar cada página.
4.  **Batch Size 1:** En inferencia VLM, procesar las imágenes una por una para evitar picos de memoria.

---

## 🧬 3. Estrategia de Indexación Vectorial (ChromaDB)

El RAG de licitaciones no debe usar "chunks" arbitrarios de 500 caracteres. El conocimiento de las bases es **Estructural**.

*   **Indexación por Página:** Cada vector en ChromaDB representa una **página completa**.
*   **Metadatos Críticos:** Cada vector debe incluir:
    *   `source`: Nombre original del archivo.
    *   `page`: Número de página (fundamental para la trazabilidad forense).
    *   `doc_type`: Clasificación semántica (BASES, ANEXOS, LEGAL).
    *   `session_id`: ID de la licitación.
*   **Page Header:** Incluir siempre un encabezado de texto `--- PÁGINA X ---` al inicio del contenido para que el LLM sepa ubicar la información en el tiempo y espacio del documento.

---

## 🩺 4. Protocolo de Diagnóstico ("Modo Cirujano")

Si los agentes dicen "no encuentro la información", seguir este checklist:

1.  **¿El contenedor ocr-vlm está Healthy?** (Vía `docker ps` o endpoint `/health`).
2.  **¿El PDF es digital o imagen?** (Comprobar si se puede seleccionar texto en Acrobat).
3.  **¿Hay conflicto de procesos?** (Verificar `nvidia-smi` para asegurar que el proceso no esté "ahogado" por Ollama).
4.  **Verificación Manual vs Agente:** Usar el script `diag.py` para comparar la extracción cruda con el resultado del backend.

---

## 📜 5. Conclusión Filosófica del FARO

> "Un agente de IA es tan inteligente como los datos que puede ver. Si la extracción falla, el razonamiento es una alucinación".

Este sistema garantiza la **Vigilancia Total**. Al separar el PDF Digital del Escaneado, LicitAI se convierte en un sistema resiliente, rápido y quirúrgico. No procesamos píxeles cuando ya tenemos letras, y no perdemos letras cuando solo tenemos píxeles.

---
*Documento de Referencia Técnica - LicitAI Multi-Agent System 2024*
