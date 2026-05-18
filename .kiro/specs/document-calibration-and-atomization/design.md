# Diseño: Calibración Documental y Atomización de Domicilio

## Alcance
Diseño técnico en dos bloques independientes:
- **Bloque A:** Filtro anti-ruido para clasificación documental.
- **Bloque B:** Atomización robusta de domicilio fiscal.

## Componentes a modificar
- `backend/app/agents/compliance.py`
- `backend/app/services/document_candidate_list_service.py`
- `backend/app/api/v1/routes/companies.py`
- `backend/app/utils/address_parser.py` (nuevo)

## Arquitectura propuesta

### A) Filtro de relevancia documental (anti-ruido)
1. **Capa determinista previa**
   - Reglas de exclusión por patrones normativos/informativos.
   - Reglas de inclusión por señales de entregable (anexo, formato, carta, propuesta, constancia, etc.).
2. **Capa de clasificación existente**
   - Se mantiene clasificación `generar|presentar_fisico|informativo`.
3. **Post-procesamiento en candidate list**
   - Revisión de consistencia por `tipo_accion`, confianza y evidencia.
   - Items débiles se conservan como `informativo` o `unresolved` para HITL, evitando sobre-generación.

### B) Pipeline de atomización de domicilio
1. **Entrada**
   - `domicilio_fiscal` texto libre.
2. **Parser determinista**
   - Extracción por patrones (CP, estado, municipio/alcaldía, colonia, número interior/exterior).
3. **Fallback controlado (opcional)**
   - Solo si el parser falla y con límites de costo.
4. **Salida**
   - Persistencia de `direccion_estructurada` junto al campo original.
   - Si hay ambigüedad, se marca pendiente de confirmación.

## Precedencia canónica de datos
- `override_usuario > documento_normalizado > valor_original`.
- Ninguna capa inferior puede sobreescribir un override confirmado.

## Contrato de datos propuesto
```json
{
  "domicilio_fiscal": "AVENIDA CAMPANARIO 99 PLAZA 99 DEP 23D ... CP 76146",
  "direccion_estructurada": {
    "calle": "AVENIDA CAMPANARIO",
    "numero_exterior": "99",
    "numero_interior": "DEP 23D",
    "colonia": "HACIENDA EL CAMPANARIO",
    "municipio_alcaldia": "QUERETARO",
    "estado": "QUERETARO",
    "cp": "76146"
  },
  "direccion_estructurada_meta": {
    "source": "document_normalized",
    "confidence": 0.9,
    "needs_human_confirmation": false
  }
}
```

## Observabilidad y trazabilidad
- Persistir metadatos de clasificación y de parseo de domicilio en sesión/API.
- Exponer señal de ambigüedad para activar HITL puntual.

## Riesgos y mitigaciones
- **Falsos negativos documentales**
  - Mitigar con lista de exclusión conservadora y cobertura de evidencias.
- **Atomización incompleta**
  - Mantener `domicilio_fiscal` original y escalar a confirmación humana.
- **Impacto en latencia**
  - Priorizar determinístico; fallback LLM solo bajo condiciones controladas.
