# 🧠 Tunning de Agente Analista - LicitAI

Este documento es el **Faro Maestro** para la operación y replicación del Agente Analista (Agente 1). Define la configuración de "Alta Fidelidad" lograda para operar en hardware balanceado (8GB VRAM) con precisión quirúrgica.

---

## 🛠️ 1. Estrategia de Descubrimiento Multinivel

El agente no realiza una sola búsqueda lineal. Para evitar la "ceguera" en documentos largos (40+ páginas), el Agente Analista opera mediante **Exploración por Capas**:

1.  **Capa Estratégica (Fechas):** Busca específicamente patrones de calendario (`junta`, `presentación`, `fallo`).
2.  **Capa Administrativa (Requisitos):** Busca obligaciones legales, fiscales y de experiencia.
3.  **Capa Financiera (Evaluación/Garantías):** Busca métodos de evaluación (`puntos y porcentajes`, `binario`) y montos de fiel cumplimiento.

**Por qué funciona:** Al separar las búsquedas en el Vector DB, evitamos que un tema "opaque" al otro en los resultados del RAG.

---

## 🖥️ 2. Configuración de Hardware (Optimización RTX 4060 8GB)

Lograr que un LLM (Llama 3.1 8B) analice documentos complejos en 8GB requiere una **Sincronización de Contexto Estricta**:

*   **Ventana de Memoria del Agente:** Configurada en **16,000 tokens** (aprox. 64,000 caracteres). 
    *   *Nota:* Esto permite al agente "ver" unas 20-30 páginas de información técnica real de un solo golpe.
*   **Ajuste de Ollama (`num_ctx`):** Es obligatorio configurar `num_ctx: 16384` en la llamada a la API de Ollama. Si Ollama se queda en su default (2k o 4k), ignorará el 75% del contexto enviado por el agente.
*   **Balance de VRAM:** 
    *   Ollama + 16k Contexto: ~5.5GB
    *   VLM OCR (Idle/Base): ~2.2GB
    *   **Total Operativo:** ~7.8GB de 8GB. (Límite de seguridad alcanzado).

---

## 📝 3. Prompt de Misión (Zero-Hallucination)

Para evitar que el agente "adivine" o use ejemplos previos, el prompt debe ser **Purista y Agnóstico**:

```text
SISTEMA:
Eres un experto analista de licitaciones. Tu misión es extraer la VERDAD del documento.
REGLAS DE ORO:
1. SI NO ESTÁ, NO EXISTE: Si un dato no aparece en el texto, escribe 'No especificado'.
2. CERO ALUCINACIONES: No uses conocimientos previos ni ejemplos. Solo lo que dice este texto.
3. LITERALIDAD TÉCNICA: Extrae requisitos como acciones completas. (Ej: 'Presentar X documento').
4. Responde ÚNICAMENTE en JSON.
```

*Clave del Tuning:* Se eliminaron todos los ejemplos del prompt para evitar que la IA los confunda con datos reales del documento actual.

---

## 🔍 4. Pormenores Técnicos Críticos (El "Know-How")

*   **Página como Unidad de Medida:** El sistema de búsqueda (`smart_search`) está configurado para recuperar **páginas completas** donde existan coincidencias, no solo fragmentos. Esto preserva la integridad de las tablas y listas.
*   **Puente de Tipos de Datos:** El agente realiza un "Double-Check" de metadatos (busca páginas como números enteros e hilos de texto) para evitar fallos de recuperación por tipos de datos inconsistentes en la base vectorial.
*   **Frecuencia de Truncamiento:** Si el descubrimiento supera los 64k caracteres, el sistema aplica un "Truncamiento de Seguridad" priorizando las secciones donde se detectaron palabras clave de mayor relevancia.

---

## 📜 5. El Faro de Replicación

Para replicar este éxito en cualquier otra aplicación:
1.  **Doble Búsqueda:** Siempre busca el "Índice" primero para orientar la búsqueda profunda.
2.  **KV-Cache Management:** Nunca subas el contexto más allá de lo que tu VRAM puede mantener (8GB = 16k tokens es el límite seguro).
3.  **Agnosticismo Total:** Nunca dejes que el agente asuma el país o el sector; oblígalo a leer las bases como si fuera la primera vez.

---
*Manual de Ingeniería de Agentes - LicitAI 2024*
