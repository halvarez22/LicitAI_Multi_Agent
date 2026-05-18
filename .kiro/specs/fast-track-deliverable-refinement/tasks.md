# Plan de Implementación: Refinamiento de Entregables

## Fase 1: Diagnóstico y Reparación en Vivo (COMPLETADO)
- [x] Identificar causa de lista vacía en UNAQ-2026.
- [x] Cuantificar ruido (205 informativos vs 83 entregables).
- [x] Reparar sesión `unaq-2026_paneles_solares` inyectando candidatos existentes.

## Fase 2: Robustez del Orquestador (COMPLETADO)
- [x] Modificar `orchestrator.py` para inyectar candidatos en `_response_with_generation_state`.
- [x] Asegurar retornos en gaps económicos incluyan la lista.

## Fase 3: Filtrado de Ruido (PENDIENTE)
- [ ] Modificar `DocumentCandidateListService.py` para excluir ítems `informativo` de la lista final.
- [ ] Actualizar el resumen (`candidate_summary`) para reflejar solo ítems accionables.
- [ ] Validar con una nueva ejecución completa.

## Fase 4: Validación y Cierre
- [ ] Verificar en UI que la lista de UNAQ-2026 bajó de 288 a ~83 ítems.
- [ ] Confirmar con el usuario que la trazabilidad es correcta.
