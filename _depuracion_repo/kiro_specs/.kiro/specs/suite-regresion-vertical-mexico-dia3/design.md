# Diseño: Día 3 — Suite de Regresión Vertical México

## Alcance

Diseño de suite de validación sectorial para `AnalystAgent` con fixtures controlados y pruebas automáticas.

Áreas objetivo:
- `backend/tests/`
- `backend/tests/fixtures/vertical_mexico/`
- soporte utilitario mínimo para cargar fixtures en tests.

## Arquitectura de pruebas

### 1) Fixtures por vertical

Estructura propuesta:

- `backend/tests/fixtures/vertical_mexico/obra_publica_case01.json`
- `backend/tests/fixtures/vertical_mexico/salud_case01.json`
- `backend/tests/fixtures/vertical_mexico/adquisiciones_case01.json`
- `backend/tests/fixtures/vertical_mexico/servicios_case01.json`

Formato sugerido por fixture:

```json
{
  "case_id": "salud_case01",
  "vertical": "salud",
  "context_text": "extracto representativo...",
  "expected": {
    "sector_id": "salud",
    "allowed_sector_ids": ["salud"],
    "required_signal_codes": ["SALUD_REG_SANITARIO", "SALUD_CARTA_APOYO_FABRICANTE"],
    "min_evidence_items": 1
  }
}
```

### 2) Test runner paramétrico

Nuevo test principal:
- `backend/tests/test_sector_vertical_mexico_suite.py`

Estrategia:
- cargar fixtures con `pytest.mark.parametrize`,
- invocar helper de clasificación sectorial (y opcionalmente `AnalystAgent.process` mockeado),
- validar expectativas por caso.

### 3) Capas de validación

#### Capa A — Clasificación sectorial pura
- función objetivo: `build_sector_classification(context, llm_data)`
- asserts:
  - `sector_id` esperado/permitido,
  - `confidence` presente,
  - evidencia con `signal_code` requerido.

#### Capa B — Contrato base del analista (smoke)
- ejecutar flujo `process` con mocks de búsqueda/LLM para asegurar:
  - campos base siguen presentes,
  - `sector_classification` coexiste sin romper salida.

## Matriz de casos (v1)

### Obra pública
- Señales mínimas:
  - `OP_ANALISIS_PRECIOS_UNITARIOS`
  - `OP_CATALOGO_CONCEPTOS`

### Salud
- Señales mínimas:
  - `SALUD_REG_SANITARIO`
  - `SALUD_CARTA_APOYO_FABRICANTE`
  - `SALUD_AVISO_FUNCIONAMIENTO`

### Adquisiciones
- Señales mínimas:
  - `ADQ_PARTIDAS`
  - `ADQ_FICHAS_TECNICAS`

### Servicios
- Señales mínimas:
  - `SER_SLA` o `SER_METODOLOGIA`

## Criterios de fallo

- `sector_id` fuera de `allowed_sector_ids`.
- ausencia total de `evidence` en caso con señal fuerte.
- falta de `signal_code` obligatorio.
- pérdida de campos base del analista.

## Reporte de salida

Formato recomendado (consola + artefacto JSON opcional):
- `case_id`
- `vertical`
- `sector_detected`
- `confidence`
- `required_signals_found`
- `status`

Esto habilita lectura ejecutiva rápida para calibración día 4.

## Riesgos y mitigaciones

- Riesgo: fixtures demasiado “fáciles”.
  - Mitigación: incluir lenguaje administrativo ruido y señales competidoras leves.

- Riesgo: falsos negativos por acentos/encoding.
  - Mitigación: variantes de texto con y sin acento en fixtures críticos.

- Riesgo: dependencia involuntaria de LLM en tests.
  - Mitigación: capa A 100% determinista y capa B con mocks controlados.
