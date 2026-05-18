# Bugfix Design: DataGap enqueue-all-missing

## Overview

Este diseño corrige la divergencia entre spec y runtime: el asistente debe solicitar por chat **todo dato faltante** detectado en perfil, mientras que el bloqueo de generación documental debe seguir aplicando solo a campos críticos.

El cambio central es desacoplar explícitamente dos conceptos:

- **Preguntar (HITL conversacional):** cola `pending_questions` con todos los faltantes.
- **Bloquear (gate transaccional):** evaluación de `missing_blocking` para `WAITING_FOR_DATA`.

## Objetivos

1. Que `DataGapAgent` encole faltantes críticos y no críticos.
2. Que `ChatbotRAG` pregunte secuencialmente una pregunta por turno.
3. Que `Orchestrator/Formats` mantengan bloqueo solo por campos críticos.
4. Preservar auto-extracción RAG y sanitización vigente.

## No objetivos

- Rediseñar reglas de `_is_data_valid`.
- Cambiar la lista de campos críticos.
- Cambiar contratos de documentos autogenerables.

---

## Arquitectura de la solución

### Componentes impactados

- `backend/app/agents/data_gap.py`
- `backend/app/agents/chatbot_rag.py`
- `backend/app/agents/formats.py` (si consume payload de faltantes)
- `backend/app/agents/technical_writer.py` (si consume payload de faltantes)
- `backend/app/agents/orchestrator.py` (solo integración/lectura de flags)

### Flujo objetivo

1. `DataGapAgent` evalúa campos activos.
2. Si no hay valor válido ni auto-extracción RAG válida:
   - agrega entrada a `missing` (siempre),
   - marca si es crítico (`is_blocking`),
   - agrega a `missing_blocking` si aplica.
3. Persiste `pending_questions` desde `missing` (no desde subset crítico).
4. `ChatbotRAG` consume `pending_questions` y formula la pregunta actual.
5. Al guardar respuesta:
   - actualiza `master_profile`,
   - avanza índice secuencial,
   - si se omite y no es crítico, continúa.
6. `Orchestrator/Formats` bloquean solo si `missing_blocking` no vacío.

---

## Contrato de datos propuesto

### DataGap output

```json
{
  "auto_filled": ["telefono"],
  "missing": [
    {
      "field": "email",
      "label": "Correo electrónico de la empresa",
      "question": "¿Cuál es el correo electrónico oficial de ...?",
      "document_hint": "Membrete corporativo",
      "type": "profile_field",
      "is_blocking": false
    },
    {
      "field": "rfc",
      "label": "RFC de la empresa",
      "question": "¿Cuál es el RFC oficial de ...?",
      "document_hint": "Cédula de Identificación Fiscal (CIF)",
      "type": "profile_field",
      "is_blocking": true
    }
  ],
  "missing_blocking": ["rfc"]
}
```

### Session state

- `pending_questions`: arreglo de entradas derivadas de `missing` (incluye `is_blocking`).
- `pending_question_index`: índice actual para flujo secuencial.

---

## Diseño por archivo

### 1) `data_gap.py`

#### Cambios

- Remover la rama que descarta no bloqueantes.
- Construir entrada de faltante única con:
  - `field`, `label`, `question`, `document_hint`, `type`, `is_blocking`.
- Poblar:
  - `missing`: todos los faltantes.
  - `missing_blocking`: claves críticas faltantes.
- Persistir `pending_questions = missing`.

#### Invariantes

- Un campo no puede estar simultáneamente en `auto_filled` y `missing`.
- `missing_blocking` es subconjunto estricto de `missing`.

### 2) `chatbot_rag.py`

#### Cambios

- Priorizar cola pendiente:
  - si existe `pending_questions`, preguntar `pending_question_index`.
  - si no existe, invocar DataGap proactivo y usar primera pregunta.
- Soportar omisión explícita de no bloqueantes:
  - marca auditada (`omitted=true`, `source=user_skip`),
  - avanza índice.
- Si el faltante actual es bloqueante y usuario intenta omitir durante generación:
  - mantener `WAITING_FOR_DATA`.

#### Invariantes

- Solo una pregunta activa por turno.
- No avanzar sin persistencia o omisión válida.

### 3) `formats.py` / `technical_writer.py` / `orchestrator.py`

#### Cambios

- Consumir `missing_blocking` para gate documental.
- No bloquear por faltantes no críticos.

#### Invariantes

- `WAITING_FOR_DATA` se justifica solo por críticos faltantes.

---

## Reglas de precedencia y gobernanza

1. Valor directo de usuario guardado en chat/UI.
2. Valor normalizado de documento del oferente.
3. Catálogo maestro/perfil persistido.
4. Inferencia RAG/LLM.

Toda omisión y toda respuesta deben dejar rastro auditable (fuente/origen).

---

## Riesgos y mitigaciones

- **Riesgo:** explosión de preguntas al usuario.
  - **Mitigación:** una por turno + opción de omitir no crítico.
- **Riesgo:** regresión en generación actual.
  - **Mitigación:** gate solo por `missing_blocking`.
- **Riesgo:** bucles por rehidratación de pendientes.
  - **Mitigación:** deduplicar por `field` y controlar `pending_question_index`.

---

## Estrategia de pruebas

### Unitarias

- `DataGap`: encola no bloqueantes; separa `missing` y `missing_blocking`.
- `ChatbotRAG`: saludo con pendientes, saludo sin pendientes (proactivo), avance secuencial.
- Gate: bloqueo solo por críticos.

### Integración

- Caso mixto (críticos + informativos) con flujo de preguntas y bloqueo correcto.
- Omitir no crítico no bloquea.
- Omitir crítico en generación mantiene `WAITING_FOR_DATA`.

### E2E funcional

- Confirmar que documentos autogenerables (protesta, integridad, no conflicto) no se piden como upload.

---

## Plan de despliegue

1. Implementación backend con feature flag opcional `ENQUEUE_ALL_GAPS=true` (default true).
2. Tests unitarios e integración en CI.
3. Smoke E2E manual en sesión real de prueba.
4. Monitoreo de logs:
   - `pending_questions_count`
   - `missing_blocking_count`
   - transición `waiting_for_data -> success`.

## Rollback

- Desactivar `ENQUEUE_ALL_GAPS` para volver temporalmente al comportamiento legacy mientras se corrige.
