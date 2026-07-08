# Plan de Implementación: Router y Auditoría Legal

## Fase 1: Infraestructura de Servicios
1. [x] Crear `backend/app/services/tender_router_service.py`.
   - Implementar método `get_triage(session_id, vector_db)`.
   - Implementar método `get_must_have_list(law, category)`.
   - Implementar método `get_critical_rules(law)`.
   - Implementar método `get_must_have_policy(law, category)` con `expected_action` y aliases.

## Fase 2: Contratos y Orquestación
2. [x] Modificar `backend/app/contracts/agent_contracts.py`.
   - Agregar `triage_context: Optional[Dict[str, Any]]` a la clase `AgentInput`.
3. [x] Modificar `backend/app/agents/orchestrator.py`.
   - Importar `TenderRouterService`.
   - Ejecutar el triage antes del bucle de análisis (`bt_iterations`).
   - Persistir `triage_context` en la sesión y pasarlo al `AgentInput`.
   - Inyectar `must_have_policy` junto con `must_have` y `critical_rules`.

## Fase 3: Inteligencia de Agentes
4. [x] Modificar `backend/app/agents/analyst.py`.
   - Inyectar el contexto legal (`law`, `category`) en el `system_prompt` para guiar el descubrimiento.
5. [x] Modificar `backend/app/agents/compliance.py`.
   - Inyectar la **Matriz de Obligatorios** y las **Reglas Críticas** en el `system_prompt` de extracción (`_extract_zone_chunk`).
   - Ajustar las instrucciones para prohibir el marcado de "Must-Haves" como informativos.
   - Aplicar enforcement determinista post-map/reduce con acción esperada por etiqueta.
   - Estampar trazabilidad de forzado (`forced_by_must_have`, `forced_by_must_have_matrix`).

## Fase 4: Validación y Cierre
6. [x] Ejecutar prueba de fuego con PDF de la UNAQ.
7. [x] Verificar que la "Opinión Estatal de Querétaro" sea detectada y marcada como obligatoria con `tipo_accion=presentar_fisico`.
8. [x] Verificar reducción de falsos informativos y revisar eventos `forced_by_must_have`.
9. [x] Validar que `LEG_`/`FIS_` no se fuercen a `generar` por error de heurística.
