# Checklist PR — estabilidad sesión / artefactos

Usar en **todo PR** que toque orquestador, invalidación, checklist, dictamen, junta, generación o rutas GET de sesión.

## Gate automático (obligatorio)

```bash
cd backend
python -m pytest tests/test_submission_checklist.py tests/test_session_bases_analysis_invalidation.py tests/test_session_health_service.py -q
docker exec licitaciones-ai-backend-1 python scripts/smoke_session_stability.py
python scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001 --all-reference
```

Exit `0` en los tres. Si **ISAPEG, UNAQ o VIGILANCIA** fallan y antes pasaban → **revertir**, no parchear encima.

## Diseño (ENTERPRISE_CANONICO_HITL)

- [ ] Sin hardcode por `session_id` / convocante.
- [ ] Invalidación: ¿qué claves se borran y cuáles se preservan? Alineado con `docs/ARTIFACT_LIFECYCLE.md`.
- [ ] GET ligeros no disparan RAG/enrichment síncrono pesado.
- [ ] Fail-soft con timeout + log estable (`error_type` / clave de log documentada).
- [ ] HITL: overrides auditables; revalidación tras cambio.

## Regresión funcional

- [ ] 3 sesiones referencia: hitos ≥6, junta ≥1, panel formatos no vacío.
- [ ] VIGILANCIA: checklist sin recursión (`checklist_elapsed_s` < 5 s en smoke).
- [ ] `GET /dictamen` mediana < 10 s en VIGILANCIA (muestra manual si tocó checklist/dictamen).
- [ ] Re-análisis / rehydrate: job async o documentado por qué no aplica.

## Documentación

- [ ] Cambio de lifecycle → actualizar `ARTIFACT_LIFECYCLE.md`.
- [ ] Nuevo smoke o umbral → actualizar `INFORME_ESTABILIZACION_HANDOFF.md`.

## Fuera de alcance en PR de estabilidad

- Subir `uvicorn workers` sin plan VRAM.
- Prompts masivos sin baseline Oracle/smoke.
- Relajar gates de fill/contaminación solo para una licitación.
