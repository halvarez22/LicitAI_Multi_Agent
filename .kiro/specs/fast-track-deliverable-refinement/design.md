# Diseño Técnico: Filtrado de Ruido y Persistencia de Candidatos

## 1. Arquitectura de Datos

### Flujo de Persistencia
Para evitar que la lista desaparezca en ejecuciones parciales, se modifica el `OrchestratorAgent`:
- **Inyección en Retornos Tempranos**: Se asegura que la clave `fast_track_document_candidates` se incluya en el diccionario de respuesta de todos los puntos de salida (Economic Gaps, Data Gaps).
- **Wrapper de Estado**: La función `_response_with_generation_state` ahora actúa como guardián, recuperando los candidatos de `session_state.document_candidates_v1` si no están presentes en el payload actual.

## 2. Lógica de Filtrado (Noise Reduction)

Se ajusta la lógica en `DocumentCandidateListService.build_candidate_document_list`:

```python
# Lógica propuesta
if final_action == "informativo":
    continue # Excluir del listado de entregables
```

### Reglas de Clasificación
- **Generar**: Basado en `must_have_policy` y detección de formatos/anexos.
- **Presentar Físico**: Documentos legales/administrativos del expediente.
- **Informativo**: Todo lo que sea normativo o descriptivo sin requerir un documento de vuelta. Estos se mantienen en la auditoría de cumplimiento (Compliance) pero se omiten del panel de candidatos.

## 3. Contrato de API
Se mantiene el contrato existente para no romper el Front-end:
```json
{
  "candidate_document_list": [...],
  "candidate_summary": { "generar": X, "presentar_fisico": Y },
  "needs_human_confirmation": bool
}
```
