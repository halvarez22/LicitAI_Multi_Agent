# Plan de Implementación: Router y Auditoría Legal

## 1. Fase Backend
- [ ] Implementar `TenderRouterService`.
- [ ] Actualizar contratos de agentes (`AgentInput`).
- [ ] Inyectar triage en `OrchestratorAgent.process`.

## 2. Fase Inteligencia
- [ ] Personalizar prompts de `AnalystAgent` con contexto legal.
- [ ] Personalizar prompts de `ComplianceAgent` con matriz de obligatorios.

## 3. Validación (QA)
- [ ] Prueba con `BASES 001-IR-UNAQ-2026 PANELESSOL.pdf`.
- [ ] Validar detección de "Ley de Querétaro".
- [ ] Validar que anexos legales no se pierdan como "informativos".
