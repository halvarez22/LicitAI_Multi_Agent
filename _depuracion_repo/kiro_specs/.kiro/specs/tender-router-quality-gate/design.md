# Diseño Técnico: Integración del Router con el Quality Gate de Generación

## Overview

El `TenderRouterService` ya detecta el tipo de licitación y produce un `triage_context` con `tender_category`. El `ComplianceAgent` ya usa ese contexto para enforcement de must-have. El gap está en los agentes de generación: `TechnicalWriterAgent` y `FormatsAgent` tienen un quality gate que no recibe el `triage_context` y aplica umbrales uniformes para todos los tipos de licitación.

El fix es mínimo y quirúrgico: extender la firma de `_should_block_by_quality_gate()` para recibir `triage_context` opcional, agregar una excepción para categoría OBRA, y asegurar que el orquestador propague el `triage_context` a los agentes de generación.

---

## Architecture

### Flujo actual (con el bug)

```
TenderRouterService.get_triage()
    → triage_context = {law: "LOPSRM", tender_category: "OBRA", ...}
    → session_state["triage_context"] = triage_context

ComplianceAgent.process()
    ← agent_input.triage_context ✅ (orquestador lo pasa)
    → enforcement de must-have con política OBRA

TechnicalWriterAgent.process()
    ← agent_input.triage_context ❌ (orquestador NO lo pasa en generation_only)
    → _should_block_by_quality_gate(generar_count=0, ...) → block: True ❌
    → WAITING_FOR_DATA — bloqueo incorrecto
```

### Flujo corregido

```
TenderRouterService.get_triage()
    → triage_context = {law: "LOPSRM", tender_category: "OBRA", ...}
    → session_state["triage_context"] = triage_context

OrchestratorAgent.process() — generation_only
    → Lee triage_context de session_state
    → agent_input.triage_context = triage_context ✅ (nuevo)

TechnicalWriterAgent.process()
    ← agent_input.triage_context = {tender_category: "OBRA"} ✅
    → _should_block_by_quality_gate(
          generar_count=0,
          presentar_fisico_count=5,
          triage_context={tender_category: "OBRA"}
      )
    → Excepción OBRA: block: False, reason: "obra_category_no_generate_items_expected" ✅
    → AgentStatus.SUCCESS con mensaje informativo ✅
```

---

## Components and Interfaces

### Cambio 1: `_should_block_by_quality_gate` en `technical_writer.py` y `formats.py`

**Firma extendida:**

```python
def _should_block_by_quality_gate(
    *,
    total_items: int,
    generar_count: int,
    unknown_count: int,
    evidence_match_ratio: float,
    presentar_fisico_count: int = 0,          # NUEVO
    triage_context: Optional[Dict[str, Any]] = None,  # NUEVO
) -> Dict[str, Any]:
```

**Lógica nueva (insertar ANTES de la condición `generar_count == 0`):**

```python
# ── Excepción por categoría de licitación ──────────────────────────────────
# Para licitaciones de OBRA (LOPSRM), los requisitos técnicos son formas
# predefinidas (AT-10, AT-13, AE-02) que el licitante llena, no redacta.
# El ComplianceAgent los clasifica correctamente como presentar_fisico.
# Si generar_count == 0 pero hay ítems presentar_fisico, no es un error
# de clasificación — es el comportamiento esperado para este tipo de licitación.
tender_category = ""
if isinstance(triage_context, dict):
    tender_category = str(triage_context.get("tender_category") or "").upper()

if tender_category == "OBRA" and generar_count == 0 and presentar_fisico_count > 0:
    return {
        "block": False,
        "reason": "obra_category_no_generate_items_expected",
        "metrics": {
            "total_items": total_items,
            "generar_count": generar_count,
            "presentar_fisico_count": presentar_fisico_count,
            "tender_category": tender_category,
            "evidence_match_ratio": evidence_match_ratio,
        },
    }
```

**Punto de inserción:** Justo después del guard `if not bool(app_settings.DOCUMENT_QUALITY_HARD_GATE_ENABLED)` y antes de `if generar_count == 0`.

---

### Cambio 2: Conteo de `presentar_fisico_count` en `TechnicalWriterAgent.process()`

En el bucle de conteo de `action_counts`, ya se cuenta `presentar_fisico`. Solo hay que pasarlo al gate:

```python
# Código existente (sin cambios):
action_counts: Dict[str, int] = {"generar": 0, "presentar_fisico": 0, "informativo": 0, "unknown": 0}
for req in all_candidates:
    action = str(req.get("tipo_accion", "unknown") or "unknown").lower()
    if action not in action_counts:
        action = "unknown"
    action_counts[action] = action_counts.get(action, 0) + 1
    ...

# Cambio: pasar presentar_fisico_count y triage_context al gate
gate = _should_block_by_quality_gate(
    total_items=total_candidates,
    generar_count=action_counts.get("generar", 0),
    unknown_count=action_counts.get("unknown", 0),
    evidence_match_ratio=evidence_ratio,
    presentar_fisico_count=action_counts.get("presentar_fisico", 0),  # NUEVO
    triage_context=agent_input.triage_context,                         # NUEVO
)
```

**Mismo cambio aplica en `FormatsAgent.process()`.**

---

### Cambio 3: Mensaje informativo cuando OBRA no tiene ítems generables

Cuando el gate no bloquea por excepción OBRA pero `tech_requirements` queda vacío (porque todos son `presentar_fisico`), el agente debe retornar `SUCCESS` con mensaje claro:

```python
# En TechnicalWriterAgent.process(), después del gate y antes de _merge_document_inventory_technical:
if not tech_requirements:
    tender_cat = str((agent_input.triage_context or {}).get("tender_category") or "").upper()
    if tender_cat == "OBRA":
        logger.info(
            "technical_writer_obra_skip",
            session_id=session_id,
            reason="all_technical_items_are_presentar_fisico",
            total_candidates=total_candidates,
        )
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            message=(
                "Licitación de obra pública: los requisitos técnicos son formas predefinidas "
                "(AT/AE) que se presentan físicamente. No hay documentos técnicos que redactar."
            ),
            data={"documentos": [], "obra_category_skip": True},
            correlation_id=correlation_id,
        )
    return AgentOutput(
        status=AgentStatus.SUCCESS,
        agent_id=self.agent_id,
        session_id=session_id,
        message="No hay requisitos técnicos por redactar.",
        correlation_id=correlation_id,
    )
```

---

### Cambio 4: Propagación de `triage_context` en el orquestador (generation_only)

El orquestador ya propaga `triage_context` a `agent_input` durante la fase de análisis. En `generation_only`, el `triage_context` se lee de `session_state` pero no se asigna a `agent_input` antes de invocar los agentes de generación.

**Ubicación:** `backend/app/agents/orchestrator.py`, bloque de `generation_only`, antes del loop `for step, a_cls in [...]`.

```python
# En el bloque generation_only, después de _ensure_economic_snapshot_ready
# y antes del loop de agentes:

# Asegurar que triage_context esté en agent_input para los agentes de generación
if not agent_input.triage_context:
    _triage = session_state.get("triage_context")
    if _triage and isinstance(_triage, dict):
        agent_input = agent_input.model_copy(
            update={"triage_context": _triage}
        )
        logger.info(
            "orchestrator_triage_injected_for_generation",
            session_id=session_id,
            tender_category=_triage.get("tender_category"),
            law=_triage.get("law"),
        )
```

---

### Cambio 5: Señales OBRA en el prompt de triage v2

El prompt v2 actual detecta OBRA pero no tiene señales explícitas para formas AT/AE ni para LOPSRM. Agregar al `TRIAGE_PROMPT_V2`:

```python
# En TRIAGE_PROMPT_V2, en la sección de REGLAS DE CLASIFICACIÓN:
"""
5. Para OBRA (LOPSRM): requieres al menos UNA señal:
   - Mención de "Ley de Obras Públicas" o "LOPSRM"
   - Presencia de formas AT- o AE- (AT-10, AT-13, AE-02, etc.)
   - Mención de "catálogo de conceptos de obra", "explosión de insumos", "programa de obra"
   - Mención de "contratista", "subcontratista", "superintendente de obra"
   Si law = "LOPSRM", tender_category SIEMPRE es "OBRA".
"""
```

---

## Data Flow

### Estructura del triage_context relevante para el gate

```json
{
  "law": "LOPSRM",
  "jurisdiction": "FEDERAL",
  "tender_category": "OBRA",
  "confidence": 0.85,
  "signals_detected": ["Ley de Obras Públicas", "Forma AT-13", "catálogo de conceptos"]
}
```

### Decisión del quality gate por categoría

| tender_category | generar_count | presentar_fisico_count | Decisión |
|---|---|---|---|
| `OBRA` | 0 | > 0 | `block: False` — excepción OBRA |
| `OBRA` | > 0 | cualquiera | Aplica umbrales normales |
| `OBRA` | 0 | 0 | `block: False` — lista vacía |
| `BIENES` / `SERVICIOS` | 0 | cualquiera | `block: True` — sin ítems generables |
| `BIENES` / `SERVICIOS` | > 0 | cualquiera | Aplica umbrales normales |
| `None` / desconocido | cualquiera | cualquiera | Aplica umbrales normales (fallback) |

---

## Correctness Properties

### Property 1: Excepción OBRA no bloquea cuando todos los ítems son presentar_fisico

*Para cualquier* lista de requisitos técnicos donde todos tienen `tipo_accion = "presentar_fisico"` y `triage_context.tender_category = "OBRA"`, `_should_block_by_quality_gate` debe retornar `block: False`.

**Validates: Requirements 1.1, 1.2**

### Property 2: Preservación de umbrales para licitaciones no-OBRA

*Para cualquier* `triage_context` con `tender_category != "OBRA"` (o `triage_context = None`), `_should_block_by_quality_gate` debe producir exactamente el mismo resultado que la versión anterior de la función.

**Validates: Requirements 4.1, 4.2, 4.3**

### Property 3: Propagación correcta del triage_context

*Para cualquier* sesión con `triage_context` en `session_state`, cuando el orquestador invoca `TechnicalWriterAgent` en modo `generation_only`, `agent_input.triage_context` debe ser igual al `triage_context` de `session_state`.

**Validates: Requirements 2.1, 2.3**

---

## Error Handling

| Escenario | Comportamiento |
|---|---|
| `triage_context` ausente en `session_state` | Gate aplica umbrales originales (fallback seguro) |
| `tender_category` con valor desconocido | Gate aplica umbrales originales (fallback seguro) |
| `triage_context` presente pero `tender_category` vacío | Gate aplica umbrales originales |
| Excepción al leer `triage_context` | Gate aplica umbrales originales, log de warning |

---

## Testing Strategy

### Tests unitarios

| Test | Qué verifica |
|---|---|
| `test_gate_obra_no_block_when_all_presentar_fisico` | OBRA + generar=0 + presentar_fisico>0 → block: False |
| `test_gate_obra_normal_when_has_generar_items` | OBRA + generar>0 → aplica umbrales normales |
| `test_gate_servicios_blocks_when_no_generar` | SERVICIOS + generar=0 → block: True |
| `test_gate_none_triage_uses_original_thresholds` | triage=None → comportamiento original |
| `test_gate_unknown_category_uses_original_thresholds` | category="SALUD" → comportamiento original |
| `test_gate_obra_empty_list_no_block` | OBRA + total=0 → block: False |

### Property tests (Hypothesis)

```python
@given(
    presentar_fisico_count=st.integers(min_value=1, max_value=50),
    total_items=st.integers(min_value=1, max_value=50),
    evidence_ratio=st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=200)
def test_obra_never_blocks_when_all_presentar_fisico(
    presentar_fisico_count, total_items, evidence_ratio
):
    """Property 1: OBRA con generar=0 y presentar_fisico>0 nunca bloquea."""
    result = _should_block_by_quality_gate(
        total_items=total_items,
        generar_count=0,
        unknown_count=0,
        evidence_match_ratio=evidence_ratio,
        presentar_fisico_count=presentar_fisico_count,
        triage_context={"tender_category": "OBRA"},
    )
    assert result["block"] is False


@given(
    generar_count=st.integers(min_value=0, max_value=20),
    unknown_count=st.integers(min_value=0, max_value=20),
    presentar_fisico_count=st.integers(min_value=0, max_value=20),
    evidence_ratio=st.floats(min_value=0.0, max_value=1.0),
    category=st.sampled_from(["BIENES", "SERVICIOS", "TECNOLOGIA", None]),
)
@settings(max_examples=200)
def test_non_obra_preserves_original_behavior(
    generar_count, unknown_count, presentar_fisico_count, evidence_ratio, category
):
    """Property 2: Para categorías no-OBRA, el resultado es idéntico al original."""
    triage = {"tender_category": category} if category else None
    total = generar_count + unknown_count + presentar_fisico_count
    
    result_new = _should_block_by_quality_gate(
        total_items=total,
        generar_count=generar_count,
        unknown_count=unknown_count,
        evidence_match_ratio=evidence_ratio,
        presentar_fisico_count=presentar_fisico_count,
        triage_context=triage,
    )
    result_original = _should_block_by_quality_gate_original(
        total_items=total,
        generar_count=generar_count,
        unknown_count=unknown_count,
        evidence_match_ratio=evidence_ratio,
    )
    assert result_new["block"] == result_original["block"]
```
