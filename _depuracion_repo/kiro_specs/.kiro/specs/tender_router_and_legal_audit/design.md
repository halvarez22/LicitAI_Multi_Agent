# Diseño de Ingeniería: Router de Peritaje Legal

## 1. Arquitectura del Sistema
Se propone una capa de servicios intermedia que gestione el conocimiento normativo antes de la ejecución de los agentes especialistas.

### Componentes Clave:
- **`TenderRouterService`**: Servicio estático que encapsula la lógica de clasificación y recuperación de matrices.
- **`AgentInput Extension`**: Adición del campo `triage_context` para propagar el conocimiento normativo.
- **`Orchestrator Pre-flight`**: Nuevo paso en el orquestador que ejecuta el triage antes de iniciar el ciclo de vida de los agentes de análisis.

## 2. Flujo de Datos (Pipeline de Dos Pasos)

### Paso 1: Triage (Discovery)
1. El orquestador solicita al `VectorDbServiceClient` los primeros fragmentos del documento (Páginas 1-10).
2. Se envía el texto al **modelo de inferencia local (Ollama)** con un prompt especializado en jurisprudencia mexicana.
3. El resultado es un objeto JSON con `law`, `jurisdiction` y `tender_category`.

### Paso 2: Auditoría (Context Injection)
1. El orquestador recupera la **Matriz de Obligatorios** y las **Reglas Críticas** desde el `TenderRouterService`.
2. Inyecta este `triage_context` en el `AgentInput` de los agentes `Analyst` y `Compliance`.
3. El `triage_context` incluye `must_have_policy` (acción esperada + aliases por etiqueta) para enforcement determinista downstream.
3. Los agentes ajustan su `System Prompt` dinámicamente para actuar como auditores bajo ese marco legal específico.

## 3. Modelo de Datos (JSON Schema)
```json
{
  "triage_context": {
    "law": "LEY_QUERETARO",
    "jurisdiction": "ESTATAL",
    "tender_category": "BIENES",
    "must_have": ["FIS_ESTATAL_OPINION", "LEG_ACTA", "ECO_PRECIOS"],
    "must_have_policy": {
      "FIS_ESTATAL_OPINION": {
        "expected_action": "presentar_fisico",
        "aliases": ["opinion estatal", "opinion de cumplimiento estatal"]
      }
    },
    "critical_rules": ["PRECIOS_MAX_2_DECIMALES"]
  }
}
```

## 4. Estrategia de Auditoría en el Agente
- **Matching de Etiquetas:** El agente mapea anexos contra taxonomía universal y aliases de política (`must_have_policy`), con normalización defensiva.
- **Reconciliación Forzada:** Si una etiqueta está en `must_have`, el agente tiene prohibido devolver `tipo_accion: informativo` y fuerza la `expected_action`.
- **Procedencia visible:** Cada forzado registra bloque `forced_by_must_have` con `label`, `matched_on`, `expected_action` y `source`.
- **Detección de Omisiones:** Si el agente termina el escaneo y falta un `must_have`, debe generar una entrada sintética marcada como `OMISO` para alertar al usuario.
