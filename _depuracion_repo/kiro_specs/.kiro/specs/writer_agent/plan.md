# Writer Agent Implementation Plan

## Fase 1: Auditoría y Refactorización Base (Completado ✅)
- [x] Crear el `WriterAgent` heredando de `BaseAgent`.
- [x] Implementar la función `draft_annex` para generación dinámica.
- [x] Construir el Contexto Tripartito (Perfil, Gap, RAG).
- [x] Corregir llamadas síncronas/asíncronas al `VectorDbServiceClient` (`query_texts`).
- [x] Blindar la extracción del Perfil Legal (Representante Legal y Objeto Social) en el `AnalystAgent` para alimentar datos puros al Redactor.

## Fase 2: Integración Frontend y Endpoints (Pendiente ⏳)
- [ ] Desarrollar endpoint REST en el backend: `POST /api/v1/sessions/{session_id}/draft/{requirement_id}`.
- [ ] Mapear el `requirement_id` de los gaps del Frontend hacia el backend.
- [ ] Implementar el botón "Magic Draft" (o "Generar Borrador") en el componente de UI que muestra los faltantes documentales.
- [ ] Renderizador Markdown en la UI para permitir edición visual antes de exportar.

## Fase 3: Exportación y Mapeo Multiformato (Futuro 🚀)
- [ ] Habilitar exportación directa a `.docx` preservando plantillas.
- [ ] Sincronizar el historial de borradores con la memoria persistente para no re-generar desde cero si el usuario pide cambios.
