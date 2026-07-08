# 🛡️ Tunning de Agente Compliance - LicitAI

Este documento es el **Manual Forense** para la operación y replicación del Agente de Auditoría y Cumplimiento (Agente 2). Define el estándar de "Despiece Quirúrgico" necesario para garantizar el 100% de cumplimiento en una licitación.

---

## 🔬 1. Estrategia de Auditoría por Macro-Zonas

A diferencia del Analista, el Agente de Compliance realiza un **Barrido Profundo** (Deep Dive). Para optimizar el tiempo sin perder detalle, el agente se divide en 4 Macro-Zonas de búsqueda lógica:

1.  **Zona Administrativa/Legal:** Localiza el "quién es quién" y los permisos de autoridad.
2.  **Zona Técnico/Operativo:** Localiza el "qué y cómo" (maquinaria, personal, uniformes).
3.  **Zona de Formatos/Anexos:** Identifica cada sobre y carta obligatoria (Ej: AE-1, AT-1).
4.  **Zona de Garantías:** Define los seguros y fianzas de cumplimiento.

**Filosofía:** Al usar los **16k tokens** de ventana, el agente puede leer hasta 20 fragmentos (aprox. 15-20 páginas) en una sola zona, permitiéndole entender la relación entre un requisito y su sección de penalizaciones.

---

## 🖥️ 2. Reglas de Oro de "Antigravity" (Extracción)

Para que el agente sea un Auditor Senior, el prompt debe forzar las siguientes conductas:

*   **Granularidad Máxima:** "Si un párrafo pide 3 cosas, son 3 requisitos separados". Esto evita que se pierdan detalles críticos como "radios con frecuencias específicas" dentro de un requisito de equipamiento.
*   **Evidencia Literal (Snippet):** El agente debe citar el texto original. Esto sirve como prueba jurídica de por qué se está pidiendo ese documento.
*   **Hash de Unicidad:** Se implementó una lógica de `snippet_hash` para evitar que requisitos duplicados (que aparecen en varias páginas del PDF) ensucien la lista maestra.

---

## ⚙️ 3. Optimización de VRAM y Contexto

*   **Window Tuning:** El agente está calibrado para enviar **64,000 caracteres** por cada zona de auditoría.
*   **Eficiencia Temporal:** Al reducir de 11 micro-zonas a 4 macro-zonas, el tiempo de auditoría bajó de **15 minutos a solo ~3 minutos**, manteniendo un 100% de efectividad en la detección de puntos clave (SAT, IMSS, Maquinaria).
*   **Consumo Operativo:** Durante el barrido, la RTX 4060 mantiene un uso aproximado de **7.7GB de VRAM**, operando en el modo de mayor eficiencia posible para 8GB.

---

## 📜 4. El Faro del Auditor

Para replicar este éxito en cualquier otra app:
1.  **No Resumas:** Un Auditor nunca resume. Extrae.
2.  **Página y Sección:** Siempre debe reportar la ubicación exacta. Un reporte de cumplimiento sin página no tiene valor forense.
3.  **Cross-Reference:** Asegúrate de que el buscador RAG traiga suficiente contexto "Smart Search" para no perder el título del numeral al leer el requisito.

---
*Manual de Ingeniería de Auditoría - LicitAI 2024*
