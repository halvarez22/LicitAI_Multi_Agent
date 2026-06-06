# SUPER ISSUE — Chat conversacional, intención del usuario y UX de mercado

**Estado:** DOCUMENTADO — **pospuesto** hasta cerrar generación documental mínima (solo entregables reales, sin duplicados, conteo estable).  
**Prioridad cuando se retome:** P0 producto / riesgo reputacional y contractual.  
**Fecha de registro:** 2026-05-21.

---

## Resumen ejecutivo

El chat de LicitAI **no es hoy un copiloto transaccional defendible en mercado abierto**: la misma frase en español natural (`generar`, `adelante`, `cómo vamos`) puede enrutarse a ramas distintas (cotización, META, RAG, HITL) y, en el peor caso, el usuario recibe **volcados forenses** (Gate 12.1, 401 ítems, `MISSING_ECONOMIC_PROPOSAL`) pensados para contexto interno del LLM, no para licitantes.

Esto es **independiente** de los bugs ya corregidos en intake de perfil (refusal PII, motor de misión, mensaje de cierre HITL).

---

## Síntomas observados (ISAPEG y reproducibles)

| Entrada usuario | Comportamiento observado | Impacto |
|-----------------|-------------------------|---------|
| `generar` (una palabra) | Clasificación META + informe compliance completo | Intimidación, abandono |
| Bootstrap “propuesta ganadora” + semáforo YELLOW | Contradicción de mensaje | Pérdida de confianza |
| Panel **Generar** sin `economic_proposal` en sesión | `MISSING_ECONOMIC_PROPOSAL` crudo en chat (META) | Cree que el sistema falló sin explicación humana |
| `generar propuesta económica` OK + limpiar expediente (antes del fix) | Se borraba snapshot económico | Panel Generar bloqueado de nuevo |

---

## Causas raíz (arquitectura)

1. **Intención por subcadenas literales** — `generar propuesta económica` sí; `generar` no dispara `EconomicAgent`.
2. **Orden de ramas dependiente de estado** — `pending_questions` vacío activa canal económico amplio; clasificador LLM → META.
3. **`_handle_meta_query` expone `_compliance_truth_prompt_section_from_session` al usuario** — diseñado para system prompt RAG, no para respuesta visible.
4. **`stop_reason` sin mapa humano** — p. ej. `MISSING_ECONOMIC_PROPOSAL` literal.
5. **Doble CTA** — Chat vs panel **Generar** vs frases exactas; no un solo “siguiente paso”.
6. **Cobertura de tests** — pocos casos de paráfrasis masivas de usuarios reales.

---

## Riesgo de mercado

- Usuario cree que ordenó generar expediente y **no se generó nada** (fecha límite).
- Mensaje técnico interpretado como “no puedo participar”.
- Cliente institucional documenta contradicción chat/panel en disputa.
- No requiere demanda masiva: basta un contrato grande perdido con evidencia en chat.

---

## Alcance del SUPER ISSUE (cuando se retome)

### P0 — Conversación usuario

- [ ] Capa de intención acotada: `COTIZAR`, `GENERAR_EXPEDIENTE`, `RESPONDER_PENDIENTE`, `PREGUNTAR_BASES`, `VER_ESTADO`, `AYUDA`.
- [ ] `generar` solo → desambiguación en una pregunta corta (no META forense).
- [ ] Prohibir volcado de compliance / gates / `stop_reason` crudos en respuestas META al usuario.
- [ ] Mapa completo `stop_reason` → español claro + un solo CTA.
- [ ] Bootstrap sobrio alineado a semáforo y snapshot económico (sin “ganadora” si YELLOW/bloqueo).

### P1 — Calidad operativa

- [ ] Batería de ≥100–200 utterances (typos, regionalismos, mensajes mixtos).
- [ ] Criterio CI: ninguna respuesta al usuario contiene `MISSING_`, `12.1.`, `Gate 12.1` sin traducción.
- [ ] Keys React únicas en `DocumentCandidatePanel` (duplicados `opinion_del_cumplimiento...`).

### P2 — Contenido y dictamen

- Calidad de redacción por documento (fuera de este SUPER ISSUE; va después de conteo estable).

---

## Relación con trabajo en curso (prioridad actual)

| Hilo | Estado |
|------|--------|
| Filtro P0 `filter_compliance_for_generation` + límites 12/18 | Implementado en código |
| Packager dedup + AD→sobre administrativo | Implementado |
| No borrar `economic_proposal` al limpiar disco | Implementado |
| Re-ejecutar `EconomicAgent` si falta snapshot al generar | Implementado |
| **Limpieza de disco antes de writers en nueva corrida** | Ver `GENERATION_WIPE_OUTPUTS_BEFORE_WRITERS` |
| **Este SUPER ISSUE** | Pospuesto explícitamente |
| **Agenda HITL económico (A–D)** | [`AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md`](AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md) |
| **Issue matriz + captura económica universal (D)** | [`ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md`](ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md) — **sin hardcode por licitación** |

---

## Referencias de código

- `backend/app/agents/chatbot_rag.py` — `_handle_meta_query`, `is_gen_request`, `_compliance_truth_prompt_section_from_session`, `_build_session_resume_message`
- `backend/app/agents/orchestrator.py` — `_ensure_economic_snapshot_ready`, `last_orchestrator_decision`
- `frontend/src/App.jsx` — `triggerGeneration`, `pollAgentsJobUntilDone`

---

## Criterio de cierre del SUPER ISSUE

Un licitante sin manual puede escribir **cualquiera** de: `generar`, `generar documentos`, `generar propuesta`, `adelante`, `cómo vamos` y siempre recibe:

1. Como máximo **3 líneas** de estado en lenguaje humano.  
2. **Un** siguiente paso clicable o frase única.  
3. **Cero** códigos internos ni informes de auditoría en el chat principal.

El detalle forense vive solo en panel de dictamen / compliance.
