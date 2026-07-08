# Documento de Requisitos: tabular-document-classification

## Introducción

El `ComplianceAgent` clasifica los documentos requeridos en una licitación con tres tipos de acción: `generar`, `presentar_fisico` e `informativo`. El problema es que documentos tabulares cuantitativos (programas calendarizados, catálogos de conceptos, explosivos de insumos) se clasifican como `generar` y el LLM inventa contenido ficticio. Esto genera documentos incorrectos que podrían descalificar al licitante.

Este feature agrega un cuarto tipo `requiere_datos_licitante` para documentos que necesitan datos reales del licitante (cantidades, precios, plazos) que el sistema no puede inventar, y define los mensajes UX que el chatbot muestra al usuario cuando detecta estos documentos.

## Glosario

- **tipo_accion**: Campo que clasifica cada documento requerido en las bases. Valores actuales: `generar`, `presentar_fisico`, `informativo`.
- **requiere_datos_licitante**: Nuevo tipo de acción para documentos tabulares cuantitativos que el sistema no puede generar sin datos del licitante.
- **Documento tabular**: Documento que consiste principalmente en una tabla con columnas de cantidades, precios, plazos o porcentajes que el licitante debe llenar con sus propios datos de propuesta.
- **Documento declarativo**: Documento de texto (carta, manifiesto, declaración) que el sistema puede generar con datos del perfil de la empresa.

---

## Requisitos

### Requisito 1: Nueva clasificación `requiere_datos_licitante` en el ComplianceAgent

**User Story:** Como sistema LicitAI, quiero clasificar correctamente los documentos tabulares para no inventar contenido ficticio que pueda descalificar al licitante.

#### Criterios de Aceptación

1. CUANDO el `ComplianceAgent` analiza las bases y detecta un documento con nombre o descripción que coincide con patrones de documentos tabulares cuantitativos, EL sistema SHALL asignar `tipo_accion: "requiere_datos_licitante"`.
2. Los patrones que identifican documentos tabulares incluyen: "programa calendarizado", "catálogo de conceptos", "explosivo de insumos", "análisis de precios unitarios", "programa de ejecución", "programa de utilización de maquinaria", "tabulador de salarios", y cualquier formato AT-* o AE-* que sea tabla con columnas de cantidades/meses/porcentajes.
3. CUANDO un documento tiene `tipo_accion: "requiere_datos_licitante"`, EL sistema SHALL NOT intentar generarlo con el LLM.
4. CUANDO un documento tiene `tipo_accion: "requiere_datos_licitante"`, EL sistema SHALL incluirlo en el inventario documental como pendiente con estado "en_espera_datos".
5. La clasificación SHALL ser genérica — aplica a cualquier licitación, no solo a licitaciones específicas.

### Requisito 2: Tratamiento correcto en FormatsAgent y TechnicalWriterAgent

**User Story:** Como sistema LicitAI, quiero que los documentos `requiere_datos_licitante` se traten igual que `presentar_fisico` en el pipeline de generación.

#### Criterios de Aceptación

1. CUANDO `FormatsAgent` procesa documentos, EL sistema SHALL tratar `requiere_datos_licitante` igual que `presentar_fisico` — omitir de la generación automática.
2. CUANDO `TechnicalWriterAgent` procesa documentos, EL sistema SHALL tratar `requiere_datos_licitante` igual que `presentar_fisico` — omitir de la generación automática.
3. EL sistema SHALL incluir los documentos `requiere_datos_licitante` en el conteo de documentos pendientes del inventario.

### Requisito 3: Mensajes UX empáticos en el chatbot

**User Story:** Como usuario sin experiencia en licitaciones, quiero que el asistente me explique claramente qué documentos necesito preparar yo mismo, sin tecnicismos y con un tono de apoyo.

#### Criterios de Aceptación

1. CUANDO el chatbot detecta documentos `requiere_datos_licitante` en el inventario, EL chatbot SHALL mostrar un mensaje empático que explique en lenguaje cotidiano qué es el documento y por qué el sistema no puede generarlo automáticamente.
2. EL mensaje SHALL ofrecer dos opciones claras: proporcionar los datos ahora (pegando en el chat o subiendo un archivo) o saltarse el paso para después.
3. EL mensaje SHALL usar lenguaje cotidiano sin tecnicismos: "la lista de tus gastos y compras" en lugar de "datos cuantitativos de la propuesta económica".
4. EL mensaje SHALL incluir el nombre específico del documento detectado.
5. EL mensaje SHALL transmitir apoyo y no generar pánico: "¡Vamos juntos, vas muy bien!"

### Requisito 4: Preservación de invariantes

**User Story:** Como desarrollador de LicitAI, quiero que el cambio no rompa ningún flujo existente.

#### Criterios de Aceptación

1. Los documentos con `tipo_accion: "generar"` (cartas, manifiestos, declaraciones) SHALL seguir generándose automáticamente sin cambios.
2. Los documentos con `tipo_accion: "presentar_fisico"` SHALL seguir comportándose igual.
3. Los documentos con `tipo_accion: "informativo"` SHALL seguir comportándose igual.
4. EL sistema SHALL mantener compatibilidad hacia atrás — sesiones existentes con documentos ya clasificados no se ven afectadas.
