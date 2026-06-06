# Contrato universal: cola de chat HITL

## Objetivo

Garantizar que **ningún ajuste por licitación** vuelva a meter en el chat semáforo Go/No-Go, condiciones contractuales, inventario de anexos ni documentos físicos de empresa. Las reglas son **semánticas** (prefijos, provenance, taxonomía), no `session_id` ni nombre de convocante.

## Fuente de verdad en código

| Módulo | Rol |
|--------|-----|
| `backend/app/contracts/chat_queue_contract.py` | Contrato: qué es solo-panel y validación `assert_chat_queue_compliant` |
| `backend/app/services/hitl_queue_service.py` | Sanitización y deduplicación de `pending_questions` |
| `backend/app/agents/intake_planner.py` | Genera `questions` (chat aptas) vs `viability_brechas` / `contractual_review` / `strategic_gaps` (paneles) |

## Qué puede ir al chat

- Captura de **precios** (`economic_price`, bloqueos económicos).
- **Data gap** de perfil no cubierto por `master_profile` (RFC, capital, etc.) cuando no es documento físico.
- Hints de **calidad** de clasificación/llenado documental (revisión puntual).

## Qué NO puede ir al chat (solo paneles)

| Canal correcto | IDs / señales |
|----------------|---------------|
| Semáforo Go/No-Go | `INTAKE-B-GNG-*`, `provenance_ui.reason=brecha_detectada`, `go_no_go_result` |
| Condiciones contractuales | `INTAKE-B-CON-*`, `condicion_contractual` |
| Gap estratégico | `INTAKE-GAP-*`, `gap_analysis` |
| Inventario de formatos/anexos | `INTAKE-COMP-FOR-*`, `master_list_formatos` |
| Documentos físicos empresa | SAT, INE, acta, opinión cumplimiento, etc. |
| Checklist participación pliego | `INTAKE-CHECK-*`, `participacion.check_*` |
| Tickets mini dictamen / Junta | `clarification_tickets`, panel Junta |

## Anti-regresión (CI)

Ejecutar siempre antes de merge en área chat/intake:

```bash
cd backend && python -m pytest tests/test_chat_queue_contract.py tests/test_hitl_queue_service.py tests/test_intake_planner_agent.py -q
```

Añadir fixture anonimizado por convocatoria cuando se cierre un caso (UNAQ, ISAPEG, ISSSTE): el test debe fallar si `find_chat_queue_violations` no está vacío tras `IntakePlanner` + `sanitize_chat_pending_questions`.

## Política de cambios

1. **Prohibido** ramas `if session_id == ...` o mensajes con nombre de convocante hardcodeado en agentes.
2. Toda nueva fuente de “preguntas” debe declarar si es `chat` o `panel` en este documento y en `chat_queue_contract.py`.
3. Los parches solo en `sanitize_*` son **red de seguridad**, no sustituto de no generar ítems prohibidos en `IntakePlanner`.

## Relación con ENTERPRISE_CANONICO_HITL

- **Cascada de precedencia:** usuario > documento > catálogo > inferencia; el chat solo captura lo que el usuario puede corregir en conversación.
- **Procedencia visible:** `provenance_ui` en ítems de panel; badges en UI de semáforo y análisis, no duplicados en chat.
