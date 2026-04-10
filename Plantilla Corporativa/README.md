# Corporate Repo Template (LicitAI Style)

Plantilla base para iniciar proyectos con rigor de ingeniería consistente:
- contratos claros,
- gates automáticos de calidad,
- foco de sprint y memoria técnica persistente.

## Qué incluye
- `INSTRUCTIONS.md`: estándares de ingeniería y arquitectura.
- `NOW.md`: foco operativo del sprint actual.
- `MEMORY.md`: decisiones históricas relevantes.
- `.github/pull_request_template.md`: checklist mínimo de PR.
- `.github/workflows/ci.yml`: pipeline base de calidad.

## Cómo usarla en un nuevo proyecto
1. Copiar el contenido de `repo-template/` a la raíz del nuevo repositorio.
2. Adaptar `NOW.md` al objetivo del sprint de arranque.
3. Ajustar comandos de CI en `.github/workflows/ci.yml` según stack real.
4. Definir rama protegida en GitHub y requerir status checks del CI.

## Convención mínima recomendada
- PRs pequeños y atómicos.
- Sin merge a `main` si falla `lint/typecheck/tests`.
- Toda decisión relevante de arquitectura se registra en `MEMORY.md`.
