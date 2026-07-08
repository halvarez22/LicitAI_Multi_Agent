# Plan de Implementación: Integración del Router con el Quality Gate de Generación

## Overview

Corrección del quality gate en `TechnicalWriterAgent` y `FormatsAgent` para que use el `triage_context` del router al decidir si bloquear la generación. El cambio principal es agregar una excepción para licitaciones de obra pública (categoría OBRA) donde `generar_count = 0` es el comportamiento correcto, no un error de clasificación.

**Archivos afectados:**
- `backend/app/agents/technical_writer.py`
- `backend/app/agents/formats.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/services/router_prompts.py`
- `backend/tests/test_tender_router_quality_gate.py` (nuevo)

---

## Tasks

- [x] 1. Extender `_should_block_by_quality_gate` en `technical_writer.py`
  - [x] 1.1 Agregar parámetros `presentar_fisico_count: int = 0` y `triage_context: Optional[Dict[str, Any]] = None` a la firma de `_should_block_by_quality_gate`
    - Ubicación: `backend/app/agents/technical_writer.py`, función `_should_block_by_quality_gate`
    - _Requirements: 1.1, 1.4_

  - [x] 1.2 Insertar la excepción OBRA antes de la condición `if generar_count == 0`
    - Si `tender_category == "OBRA"` y `generar_count == 0` y `presentar_fisico_count > 0`: retornar `{"block": False, "reason": "obra_category_no_generate_items_expected", "metrics": {...}}`
    - Si `tender_category == "OBRA"` y `total_items == 0`: retornar `{"block": False, "reason": "", "metrics": {}}`
    - Incluir `tender_category` en las métricas del resultado cuando está disponible
    - _Requirements: 1.1, 1.2, 5.1_

  - [x] 1.3 Actualizar la llamada a `_should_block_by_quality_gate` en `TechnicalWriterAgent.process()` para pasar los nuevos parámetros
    - Pasar `presentar_fisico_count=action_counts.get("presentar_fisico", 0)`
    - Pasar `triage_context=agent_input.triage_context`
    - Ubicación: `backend/app/agents/technical_writer.py`, método `process()`, línea donde se llama `_should_block_by_quality_gate`
    - _Requirements: 1.1, 2.1_

- [x] 2. Agregar mensaje informativo para OBRA sin ítems generables en `TechnicalWriterAgent`
  - [x] 2.1 Modificar el bloque `if not tech_requirements` para distinguir entre OBRA y otros casos
    - Si `tender_category == "OBRA"`: retornar `AgentStatus.SUCCESS` con mensaje explicativo y log `technical_writer_obra_skip`
    - Si no es OBRA: mantener el mensaje actual "No hay requisitos técnicos por redactar."
    - Ubicación: `backend/app/agents/technical_writer.py`, método `process()`, bloque `if not tech_requirements`
    - _Requirements: 1.1, 5.3_

- [x] 3. Extender `_should_block_by_quality_gate` en `formats.py`
  - [x] 3.1 Aplicar los mismos cambios de la Tarea 1 a la función `_should_block_by_quality_gate` en `FormatsAgent`
    - Misma firma extendida: `presentar_fisico_count` y `triage_context`
    - Misma excepción OBRA
    - Ubicación: `backend/app/agents/formats.py`, función `_should_block_by_quality_gate`
    - _Requirements: 1.5_

  - [x] 3.2 Actualizar la llamada a `_should_block_by_quality_gate` en `FormatsAgent.process()` para pasar los nuevos parámetros
    - Pasar `presentar_fisico_count` desde `action_counts`
    - Pasar `triage_context=agent_input.triage_context`
    - Ubicación: `backend/app/agents/formats.py`, método `process()`, línea donde se llama `_should_block_by_quality_gate`
    - _Requirements: 1.5, 2.2_

- [x] 4. Propagar `triage_context` en el orquestador para modo `generation_only`
  - [x] 4.1 Agregar bloque de inyección de `triage_context` en `agent_input` antes del loop de agentes de generación
    - Leer `triage_context` de `session_state` si `agent_input.triage_context` está vacío
    - Actualizar `agent_input` con `model_copy(update={"triage_context": _triage})`
    - Registrar log `orchestrator_triage_injected_for_generation` con `tender_category` y `law`
    - Ubicación: `backend/app/agents/orchestrator.py`, bloque `generation_only`, después de `_ensure_economic_snapshot_ready` y antes del loop `for step, a_cls in [...]`
    - _Requirements: 2.1, 2.2, 2.4_

- [x] 5. Agregar señales OBRA al prompt de triage v2
  - [x] 5.1 Extender `TRIAGE_PROMPT_V2` en `router_prompts.py` con regla explícita para OBRA/LOPSRM
    - Agregar regla: si `law = "LOPSRM"`, `tender_category` siempre es `"OBRA"`
    - Agregar señales: formas AT/AE, "catálogo de conceptos de obra", "explosión de insumos", "programa de obra", "contratista", "superintendente de obra"
    - Ubicación: `backend/app/services/router_prompts.py`, constante `TRIAGE_PROMPT_V2`
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 6. Tests unitarios y de propiedades
  - [x] 6.1 Crear archivo `backend/tests/test_tender_router_quality_gate.py` ✅
  - [x] 6.2 `test_obra_no_block_when_all_presentar_fisico` ✅
  - [x] 6.3 `test_obra_normal_when_has_generar_items` ✅
  - [x] 6.4 `test_servicios_blocks_when_no_generar` ✅
  - [x] 6.5 `test_none_triage_uses_original_thresholds` ✅
  - [x] 6.6 `test_obra_empty_list_no_block` ✅
  - [x] 6.7 Property test `test_obra_never_blocks_when_all_presentar_fisico` ✅
  - [x] 6.8 Property test `test_non_obra_preserves_original_behavior` ✅

- [x] 7. Checkpoint final — Todos los tests pasan
  - **20/20 tests pasan** en `backend/tests/test_tender_router_quality_gate.py`
  - Cero errores de diagnóstico en los 4 archivos modificados
    - Pasar `triage_context=agent_input.triage_context`
    - Ubicación: `backend/app/agents/technical_writer.py`, método `process()`, línea donde se llama `_should_block_by_quality_gate`
    - _Requirements: 1.1, 2.1_

- [ ] 2. Agregar mensaje informativo para OBRA sin ítems generables en `TechnicalWriterAgent`
  - [ ] 2.1 Modificar el bloque `if not tech_requirements` para distinguir entre OBRA y otros casos
    - Si `tender_category == "OBRA"`: retornar `AgentStatus.SUCCESS` con mensaje explicativo y log `technical_writer_obra_skip`
    - Si no es OBRA: mantener el mensaje actual "No hay requisitos técnicos por redactar."
    - Ubicación: `backend/app/agents/technical_writer.py`, método `process()`, bloque `if not tech_requirements`
    - _Requirements: 1.1, 5.3_

- [ ] 3. Extender `_should_block_by_quality_gate` en `formats.py`
  - [ ] 3.1 Aplicar los mismos cambios de la Tarea 1 a la función `_should_block_by_quality_gate` en `FormatsAgent`
    - Misma firma extendida: `presentar_fisico_count` y `triage_context`
    - Misma excepción OBRA
    - Ubicación: `backend/app/agents/formats.py`, función `_should_block_by_quality_gate`
    - _Requirements: 1.5_

  - [ ] 3.2 Actualizar la llamada a `_should_block_by_quality_gate` en `FormatsAgent.process()` para pasar los nuevos parámetros
    - Pasar `presentar_fisico_count` desde `action_counts`
    - Pasar `triage_context=agent_input.triage_context`
    - Ubicación: `backend/app/agents/formats.py`, método `process()`, línea donde se llama `_should_block_by_quality_gate`
    - _Requirements: 1.5, 2.2_

- [ ] 4. Propagar `triage_context` en el orquestador para modo `generation_only`
  - [ ] 4.1 Agregar bloque de inyección de `triage_context` en `agent_input` antes del loop de agentes de generación
    - Leer `triage_context` de `session_state` si `agent_input.triage_context` está vacío
    - Actualizar `agent_input` con `model_copy(update={"triage_context": _triage})`
    - Registrar log `orchestrator_triage_injected_for_generation` con `tender_category` y `law`
    - Ubicación: `backend/app/agents/orchestrator.py`, bloque `generation_only`, después de `_ensure_economic_snapshot_ready` y antes del loop `for step, a_cls in [...]`
    - _Requirements: 2.1, 2.2, 2.4_

- [ ] 5. Agregar señales OBRA al prompt de triage v2
  - [ ] 5.1 Extender `TRIAGE_PROMPT_V2` en `router_prompts.py` con regla explícita para OBRA/LOPSRM
    - Agregar regla: si `law = "LOPSRM"`, `tender_category` siempre es `"OBRA"`
    - Agregar señales: formas AT/AE, "catálogo de conceptos de obra", "explosión de insumos", "programa de obra", "contratista", "superintendente de obra"
    - Ubicación: `backend/app/services/router_prompts.py`, constante `TRIAGE_PROMPT_V2`
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 6. Tests unitarios y de propiedades
  - [ ] 6.1 Crear archivo `backend/tests/test_tender_router_quality_gate.py`
    - Estructura base con imports y helpers para construir `triage_context` de prueba
    - _Requirements: 4.1_

  - [ ] 6.2 Test unitario: `test_gate_obra_no_block_when_all_presentar_fisico`
    - OBRA + generar=0 + presentar_fisico=5 → `block: False`, `reason: "obra_category_no_generate_items_expected"`
    - _Requirements: 1.1_

  - [ ] 6.3 Test unitario: `test_gate_obra_normal_when_has_generar_items`
    - OBRA + generar=3 + presentar_fisico=2 + evidence_ratio=0.3 → aplica umbrales normales (puede bloquear por evidence)
    - _Requirements: 1.1_

  - [ ] 6.4 Test unitario: `test_gate_servicios_blocks_when_no_generar`
    - SERVICIOS + generar=0 + presentar_fisico=5 → `block: True`, `reason: "no_actionable_generate_items"`
    - _Requirements: 4.1_

  - [ ] 6.5 Test unitario: `test_gate_none_triage_uses_original_thresholds`
    - triage=None + generar=0 → `block: True` (comportamiento original preservado)
    - _Requirements: 4.3_

  - [ ] 6.6 Test unitario: `test_gate_obra_empty_list_no_block`
    - OBRA + total=0 + generar=0 + presentar_fisico=0 → `block: False` (lista vacía, no hay nada que evaluar)
    - _Requirements: 1.2_

  - [ ]* 6.7 Property test: `test_obra_never_blocks_when_all_presentar_fisico`
    - `@given(presentar_fisico_count=st.integers(min_value=1, max_value=50), ...)`
    - OBRA + generar=0 + presentar_fisico>0 → `block: False` para cualquier combinación de parámetros
    - **Property 1: Excepción OBRA no bloquea cuando todos los ítems son presentar_fisico**
    - _Requirements: 1.1_

  - [ ]* 6.8 Property test: `test_non_obra_preserves_original_behavior`
    - `@given(category=st.sampled_from(["BIENES", "SERVICIOS", "TECNOLOGIA", None]), ...)`
    - Para categorías no-OBRA, el resultado es idéntico al comportamiento original
    - **Property 2: Preservación de umbrales para licitaciones no-OBRA**
    - _Requirements: 4.1, 4.2, 4.3_

- [ ] 7. Checkpoint final — Todos los tests pasan
  - Ejecutar `pytest backend/tests/test_tender_router_quality_gate.py -v` y verificar que todos los tests pasan
  - Verificar manualmente con la sesión de "licitacion OPM-001-2026 MADERA CHIHUAHUA" que la generación avanza sin bloqueo por quality gate

## Notes

- Las tareas marcadas con `*` son opcionales para MVP
- El orden recomendado: 1 → 2 → 3 → 4 → 6 (tests) → 5 (prompt) → 7 (checkpoint)
- La Tarea 4 (orquestador) es independiente de las Tareas 1-3 y puede implementarse en paralelo
- La Tarea 5 (prompt) solo afecta sesiones nuevas; las sesiones existentes ya tienen `triage_context` guardado
- Los cambios en `_should_block_by_quality_gate` son retrocompatibles: los parámetros nuevos tienen valores por defecto
- El fix no requiere cambios en la DB ni en el frontend
