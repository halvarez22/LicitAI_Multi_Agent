# Documento de Requisitos: Integración del Router con el Quality Gate de Generación

## Introducción

El `TenderRouterService` detecta correctamente el tipo de licitación (ley, categoría, jurisdicción) y persiste ese contexto en `session_state.triage_context`. Sin embargo, el **quality gate** de los agentes de generación (`TechnicalWriterAgent` y `FormatsAgent`) es ciego a esa información: aplica los mismos umbrales para una licitación de servicios que para una de obra pública, bloqueando la generación cuando el comportamiento correcto sería continuar.

El caso concreto que dispara este bug: licitaciones de **obra pública** (LOPSRM / categoría OBRA) donde los requisitos técnicos son formas predefinidas numeradas (AT-10, AT-13, AE-02) que el ComplianceAgent clasifica correctamente como `presentar_fisico`. El quality gate ve `generar_count = 0` y bloquea, aunque no haya nada que redactar — ese es el comportamiento esperado para ese tipo de licitación.

Este spec cubre los cambios necesarios para que el quality gate use el `triage_context` del router al tomar decisiones de bloqueo.

---

## Glosario

- **triage_context**: Diccionario persistido en `session_state` por `TenderRouterService.get_triage()`. Contiene `law`, `tender_category`, `jurisdiction`, `confidence`, `signals_detected`, `must_have`, `must_have_policy`.
- **quality gate**: Función `_should_block_by_quality_gate()` en `TechnicalWriterAgent` y `FormatsAgent` que evalúa si la lista de requisitos tiene suficiente calidad para generar documentos.
- **generar_count**: Número de ítems en la zona técnica/administrativa clasificados con `tipo_accion = "generar"`.
- **presentar_fisico_count**: Número de ítems clasificados con `tipo_accion = "presentar_fisico"`.
- **evidence_match_ratio**: Proporción de ítems cuyo snippet fue verificado literalmente en el contexto RAG.
- **OBRA**: Categoría de licitación de obra pública (LOPSRM). Sus requisitos técnicos son formas predefinidas que el licitante llena, no documentos que redacta desde cero.
- **LOPSRM**: Ley de Obras Públicas y Servicios Relacionados con las Mismas. Marco normativo para licitaciones de construcción e infraestructura.
- **Forma AT/AE**: Formatos numerados predefinidos por la SHCP/SCT para licitaciones de obra (AT-10, AT-13, AE-02, etc.). Son documentos que el licitante llena, no redacta.

---

## Requisitos

### Requisito 1: Quality gate consciente del tipo de licitación

**User Story:** Como usuario de LicitAI que participa en una licitación de obra pública, quiero que el sistema genere los documentos de mi propuesta sin bloquearse por "baja calidad documental", ya que en obra pública los requisitos técnicos son formas predefinidas que se llenan, no documentos que se redactan.

#### Criterios de Aceptación

1. WHEN `TechnicalWriterAgent` evalúa el quality gate y `triage_context.tender_category == "OBRA"` y `generar_count == 0` y `presentar_fisico_count > 0`, THEN el quality gate SHALL retornar `block: False` y el agente SHALL retornar `AgentStatus.SUCCESS` con un mensaje informativo indicando que no hay documentos técnicos que redactar para este tipo de licitación.

2. WHEN `TechnicalWriterAgent` evalúa el quality gate y `triage_context.tender_category == "OBRA"` y `generar_count == 0` y `presentar_fisico_count == 0` y `total_items == 0`, THEN el quality gate SHALL retornar `block: False` (lista vacía, no hay nada que evaluar).

3. WHEN `TechnicalWriterAgent` evalúa el quality gate y `triage_context.tender_category` es distinto de `"OBRA"` (ej: `"BIENES"`, `"SERVICIOS"`, `"TECNOLOGIA"`), THEN el quality gate SHALL aplicar los umbrales existentes sin cambios.

4. WHEN `triage_context` no está disponible o `tender_category` es desconocido, THEN el quality gate SHALL aplicar los umbrales existentes como fallback seguro.

5. WHEN `FormatsAgent` evalúa el quality gate y `triage_context.tender_category == "OBRA"` y `generar_count == 0` y `presentar_fisico_count > 0`, THEN el quality gate SHALL retornar `block: False` con la misma lógica que `TechnicalWriterAgent`.

---

### Requisito 2: Propagación del triage_context a los agentes de generación

**User Story:** Como desarrollador, quiero que el `triage_context` detectado por el router esté disponible en los agentes de generación, para que puedan adaptar su comportamiento al tipo de licitación.

#### Criterios de Aceptación

1. WHEN el orquestador invoca `TechnicalWriterAgent` en modo `generation_only` o `generation`, THE orquestador SHALL incluir el `triage_context` en el `agent_input` del agente.

2. WHEN el orquestador invoca `FormatsAgent` en modo `generation_only` o `generation`, THE orquestador SHALL incluir el `triage_context` en el `agent_input` del agente.

3. WHEN `triage_context` está en `session_state` pero no en `agent_input.triage_context`, THE `TechnicalWriterAgent` SHALL leerlo directamente desde `session_state` como fallback.

4. THE `triage_context` propagado a los agentes de generación SHALL ser el mismo objeto persistido por el router durante la fase de análisis, sin modificaciones.

---

### Requisito 3: Extensión del router para categorías adicionales

**User Story:** Como desarrollador, quiero que el router detecte correctamente licitaciones de obra pública y produzca un `triage_context` con `tender_category = "OBRA"` cuando las bases correspondan a LOPSRM o contengan señales de obra.

#### Criterios de Aceptación

1. WHEN el texto de las bases contiene señales de obra pública (menciones de LOPSRM, "obra pública", "construcción", "infraestructura", formas AT/AE), THE `TenderRouterService.get_triage()` SHALL retornar `tender_category = "OBRA"` con `confidence >= 0.7`.

2. WHEN el triage detecta `law = "LOPSRM"`, THE `tender_category` SHALL ser `"OBRA"` por defecto, independientemente de otras señales.

3. THE prompt de triage v2 SHALL incluir señales explícitas para detectar licitaciones de obra pública (LOPSRM, formas AT/AE, catálogo de conceptos de obra).

---

### Requisito 4: Preservación del comportamiento existente

**User Story:** Como desarrollador, quiero que los cambios al quality gate no afecten el comportamiento para licitaciones de servicios y bienes, para garantizar que el gate siga protegiendo contra generación de documentos de baja calidad en esos casos.

#### Criterios de Aceptación

1. WHEN `triage_context.tender_category` es `"BIENES"`, `"SERVICIOS"` o `"TECNOLOGIA"`, THE quality gate SHALL aplicar exactamente los mismos umbrales que antes: `generar_count > 0`, `unknown_ratio <= 0.6`, `evidence_match_ratio >= 0.5`.

2. WHEN `DOCUMENT_QUALITY_HARD_GATE_ENABLED = False`, THE quality gate SHALL retornar `block: False` sin evaluar ninguna condición, igual que antes.

3. WHEN `triage_context` es `None` o está ausente, THE quality gate SHALL comportarse exactamente igual que antes (sin cambios en umbrales).

---

### Requisito 5: Observabilidad del comportamiento del gate

**User Story:** Como desarrollador, quiero que el quality gate registre en los logs por qué tomó la decisión de bloquear o no bloquear, incluyendo el tipo de licitación detectado, para facilitar el debugging.

#### Criterios de Aceptación

1. WHEN el quality gate retorna `block: False` por excepción de categoría OBRA, THE resultado SHALL incluir `reason: "obra_category_no_generate_items_expected"` y `tender_category: "OBRA"` en el dict de métricas.

2. WHEN el quality gate retorna `block: True`, THE resultado SHALL incluir el `tender_category` detectado en las métricas para trazabilidad.

3. THE `TechnicalWriterAgent` SHALL registrar un log estructurado `technical_writer_obra_skip` cuando omite la generación por categoría OBRA con `generar_count = 0`.
