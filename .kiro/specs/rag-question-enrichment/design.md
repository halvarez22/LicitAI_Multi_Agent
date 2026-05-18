# Diseño Técnico: rag-question-enrichment

## Overview

El `ChatbotRAGAgent` necesita enriquecer las `pending_questions` con fragmentos reales de las bases de licitación antes de formularlas al usuario. El método actual `_enrich_pending_with_rag_context` tiene cinco deficiencias: queries pobres, cobertura limitada (ignora campos `intake_planner`), ausencia de validación de relevancia por score, truncado incoherente y lógica de términos hardcodeada con `elif` en cascada.

Este diseño reemplaza la implementación interna del método y agrega tres métodos auxiliares estáticos privados en `ChatbotRAGAgent`. El único archivo modificado es `backend/app/agents/chatbot_rag.py`. No se modifica ningún otro componente del sistema.

### Objetivo

Producir un `rag_context` de alta calidad que:
1. Sea semánticamente relevante al campo específico preguntado (validado por score de distancia coseno).
2. Sea legible para el usuario (sin variables técnicas, oración completa, ≤ 400 chars).
3. Cubra tanto campos estructurados como campos de tipo `intake_planner`.
4. Nunca bloquee el flujo conversacional ante cualquier fallo externo.

---

## Architecture

El `Enricher` es un componente lógico interno de `ChatbotRAGAgent`. No es una clase separada ni un servicio externo. Se implementa como un conjunto de métodos privados estáticos más el método principal asíncrono.

```mermaid
flowchart TD
    A[process: pending_question] --> B{¿Es enriquecible?}
    B -- No --> Z[Retornar original]
    B -- Sí --> C[_build_rag_query]
    C --> D[VectorDbServiceClient.query_texts n=3]
    D -- Excepción --> W[log warning → Retornar original]
    D -- Respuesta --> E{¿Distancias disponibles?}
    E -- No/vacío --> Z
    E -- Sí --> F{score ≤ RAG_RELEVANCE_THRESHOLD?}
    F -- No → log debug --> Z
    F -- Sí --> G[_truncate_to_sentence]
    G --> H{len ≥ RAG_CONTEXT_MIN_CHARS?}
    H -- No --> Z
    H -- Sí --> I[_is_rag_context_clean]
    I -- False → log warning --> Z
    I -- True --> J[enriched = dict(pending_question)]
    J --> K[enriched['rag_context'] = contexto]
    K --> L[log info → Retornar enriched]
```

### Modos de enriquecimiento

| Tipo de campo | Condición de activación | Fuente de la query semántica |
|---|---|---|
| `intake_planner` | `type == "intake_planner"` | `question` + `provenance_ui.reason` |
| Estructurado | `field_target` comienza con prefijo conocido | label humanizado + términos del `_DOMAIN_TERMS_MAP` |
| No enriquecible | Ninguna de las anteriores | — (retorna original sin búsqueda) |

---

## Components and Interfaces

### Constantes de clase en `ChatbotRAGAgent`

```python
# Umbral máximo de distancia coseno para considerar un fragmento relevante.
# ChromaDB retorna distancias en [0, 2]; valores cercanos a 0 = alta similitud.
RAG_RELEVANCE_THRESHOLD: float = 0.75

# Longitud máxima del rag_context en caracteres.
RAG_CONTEXT_MAX_CHARS: int = 400

# Longitud mínima del rag_context para que sea considerado útil.
RAG_CONTEXT_MIN_CHARS: int = 30

# Prefijos de field_target que indican campos con contexto en las bases.
RAG_ENRICHABLE_PREFIXES: tuple = (
    "condiciones_contractuales.",
    "solvencia_economica.",
    "solvencia_legal.",
    "solvencia_tecnica.",
    "gng_",
)

# Mapa de términos de dominio por subcadena del field_target.
# Reemplaza los elif hardcodeados del método original.
_DOMAIN_TERMS_MAP: dict = {
    "penalizacion":       "pena convencional multa retraso incumplimiento",
    "penaliz":            "pena convencional multa retraso incumplimiento",
    "condiciones_pago":   "forma de pago plazo facturación anticipo",
    "garantia":           "garantía vicios ocultos defectos cumplimiento",
    "capital":            "capital contable mínimo requerido patrimonio",
    "facturacion":        "facturación anual ingresos comprobables",
    "experiencia":        "años experiencia contratos similares previos",
    "solvencia_legal":    "requisito legal documento acreditar constitución",
    "solvencia_tecnica":  "capacidad técnica personal especializado equipo",
    "gng_":               "criterio viabilidad participación licitación",
}
```

### Método auxiliar: `_build_rag_query`

```python
@staticmethod
def _build_rag_query(pending_question: Dict[str, Any]) -> str:
    """
    Construye la query semántica para ChromaDB según el tipo de campo.

    Para intake_planner: usa question + provenance_ui.reason (semánticamente ricos).
    Para estructurados: usa label humanizado + términos del _DOMAIN_TERMS_MAP.
    Garantiza longitud mínima de 10 chars con fallback al label humanizado.
    """
```

**Lógica:**
1. Si `type == "intake_planner"`: `query = question + " " + reason` (si reason no vacío).
2. Si no: `label = _humanize_field_target(field_target)` + términos del `_DOMAIN_TERMS_MAP` (primer match por subcadena).
3. Si `len(query.strip()) < 10`: fallback a `_humanize_field_target(field_target)`.
4. Retorna `query.strip()`.

### Método auxiliar: `_truncate_to_sentence`

```python
@staticmethod
def _truncate_to_sentence(text: str, max_chars: int, min_chars: int) -> str:
    """
    Trunca text a max_chars garantizando que el resultado termine en oración completa.

    Estrategia de corte (en orden de preferencia):
    1. Si text <= max_chars y ya termina en separador: retornar tal cual.
    2. Truncar a max_chars; buscar hacia atrás el último '.', '!', '?'.
    3. Fallback: buscar hacia atrás la última ',' o ';'.
    4. Fallback final: usar el texto truncado tal cual.
    5. Si len(resultado) < min_chars: retornar "" (señal de descarte).
    """
```

**Invariantes garantizadas:**
- `len(resultado) <= max_chars` siempre.
- Si `resultado != ""`, entonces `len(resultado) >= min_chars`.
- Si el texto original contiene al menos un separador de oración dentro de los primeros `max_chars`, el resultado termina en ese separador.

### Método auxiliar: `_is_rag_context_clean`

```python
@staticmethod
def _is_rag_context_clean(text: str, min_chars: int) -> bool:
    """
    Verifica que el texto es legible para el usuario y no contiene variables técnicas.

    Retorna False si:
    - len(text) < min_chars
    - Contiene patrón \w+\.\w+ (namespace técnico como "solvencia_legal.rfc")
    """
```

**Lógica:**
```python
import re
if len(text) < min_chars:
    return False
if re.search(r'\w+\.\w+', text):
    return False
return True
```

### Método principal: `_enrich_pending_with_rag_context`

```python
async def _enrich_pending_with_rag_context(
    self,
    session_id: str,
    pending_question: Dict[str, Any],
) -> Dict[str, Any]:
```

**Firma idéntica al método actual.** Retorna siempre un `Dict[str, Any]`. Nunca lanza excepciones.

---

## Data Models

### Entrada: `pending_question`

No se modifica la estructura. Campos relevantes para el Enricher:

| Campo | Tipo | Descripción |
|---|---|---|
| `type` | `str` | Tipo de pregunta. `"intake_planner"` activa modo semántico rico. |
| `field_target` | `str` | Clave técnica del campo en `master_profile`. |
| `question` | `str` | Pregunta generada por `IntakePlannerAgent`. Rica semánticamente. |
| `provenance_ui` | `dict` | Metadatos de provenance. Contiene `reason` y `clausula_texto`. |
| `label` | `str` | Label legible del campo (opcional, puede estar ausente). |

### Salida: `pending_question` enriquecido

Copia del `pending_question` original con un campo adicional:

| Campo | Tipo | Descripción |
|---|---|---|
| `rag_context` | `str` | Fragmento de las bases de licitación. ≤ 400 chars, oración completa, sin variables técnicas. |

### Respuesta de `VectorDbServiceClient.query_texts`

```python
{
    "documents": [str, ...],    # Lista plana de fragmentos (post-procesado por vector_service)
    "distances": [float, ...],  # Distancias coseno correspondientes
    "metadatas": [dict, ...],   # Metadatos de cada fragmento
}
```

> **Nota:** `query_texts` en `vector_service.py` ya aplana la lista de listas de ChromaDB. El primer elemento de `documents` es el fragmento más similar.

---

## Pseudocódigo PASCAL del algoritmo principal

```pascal
FUNCTION EnrichPendingWithRagContext(session_id: String; pending_question: Dict): Dict;
VAR
  field_target, question_type, query, raw_doc, rag_context: String;
  results: Dict;
  distances: List;
  score: Float;
  enriched: Dict;
BEGIN
  { Validación de entrada }
  IF session_id = '' OR session_id = NULL THEN
    RETURN pending_question;
  END;

  field_target := pending_question.get('field_target', '');
  question_type := pending_question.get('type', '');

  { Determinar si el campo es enriquecible }
  is_intake := (question_type = 'intake_planner');
  is_structured := StartsWithAnyPrefix(field_target, RAG_ENRICHABLE_PREFIXES);

  IF NOT (is_intake OR is_structured) THEN
    RETURN pending_question;  { No enriquecible: retornar original }
  END;

  { Construir query semántica }
  query := BuildRagQuery(pending_question);

  { Buscar en ChromaDB }
  TRY
    results := vector_db.query_texts(session_id, query, n_results=3);
  EXCEPT Exception AS e DO
    LogWarning('rag_enrichment_failed', session_id, field_target, e);
    RETURN pending_question;
  END;

  { Validar estructura de respuesta }
  distances := results.get('distances', []);
  documents := results.get('documents', []);
  IF (distances = []) OR (documents = []) THEN
    RETURN pending_question;
  END;

  { Validar score de relevancia }
  score := distances[0];
  IF score > RAG_RELEVANCE_THRESHOLD THEN
    LogDebug('rag_score_too_high', session_id, field_target, score);
    RETURN pending_question;
  END;

  { Truncar a oración completa }
  raw_doc := documents[0];
  rag_context := TruncateToSentence(raw_doc, RAG_CONTEXT_MAX_CHARS, RAG_CONTEXT_MIN_CHARS);

  IF rag_context = '' THEN
    RETURN pending_question;  { Fragmento demasiado corto }
  END;

  { Validar ausencia de variables técnicas }
  IF NOT IsRagContextClean(rag_context, RAG_CONTEXT_MIN_CHARS) THEN
    LogWarning('rag_technical_variable_detected', session_id, field_target, rag_context[:80]);
    RETURN pending_question;
  END;

  { Enriquecer: crear copia del pending_question }
  enriched := COPY(pending_question);
  enriched['rag_context'] := rag_context;

  LogInfo('rag_enrichment_success', session_id, field_target,
          query_type=IIF(is_intake, 'intake_planner', 'structured'),
          rag_chars=LEN(rag_context), score=score);

  RETURN enriched;
END;
```

---

## Correctness Properties

*Una propiedad es una característica o comportamiento que debe cumplirse en todas las ejecuciones válidas del sistema — esencialmente, un enunciado formal sobre lo que el software debe hacer. Las propiedades sirven como puente entre las especificaciones legibles por humanos y las garantías de corrección verificables por máquina.*

### Property 1: Longitud máxima de `_truncate_to_sentence`

*Para cualquier* texto de longitud arbitraria y cualquier valor de `max_chars` positivo, `_truncate_to_sentence` nunca retorna un string con más de `max_chars` caracteres.

**Validates: Requirements 4.1, 4.6**

### Property 2: Terminación en separador de `_truncate_to_sentence`

*Para cualquier* texto que contenga al menos un separador de oración (`.`, `!`, `?`, `,`, `;`) dentro de los primeros `max_chars` caracteres, `_truncate_to_sentence` retorna un string que termina en uno de esos separadores, o retorna el texto completo si ya cabe en `max_chars`.

**Validates: Requirements 4.2, 4.3, 4.4**

### Property 3: `_is_rag_context_clean` rechaza namespaces técnicos

*Para cualquier* string que contenga el patrón `\w+\.\w+` (palabra, punto, palabra), `_is_rag_context_clean` retorna `False`.

**Validates: Requirements 5.1, 5.2, 5.3**

### Property 4: `_build_rag_query` incluye el `question` original para `intake_planner`

*Para cualquier* `pending_question` con `type == "intake_planner"` y campo `question` no vacío, `_build_rag_query` retorna una query que contiene el `question` original como subcadena.

**Validates: Requirements 1.1, 1.2**

### Property 5: Inmutabilidad del `pending_question` original ante fallos

*Para cualquier* `pending_question` y cualquier condición de fallo (excepción de ChromaDB, score alto, fragmento sucio, fragmento corto), `_enrich_pending_with_rag_context` retorna el mismo objeto `pending_question` recibido (identidad de objeto Python: `result is pending_question`), sin mutaciones.

**Validates: Requirements 6.1, 6.6, 8.2**

### Property 6: Score alto implica retorno del original

*Para cualquier* `pending_question` enriquecible y cualquier score de distancia mayor a `RAG_RELEVANCE_THRESHOLD`, `_enrich_pending_with_rag_context` retorna el `pending_question` original sin campo `rag_context`.

**Validates: Requirements 3.3**

---

## Error Handling

### Tabla de condiciones de fallo y comportamiento

| Condición | Comportamiento | Log |
|---|---|---|
| `session_id` vacío o `None` | Retornar original sin búsqueda | — |
| `pending_question` sin campos esperados | Retornar original (defaults a `""`) | — |
| Campo no enriquecible (tipo/prefijo) | Retornar original sin búsqueda | — |
| `query_texts` lanza excepción | Retornar original | `warning: rag_enrichment_failed` |
| Respuesta de ChromaDB con estructura inesperada | Retornar original | — |
| Score > `RAG_RELEVANCE_THRESHOLD` | Retornar original | `debug: rag_score_too_high` |
| `_truncate_to_sentence` retorna `""` (< min_chars) | Retornar original | — |
| `_is_rag_context_clean` retorna `False` | Retornar original | `warning: rag_technical_variable_detected` |

### Principio de resiliencia

El método `_enrich_pending_with_rag_context` es un **best-effort enrichment**: si cualquier paso falla, el flujo conversacional continúa con el `pending_question` original. El enriquecimiento es una optimización de calidad, no un requisito de funcionamiento.

El bloque `try/except` envuelve únicamente la llamada a `query_texts`. El resto de la lógica (validación de score, truncado, limpieza) opera sobre datos ya en memoria y no debe lanzar excepciones si se implementa correctamente.

---

## Testing Strategy

### Librería de PBT

Se usa **Hypothesis** (ya presente en el proyecto, confirmado por `.hypothesis/` en la raíz y `backend/.hypothesis/`).

### Enfoque dual

**Tests de ejemplo (pytest):** Verifican comportamientos específicos, casos edge y logging.
**Tests de propiedad (Hypothesis):** Verifican invariantes universales sobre los métodos auxiliares y el método principal con mocks.

### Configuración de Hypothesis

```python
from hypothesis import given, settings
from hypothesis import strategies as st

@settings(max_examples=200)
@given(...)
def test_property_N(...):
    ...
```

Mínimo 200 iteraciones por propiedad (se usa `@settings(max_examples=200)`).

### Tests de propiedad (uno por propiedad del diseño)

#### Property 1: Longitud máxima de `_truncate_to_sentence`

```python
# Feature: rag-question-enrichment, Property 1: _truncate_to_sentence never exceeds max_chars
@settings(max_examples=200)
@given(
    text=st.text(min_size=0, max_size=2000),
    max_chars=st.integers(min_value=10, max_value=1000),
    min_chars=st.integers(min_value=1, max_value=50),
)
def test_truncate_never_exceeds_max_chars(text, max_chars, min_chars):
    assume(min_chars < max_chars)
    result = ChatbotRAGAgent._truncate_to_sentence(text, max_chars, min_chars)
    assert len(result) <= max_chars
```

#### Property 2: Terminación en separador

```python
# Feature: rag-question-enrichment, Property 2: _truncate_to_sentence ends in sentence separator
SEPARATORS = {'.', '!', '?', ',', ';'}

@settings(max_examples=200)
@given(
    prefix=st.text(min_size=0, max_size=350, alphabet=st.characters(blacklist_characters='.!?,;')),
    sep=st.sampled_from(['.', '!', '?', ',', ';']),
    suffix=st.text(min_size=0, max_size=100, alphabet=st.characters(blacklist_characters='.!?,;')),
)
def test_truncate_ends_in_separator(prefix, sep, suffix):
    # Construir texto que tiene un separador dentro de los primeros 400 chars
    text = prefix + sep + suffix
    result = ChatbotRAGAgent._truncate_to_sentence(text, 400, 1)
    if result:
        assert result[-1] in SEPARATORS or result == text[:400]
```

#### Property 3: `_is_rag_context_clean` rechaza namespaces técnicos

```python
# Feature: rag-question-enrichment, Property 3: _is_rag_context_clean rejects namespace patterns
@settings(max_examples=200)
@given(
    word_a=st.from_regex(r'[a-zA-Z_]{2,10}', fullmatch=True),
    word_b=st.from_regex(r'[a-zA-Z_]{2,10}', fullmatch=True),
    surrounding=st.text(min_size=30, max_size=200),
)
def test_clean_rejects_namespace_pattern(word_a, word_b, surrounding):
    text = surrounding + word_a + '.' + word_b + surrounding
    result = ChatbotRAGAgent._is_rag_context_clean(text, min_chars=30)
    assert result is False
```

#### Property 4: `_build_rag_query` incluye `question` para `intake_planner`

```python
# Feature: rag-question-enrichment, Property 4: _build_rag_query includes question for intake_planner
@settings(max_examples=200)
@given(
    question=st.text(min_size=10, max_size=300),
    reason=st.text(min_size=0, max_size=200),
    field_target=st.text(min_size=0, max_size=50),
)
def test_build_query_includes_question_for_intake_planner(question, reason, field_target):
    pq = {
        "type": "intake_planner",
        "question": question,
        "provenance_ui": {"reason": reason},
        "field_target": field_target,
    }
    query = ChatbotRAGAgent._build_rag_query(pq)
    assert question in query
```

#### Property 5: Inmutabilidad ante fallos

```python
# Feature: rag-question-enrichment, Property 5: original pending_question is never mutated on failure
@settings(max_examples=200)
@given(
    pending_question=st.fixed_dictionaries({
        "type": st.sampled_from(["intake_planner", "structured_field"]),
        "field_target": st.sampled_from([
            "solvencia_economica.capital_contable",
            "condiciones_contractuales.penalizaciones",
            "intake_field",
        ]),
        "question": st.text(min_size=5, max_size=100),
    }),
    session_id=st.text(min_size=1, max_size=50),
)
@pytest.mark.asyncio
async def test_original_not_mutated_on_failure(pending_question, session_id):
    agent = make_agent_with_failing_vector_db()  # mock que lanza Exception
    result = await agent._enrich_pending_with_rag_context(session_id, pending_question)
    assert result is pending_question  # identidad de objeto, no solo igualdad
```

#### Property 6: Score alto implica retorno del original

```python
# Feature: rag-question-enrichment, Property 6: high score returns original without rag_context
@settings(max_examples=200)
@given(
    score=st.floats(
        min_value=ChatbotRAGAgent.RAG_RELEVANCE_THRESHOLD + 0.001,
        max_value=2.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    pending_question=st.fixed_dictionaries({
        "type": st.just("intake_planner"),
        "question": st.text(min_size=10, max_size=100),
        "field_target": st.just("solvencia_economica.capital_contable"),
        "provenance_ui": st.just({}),
    }),
    session_id=st.text(min_size=1, max_size=50),
)
@pytest.mark.asyncio
async def test_high_score_returns_original(score, pending_question, session_id):
    agent = make_agent_with_mock_vector_db(
        documents=["Fragmento de prueba con suficiente longitud para pasar validaciones básicas."],
        distances=[score],
    )
    result = await agent._enrich_pending_with_rag_context(session_id, pending_question)
    assert result is pending_question
    assert "rag_context" not in result
```

### Tests de ejemplo (pytest)

- **Enriquecimiento exitoso end-to-end**: mock de `query_texts` con score 0.3 y fragmento limpio; verificar que `result["rag_context"]` existe y tiene ≤ 400 chars.
- **Términos de dominio por tipo de campo**: verificar que `_build_rag_query` incluye "capital contable" para `solvencia_economica.capital_contable`.
- **Logging de enriquecimiento exitoso**: verificar que se llama a `logger.info` con `session_id`, `field_target`, `rag_chars` y `score`.
- **Logging de score alto**: verificar que se llama a `logger.debug` con el score cuando se descarta por relevancia.
- **Logging de variable técnica**: verificar que se llama a `logger.warning` cuando `_is_rag_context_clean` retorna `False`.
- **session_id vacío**: verificar que retorna el original sin llamar a `query_texts`.
- **Tipos no enriquecibles**: `quality_validation_blocking`, `economic_price`, `economic_validation_blocking` retornan el original.
- **Respuesta de ChromaDB con listas vacías**: retorna el original sin excepciones.
- **Fragmento con namespace técnico**: `solvencia_legal.rfc` en el fragmento → descartado.

### Ubicación de los tests

```
backend/tests/agents/test_rag_question_enrichment.py
```

Siguiendo la convención del proyecto (tests en `backend/tests/`).
