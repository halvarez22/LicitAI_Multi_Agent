# Requisitos: expediente maestro universal (representante, merge, CIF, contexto)

**Spec ID (Kiro):** `representante-legal-expediente-universal`  
**Estado:** Implementado en código (cierre técnico documentado aquí para handoff).

Este documento es la **evidencia de problema + decisión**: qué fallaba en producción, por qué, y qué política adoptamos. Otra IA o desarrollador debe poder orientarse **solo** leyendo este paquete (requirements + design + tasks) y los archivos citados.

---

## 1. Contexto del sistema

- **Expediente Maestro:** datos de empresa en `master_profile`, alimentados principalmente por `POST /companies/{id}/analyze` en `backend/app/api/v1/routes/companies.py` (OCR → vectores `company_{id}` → contexto → LLM JSON → parches → merge con perfil previo).
- **Consumidores:** `DataGapAgent`, formatos, chatbot, orquestador — esperan RFC, razón social, domicilio, representante, objeto social, etc., sin mezclar texto basura del modelo.

---

## 2. Problemas observados (síntomas)

| Síntoma en UI / perfil | Causa raíz (resumida) |
|------------------------|------------------------|
| Representante u objeto social sustituidos por frases tipo *«No se especifica… en los documentos proporcionados»* | El LLM devolvía **narración** en campos JSON; `_merge_profile_with_hitl` aceptaba cualquier string ≠ `No encontrado` y **pisaba** valores buenos del perfil. |
| Representante incorrecto (p. ej. apoderado del acta fundador vs quien comparece en asamblea como **delegado especial**) | `detect_legal_representative` usaba **primera** coincidencia global (`re.search`); el apoderado legal aparecía antes en el texto concatenado que la figura de asamblea. |
| Énfasis del prompt en «**NUEVO**» administrador | El modelo interpretaba que sin asamblea de “cambio” debía **explicar** en lugar de devolver el nombre del administrador del acta. |
| Domicilio fiscal vacío pese a CIF cargado | El JSON del LLM (moral) no pedía `domicilio_fiscal`; no había paso explícito de extracción desde texto tipo constancia SAT. |
| Preguntas HITL por datos no exigidos por la licitación (p. ej. plantilla) | `DataGapAgent` evaluaba **todo** `FIELD_DEFINITIONS`; mezcla checklist global con sesión de licitación. |

Ninguno de estos problemas se resuelve hardcodeando un expediente real (nombres, RFC, PDF concreto).

---

## 3. Objetivos / política (cerrados)

1. **Universalidad de actas:** Inferencia por **léxico jurídico mexicano** reutilizable (delegado especial, presidente de asamblea/mesa directiva, administrador único, apoderado legal, etc.), sin cadenas fijas de cliente en código.
2. **Precedencia entre figuras:** Si conviven varias señales, elegir por **tabla de confianza** del patrón + regla de empate documentada en `design.md`.
3. **Integridad del merge:** No fusionar valores que sean **placeholders narrados** del LLM; respetar `_manual_locked_fields`.
4. **CIF como fuente de domicilio (y refuerzo de razón social moral):** Extracción determinista desde blobs OCR identificados como constancia + ampliación del prompt JSON.
5. **DataGap acotado a licitación:** Solo bloqueantes + campos inferidos desde `compliance_master_list` (spec aparte).

---

## 4. Criterios de aceptación (verificación)

- **R1:** Solo apoderado legal en texto sintético → el representante extraído es ese nombre (`test_legal_representative_parser.py`).
- **R2:** Apoderado + delegado especial (nombres ficticios) → gana el patrón de mayor confianza (delegado).
- **R3:** Merge: perfil existente con representante válido + nuevo JSON con placeholder narrado → **no** se sobrescribe (`test_companies_route_helpers.py`).
- **R4:** No hay literales de PII real de clientes en tests ni en condiciones de negocio del código de extracción.
- **R5:** `domicilio_fiscal` poblable desde texto tipo SAT en pruebas de `cif_profile_extract` + integración en analyze.

---

## 5. Specs relacionados (mismo producto, otros focos)

| Spec (carpeta `.kiro/specs/`) | Qué documenta |
|-------------------------------|----------------|
| `cif-profile-extraction/` | Domicilio / razón social desde CIF; acumulación `cif_text_blobs` en analyze. |
| `datagap-tender-scoped-gaps/` | `active_fields` = bloqueantes ∪ slots de compliance; no checklist global. |
| `datagap-enqueue-all-missing/` | Encolado de faltantes una vez **dentro** del conjunto activo (convive con tender-scoped). |

---

## 6. Fuera de alcance

- Garantizar cobertura del 100 % de redacciones notariales de México.
- Sustituir criterio legal humano sobre quién es representante válido ante terceros.
