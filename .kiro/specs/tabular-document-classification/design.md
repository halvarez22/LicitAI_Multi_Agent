# Documento de Diseño: tabular-document-classification

## Visión General

Tres cambios quirúrgicos en el pipeline de generación:

1. **`ComplianceAgent`** — agregar `requiere_datos_licitante` al prompt de clasificación con ejemplos de documentos tabulares.
2. **`FormatsAgent` y `TechnicalWriterAgent`** — tratar `requiere_datos_licitante` igual que `presentar_fisico`.
3. **`ChatbotRAGAgent`** — mostrar mensaje UX empático cuando detecta documentos `requiere_datos_licitante` en el inventario.

---

## Cambio 1: ComplianceAgent — Nuevo tipo en el prompt

### Archivo: `backend/app/agents/compliance.py`

Agregar `requiere_datos_licitante` a la sección `CLASIFICACIÓN tipo_accion`:

```python
# ANTES:
- "generar": el licitante DEBE redactar y entregar este documento
- "presentar_fisico": el licitante debe presentar un documento físico existente
- "informativo": es una regla, fecha, procedimiento o descripción

# DESPUÉS (agregar):
- "requiere_datos_licitante": documento tabular/cuantitativo que requiere datos del licitante
  (cantidades, precios, plazos, programas de obra). El sistema NO puede generarlo automáticamente
  porque los números son privados del licitante. Ejemplos: programas calendarizados,
  catálogos de conceptos, explosivos de insumos, análisis de precios unitarios.
```

Agregar ejemplos al prompt:

```python
# Ejemplos nuevos a agregar:
- "AT-13 Programa calendarizado de materiales" → tipo_accion: "requiere_datos_licitante"
- "Programa calendarizado de suministro de materiales y equipo" → tipo_accion: "requiere_datos_licitante"
- "Catálogo de conceptos con cantidades y precios" → tipo_accion: "requiere_datos_licitante"
- "Explosivo de insumos" → tipo_accion: "requiere_datos_licitante"
- "Análisis de precios unitarios" → tipo_accion: "requiere_datos_licitante"
- "Programa de ejecución de obra" → tipo_accion: "requiere_datos_licitante"
- "Programa de utilización de maquinaria y equipo" → tipo_accion: "requiere_datos_licitante"
- "Tabulador de salarios" → tipo_accion: "requiere_datos_licitante"
- "Relación de maquinaria con cantidades y costos" → tipo_accion: "requiere_datos_licitante"
```

**Criterio de clasificación para el LLM:**
Un documento es `requiere_datos_licitante` si:
- Su nombre o descripción incluye palabras como: "programa calendarizado", "catálogo de conceptos", "explosivo", "análisis de precios unitarios", "programa de ejecución", "tabulador"
- Es un formato AT-* o AE-* que describe una tabla con columnas de cantidades, meses o porcentajes
- Requiere que el licitante llene números de su propia propuesta económica

---

## Cambio 2: FormatsAgent y TechnicalWriterAgent

### Archivo: `backend/app/agents/formats.py`

En la función que filtra documentos por `tipo_accion`, agregar `requiere_datos_licitante` al conjunto de tipos que se omiten de la generación:

```python
# ANTES:
if tipo_accion == "informativo" or tipo_accion == "presentar_fisico":
    continue  # no generar

# DESPUÉS:
if tipo_accion in ("informativo", "presentar_fisico", "requiere_datos_licitante"):
    continue  # no generar
```

### Archivo: `backend/app/agents/technical_writer.py`

En la función `_should_generate_document`:

```python
# ANTES:
if tipo_accion in ("informativo", "presentar_fisico"):
    return False

# DESPUÉS:
if tipo_accion in ("informativo", "presentar_fisico", "requiere_datos_licitante"):
    return False
```

---

## Cambio 3: ChatbotRAGAgent — Mensaje UX empático

### Archivo: `backend/app/agents/chatbot_rag.py`

Cuando el chatbot construye el resumen de sesión (`_build_session_resume_message`) o responde sobre el estado del inventario, detectar documentos `requiere_datos_licitante` y mostrar el mensaje de Gemini.

**Mensaje template:**

```python
_REQUIERE_DATOS_MSG = """¡Oye, aquí necesito tu ayuda! (Es muy fácil)

Revisé las reglas de la licitación y encontré el documento **{nombre_documento}**.

Este documento es una tabla donde tienes que poner qué materiales vas a usar, cuántos y en qué mes los vas a comprar. Como son los números reales de lo que vas a gastar en tu proyecto, yo no puedo inventarlos por ti (si pongo números al azar, te podrían descalificar, y no queremos eso).

**¿Qué hacemos ahora?** Tienes dos opciones muy sencillas:
- **Si ya tienes esos números:** Pégamelos aquí abajo en el chat de la forma que quieras, o sube el archivo de Excel, Word o PDF donde los tengas anotados. Yo me encargo de acomodarlos en el formato oficial.
- **Si todavía no calculas tus gastos:** No te preocupes. Sáltate este paso por ahora, sigue avanzando con los demás documentos y regresa aquí cuando tengas listos tus números.

¡Vamos juntos, vas muy bien! ¿Tienes el archivo a la mano?"""
```

Este mensaje se muestra cuando el usuario pregunta sobre el estado de los documentos o cuando el chatbot detecta documentos pendientes de tipo `requiere_datos_licitante` en el inventario.

---

## Propiedades de Corrección

### Propiedad 1: Documentos tabulares nunca se generan con contenido inventado

Para cualquier documento con `tipo_accion: "requiere_datos_licitante"`, el sistema nunca llama al LLM para generar su contenido. El documento aparece en el inventario como pendiente.

**Valida: Requisitos 1.3, 2.1, 2.2**

### Propiedad 2: Clasificación genérica — no acoplada a licitaciones específicas

La clasificación se basa en patrones de texto del nombre/descripción del documento, no en identificadores específicos de licitaciones. Aplica a cualquier licitación que contenga documentos con esos patrones.

**Valida: Requisito 1.5**

### Propiedad 3: Compatibilidad hacia atrás

Los documentos `generar`, `presentar_fisico` e `informativo` mantienen exactamente el mismo comportamiento que antes del cambio.

**Valida: Requisito 4.1, 4.2, 4.3**

---

## Estrategia de Testing

- Test unitario: `ComplianceAgent` clasifica "AT-13 Programa calendarizado" como `requiere_datos_licitante`
- Test unitario: `FormatsAgent` omite documentos `requiere_datos_licitante` de la generación
- Test unitario: `TechnicalWriterAgent` omite documentos `requiere_datos_licitante` de la generación
- Test de propiedad: Para cualquier nombre de documento tabular, la clasificación es `requiere_datos_licitante`
- Test de no-regresión: Documentos `generar` siguen generándose correctamente
