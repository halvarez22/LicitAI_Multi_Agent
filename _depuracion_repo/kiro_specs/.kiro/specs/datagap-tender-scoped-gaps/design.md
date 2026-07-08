# Diseño técnico: DataGap con conjunto activo acotado

## Decisión

**Conjunto activo** `active_fields` = orden estable:

1. `sorted(BLOCKING_FIELDS)`
2. `sorted(mapped_inferred_slots)` excluyendo duplicados

Donde `mapped_inferred_slots` se construye igual que hoy: unión de slots por requisito en `compliance_master_list` (administrativo + técnico), inferidos con caché por `req.id`, mapeados con `INFERRED_TO_PROFILE_MAP`.

**Eliminado:** semilla `list(FIELD_DEFINITIONS.keys())`.

## Contrato de salida

Sin cambios en forma de `missing[]` (`field`, `label`, `question`, `document_hint`, `type`, `is_blocking`) ni en `missing_blocking`, `auto_filled`, `AgentStatus`.

## Precedencia y datos

| Fuente | Rol |
|--------|-----|
| `master_profile` (DB / `company_data`) | Valor a validar |
| `compliance_master_list` | Texto para inferir slots por requisito |
| `BLOCKING_FIELDS` | Siempre en el conjunto activo |
| `FIELD_DEFINITIONS` | Metadatos de pregunta/RAG solo para claves que entren en `active_fields` |

## Impacto

- **`data_gap.py`:** único cambio de lógica de alcance (construcción de `active_fields`).
- **Tests:** expectativas que asumían faltantes “globales” sin compliance deben alinearse; tests que validan inferencia desde compliance se mantienen; nuevos casos para “sin slot → no pregunta campo informativo”.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|------------|
| Requisito mal inferido → no se pide un dato que sí hace falta | Mejorar `slot_inference` o texto en compliance; no reabrir checklist global sin criterio |
| Lista de compliance vacía al correr DataGap | Solo bloqueantes; resto queda para captura fuera de flujo o re-ejecución tras analyst |

## Logging

Mensaje de log actualizado para dejar claro “bloqueantes + inferidos desde compliance”.
