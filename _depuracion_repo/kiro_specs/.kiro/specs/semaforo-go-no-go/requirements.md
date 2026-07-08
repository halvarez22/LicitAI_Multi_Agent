# Documento de Requisitos

## Introducción

El **Semáforo Go/No-Go** es una capa de decisión explícita que se inserta en el pipeline de LicitAI
inmediatamente después del `ComplianceAgent` y antes de los agentes de generación de documentos.

La feature tiene dos componentes principales:

1. **Semáforo Go/No-Go con Brechas Críticas** — eleva los knock-outs (causas de descalificación) y
   las brechas entre el perfil de empresa y los requisitos de las bases a una pantalla de decisión
   explícita. El usuario debe autorizar cada brecha para continuar o detener el pipeline.

2. **Score de Cumplimiento Técnico** — mide qué tan robusta es la propuesta del usuario frente a la
   rúbrica de evaluación que ya extrajo el `AnalystAgent` (`criterios_evaluacion` /
   `reglas_economicas`). El score es auditable: muestra qué criterios se cumplen, cuáles no y con
   qué evidencia del perfil maestro.

### Restricciones de diseño

- El pipeline existente (Intake → Analyst → Compliance → Economic → Generación) **no debe romperse**.
- Los contratos `AgentInput` / `AgentOutput` definidos en `agent_contracts.py` **deben respetarse**.
- El dictamen forense actual (`ComplianceAgent` + `ComplianceGate`) **debe seguir funcionando** sin
  modificaciones.
- La arquitectura de agentes existente (MCP, Redis Bus, Backtracking) **debe preservarse**.

---

## Glosario

- **Brecha Crítica**: Diferencia verificable entre un requisito de las bases y el perfil maestro de
  la empresa (p. ej. certificación faltante, capital contable insuficiente).
- **Knock-out**: Causa de descalificación (`causas_desechamiento`) detectada por el `ComplianceAgent`
  que impide la participación si no se subsana.
- **Perfil Maestro** (`master_profile`): JSON almacenado en el modelo `Company` con datos de la
  empresa: RFC, representante legal, certificaciones, estados financieros, catálogo de precios, años
  de experiencia, etc.
- **Rúbrica de Evaluación**: Criterios de puntos y porcentajes (o binario) extraídos por el
  `AnalystAgent` en los campos `criterios_evaluacion` y `reglas_economicas`.
- **Score de Cumplimiento Técnico**: Puntuación calculada de forma determinista (sin LLM) que
  refleja el porcentaje de criterios de la rúbrica que la empresa puede acreditar con evidencia del
  perfil maestro.
- **GoNoGoAgent**: Nuevo agente Python que implementa esta feature, insertado en el pipeline entre
  `ComplianceAgent` y `EconomicAgent`.
- **GoNoGoResult**: Contrato de salida del `GoNoGoAgent` (extiende `AgentOutput`).
- **Pantalla de Decisión**: Componente React que muestra el semáforo, las brechas y el score, y
  captura la decisión del usuario (continuar / detener).
- **Pipeline**: Secuencia de agentes orquestada por `OrchestratorAgent`.
- **Session_State**: Estado de sesión versionado (`SessionStateV1`) gestionado por `MCPContextManager`.
- **stop_reason**: Campo del `OrchestratorState` que indica por qué el pipeline se detuvo.

---

## Requisitos

### Requisito 1: Detección y Clasificación de Brechas Críticas

**User Story:** Como usuario de LicitAI, quiero ver una lista clara de las brechas entre mi perfil
de empresa y los requisitos de las bases, para poder decidir con información si vale la pena
continuar con la licitación.

#### Criterios de Aceptación

1. WHEN el `ComplianceAgent` completa su ejecución con `status` `success` o `partial`,
   THE `GoNoGoAgent` SHALL comparar cada elemento de `causas_desechamiento` y de las listas
   `administrativo`, `tecnico` y `formatos` del `ComplianceAgent` contra los campos del
   `master_profile` de la empresa.

2. THE `GoNoGoAgent` SHALL clasificar cada brecha detectada en una de las siguientes categorías:
   `certificacion_faltante`, `capital_insuficiente`, `experiencia_insuficiente`,
   `documento_faltante`, `requisito_no_acreditado`.

3. WHEN una brecha proviene directamente de `causas_desechamiento`, THE `GoNoGoAgent` SHALL
   marcarla con `is_knockout: true` en el objeto de brecha.

4. THE `GoNoGoAgent` SHALL incluir en cada objeto de brecha los campos:
   `id`, `categoria`, `descripcion`, `requisito_bases` (texto literal de las bases),
   `valor_empresa` (dato del perfil maestro o `null` si no existe), `is_knockout`,
   `zona_origen` (zona del `ComplianceAgent`: `ADMINISTRATIVO/LEGAL`, `TÉCNICO/OPERATIVO`,
   `FORMATOS/ANEXOS` o `GARANTÍAS/SEGUROS`).

5. IF el `master_profile` de la empresa está vacío o no contiene los campos necesarios para
   comparar un requisito, THEN THE `GoNoGoAgent` SHALL crear una brecha con
   `categoria: "requisito_no_acreditado"` y `valor_empresa: null`.

6. THE `GoNoGoAgent` SHALL ejecutar la detección de brechas de forma determinista, sin llamadas
   al LLM, para garantizar trazabilidad y reproducibilidad.

---

### Requisito 2: Semáforo de Decisión Go/No-Go

**User Story:** Como usuario de LicitAI, quiero ver un semáforo visual (rojo/amarillo/verde) que
resuma el riesgo de continuar, para tomar una decisión informada antes de invertir tiempo en
generar documentos.

#### Criterios de Aceptación

1. THE `GoNoGoAgent` SHALL calcular el estado del semáforo según estas reglas deterministas:
   - `RED`: existe al menos una brecha con `is_knockout: true`.
   - `YELLOW`: no hay knock-outs pero hay al menos una brecha con `is_knockout: false`.
   - `GREEN`: no hay brechas detectadas.

2. THE `GoNoGoAgent` SHALL incluir en `GoNoGoResult.data` los campos:
   `semaforo` (`RED`, `YELLOW` o `GREEN`), `brechas` (lista de objetos de brecha),
   `total_knockouts` (entero), `total_brechas` (entero).

3. WHEN el `GoNoGoAgent` produce un `GoNoGoResult`, THE `OrchestratorAgent` SHALL persistir
   el resultado en `session_state` bajo la clave `go_no_go_result` mediante
   `MCPContextManager.record_task_completion`.

4. WHEN `semaforo` es `RED` o `YELLOW`, THE `OrchestratorAgent` SHALL detener el pipeline
   con `stop_reason: "GO_NO_GO_PENDING"` y devolver el `GoNoGoResult` al frontend sin
   ejecutar el `EconomicAgent` ni los agentes de generación.

5. WHEN `semaforo` es `GREEN`, THE `OrchestratorAgent` SHALL continuar el pipeline hacia el
   `EconomicAgent` sin interrupciones.

6. IF el `GoNoGoAgent` falla con una excepción no controlada, THEN THE `OrchestratorAgent`
   SHALL registrar el error en el log estructurado y continuar el pipeline como si el semáforo
   fuera `GREEN`, para no bloquear el flujo por un fallo de la nueva capa.

---

### Requisito 3: Autorización Explícita del Usuario

**User Story:** Como usuario de LicitAI, quiero poder autorizar cada brecha crítica y decidir si
continuo o detengo el proceso, para que quede registro de mi decisión y el sistema respete mi
elección.

#### Criterios de Aceptación

1. THE `Pantalla_de_Decisión` SHALL mostrar al usuario la lista completa de brechas con su
   clasificación, descripción, requisito de las bases y valor del perfil maestro.

2. THE `Pantalla_de_Decisión` SHALL presentar dos acciones mutuamente excluyentes:
   "Continuar asumiendo el riesgo" y "Detener y revisar".

3. WHEN el usuario selecciona "Continuar asumiendo el riesgo", THE `Pantalla_de_Decisión`
   SHALL enviar al backend una solicitud de reanudación del pipeline con el campo
   `user_override: true` y la lista de `brechas_autorizadas` (IDs de brechas aceptadas).

4. WHEN el usuario selecciona "Detener y revisar", THE `Pantalla_de_Decisión` SHALL enviar
   al backend una solicitud de detención con `user_override: false` y el pipeline SHALL
   permanecer en estado `GO_NO_GO_PENDING`.

5. THE `OrchestratorAgent` SHALL aceptar una reanudación con `user_override: true` únicamente
   cuando `session_state.go_no_go_result` exista y `stop_reason` sea `"GO_NO_GO_PENDING"`.

6. WHEN el pipeline se reanuda con `user_override: true`, THE `OrchestratorAgent` SHALL
   persistir en `session_state` el campo `go_no_go_override` con los campos:
   `authorized_by: "user"`, `timestamp` (ISO-8601 UTC), `brechas_autorizadas`.

7. THE `GoNoGoAgent` SHALL incluir en `GoNoGoResult.data` el campo `requires_user_decision: true`
   cuando `semaforo` sea `RED` o `YELLOW`, y `requires_user_decision: false` cuando sea `GREEN`.

---

### Requisito 4: Score de Cumplimiento Técnico

**User Story:** Como usuario de LicitAI, quiero ver un score que mida qué tan bien cubre mi
propuesta la rúbrica de evaluación de las bases, para saber dónde reforzar mi oferta técnica.

#### Criterios de Aceptación

1. WHEN el `AnalystAgent` produce `criterios_evaluacion` con valor distinto a `"No especificado"`,
   THE `GoNoGoAgent` SHALL calcular el `score_cumplimiento_tecnico` comparando los criterios de
   la rúbrica contra los campos del `master_profile`.

2. THE `GoNoGoAgent` SHALL representar el score como un número entero entre 0 y 100, calculado
   como el porcentaje de criterios de la rúbrica que tienen evidencia en el `master_profile`.

3. THE `GoNoGoAgent` SHALL incluir en `GoNoGoResult.data.score_detalle` una lista de objetos,
   uno por criterio de la rúbrica, con los campos: `criterio` (descripción del criterio),
   `cumple` (booleano), `evidencia` (campo del `master_profile` que lo acredita o `null`),
   `peso` (porcentaje o puntos del criterio según las bases, o `null` si no está especificado).

4. WHEN `criterios_evaluacion` es `"No especificado"` o está ausente en la salida del
   `AnalystAgent`, THE `GoNoGoAgent` SHALL asignar `score_cumplimiento_tecnico: null` y
   `score_detalle: []`, sin generar error.

5. THE `GoNoGoAgent` SHALL calcular el score de forma determinista, sin llamadas al LLM,
   usando únicamente los datos del `master_profile` y la salida del `AnalystAgent`.

6. THE `Pantalla_de_Decisión` SHALL mostrar el score como un indicador visual (barra de progreso
   o porcentaje) junto con la lista de criterios, indicando para cada uno si se cumple o no y
   con qué evidencia.

7. THE `Pantalla_de_Decisión` SHALL mostrar el score únicamente cuando
   `score_cumplimiento_tecnico` no sea `null`.

---

### Requisito 5: Integración con el Pipeline sin Ruptura

**User Story:** Como desarrollador de LicitAI, quiero que el semáforo se integre en el pipeline
existente sin modificar los contratos ni el comportamiento actual, para no introducir regresiones.

#### Criterios de Aceptación

1. THE `GoNoGoAgent` SHALL implementar la interfaz `BaseAgent` y producir un `AgentOutput`
   válido con `agent_id: "go_no_go_001"`.

2. THE `GoNoGoAgent` SHALL recibir como entrada un `AgentInput` estándar y acceder a los
   resultados del `AnalystAgent` y del `ComplianceAgent` a través del `MCPContextManager`
   (vía `tasks_completed` en `session_state`).

3. THE `OrchestratorAgent` SHALL ejecutar el `GoNoGoAgent` después de que
   `stage_completed:compliance` esté registrado en `tasks_completed` y antes de ejecutar el
   `EconomicAgent`.

4. WHEN el pipeline se ejecuta en modo `analysis_only`, THE `OrchestratorAgent` SHALL ejecutar
   el `GoNoGoAgent` e incluir su resultado en la respuesta, pero no ejecutar el `EconomicAgent`
   ni los agentes de generación.

5. WHEN el pipeline se ejecuta en modo `generation_only` o `generation`, THE `OrchestratorAgent`
   SHALL omitir el `GoNoGoAgent` si `session_state.go_no_go_result` ya existe y
   `session_state.go_no_go_override.authorized_by` es `"user"`.

6. THE `GoNoGoAgent` SHALL completar su ejecución en menos de 5 segundos para sesiones con
   hasta 200 brechas candidatas, dado que opera de forma determinista sin llamadas al LLM ni
   a la base de datos vectorial.

7. IF `stage_completed:compliance` no está en `tasks_completed` cuando el `OrchestratorAgent`
   intenta ejecutar el `GoNoGoAgent`, THEN THE `OrchestratorAgent` SHALL omitir el
   `GoNoGoAgent` y continuar el pipeline sin error.

---

### Requisito 6: Persistencia y Trazabilidad de la Decisión

**User Story:** Como auditor de LicitAI, quiero que la decisión Go/No-Go quede registrada en el
dictamen forense, para tener trazabilidad completa de por qué se continuó o se detuvo el proceso.

#### Criterios de Aceptación

1. THE `OrchestratorAgent` SHALL incluir el `GoNoGoResult` en el dictamen forense
   (`process_audit_results_backend`) bajo la clave `go_no_go` cuando esté disponible.

2. WHEN el usuario autoriza continuar con brechas (`user_override: true`), THE sistema SHALL
   registrar en el dictamen el campo `go_no_go.override_timestamp` con la fecha y hora UTC
   de la autorización.

3. THE `GoNoGoResult` persistido en `session_state` SHALL incluir el campo
   `schema_version: 1` para permitir migraciones futuras.

4. WHEN el pipeline se detiene con `stop_reason: "GO_NO_GO_PENDING"`, THE `OrchestratorAgent`
   SHALL devolver en la respuesta el campo `go_no_go_result` con el contenido completo del
   `GoNoGoResult` para que el frontend pueda renderizar la pantalla de decisión.

5. THE `Pantalla_de_Decisión` SHALL mostrar, cuando el dictamen ya tenga `go_no_go.override_timestamp`,
   un aviso de que el usuario autorizó continuar con brechas en esa fecha y hora.

---

### Requisito 7: Experiencia de Usuario en la Pantalla de Decisión

**User Story:** Como usuario de LicitAI, quiero que la pantalla de decisión sea clara y no
ambigua, para entender el riesgo sin necesidad de conocimientos técnicos de compliance.

#### Criterios de Aceptación

1. THE `Pantalla_de_Decisión` SHALL mostrar el semáforo con un color y etiqueta de texto
   inequívocos: rojo con "Alto Riesgo — Causas de Descalificación Detectadas", amarillo con
   "Riesgo Moderado — Brechas a Revisar", verde con "Sin Brechas Detectadas".

2. THE `Pantalla_de_Decisión` SHALL mostrar cada brecha con knock-out en una sección separada
   y visualmente diferenciada de las brechas sin knock-out.

3. THE `Pantalla_de_Decisión` SHALL mostrar para cada brecha: la descripción en lenguaje
   natural, el texto literal del requisito de las bases y el valor actual del perfil maestro
   (o "No registrado" si es `null`).

4. WHEN el semáforo es `GREEN`, THE `Pantalla_de_Decisión` SHALL ocultar el bloque de brechas
   y mostrar únicamente el score de cumplimiento técnico y el botón "Continuar".

5. THE `Pantalla_de_Decisión` SHALL usar el sistema de estilos CSS existente del proyecto
   (sin TailwindCSS) y seguir el patrón de "Tarjeta Forense" (`ForensicCard`) para mostrar
   cada brecha.

6. THE `Pantalla_de_Decisión` SHALL ser accesible desde el flujo principal de la aplicación
   sin requerir navegación adicional: debe aparecer automáticamente cuando el pipeline devuelve
   `stop_reason: "GO_NO_GO_PENDING"`.

---

### Requisito 8: Calidad de Software (SQA)

**User Story:** Como desarrollador de LicitAI, quiero que el `GoNoGoAgent` y su lógica de scoring
cumplan los estándares SQA obligatorios del proyecto, para garantizar mantenibilidad, trazabilidad
y ausencia de regresiones.

#### Criterios de Aceptación

1. THE `GoNoGoAgent` SHALL tener pruebas unitarias que cubran los tres estados del semáforo:
   al menos un caso para `RED` (brecha con `is_knockout: true`), uno para `YELLOW` (brecha sin
   knock-out) y uno para `GREEN` (sin brechas).

2. THE `go_no_go_scorer` SHALL tener pruebas unitarias con los siguientes casos límite:
   rúbrica vacía (`criterios_evaluacion: []`), perfil maestro vacío (`master_profile: {}`),
   todos los criterios cumplidos (score esperado: 100) y ningún criterio cumplido (score
   esperado: 0).

3. THE `GoNoGoAgent` SHALL incluir type hints en todas las funciones y métodos Python del módulo,
   sin excepción.

4. THE `GoNoGoAgent` SHALL incluir docstrings en español siguiendo el Google Style Guide, con
   descripción de parámetros de entrada (`Args:`), valor de retorno (`Returns:`) y excepciones
   posibles (`Raises:`).

5. THE `GoNoGoAgent` SHALL tener como máximo 200 líneas de código; toda la lógica de cálculo
   del score de cumplimiento técnico SHALL residir en un módulo separado denominado
   `go_no_go_scorer.py`.

6. WHEN se realiza cualquier cambio al `GoNoGoAgent` o a `go_no_go_scorer.py`, THE desarrollador
   SHALL acompañar el cambio con evidencia mínima de validación: prueba local ejecutada, test
   automatizado o checklist de verificación documentado.

---

### Requisito 9: Seguridad (ISO/IEC 27034)

**User Story:** Como responsable de seguridad de LicitAI, quiero que los datos sensibles del
perfil maestro de la empresa estén protegidos en logs, respuestas HTTP y registros de auditoría,
para cumplir los controles ISO/IEC 27034 obligatorios del proyecto.

#### Criterios de Aceptación

1. THE `GoNoGoAgent` SHALL omitir de los logs de producción los campos sensibles del
   `master_profile` que aparezcan en las brechas: RFC, capital contable, certificaciones y
   estados financieros; en su lugar SHALL registrar únicamente el identificador de brecha
   (`brecha_id`) y la categoría.

2. THE endpoint de Go/No-Go SHALL sanitizar la respuesta HTTP de modo que no exponga campos
   internos del `master_profile` más allá de los estrictamente necesarios para renderizar la
   pantalla de decisión: `descripcion`, `requisito_bases`, `valor_empresa` (valor de presentación,
   no el objeto completo), `is_knockout` y `categoria`.

3. WHEN el campo `go_no_go_override` se persiste en `session_state`, THE sistema SHALL incluir
   los campos de auditoría: `authorized_by` (identificador del usuario), `timestamp` (ISO-8601
   UTC), e `ip_hash` (hash SHA-256 de la IP del usuario, nunca la IP directa).

4. WHEN cualquier operación modifica el estado de sesión relacionado con el semáforo
   (autorización de brechas, override, cambio de `stop_reason`), THE sistema SHALL registrar
   la operación en el log de auditoría estructurado con los campos: `event_type`,
   `session_id`, `timestamp` UTC, `actor` y `details` (sin datos sensibles del perfil maestro).

---

### Requisito 10: MCP y Arquitectura

**User Story:** Como arquitecto de LicitAI, quiero que el `GoNoGoAgent` y sus módulos asociados
respeten los patrones de MCP, stateless design y contratos REST existentes, para mantener la
coherencia arquitectónica del sistema.

#### Criterios de Aceptación

1. THE `GoNoGoAgent` SHALL usar exclusivamente `MCPContextManager` para leer y escribir estado
   de sesión; el agente no SHALL acceder directamente a la base de datos PostgreSQL ni a
   ChromaDB.

2. THE `go_no_go_scorer` SHALL ser un módulo stateless y puro: no SHALL mantener estado interno
   entre llamadas, no SHALL producir efectos secundarios (escritura a base de datos, logs de
   negocio, llamadas HTTP) y SHALL recibir únicamente los datos necesarios como parámetros
   explícitos.

3. THE comunicación del resultado Go/No-Go al frontend SHALL seguir el patrón de job polling
   existente en el proyecto; no SHALL crearse un nuevo endpoint de long-polling ni WebSocket
   exclusivo para esta feature.

4. THE nuevo endpoint de autorización de brechas SHALL seguir el contrato REST existente del
   proyecto, devolviendo una respuesta con los campos `success` (booleano), `data` (objeto con
   el resultado) y `message` (cadena descriptiva), con los códigos HTTP estándar del proyecto.
