# Design: Semantic Intake Architecture

## 1. Cambio de Paradigma: De Regex a LLM Extraction
Se abandona el uso de expresiones regulares en `_detect_economic_transaction_intent` en favor de una llamada estructurada al LLM (`ResilientLLMClient`).

### Componentes:
- **`_extract_economic_data_llm`**: Genera un prompt de extracción que inyecta las partidas sugeridas (`economic_unverified_suggestions`) para guiar la inferencia (Grounding).
- **Format JSON**: Se utiliza el modo `format="json"` de Ollama/Gemini para garantizar un esquema predecible.

## 2. Resolución Semántica (Fuzzy Mapping)
El sistema implementa `_resolve_economic_concept` que actúa como puente entre el lenguaje humano ("Zona A") y las llaves técnicas de la base de datos ("price_Anexo_III_Zona_A").

## 3. Integración con el Motor Económico
Para evitar que los datos capturados sean ignorados por el orquestador, se dispara `refresh_economic_validations_for_session` inmediatamente después de cada guardado exitoso en el chat. Esto garantiza que el semáforo económico se actualice en tiempo real.
