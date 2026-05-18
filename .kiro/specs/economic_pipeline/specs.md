# Economic Pipeline Specifications

## Objetivo
Establecer un pipeline robusto, determinista y auditable para la captura, validación y formateo de la propuesta económica en LicitAI. El sistema debe evitar la "amnesia" conversacional y garantizar que los datos financieros del usuario se persistan en memoria y se validen contra las restricciones de la convocatoria.

## Componentes y Requisitos Funcionales

### 1. Extractor Económico en Chat (El Colector)
- **Función:** El `ChatbotRAGAgent` debe ser capaz de detectar cuándo el usuario proporciona datos económicos (ej. precios unitarios, totales, costos por zona).
- **Mecanismo:** En lugar de solo responder con texto, el agente debe usar *Function Calling* o un extractor estructurado para mutar el estado `session["state_data"]["economic_parameters"]`.
- **Restricción:** No debe avanzar al siguiente paso si detecta ambigüedad en los números (ej. si el usuario da un precio sin especificar la zona o unidad).

### 2. Economic Agent (El Validador Matemático)
- **Función:** Actúa como auditor financiero. NO extrae datos de la conversación; su única fuente de verdad es `session["state_data"]["economic_parameters"]`.
- **Mecanismo:**
  - Lee los datos persistidos.
  - Ejecuta RAG sobre las bases para buscar restricciones (Techos presupuestales, salarios mínimos, impuestos).
  - Realiza validaciones matemáticas (Cálculo de IVA, sumatorias).
- **Salidas:** 
  - `ECONOMIC_VALIDATED`: Si los números cuadran y cumplen las reglas.
  - `ECONOMIC_ERROR`: Si hay discrepancias o faltan datos, emitiendo una alerta específica (ej. "Falta el precio de la Zona 2").

### 3. Economic Writer Agent (El Generador de Anexos)
- **Función:** Generar la tabla de cotización final o el formato requerido por la convocante.
- **Mecanismo:** Se activa únicamente cuando el estado es `ECONOMIC_VALIDATED`. 
- **Restricción:** Transcribe *exactamente* los números de `economic_parameters`. Prohibido alterar, redondear al azar o alucinar precios.
- **Salida:** Formato Markdown o JSON tabular listo para la UI o exportación a Excel/Word.
