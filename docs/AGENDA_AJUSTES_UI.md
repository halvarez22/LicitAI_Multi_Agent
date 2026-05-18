# Agenda de ajustes (UI / producto)

Lista priorizable de mejoras acordadas en conversación; implementación pendiente.

**Plan técnico detallado (contraste / revisión):** [`PLAN_AJUSTES_UI_TECNICO_GEMINI.md`](./PLAN_AJUSTES_UI_TECNICO_GEMINI.md)

---

## 1. Hitos del procedimiento — panel colapsable (acordeón)

**Problema:** El bloque se percibe recortado (altura máxima + scroll), el título compite con el badge de porcentaje y **clic en la cabecera no hace nada** (no hay affordance de expandir/contraer).

**Objetivo:**

- Convertir `SubmissionChecklistPanel` en **lista / panel desplegable** (acordeón).
- **Clic en cabecera** = abrir / cerrar; estado visual claro (chevron, `aria-expanded`).
- **Cerrado:** mostrar al menos título + **% listo** (opcional: conteo de hitos pendientes).
- **Abierto:** checklist completo con scroll interno razonable o altura mayor solo al expandir.
- Accesibilidad: teclado (Enter/Espacio en cabecera si aplica), foco visible.

**Referencia técnica:** `frontend/src/components/SubmissionChecklistPanel.jsx`

---

## 2. Actas y aclaraciones — mismo patrón colapsable

**Problema:** Con borrador / contexto de acta el panel **crece** y compite con el resto de la vista; conviene **coherencia** con el gesto de Hitos (cabecera = desplegar).

**Objetivo:**

- `PostClarificationPanel` como **acordeón** alineado con Hitos.
- **Sin datos aún:** cabecera + mensaje breve (subir PDF en Fuentes); puede ir cerrado por defecto.
- **Con datos (acta procesada, borrador, avisos):** **cerrado por defecto** con **resumen** en cabecera (ej. tipo de junta, “borrador listo”, aviso de revisión humana si baja confianza); al expandir, controles y texto completos.
- Botones **Procesar acta** / **Regenerar** visibles en modo expandido (o resumen + “expandir para acciones” según diseño final).

**Referencia técnica:** `frontend/src/components/PostClarificationPanel.jsx`

---

## 3. Validaciones económicas — panel colapsable (acordeón)

**Problema:** Cuando ya hay resultado (lista de reglas OK/WARN/BLOCKING, alertas, perfil usado), el bloque **ocupa mucho vertical**; sin datos el mensaje “No hay validaciones…” también fija altura. Falta **coherencia** con Hitos y Actas (misma metáfora: cabecera = desplegar).

**Objetivo:**

- `EconomicValidationPanel` como **acordeón** alineado con los otros dos paneles.
- **Cerrado:** cabecera **Validaciones económicas** + **resumen** (ej. “OK / WARN / BLOCKING” en una línea, o “Sin datos — generar propuesta o refrescar”) + botón **refrescar** accesible según diseño (cabecera o siempre visible como icono pequeño).
- **Abierto:** detalle completo (perfil, lista, bloqueos, alertas) y scroll interno si hace falta.
- **Con bloqueos:** valorar **resumen en rojo** en cabecera cerrada (“N bloqueantes”) para que no pase desapercibido sin abrir.

**Referencia técnica:** `frontend/src/components/EconomicValidationPanel.jsx`

---

## 4. Logística y Expedientes (`DeliveryPanel`) — copys y claridad

**Contexto:** Mensajes vacíos (“no hay archivos”, checklist sin poblar) y valores por defecto en **Modalidad de entrega** (lugar “Ver Guía PDF”, horario `09:00 - 15:00`, límite “Consultar bases”) pueden leerse como **datos oficiales** cuando son **placeholders** o ausencia de dato inferido.

**Objetivo:**

- ~~**Corregir typo** en UI: “Generacción” → **“Generación”**~~ **Hecho en código** (`DeliveryPanel.jsx`, 2026-04-23). Mantener chequeo CI `rg Generacción frontend` → 0 coincidencias.
- **Etiquetar explícitamente** cuando un valor es **genérico de respaldo** (ej. horario por defecto) vs. dato **extraído de bases**; evitar que el usuario confíe en horario/límite sin verificación en PDF/bases.
- Opcional: línea de **descargo** bajo la tarjeta de modalidad (“Confirmar siempre en convocatoria / bases oficiales”) alineado con gobernanza HITL.

**Referencia técnica:** `frontend/src/components/DeliveryPanel.jsx`

**Progreso 2026-04-23:** constantes `FALLBACK_*`, etiqueta indicativa y descargo en `DeliveryPanel.jsx` aplicados. Informe: `docs/REPORTE_EJECUTIVO_SPRINT_UI.md`.

---

## 5. Actas / Validaciones / Orquestación (acordeón + D1) — hecho

Implementado en sprint: `PostClarificationPanel`, `EconomicValidationPanel`, `Dashboard` (colapsar orquestación + auto-expand al analizar). Ver `docs/REPORTE_EJECUTIVO_SPRINT_UI.md` y `docs/instrucciones_cursor_sprint_ui.md`.

---

## 6. Cargador de archivos (Fuentes) — porcentaje de avance real — **hecho**

**Implementado (2026-04-23):** `handleFileUpload` en `frontend/src/App.jsx` usa `onUploadProgress` en el `POST` a `/upload/upload`; el overlay `auditProgress` muestra **0–99%** durante la subida, **100%** con mensaje de subida completa, luego **Extrayendo…** (45%) y éxito (90%). Se limpia el valor del `input` file al terminar la cola.

---

## 7. Empresas (`CompaniesManager`) — doble diálogo al subir CIF / Acta — **corregido 2026-04-27**

**Problema:** Al elegir archivo y aceptar, el selector parecía **relanzarse**; a la segunda selección sí subía. Afectaba CIF y Acta constitutiva.

**Causa:** La tarjeta tenía `onClick={handleFileUploadRequest}` en el contenedor **y** el botón «SUBIR DOC» llamaba otra vez a la misma función; el evento **subía** (`bubble`) → **`fileInput.click()` dos veces** seguidas.

**Corrección:** `e.stopPropagation()` en el botón + `type="button"`. Archivo: `frontend/src/components/CompaniesManager.jsx`.

---

*Última actualización: 2026-04-27*
