# Demo cliente — 3 sesiones de referencia (P5-01)

Guía operativa para mostrar LicitAI estable sin sorpresas en UI. Duración estimada: **25–35 min** (3 sesiones × ~8 min).

## Antes de empezar

| Requisito | Comando / valor |
|-----------|-----------------|
| Stack levantado | `docker compose up -d` |
| Backend API | `http://127.0.0.1:8001` |
| Frontend (Vite) | `http://localhost:8504` (proxy → 8001) |
| Smoke rápido (opcional) | `docker exec licitaciones-ai-backend-1 python scripts/smoke_session_stability.py` |

Si el banner ámbar **«Artefactos desactualizados»** aparece: pulsar **Actualizar artefactos** o ejecutar `rehydrate_analysis_artifacts.py --all-reference`.

---

## Orden sugerido de la demo

1. **ISAPEG** — caso maduro, generación completa, muchos requisitos (impacto “enterprise”).
2. **UNAQ** — caso compacto, paneles ligeros rápidos.
3. **VIGILANCIA ISSSTE** — re-análisis + generación recién cerrada (`FINAL_OK`), muestra resiliencia post-estabilización.

---

## Sesión 1 — `isapeg_servicios_de_limpieza`

**Perfil:** limpieza hospitalaria · generación `FINAL_OK` · ~1 952 partidas económicas.

| Paso | Dónde en UI | Qué decir / qué validar |
|------|-------------|-------------------------|
| 1 | Selector de sesión → ISAPEG | Carga inicial: **no pantalla vacía** mientras el dictamen termina. |
| 2 | Preview / **Hitos / calendario** | **6 hitos** visibles sin esperar dictamen (API paralela P0-01). |
| 3 | Panel central **Dictamen Forense** | Zonas administrativo / técnico / formatos; conteo coherente (~349 requisitos en dictamen). |
| 4 | **Documentos detectados** | Lista corporate (~20 docs); carga lazy al abrir pestaña (P0-02). |
| 5 | **Formatos/Anexos Detectados** | Panel `sobre_1_tecnico` ≈ **16** ítems; no depende del dictamen monolítico. |
| 6 | **Preguntas para la Junta** | **4** preguntas con citas; pestaña independiente del dictamen. |
| 7 | **Logística y Expedientes** (panel derecho) | Descargas / sobres si generación previa existe. |
| 8 | Chat (opcional) | Intención HITL: corrección de dato → badge procedencia coherente con panel. |

**No mostrar:** re-análisis completo en vivo (tarda); usar solo si el cliente lo pide.

---

## Sesión 2 — `unaq-2026_paneles_solares`

**Perfil:** paneles solares · generación `FINAL_OK` · UI ligera (referencia “rápida”).

| Paso | Dónde en UI | Qué decir / qué validar |
|------|-------------|-------------------------|
| 1 | Cambiar sesión → UNAQ | Transición limpia: hitos y health sin recargar manualmente (F5 solo si cambiaste código). |
| 2 | **Hitos / calendario** | 6 hitos; fechas parseables. |
| 3 | **Documentos detectados** | ~10 corporate docs; respuesta &lt;1 s. |
| 4 | **Formatos/Anexos Detectados** | **9** formatos técnicos/administrativos (baseline panel). |
| 5 | **Preguntas para la Junta** | **3** ítems. |
| 6 | `GET /health` (opcional, terminal) | `healthy=true`, `rehydrate_recommended=false`. |

**Mensaje clave:** misma arquitectura que ISAPEG, menos volumen → ideal para validar latencia de paneles.

---

## Sesión 3 — `vigilancia_issste`

**Perfil:** vigilancia ISSSTE · SEPIMSA/Manavil · generación **`FINAL_OK`** (P4-01 cerrado).

| Paso | Dónde en UI | Qué decir / qué validar |
|------|-------------|-------------------------|
| 1 | Sesión VIGILANCIA | Tras estabilización: **hitos=6, junta=5**, sin worker colgado. |
| 2 | **Hitos / calendario** | Checklist persistido aunque cronograma en analysis esté incompleto (`checklist_at_risk` en smoke — **no bloquea UI**). |
| 3 | **Formatos/Anexos Detectados** | ~**26–31** ítems panel; incluye anexos administrativos materializados. |
| 4 | **Preguntas para la Junta** | **5** preguntas. |
| 5 | **Validaciones económicas** | 8 claves FSR / inputs usuario; propuesta económica generada. |
| 6 | **Logística y Expedientes** | Carpetas `SOBRE_1…3`, `_compranet_validated`, propuesta económica en disco. |
| 7 | Dictamen | Mediana **&lt;1 s** (antes ~50 s / recursión); mencionar fast-path P0-03. |

**Mensaje clave:** caso que rompía la UI y la generación; hoy pasa smoke 3/3 y pipeline completo.

---

## Cierre de demo (2 min)

1. Ejecutar en terminal (visible al cliente o en segunda pantalla):

```bash
docker exec licitaciones-ai-backend-1 python scripts/smoke_session_stability.py
python backend/scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001 --all-reference
```

2. Resaltar: **3/3 OK**, `FINAL_OK` en generación, paneles lazy, health + rehydrate bajo demanda.

3. Backlog honesto: re-análisis largo aún síncrono (P3-01), documentación lifecycle (P3-02).

---

## Troubleshooting en vivo

| Síntoma | Acción |
|---------|--------|
| Hitos vacíos, junta OK | F5; si persiste → **Actualizar artefactos** |
| Dictamen lento (&gt;10 s) | Verificar backend reciente; smoke P0-03 |
| Paneles vacíos | Abrir pestaña (lazy load); revisar proxy 8504→8001 |
| Generación bloqueada | Ver `stop_reason` en chat; `resume_session_generation.py <session>` |

**Checkpoint:** `checkpoint/p5-01-handoff`
