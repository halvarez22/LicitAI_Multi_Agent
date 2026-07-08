# Documento de Diseño: semantic-file-extractor

## Visión General

Cuando el usuario sube un archivo en respuesta a una pregunta activa del asistente, el sistema actualmente lo indexa de forma pasiva y espera que el usuario haga clic en "Analizar Fuentes". El `DataGapAgent` entonces busca todos los campos faltantes en el documento — sin saber qué dato específico se estaba pidiendo.

Este feature introduce un **extractor semántico dirigido por misión**: el asistente ya sabe qué dato está esperando (gracias al `mission_context` de la Fase 1), y cuando el usuario sube un archivo, el sistema extrae activamente ese dato específico, lo valida matemáticamente si aplica, y presenta el mapeo al usuario para confirmación antes de guardarlo.

**Principio de diseño central:** Python para filtrar y validar, LLM solo para interpretar. El 90% del trabajo (reducción del archivo, validación numérica) lo hace Python puro. El LLM solo recibe el fragmento relevante ya limpio.

**Restricciones:**
- Sin cambios en el frontend
- `DocumentPreprocessor` y `NumericValidator` son Python puro (sin LLM)
- `MissionDataExtractor` usa el `ResilientLLMClient` existente
- `DocumentIngestionRouter` ya existe — no se modifica
- Si el archivo no contiene el dato, el asistente lo comunica y mantiene la pregunta pendiente

---

## Arquitectura

```
[Usuario sube archivo con pregunta activa]
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  ChatbotRAGAgent._handle_file_upload_with_mission   │
│  (Componente 4 — orquestador del flujo)             │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  DocumentPreprocessor.extract_relevant_sections     │
│  (Componente 1 — Python puro, sin LLM)              │
│  Input:  extracted_text + dato_solicitado           │
│  Output: fragmento relevante ≤ 3000 tokens          │
│  Reducción típica: 90% del texto descartado         │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  MissionDataExtractor.extract                       │
│  (Componente 2 — usa LLM)                           │
│  Input:  fragmento relevante + mission_context      │
│  Output: ExtractionResult {value, confidence,       │
│          source_reference, raw_snippet,             │
│          extraction_status}                         │
└─────────────────────────────────────────────────────┘
         │
         ▼ (solo si dato es numérico)
┌─────────────────────────────────────────────────────┐
│  NumericValidator.validate_and_normalize            │
│  (Componente 3 — Python puro, sin LLM)              │
│  Input:  raw_value + field_type                     │
│  Output: ValidationResult {normalized_value,        │
│          numeric_value, is_valid, adjustment_applied}│
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  Mensaje de confirmación al usuario                 │
│  "Encontré [valor] en [referencia]. ¿Es correcto?"  │
│  session_state["pending_mapping_confirmation"]      │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  ChatbotRAGAgent._handle_mapping_confirmation       │
│  (Componente 5 — procesa respuesta del usuario)     │
│  "sí" → guardar en master_profile                   │
│  "no, es X" → guardar X                             │
│  "no aplica" → mantener pregunta pendiente          │
└─────────────────────────────────────────────────────┘
```

---

## Componentes e Interfaces

### Componente 1: `DocumentPreprocessor`

**Archivo:** `backend/app/services/document_preprocessor.py`

```python
from dataclasses import dataclass
from typing import List

@dataclass
class PreprocessResult:
    relevant_text: str
    total_chars_original: int
    total_chars_filtered: int
    reduction_ratio: float      # 0.0 a 1.0
    keywords_found: List[str]

class DocumentPreprocessor:
    """
    Filtra un texto largo para extraer solo las secciones relevantes
    para un dato específico. Sin LLM — Python puro.
    
    Estrategia de scoring por chunk:
    - +3 puntos por cada keyword del dato_solicitado encontrada (case-insensitive)
    - +2 puntos si el chunk contiene dígitos (para datos numéricos)
    - +1 punto por palabras de contexto de licitación (monto, precio, capital, etc.)
    """
    
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    TOP_K_CHUNKS: int = 6
    
    def extract_relevant_sections(
        self,
        extracted_text: str,
        dato_solicitado: str,
        max_tokens: int = 3000,
    ) -> PreprocessResult:
        ...
    
    def _extract_keywords(self, dato_solicitado: str) -> List[str]:
        """Extrae keywords del dato_solicitado limpiando stopwords."""
        ...
    
    def _score_chunk(self, chunk: str, keywords: List[str]) -> int:
        """Calcula el score de relevancia de un chunk."""
        ...
    
    def _split_into_chunks(self, text: str) -> List[str]:
        """Divide el texto en chunks con overlap."""
        ...
```

**Precondiciones:**
- `extracted_text` es un string (puede estar vacío)
- `dato_solicitado` es un string no vacío
- `max_tokens` es un entero positivo

**Postcondiciones:**
- `relevant_text` tiene ≤ `max_tokens * 4` caracteres
- `reduction_ratio` ∈ [0.0, 1.0]
- Si `extracted_text` está vacío → `relevant_text = ""`, `reduction_ratio = 0.0`
- Nunca lanza excepciones

---

### Componente 2: `MissionDataExtractor`

**Archivo:** `backend/app/agents/mission_data_extractor.py`

```python
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass
class ExtractionResult:
    value: Optional[str]            # None si no se encontró
    confidence: float               # 0.0 a 1.0
    source_reference: str           # "Hoja 2, fila 15" o "Página 3"
    raw_snippet: str                # fragmento exacto del texto
    extraction_status: str          # "found" | "not_found" | "ambiguous"

class MissionDataExtractor:
    """
    Extrae un dato específico de un fragmento de texto usando el LLM,
    guiado por el mission_context activo.
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    async def extract(
        self,
        relevant_text: str,
        mission_context: Dict[str, Any],
    ) -> ExtractionResult:
        ...
```

**System prompt:**
```
Eres un extractor de datos para licitaciones públicas mexicanas.
Tu tarea es encontrar UN dato específico en el texto proporcionado.

Dato a buscar: {dato_solicitado}
Contexto: {por_que_importa}

REGLAS:
1. Extrae SOLO el valor del dato solicitado.
2. Indica en qué parte del texto lo encontraste (referencia de origen).
3. Si hay múltiples valores, elige el más reciente o específico.
4. Si NO encuentras el dato: extraction_status="not_found", value=null.
5. Si hay ambigüedad: extraction_status="ambiguous", value=la opción más probable.

Responde SOLO en JSON:
{"value": "...", "confidence": 0.0-1.0, "source_reference": "...", "raw_snippet": "...", "extraction_status": "found|not_found|ambiguous"}
```

**Postcondiciones:**
- `confidence` ∈ [0.0, 1.0]
- `extraction_status` ∈ {"found", "not_found", "ambiguous"}
- Si el LLM falla → retorna `ExtractionResult` con `extraction_status="not_found"`, `confidence=0.0`
- Nunca lanza excepciones

---

### Componente 3: `NumericValidator`

**Archivo:** `backend/app/services/numeric_validator.py`

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ValidationResult:
    normalized_value: Optional[str]
    numeric_value: Optional[float]
    is_valid: bool
    validation_notes: str
    adjustment_applied: bool

@dataclass
class DistributionResult:
    is_valid: bool
    adjusted_values: List[float]
    adjustment_applied: bool
    discrepancy: float

class NumericValidator:
    """
    Valida y normaliza valores numéricos. Python puro — sin LLM.
    """
    
    # Patrones de limpieza para valores monetarios mexicanos
    # "$1,234,567.89" → 1234567.89
    # "1.234.567,89" → 1234567.89
    # "1234567" → 1234567.0
    
    def validate_and_normalize(
        self,
        raw_value: str,
        field_type: str = "text",  # "currency" | "integer" | "percentage" | "text"
    ) -> ValidationResult:
        """Nunca lanza excepciones para ningún input de string."""
        ...
    
    def validate_monthly_distribution(
        self,
        monthly_values: List[float],
        total: float,
        tolerance: float = 0.01,
    ) -> DistributionResult:
        """
        Verifica que sum(monthly_values) == total (con tolerancia).
        Si hay discrepancia, aplica ajuste proporcional al último mes.
        
        Invariante: si adjustment_applied=True,
        entonces abs(sum(adjusted_values) - total) <= tolerance
        """
        ...
```

**Postcondiciones:**
- `validate_and_normalize` nunca lanza excepciones para ningún string input
- Si `adjustment_applied=True` → `abs(sum(adjusted_values) - total) <= tolerance`
- `ValidationResult.numeric_value` es `None` si el valor no es parseable como número

---

### Componente 4: `_handle_file_upload_with_mission` en `ChatbotRAGAgent`

Nuevo método en `backend/app/agents/chatbot_rag.py`:

```python
async def _handle_file_upload_with_mission(
    self,
    session_id: str,
    doc_id: str,
    session_state: Dict[str, Any],
    pending_questions: List[Dict[str, Any]],
    current_idx: int,
    correlation_id: str,
) -> AgentOutput:
    """
    Orquesta el flujo de extracción cuando el usuario sube un archivo
    con una pregunta activa.
    
    Punto de integración: se invoca desde process() cuando se detecta
    que el mensaje del usuario contiene un doc_id recién subido Y hay
    pending_questions activas.
    """
```

**Mensaje de confirmación al usuario:**
```
Revisé tu archivo y encontré lo siguiente:

📋 **{dato_solicitado}**: {value}
📍 Origen: {source_reference}

¿Es correcto? Puedes responder:
- **Sí** para guardar este valor
- **No, el valor correcto es [X]** para corregirlo  
- **No aplica** si este dato no está en el archivo
```

**Estado persistido en `session_state`:**
```python
session_state["pending_mapping_confirmation"] = {
    "field": pending_question["field"],
    "label": pending_question["label"],
    "proposed_value": extraction_result.value,
    "source_reference": extraction_result.source_reference,
    "confidence": extraction_result.confidence,
    "question_idx": current_idx,
}
```

---

### Componente 5: `_handle_mapping_confirmation` en `ChatbotRAGAgent`

Nuevo método en `backend/app/agents/chatbot_rag.py`:

```python
async def _handle_mapping_confirmation(
    self,
    user_response: str,
    session_id: str,
    company_id: str,
    session_state: Dict[str, Any],
    correlation_id: str,
) -> AgentOutput:
    """
    Procesa la respuesta del usuario a la confirmación del mapeo propuesto.
    
    Patrones de respuesta reconocidos:
    - Confirmación: "sí", "si", "correcto", "exacto", "ok", "dale", "va"
    - Corrección: "no, es X", "no, el valor es X", "en realidad es X"
    - Rechazo: "no aplica", "no está", "no tengo", "no lo tengo"
    """
```

**Lógica de detección de intención:**
```python
@staticmethod
def _classify_confirmation_response(user_response: str) -> str:
    """
    Retorna: "confirm" | "correct" | "reject"
    """
    lo = user_response.lower().strip()
    
    CONFIRM_TOKENS = {"sí", "si", "correcto", "exacto", "ok", "dale", "va", "así es", "eso es"}
    REJECT_TOKENS = {"no aplica", "no está", "no tengo", "no lo tengo", "no existe"}
    
    if any(t in lo for t in REJECT_TOKENS):
        return "reject"
    if lo.startswith("no") and len(lo) > 5:
        return "correct"  # "no, el valor es X"
    if any(t in lo for t in CONFIRM_TOKENS):
        return "confirm"
    return "confirm"  # default: asumir confirmación si no hay señal de rechazo
```

---

## Modelos de Datos

### `pending_mapping_confirmation` (en `session_state`)

```python
{
    "field": str,               # campo del master_profile a actualizar
    "label": str,               # label legible del dato
    "proposed_value": str,      # valor extraído del archivo
    "source_reference": str,    # "Hoja 2, fila 15"
    "confidence": float,        # 0.0 a 1.0
    "question_idx": int,        # índice en pending_questions
}
```

### `ExtractionResult` (interno, no persistido)

```python
{
    "value": str | None,
    "confidence": float,
    "source_reference": str,
    "raw_snippet": str,
    "extraction_status": "found" | "not_found" | "ambiguous",
}
```

### `PreprocessResult` (interno, no persistido)

```python
{
    "relevant_text": str,
    "total_chars_original": int,
    "total_chars_filtered": int,
    "reduction_ratio": float,
    "keywords_found": List[str],
}
```

---

## Propiedades de Corrección

### Propiedad 1: DocumentPreprocessor nunca excede el límite de tokens

*Para cualquier* `extracted_text` y `dato_solicitado`, `PreprocessResult.relevant_text` tiene ≤ `max_tokens * 4` caracteres.

**Valida: Requisito 1.3**

### Propiedad 2: NumericValidator nunca lanza excepciones

*Para cualquier* string `raw_value` (incluyendo vacíos, con caracteres especiales, con formatos inválidos), `validate_and_normalize` retorna un `ValidationResult` sin lanzar excepciones.

**Valida: Requisito 3.1**

### Propiedad 3: Invariante de ajuste proporcional

*Para cualquier* lista `monthly_values` y `total`, si `DistributionResult.adjustment_applied=True`, entonces `abs(sum(adjusted_values) - total) <= tolerance`.

**Valida: Requisito 3.3**

### Propiedad 4: ExtractionResult.confidence siempre en [0.0, 1.0]

*Para cualquier* `relevant_text` y `mission_context`, `ExtractionResult.confidence` ∈ [0.0, 1.0].

**Valida: Requisito 2.2**

### Propiedad 5: PreprocessResult.reduction_ratio siempre en [0.0, 1.0]

*Para cualquier* `extracted_text` no vacío, `PreprocessResult.reduction_ratio` ∈ [0.0, 1.0].

**Valida: Requisito 1.4**

### Propiedad 6: Texto vacío produce relevant_text vacío

*Para cualquier* `dato_solicitado`, si `extracted_text=""`, entonces `PreprocessResult.relevant_text=""`.

**Valida: Requisito 1.5**

---

## Manejo de Errores

| Escenario | Comportamiento | Impacto |
|-----------|---------------|---------|
| Archivo no contiene el dato (`not_found`) | Asistente comunica que no encontró el dato y mantiene la pregunta pendiente | Sin pérdida de datos |
| LLM falla en extracción | `ExtractionResult` con `extraction_status="not_found"`, `confidence=0.0` | Asistente pide al usuario que escriba el dato manualmente |
| Valor numérico no parseable | `ValidationResult.is_valid=False`, `numeric_value=None` | Asistente muestra el valor crudo y pide confirmación |
| Archivo gigante (>500KB de texto) | `DocumentPreprocessor` trunca a `max_tokens` antes de enviar al LLM | Sin error, costo controlado |
| `pending_mapping_confirmation` ausente en `session_state` | `_handle_mapping_confirmation` retorna al flujo normal de pendientes | Sin interrupción |

**Principio de resiliencia:** Si cualquier componente falla, el flujo degrada al comportamiento anterior: el asistente pide el dato directamente al usuario en el chat.

---

## Estrategia de Testing

### Tests unitarios

- `test_preprocessor_empty_text`: texto vacío → `relevant_text=""`
- `test_preprocessor_reduction_ratio`: ratio siempre en [0.0, 1.0]
- `test_preprocessor_max_tokens_respected`: output ≤ max_tokens * 4 chars
- `test_preprocessor_keywords_scoring`: chunks con keywords del dato tienen mayor score
- `test_numeric_validator_currency_mx`: "$1,234,567.89" → 1234567.89
- `test_numeric_validator_invalid_input`: strings inválidos → `is_valid=False`, sin excepción
- `test_monthly_distribution_valid`: suma correcta → `adjustment_applied=False`
- `test_monthly_distribution_adjustment`: suma incorrecta → ajuste proporcional aplicado
- `test_extraction_result_not_found`: LLM retorna `not_found` → `value=None`
- `test_confirmation_classify_confirm`: "sí" → "confirm"
- `test_confirmation_classify_correct`: "no, es 500000" → "correct"
- `test_confirmation_classify_reject`: "no aplica" → "reject"

### Tests de propiedades (Hypothesis)

- **Propiedad 1**: `@given(st.text(), st.text(min_size=1), st.integers(min_value=100, max_value=10000))` → `len(result.relevant_text) <= max_tokens * 4`
- **Propiedad 2**: `@given(st.text())` → `validate_and_normalize` no lanza excepciones
- **Propiedad 3**: `@given(st.lists(st.floats(min_value=0, max_value=1000)), st.floats(min_value=0, max_value=10000))` → invariante de ajuste
- **Propiedad 4**: `@given(st.text(), st.text(min_size=1))` → `reduction_ratio` ∈ [0.0, 1.0]
