# Diseño: Preservación `tipo_accion` y filtro de generación

## Decisión central

No se introduce un modelo Pydantic nuevo en esta iteración; se endurece el contrato sobre el dict actual para minimizar riesgo de regresión:

- Campo obligatorio lógico: `tipo_accion` (`generar|presentar_fisico|informativo|unknown`).
- Campo complementario: `categoria_sugerida`.
- Campo complementario: `action_confidence` (`0..1`).

## Cambios por componente

### ComplianceAgent (`compliance.py`)
- `_normalize_item`:
  - conserva `tipo_accion` del `raw`;
  - valida y normaliza catálogo de valores;
  - agrega `categoria_sugerida` y `action_confidence`.
- `_reduce_zone_items`:
  - acumula histograma `tipo_accion` para auditoría.

### TechnicalWriter (`technical_writer.py`)
- `_is_technical_writable`:
  - respeta contrato por acción;
  - heurística solo para `unknown`.
- `process`:
  - computa métricas de distribución de acciones para trazabilidad.

### Formats (`formats.py`)
- Filtro de requisitos:
  - ruta principal por `tipo_accion`;
  - exclusión explícita `informativo|presentar_fisico`;
  - fallback heurístico únicamente para `unknown`.
- Incluye resumen de acciones en `result_data`.

## Verificación

- Test unitario de `ComplianceAgent._normalize_item`:
  - preserva `tipo_accion=generar`;
  - normaliza valor inválido a `unknown`.
