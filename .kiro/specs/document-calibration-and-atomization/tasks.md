# Plan de Implementación: Calibración y Atomización

## Fase 0 — Control de alcance (obligatoria)
- [ ] Congelar alcance en dos entregables: A) anti-ruido documental, B) atomización de domicilio.
- [ ] Excluir de esta corrida cambios de identidad RFC/representante (va a spec separada).

## Fase 1 — Anti-ruido documental (Entregable A)
- [ ] Añadir reglas deterministas de exclusión de contenido normativo/informativo en `compliance`.
- [ ] Ajustar post-procesamiento en `document_candidate_list_service` para degradar ítems débiles a `informativo`/`unresolved`.
- [ ] Mantener evidencia por ítem (snippet/fuente/razón) para auditoría.
- [ ] Agregar tests unitarios de clasificación anti-ruido con casos tipo "normas", "avisos", "glosario".

## Fase 2 — Atomización de domicilio (Entregable B)
- [ ] Crear `backend/app/utils/address_parser.py` con parser determinista.
- [ ] Integrar parser en flujo de empresas (`companies.py`) y persistir `direccion_estructurada`.
- [ ] Mantener `domicilio_fiscal` original sin alteración.
- [ ] Si parseo es ambiguo, marcar `needs_human_confirmation`.
- [ ] Agregar tests unitarios con domicilios reales de variación alta.

## Fase 3 — Validación E2E controlada
- [ ] Correr caso UNAQ desde sesión limpia.
- [ ] Verificar lista candidata en rango objetivo operativo (~12-15).
- [ ] Confirmar que no haya ítems normativos clasificados como `generar`.
- [ ] Validar disponibilidad de `direccion_estructurada` en perfil de empresa.

## Fase 4 — Cierre y trazabilidad
- [ ] Publicar resultados de métricas pre/post (cantidad, precisión operativa, tiempos).
- [ ] Registrar decisiones técnicas en artefactos de spec y evidencias de pruebas.
