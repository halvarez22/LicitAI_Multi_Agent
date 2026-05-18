# Tasks: Implementation Log

- [x] **Fase 1: Humanización de Labels**
    - Corregir el bucle del subtotal saltando a sugerencias individuales.
    - Eliminar templates robóticos ("0 citas", "fila detectado").
- [x] **Fase 2: Motor de Extracción Inteligente**
    - Implementar `_extract_economic_data_llm`.
    - Actualizar `_classify_message` para detectar `DATA_INTAKE` por contexto.
- [x] **Fase 3: Integración de Ciclo Cerrado**
    - Conectar extracción con `_handle_economic_transaction`.
    - Activar `refresh_economic_validations_for_session` post-save.
    - Validar con captura multivariable masiva.
