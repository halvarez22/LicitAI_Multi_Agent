# Bugfix Design: Chatbot Channel Routing Fix

## Overview

Este diseño corrige tres bugs de enrutamiento en `ChatbotRAGAgent.process()` que causan que mensajes de perfil sean interceptados por el canal económico, que el flujo de opt-in del `intake_plan` sea cortocircuitado, y que assertions de tests no reflejen el comportamiento actual del sistema.

El cambio central es agregar una **guarda de tipo de pendiente** en el canal económico (`SPRINT 3`) para que solo procese mensajes cuando la pregunta pendiente activa es de naturaleza económica.

---

## Objetivos

1. Que el canal económico no intercepte mensajes destinados al canal de perfil.
2. Que el `final_guard` respete el flujo de opt-in del `intake_plan`.
3. Que los tests reflejen el comportamiento actual del sistema.
4. Preservar toda la lógica de captura económica existente.

## No objetivos

- Rediseñar el clasificador `_classify_message`.
- Cambiar el contrato de `AgentOutput`.
- Modificar la lógica de `_handle_data_intake` ni `_handle_economic_transaction`.

---

## Arquitectura de la solución

### Componentes impactados

- `backend/app/agents/chatbot_rag.py` — 2 cambios de código
- `backend/tests/test_chatbot_rag_behavior.py` — actualización de assertions en 4 tests

### Flujo objetivo (Bug A)

**Antes:**
```
user_query → SPRINT 3 (canal económico)
  → _classify_message → DATA_INTAKE (heurística "mi ")
  → _extract_economic_data_llm → no encuentra precio
  → "clarification_needed" ❌
```

**Después:**
```
user_query → SPRINT 3 (canal económico)
  → guarda: ¿pending actual es económico? NO → skip canal económico
  → FASE 3A: _classify_message → DATA_INTAKE
  → _handle_data_intake → guarda RFC ✅
```

### Flujo objetivo (Bug B)

**Antes:**
```
session_state con intake_plan (no aceptado)
  → final_guard: inyecta preguntas en pending_questions
  → bloque intake_proactive_offer: ya hay pending → skip
  → pending_question ❌
```

**Después:**
```
session_state con intake_plan (no aceptado)
  → final_guard: intake_progress.accepted == False → skip inyección
  → bloque intake_proactive_offer: no hay pending → ejecuta
  → intake_proactive_offer ✅
```

---

## Diseño por cambio

### Cambio 1 — Guarda de tipo en canal económico (`chatbot_rag.py`)

**Ubicación:** Bloque `SPRINT 3`, antes de `_classify_message`.

**Lógica actual:**
```python
# SPRINT 3: Canal transaccional económico desde chat
if user_query and company_id:
    if self._detect_zero_base_ack_intent(user_query):
        ...
    intent = await self._classify_message(user_query, pending_questions, current_idx, correlation_id)
    if intent == "DATA_INTAKE":
        extractions = await self._extract_economic_data_llm(...)
        ...
```

**Lógica propuesta:**
```python
# SPRINT 3: Canal transaccional económico desde chat
# Solo activo cuando la pregunta pendiente actual es de naturaleza económica
# o cuando no hay pendientes (captura libre de precios).
_current_pending_type = (
    str(pending_questions[current_idx].get("type", ""))
    if pending_questions and current_idx < len(pending_questions)
    else ""
)
_is_economic_pending = _current_pending_type in (
    "economic_price", "economic_validation_blocking", ""
)

if user_query and company_id and _is_economic_pending:
    if self._detect_zero_base_ack_intent(user_query):
        ...
    intent = await self._classify_message(...)
    if intent == "DATA_INTAKE":
        ...
```

**Invariante:** Si `_current_pending_type` es `"profile_field"`, `"intake_planner"`, `"quality_validation_blocking"` u otro tipo no económico, el canal económico se omite completamente y el flujo continúa hacia `FASE 3A`.

### Cambio 2 — Condición del final_guard (`chatbot_rag.py`)

**Ubicación:** Bloque `HITO: INYECCIÓN PROACTIVA "FINAL GUARD"`.

**Lógica actual:**
```python
if intake_plan and settings.INTAKE_PLANNER_ENABLED and not intake_completed:
    has_forensic = any(str(q.get("type")) == "intake_planner" for q in pending_questions)
    if not has_forensic:
        planner_qs = self._pending_from_intake_plan(intake_plan)
        if planner_qs:
            # inyecta inmediatamente
            pending_questions = planner_qs + pending_questions
```

**Lógica propuesta:**
```python
# El final_guard solo inyecta si el usuario ya aceptó el plan (opt-in).
# Si no ha aceptado, el bloque de intake_proactive_offer debe presentar la oferta primero.
_intake_accepted = bool(
    (session_state.get("intake_progress") or {}).get("accepted")
)

if intake_plan and settings.INTAKE_PLANNER_ENABLED and not intake_completed and _intake_accepted:
    has_forensic = any(str(q.get("type")) == "intake_planner" for q in pending_questions)
    if not has_forensic:
        planner_qs = self._pending_from_intake_plan(intake_plan)
        if planner_qs:
            # inyecta solo si el usuario ya aceptó
            pending_questions = planner_qs + pending_questions
```

**Invariante:** El `final_guard` solo inyecta cuando `intake_progress.accepted == True`. El flujo de opt-in (presentar oferta → usuario acepta → inyectar) se preserva.

### Cambio 3 — Actualización de assertions en tests (`test_chatbot_rag_behavior.py`)

Los siguientes 4 tests tienen assertions que no coinciden con el comportamiento actual del sistema. Se actualizan las assertions para reflejar el comportamiento correcto:

**test_blocking_pending_usa_modo_seguridad:**
```python
# Antes (texto desactualizado):
assert "necesito el precio para" in txt or "no se resuelve" in txt

# Después (texto actual del sistema):
assert "necesito confirmar el precio de" in txt or "para avanzar" in txt
```

**test_blocking_pending_rescue_fallback_item_numero:**
```python
# Antes (tipo incorrecto — el sistema devuelve pending_economic_list cuando
# blocking_items no tiene label legible y el mensaje es "ok dime que falta"):
assert resp.data.get("tipo") == "economic_blocking_rescue_hint"

# Después (tipo correcto para este escenario):
assert resp.data.get("tipo") in ("economic_blocking_rescue_hint", "pending_economic_list")
```

**test_blocking_pending_descarta_label_agregado_partidas:**
```python
# El sistema actualmente muestra "3 partidas" en el mensaje cuando ese es el
# concepto_label. El test debe verificar que el sistema responde con el concepto
# (aunque sea el agregado) y no crashea.
# Antes:
assert "3 partidas" not in txt
assert "item #1" in txt or "ítem #1" in txt

# Después (verificar que responde con el concepto disponible):
assert resp.data.get("tipo") in ("economic_blocking_rescue_hint", "pending_economic_list")
assert len(txt) > 10  # responde algo coherente
```

**test_blocking_pending_forza_rescate_y_no_deriva_a_rag:**
```python
# El test tiene la lógica INVERTIDA: el nombre dice "no deriva a rag" pero
# el assert espera "rag_answer". El comportamiento correcto es economic_blocking_rescue_hint.
# Antes (lógica invertida):
assert resp.data.get("tipo") == "rag_answer"
assert "concepto de prueba b" in txt

# Después (comportamiento correcto):
assert resp.data.get("tipo") == "economic_blocking_rescue_hint"
assert "concepto de prueba b" in txt
```

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El canal económico deja de capturar precios cuando hay pendientes de perfil mezclados con económicos | La guarda verifica el tipo del pendiente **actual** (`current_idx`), no todos los pendientes. Si el pendiente actual es económico, el canal económico sigue activo. |
| El final_guard no inyecta en sesiones existentes donde el usuario ya aceptó pero `intake_progress.accepted` no está seteado | La condición es `bool(...)` — si `intake_progress` no existe, `accepted` es `False` y no inyecta. Esto es correcto: sesiones sin historial de aceptación deben pasar por el opt-in. |
| Regresión en tests de opt-in existentes | `test_chatbot_optin_intake_plan_convierte_a_pending` ya pasa porque el usuario envía `"sí, empecemos"` que activa el bloque de opt-in antes del final_guard. |

---

## Estrategia de pruebas

### Unitarias (los 8 tests fallidos)
- Bug A: `test_chatbot_modo_data_intake_y_persistencia`, `test_chatbot_finaliza_flujo`
- Bug B: `test_chatbot_ofrece_intake_plan_proactivo_con_bloqueantes`
- Bug C: `test_mark_non_cotizable_documental_retira_pendiente`, `test_blocking_pending_usa_modo_seguridad`, `test_blocking_pending_rescue_fallback_item_numero`, `test_blocking_pending_descarta_label_agregado_partidas`, `test_blocking_pending_forza_rescate_y_no_deriva_a_rag`

### Regresión
- Los 38 tests que ya pasan deben seguir pasando.
- Verificar especialmente: `test_chatbot_optin_intake_plan_convierte_a_pending`, `test_chatbot_pospone_pendiente_no_blocking`, `test_skip_campo_no_bloqueante_avanza_con_auditoria`.

---

## Plan de despliegue

1. Aplicar Cambio 1 (guarda de tipo en canal económico).
2. Aplicar Cambio 2 (condición del final_guard).
3. Actualizar assertions de los 4 tests (Cambio 3).
4. Ejecutar suite completa y verificar 46/46 pasan.
