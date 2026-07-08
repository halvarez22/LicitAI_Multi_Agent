# Tareas: document-fill-policy-registry

## Fase actual (hoy): especificación y diseño
- [x] Definir requisitos de registry por documento/campo.
- [x] Diseñar contrato de procedencia/confianza por campo.
- [x] Definir salida extendida del gate y rollout.

## Fase siguiente (tras contraste con Gemini): implementación
- [ ] Crear `DocumentFieldPolicyRegistry` (catálogo inicial v1.1.0).
- [ ] Crear `FieldProvenanceResolver` con cascada de precedencia.
- [ ] Integrar registry+resolver en `document_fill_quality_gate`.
- [ ] Integrar metadatos documentales desde writers.
- [ ] Extender tests unitarios e integración.

## Fase posterior: endurecimiento
- [ ] Activar enforce parcial en campos críticos.
- [ ] Revisar falsos positivos y ajustar políticas.
- [ ] Activar enforce total.
