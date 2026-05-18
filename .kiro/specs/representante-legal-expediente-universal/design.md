# Diseño técnico (evidencia): cómo se resolvió y dónde está el código

Documento de **handoff**: otra IA debe localizar la lógica en los paths indicados y reproducir el razonamiento sin acceder al chat original.

---

## A. Representante legal — extractor determinista

**Archivo:** `backend/app/services/legal_representative_parser.py`  
**Función principal:** `detect_legal_representative(text: str) -> dict`

### A.1 Algoritmo

1. Normalizar espacios (`_normalize_spaces`).
2. Para cada patrón en la lista ordenada por **confianza decreciente conceptual** (lista en código), ejecutar `re.finditer` sobre el texto completo.
3. Cada match produce un candidato (último grupo capturante del `NAME_PATTERN`).
4. Filtrar con `_looks_like_person_name` (evita razones sociales tipo “… S.A. DE C.V.”).
5. Elegir el **mejor** match con clave de ordenación:
   - `key = (confidence, -m.start())`
   - Maximizar: mayor `confidence`; si empate, **menor** índice de inicio (aparece antes en el string).
6. Motivo del empate por posición: en `analyze_company`, el contexto RAG se **reordena** para poner fragmentos societarios (asamblea, poder, acta) **antes** que CIF; la primera aparición de alta confianza alinea con “documento societario primero”.

### A.2 Tabla de triggers y `confidence` (fuente de verdad: código)

Orden aproximado en lista (mayor número = más prioridad al comparar):

| `trigger` (ejemplos) | `confidence` | Rol |
|----------------------|--------------|-----|
| `c_comparece_delegado_especial`, `nombre_coma_caracter_delegado_especial` | 0.98 | Asamblea / escritura de delegado |
| `delegado_especial_el_c_nombre` | 0.975 | Variante redacción |
| `presidente_asamblea_el_c` | 0.965 | Mesa de asamblea |
| `presidente_mesa_directiva_el_c` | 0.964 | Mesa directiva |
| `se_designa` | 0.95 | Nombramiento explícito |
| `admin_unico_recayendo_*` … | 0.93 → 0.9 | Acta constitutiva típica |
| `representante_legal` (incl. apoderado legal) | 0.85 | Señal genérica; pierde frente a delegado si ambos existen |

### A.3 Salida (contrato estable)

`found`, `representative`, `confidence`, `strategy` (`deterministic_regex`), `evidence` (substring acotado), `trigger`.

### A.4 Precedencia parser vs LLM (persona moral) — 2026-04-27

Si `parser_result["trigger"]` pertenece a un conjunto de señales societarias **fuertes** (delegado especial, presidente de asamblea/mesa, `se_designa`, etc.), **`_apply_moral_representante_from_parser`** en `companies.py` **sustituye** `representante_legal` del JSON del LLM aunque el LLM haya devuelto otro nombre (típico: apoderado del acta fundador). No aplica si `representante_legal` está en `_manual_locked_fields`.

Patrón OCR adicional: `c_nombre_hasta_caracter_delegado_especial` — tolera saltos entre `C.` + nombre y la frase «carácter de delegado especial».

---

## B. Análisis corporativo — LLM, orden de contexto, CIF, sanitización, merge

**Archivo:** `backend/app/api/v1/routes/companies.py`

### B.1 Orden de fragmentos antes de `context = "\n---\n".join(docs)`

- Tras deduplicar chunks por texto, se ordenan pares `(docs[i], metadatas[i])` por `_meta_priority(meta)` **descendente**.
- `_meta_priority`: asamblea (5) > poder (4) > acta (3) > constancia/CIF (1) > resto (0).  
  **Intención:** el LLM y `detect_legal_representative` “ven” primero lo societario, no la constancia fiscal.

### B.2 Prompt moral (persona moral)

- Instrucciones explícitas: si **no** hay asamblea de cambio, usar administrador/representante del **acta**; prohibido narrar en JSON; si falta dato → exactamente `No encontrado`.
- JSON ampliado con `domicilio_fiscal` (respaldo frente a regex CIF).

### B.3 Acumulación CIF (`cif_text_blobs`)

- En el bucle OCR por documento: si el título sugiere CIF (`_company_doc_title_suggests_cif`) o `is_constancia_cif_text` (`legal_representative_parser`), se acumula texto para blob.
- Tras parsear JSON LLM: `_apply_cif_constancia_patch` usa `extract_cif_company_profile_patch` de `backend/app/services/cif_profile_extract.py`.

### B.4 Anti-placeholders del LLM

| Función | Rol |
|---------|-----|
| `_is_llm_placeholder_profile_value` | Detecta narraciones tipo “no se especifica… documentos proporcionados”. |
| `_sanitize_llm_profile_placeholders` | Sustituye esos valores por `No encontrado` antes del resto del pipeline. |
| `_merge_profile_with_hitl` | No escribe clave si valor es placeholder o `No encontrado` (preserva existente). |

**Servicio CIF:** `backend/app/services/cif_profile_extract.py`  
**Marcador constancia:** `is_constancia_cif_text` en `legal_representative_parser.py`.

---

## C. DataGap (sesión licitación) — recordatorio

**Archivo:** `backend/app/agents/data_gap.py`  
**Cambio:** `active_fields` = `BLOCKING_FIELDS` ∪ slots inferidos desde compliance (no todo `FIELD_DEFINITIONS`).  
**Spec:** `.kiro/specs/datagap-tender-scoped-gaps/`.

---

## D. Pruebas como evidencia ejecutable

| Área | Archivo |
|------|---------|
| Parser representante | `backend/tests/test_legal_representative_parser.py` |
| Merge, placeholders, CIF patch, queries | `backend/tests/test_companies_route_helpers.py` |
| Extracción CIF | `backend/tests/test_cif_profile_extract.py` |
| DataGap acotado | `backend/tests/test_data_gap_behavior.py` |

Comando útil: `python -m pytest tests/test_legal_representative_parser.py tests/test_companies_route_helpers.py tests/test_cif_profile_extract.py tests/test_data_gap_behavior.py`

---

## E. Riesgos residuales

- OCR ilegible o redacción sin ninguna frase cercana a los patrones → fallback LLM; puede fallar sin datos suficientes en contexto.
- Ajustar `confidence` o añadir patrones solo con **nuevos tipos léxicos** y tests sintéticos (ver `tasks.md`).
