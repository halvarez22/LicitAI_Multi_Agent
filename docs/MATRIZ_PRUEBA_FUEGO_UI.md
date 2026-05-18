# Matriz de Prueba de Fuego UI (E2E)

## Objetivo

Validar de forma integral que el sistema funciona de punta a punta bajo flujo real de operación:

1. Crear licitación.
2. Cargar bases y anexos.
3. Analizar bases.
4. Seleccionar empresa.
5. Aceptar riesgos.
6. Generar propuestas.

Durante la prueba, cuando falte información, se permite usar **datos sintéticos/inventados** para completar el flujo y evaluar comportamiento total del sistema.

## Regla operativa clave

- Todo dato inventado para pruebas debe marcarse como **sintético** en observaciones.
- Ningún resultado de esta batería se considera válido para envío legal/productivo.

---

## Criterios de aceptación (macro)

- Extracción de texto: completa y sin omisiones críticas.
- RAG: indexación y recuperación útiles, consistentes y trazables.
- Detección de formatos: correcta (ni faltantes ni sobre-generación).
- Solicitud de faltantes: mínima, clara y suficiente.
- Generación documental: solo documentos requeridos y correctamente llenados.
- Trazabilidad: cada bloqueo/decisión con evidencia explicable.

---

## Matriz por etapa del flujo UI

## Etapa 1 — Crear licitación

**Qué validar**
- Se crea sesión sin errores.
- ID/sesión persisten correctamente.

**Evidencia**
- Captura de UI con sesión creada.
- ID de sesión visible.

**Resultado esperado**
- Estado listo para carga documental.

---

## Etapa 2 — Carga de bases y anexos

**Qué validar**
- Ingesta de archivos completa (PDF/DOCX/XLSX/TXT según aplique).
- No hay pérdidas ni archivos “fantasma”.
- OCR/parse inicial ejecuta sin error fatal.

**Evidencia**
- Lista de fuentes en UI.
- Conteo de documentos cargados vs esperados.

**Resultado esperado**
- 100% de archivos esperados disponibles para análisis.

---

## Etapa 3 — Analizar bases

**Qué validar**
- Extracción de texto relevante (cronograma, requisitos, reglas económicas, alcance).
- Clasificación sectorial consistente.
- Señales y evidencias literales presentes.

**Evidencia**
- Resultado del dictamen en UI.
- Campos clave extraídos.
- Evidencias/snippets donde aplique.

**Resultado esperado**
- Análisis utilizable para las siguientes etapas (sin “vacíos” críticos no detectados).

---

## Etapa 4 — Seleccionar empresa

**Qué validar**
- Perfil maestro se aplica correctamente (RFC, razón social, representante, etc.).
- No hay mezcla de datos entre empresas/sesiones.

**Evidencia**
- Empresa seleccionada en UI.
- Datos corporativos reflejados en paneles/flujo.

**Resultado esperado**
- Contexto empresarial consistente para generación documental.

---

## Etapa 5 — Aceptar riesgos

**Qué validar**
- Riesgos y validaciones se muestran con severidad correcta.
- Acciones de usuario (aceptar/justificar) se registran.
- Revalidación posterior respeta estado actualizado.

**Evidencia**
- Alertas en UI con `error_type`.
- Registro de acción del usuario.

**Resultado esperado**
- Riesgos gestionados y trazables sin inconsistencias.

---

## Etapa 6 — Generar propuestas

**Qué validar**
- Se generan solo documentos detectados como requeridos.
- No hay sobre-generación ni duplicados injustificados.
- Fill Quality Gate actúa correctamente (bloquea lo crítico, no molesta por ruido).
- Documentos salen con datos correctos del usuario (o sintéticos cuando se haya decidido así).

**Evidencia**
- Lista final de documentos generados.
- Revisión de contenido (campos críticos).
- Eventos de validación/bloqueo si ocurren.

**Resultado esperado**
- Paquete final coherente, completo y trazable.

---

## Casos transversales obligatorios

1. **Dato faltante real**
- Esperado: sistema pregunta faltante de forma clara y accionable.

2. **Dato sintético inyectado para completar prueba**
- Esperado: el flujo continúa y permite concluir E2E.
- Registrar que el dato fue inventado.

3. **Caso de bloqueo por calidad documental**
- Esperado: bloqueo explícito con acción sugerida y revalidación posible.

4. **Caso económico con consistencia numérica**
- Esperado: no ruido excesivo si subtotal+iva=total y no hay placeholders.

5. **Placeholder intencional**
- Esperado: bloqueo o alerta crítica según política vigente.

---

## Plantilla de registro por corrida

Usar esta tabla por cada licitación probada:

| Campo | Valor |
|---|---|
| ID de corrida | |
| Fecha/hora | |
| Vertical (obra/salud/adq/servicios/otro) | |
| Sesión | |
| Empresa | |
| ¿Se usaron datos sintéticos? | Sí/No |
| Etapa con incidencias | |
| Resumen de hallazgos | |
| Evidencias (capturas/rutas) | |
| Dictamen de corrida | GO / GO condicionado / NO GO |

---

## Criterio final de dictamen

- **GO**: sin fallos críticos; trazabilidad completa; generación correcta.
- **GO condicionado**: flujo completo logrado, pero con hallazgos no bloqueantes a corregir.
- **NO GO**: fallo crítico en extracción, RAG, detección, solicitud de faltantes o generación final.

---

## Nota para ejecución conjunta

Cuando durante la sesión de prueba me pidas inventar datos para avanzar, responderé con valores sintéticos coherentes y etiquetados para no contaminar conclusiones de negocio/legal.
