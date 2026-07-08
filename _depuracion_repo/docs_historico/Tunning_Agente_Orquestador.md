# 🏗️ Tunning de Agente Orquestador - LicitAI

Este documento es el **Manual de Operaciones Maestras** para la supervisión y encadenamiento de la inteligencia de LicitAI. Define el estándar de "Secuencialismo Transparente" necesario para operar flujos complejos de IA en hardware de 8GB VRAM.

---

## 🔩 1. Estrategia de Cascada Determinista

El Orquestador no lanza agentes en paralelo. Opera mediante una **Cascada de Puntos de Control** para garantizar la integridad de los datos y la estabilidad del hardware:

1.  **Analista (AWAIT):** Primero, se construye el mapa estructural de la licitación.
2.  **Compliance (AWAIT):** Solo después, se inicia la auditoría forense sobre los datos del Analista.
3.  **DataGap (AWAIT):** Finalmente, se comparan los hallazgos de los dos anteriores contra la realidad del expediente.

**Por qué funciona:** Al usar `await` secuencial, el Orquestador asegura que la GPU esté dedicada al 100% a un solo agente en cada micro-momento, evitando colisiones de memoria (VRAM).

---

## 💉 2. Inyección de Contexto Entre Agentes

Para que LicitAI sea "Inteligente como un humano", el Orquestador gestiona la **Herencia de Hallazgos**:

*   **Paso de Estafeta:** El Orquestador toma la `master_compliance_list` generada por el Auditor y la inyecta directamente en el **DataGapAgent** y el **TechnicalWriter**. 
*   **Ahorro de Carga:** Esto evita que el Redactor Técnico tenga que volver a buscar los requisitos en el PDF completo, ahorrando hasta un 60% de llamadas al LLM durante la generación.

---

## 🚦 3. Puntos de Decisión (Filtro de Datos Faltantes)

El Orquestador actúa como el **"Guardia de Seguridad"** de la generación documental:

*   **Pause & Wait:** Si el DataGapAgent detecta un vacío crítico (ej: falta INE), el Orquestador tiene la lógica de **CONGELAR** la tubería y devolver un estado de `waiting_for_data`. 
*   **Prevención de Basura:** No permite que el flujo avance hacia la redacción de documentos si el perfil no ha pasado los filtros de sanidad establecidos en los manuales anteriores.

---

## 📜 4. El Faro de la Orquestación

Para replicar este éxito en cualquier otra app:
1.  **Secuencialismo es Estabilidad:** En IA local, lo rápido es lo secuencial. El paralelismo satura la VRAM y causa cuellos de botella.
2.  **Validación de Salida:** Cada agente debe reportar un "Estado de Tarea" (Success/Error/Waiting) para que el Orquestador tome decisiones lógicas.
3.  **Monitoreo del Usuario:** Siempre reporta qué agente tiene el control. La IA no debe ser una "caja negra" silenciosa.

---
*Manual de Ingeniería de Orquestación - LicitAI 2024*
