# Plan de trabajo y evidencia de cierre (tasks)

**Propósito:** Lista verificable para auditoría y para una IA que entre al repo después. Cada ítem apunta a **artefacto de evidencia** (código o test).

---

## Implementado (cierre documentado)

| ID | Tarea | Evidencia (archivos / tests) |
|----|--------|-------------------------------|
| T1 | Documentar anti–“caso único” y precedencia en spec | Este directorio `requirements.md` + `design.md` |
| T2 | Parser: multi-match, tabla de `confidence`, delegado/presidente/admin/apoderado | `legal_representative_parser.py` (`detect_legal_representative`, `_looks_like_person_name`) |
| T3 | Tests sintéticos parser (solo apoderado; apoderado+delegado) | `test_legal_representative_parser.py` |
| T4 | Orden de contexto societario > CIF en analyze | `companies.py` — ordenación por `_meta_priority` antes de armar `context` |
| T5 | Prompt moral: sin sesgo “solo NUEVO”; solo datos o `No encontrado` | `companies.py` — `system_prompt` / `prompt` rama moral |
| T6 | Sanitizar placeholders LLM + merge que no pise perfil | `companies.py` — `_sanitize_llm_profile_placeholders`, `_is_llm_placeholder_profile_value`, `_merge_profile_with_hitl` |
| T7 | Tests merge y placeholders | `test_companies_route_helpers.py` |
| T8 | CIF: extracción determinista domicilio (+ razón moral) | `cif_profile_extract.py`, acumulación + `_apply_cif_constancia_patch` en `companies.py` |
| T9 | Tests CIF | `test_cif_profile_extract.py` |
| T10 | DataGap: campos activos solo bloqueantes + compliance | `data_gap.py`; spec `datagap-tender-scoped-gaps/`; tests `test_data_gap_behavior.py` |

---

## Pendiente (mantenimiento, no bloquea cierre)

| ID | Tarea | Notas |
|----|--------|--------|
| P1 | Ampliar patrones de representante | Solo nuevos **tipos** léxicos; añadir test sintético por patrón; **no** pegar actas reales al repo. |
| P2 | Revisión periódica con escrituras anónimas | QA interno; resultados en plantillas de evaluación si aplica (`docs/`), no duplicar PII en specs. |

---

## Orden de lectura sugerido para handoff (otra IA)

1. `requirements.md` (problema + política + links a otros specs)  
2. `design.md` (algoritmos + rutas de código + tests)  
3. Código citado en `design.md` (orden: `legal_representative_parser.py` → `companies.py` → `cif_profile_extract.py` → `data_gap.py`)  
4. Ejecutar pytest de la sección D de `design.md`

---

## Checklist rápido “¿se rompió el universal?”

- [ ] `pytest tests/test_legal_representative_parser.py` — verde  
- [ ] `pytest tests/test_companies_route_helpers.py` — verde  
- [ ] Grep en `backend/app`: sin nombres propios de expedientes reales en regex de representante  
- [ ] Nuevo patrón: incluye test con texto **ficticio**
