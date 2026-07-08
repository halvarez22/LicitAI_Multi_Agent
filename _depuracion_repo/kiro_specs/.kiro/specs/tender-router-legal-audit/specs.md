# Specs: Tender Router and Legal Audit

## 1. Objetivo
Resolver la imprecisión del `ComplianceAgent` al clasificar documentos obligatorios como "informativos". Se busca transformar el agente de un lector pasivo a un **Perito Auditor** que valida contra un marco normativo específico.

## 2. Requerimientos Funcionales
- **RF1 - Triage Normativo:** Identificación automática de Ley Aplicable, Jurisdicción y Categoría.
- **RF2 - Matriz de Obligatorios (Must-Haves):** Lista predefinida de documentos obligatorios por marco normativo.
- **RF3 - Clasificación Determinista:** Clasificación forzada de "Must-Haves" como acción de generación/presentación.
- **RF4 - Auditoría de Reglas Críticas:** Extracción de reglas de negocio específicas (ej: decimales).

## 3. Criterios de Aceptación
- Detección correcta de la Ley de Querétaro en el PDF UNAQ.
- Reducción de falsos informativos.
- Alerta sobre documentos obligatorios omitidos.
