# Diseño: Fast Track Document Candidate List (8GB-friendly)

## Alcance

Diseño de un carril rápido para clasificación documental asistida por humano, sin romper guardas de seguridad ni trazabilidad enterprise.

Componentes objetivo:
- `backend/app/agents/compliance.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/agents/chatbot_rag.py`
- `frontend` (panel/chat para confirmación)

## Arquitectura propuesta

### 1) Candidate Extractor (rápido)

Fuente principal: salida de `ComplianceAgent` (items con `tipo_accion`, `snippet`, `action_confidence`).

Genera `candidate_document_list` con normalización:
- dedupe por fingerprint documental,
- consolidación por categoría,
- score de confianza por documento.

Resultado:
- lista rápida inicial (sin esperar validación profunda completa).

### 2) Human Confirm Layer (HITL)

Nuevo bloque de sesión:
- `document_candidates_v1`
- `document_candidates_user_overrides`
- `document_candidates_final`

Regla de resolución final:
- si existe override de usuario -> usar override,
- si no existe -> usar propuesta automática.

Se registra `provenance_ui` por documento:
- `source: auto_candidate|user_override`
- `confidence`
- `evidence_snippet`

### 3) Quality Gates post-confirmación

Después de confirmar lista:
- ejecutar gates existentes (`document_quality_gate`, `document_fill_quality_gate`) en modo correspondiente.
- si bloqueo crítico: emitir pregunta puntual, no reiniciar todo el flujo.

### 4) Writers consumen lista final reconciliada

Writers leen `document_candidates_final`:
- generar solo `tipo_accion=generar`,
- excluir `presentar_fisico` e `informativo`,
- respetar `no_aplica=true`.

## Contrato de datos sugerido

```json
{
  "candidate_document_list": [
    {
      "document_id": "AT-10",
      "nombre": "Experiencia de la empresa",
      "categoria": "tecnico",
      "tipo_accion_propuesto": "generar",
      "tipo_accion_final": "generar",
      "confidence": 0.88,
      "no_aplica": false,
      "evidence_snippet": "Forma AT-10 ...",
      "provenance_ui": {
        "source": "user_override",
        "reason": "confirmado_por_usuario"
      }
    }
  ],
  "candidate_summary": {
    "generar": 18,
    "presentar_fisico": 9,
    "informativo": 22,
    "no_aplica": 1
  },
  "needs_human_confirmation": true,
  "unresolved_count": 3
}
```

## UX conversacional

### Mensaje inicial Fast Track
- “Ya detecté la lista candidata de documentos. Confirmemos en 1 minuto cuáles generar y cuáles solo presentar.”

### Preguntas tipo
- “El anexo AT-07A aparece en bases, pero parece no aplicable. ¿Lo marcamos como NO APLICA?”
- “¿Este documento lo generamos aquí o lo presentarás como documento existente?”

## Optimización específica para 8GB

1. **Single-pass candidate extraction**
- Evitar múltiples rondas LLM para “certeza perfecta” antes de mostrar lista.

2. **Fallback determinista temprano**
- Si confianza intermedia, proponer y pedir confirmación humana.

3. **Batch de confirmaciones**
- Resolver múltiples documentos en una interacción compacta.

4. **Menos pasamanos entre agentes**
- Reusar salida de compliance para candidate list sin reprocesar todo el pipeline.

## Feature flags propuestas

- `FAST_TRACK_DOC_CANDIDATES_ENABLED` (bool)
- `FAST_TRACK_REQUIRE_HUMAN_CONFIRM` (bool)
- `FAST_TRACK_MAX_UNRESOLVED_BEFORE_BLOCK` (int)

## Riesgos y mitigaciones

- Riesgo: usuario confirme mal por prisa.
  - Mitigación: resaltar bloqueantes y evidencias literales por documento.

- Riesgo: sobredependencia de override humano.
  - Mitigación: gates finales no relajables.

- Riesgo: divergencia con flujo legacy.
  - Mitigación: flag + contrato aditivo + rollback simple.

## Criterios de diseño aprobables

- Lista candidata aparece rápidamente y es útil.
- Confirmación humana reduce fricción sin sacrificar seguridad.
- Pipeline final mantiene calidad documental y trazabilidad.
