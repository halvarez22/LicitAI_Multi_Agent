# 🚀 Plan de Acción: LicitAI Evolución - Memoria y Economía (Fase 2)

Este plan detalla la implementación de los dos pilares críticos para transformar LicitAI en un **Director de Licitaciones**: La Memoria Organizacional y el Agente Económico.

---

## 🏗️ Fase 1: Infraestructura de Datos (Cerebro de Almacenamiento)
*Objetivo: Dotar al sistema de memoria persistente para la empresa y sus precios.*

1.  **Actualización de PostgreSQL:**
    *   **Tabla `company_catalog`:** Para guardar el catálogo de precios unitarios de la empresa (Insumos, Personal, Maquinaria).
    *   **Tabla `company_assets`:** Para registrar documentos clave (INE, Acta, SAT) con su fecha de vencimiento y estatus de indexación.
    *   **Tabla `session_economics`:** Para guardar los márgenes de utilidad e indirectos específicos de cada licitación.
2.  **Mantenimiento de Colecciones Vectoriales:**
    *   Asegurar un "Namespace" perpetuo en ChromaDB: `company_{company_id}`.

---

## 🔍 Fase 2: Memoria Organizacional (Auto-Mapeo)
*Objetivo: Que el sistema "sepa" quién es la empresa sin preguntar.*

1.  **Pipeline de Pre-Extracción (Intake Internal):**
    *   Al subir un archivo al expediente de empresa, se dispara un proceso de OCR + Extracción.
    *   El **IntakeAgent** busca patrones (RFC, INE, Fecha de Fundación) y actualiza el `master_profile` automáticamente.
2.  **Búsqueda Cross-Collection (DataGap L2):**
    *   El **DataGapAgent** ya no solo busca en la licitación. 
    *   Si detecta que falta un requisito (ej: Acta de Nacimiento), hace una consulta a la colección `company_{id}`. 
    *   *Lógica:* "Si está en mi memoria de empresa, el Gap está cerrado automáticamente".

---

## 💰 Fase 3: Agente Económico (El Corazón Financiero)
*Objetivo: Generar propuestas económicas basadas en matemáticas reales.*

1.  **Nuevo: `EconomicAgent.py`:**
    *   **Función A:** Leer el "Anexo de Precios" o "Catálogo de Conceptos" de la licitación (desde el Analista).
    *   **Función B:** Consultar el `company_catalog` para encontrar el precio unitario de esos ítems.
    *   **Función C:** Aplicar la fórmula: `(Cantidades x Precios) + Indirectos + Utilidad = Precio Sugerido`.
2.  **Detección de "Gap Financiero":**
    *   Si la licitación pide un insumo que NO tenemos en catálogo, el Agente Económico lanza una alerta al **IntakeAgent** para preguntárselo al usuario vía Chat.

---

## 🚦 Fase 4: Orquestación y UX (Control de Flujo)
*Objetivo: Integrar todo en la cascada secuencial estable.*

1.  **Actualización del Orquestador:**
    *   Añadir el paso: `Economic_Analysis_START` al final de la cadena.
    *   Vincular el éxito del DataGap a la existencia de la "Memoria Organizacional".
2.  **Feedback Visual:**
    *   Mostrar al usuario: *"Detectando documentos previos... INE encontrado ✅"*.
    *   Mostrar: *"Calculando margen de utilidad del 15%... Propuesta Económica lista 🟢"*.

---

## 🧪 Estrategia de Pruebas (Exhaustivas)
1.  **Test de Memoria:** Subir un INE genérico a la carpeta de empresa y verificar que el `master_profile` se llene solo.
2.  **Test de Catálogo:** Subir un Excel de precios y verificar que el Agente Económico lo asocie a un requerimiento de licitación.
3.  **Test de Estrés de VRAM:** Correr el flujo completo (Analista -> Compliance -> DataGap -> Económico) asegurando que no supere los 8GB.

---
**Veredicto del Plan:** Esta arquitectura elimina el trabajo redundante de subir documentos cada vez y convierte a LicitAI en un estratega de precios. ⚖️🤖💸
