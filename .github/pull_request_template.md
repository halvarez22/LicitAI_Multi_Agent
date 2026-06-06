## Summary

<!-- Qué cambia y por qué (1–3 bullets) -->

## Checklist estabilidad

Antes de merge, revisar [`docs/PR_CHECKLIST_ESTABILIDAD.md`](../docs/PR_CHECKLIST_ESTABILIDAD.md) y ejecutar smoke 3/3 referencia si el PR toca sesión, checklist, dictamen, junta o generación.

```bash
docker exec licitaciones-ai-backend-1 python scripts/smoke_session_stability.py
python backend/scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001 --all-reference
```

## Test plan

- [ ] Pytest áreas tocadas
- [ ] Smoke ISAPEG + UNAQ + VIGILANCIA (si aplica)
