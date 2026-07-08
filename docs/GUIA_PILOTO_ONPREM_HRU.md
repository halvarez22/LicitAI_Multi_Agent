# Guía piloto on-premise HRU (1 página)

**Versión:** 1.1.0 · **Alcance:** F0–F10 · **Normativa:** [`SPEC_DUAL_STREAM_GENERATION_AND_CHAT_COPILOT_COMPLETO_HRU.md`](SPEC_DUAL_STREAM_GENERATION_AND_CHAT_COPILOT_COMPLETO_HRU.md)

---

## Antes de empezar

1. Empresa seleccionada en el menú superior (RFC y perfil completos).
2. Bases PDF subidas en **Fuentes** → **ANALIZAR BASES** completado.
3. Flags piloto recomendados (ver [`DEPLOY_HARDENING_PLAYBOOK.md`](../DEPLOY_HARDENING_PLAYBOOK.md) §8–§9).

---

## Flujo 1 — Cotizar conversando (copiloto económico)

| Paso | Acción | Qué verificar |
|------|--------|---------------|
| 1 | Tras el análisis, lee el mensaje del chat (≤3 líneas + 1 CTA) | Conteo de precios pendientes, sin códigos `MISSING_*` |
| 2 | Responde en lenguaje natural: *«Zona A 45,250 mensual»* | Confirmación con **totales actualizados** (F8) |
| 3 | Opcional: pega bloque TSV desde Excel | Misma verdad canónica que chat |
| 4 | Pregunta *«cuántos precios faltan»* | Tabla/resumen en `economic_capture_v1` |
| 5 | Pulsa **ECONÓMICA** o escribe *«generar propuesta económica»* | Archivos en logística / sobre 3 |

**Procedencia:** en matriz o panel económico debe verse si el precio vino de **chat**, **Excel** o **catálogo**.

---

## Flujo 2 — Completar técnica conversando (copiloto técnico)

| Paso | Acción | Qué verificar |
|------|--------|---------------|
| 1 | Tras análisis, lee slots técnicos pendientes | Mensaje ≤3 líneas, sin jerga interna |
| 2 | Captura con prefijo: *«metodologia: …»*, *«personal: …»* | Confirmación + siguiente slot sugerido |
| 3 | Pregunta *«cómo vamos técnica y económica»* | Estado dual unificado (F9) |
| 4 | Pulsa **TÉCNICA** o *«generar propuesta técnica»* | Cola técnica activa; económica omitida si modo parcial |

**Procedencia:** cada slot técnico debe mostrar `provenance_ui` (canal chat).

---

## Flujo 3 — Streams paralelos (técnica + económica, F6)

| Paso | Acción | Qué verificar |
|------|--------|---------------|
| 1 | Completa capturas chat (flujos 1 y 2) | `capture_complete` en ambos copilotos |
| 2 | Lanza **TÉCNICA** y **ECONÓMICA** en paralelo | Banner de generación paralela en UI |
| 3 | Revisa **GenerationQueuePanel** | Dos streams; jobs del otro modo = *Omitida* |
| 4 | Descarga ZIP / manifiesto | Banner *Expediente parcial* si faltan sobres |

**Completo:** usa **GENERAR COMPLETO** cuando ambos equipos estén listos y el portal exija ZIP íntegro.

---

## Smoke en VM cliente

```powershell
cd backend
$env:PYTHONPATH='.'
python scripts/smoke_pilot_onprem_hru.py
# Opcional con API levantada:
$env:PILOT_API_BASE='http://127.0.0.1:8001/api/v1'
python scripts/smoke_pilot_onprem_hru.py
```

Criterio de pase: `SMOKE OK: pilot on-premise F10 (HRU suite F0–F10)`.

Sign-off: [`PILOT_SIGNOFF_CHECKLIST.md`](PILOT_SIGNOFF_CHECKLIST.md)
