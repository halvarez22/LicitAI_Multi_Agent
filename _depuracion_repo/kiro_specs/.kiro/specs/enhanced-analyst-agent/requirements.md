# Requirements Document

## Introduction

El sistema LicitAI Multi-Agent necesita mejorar el AnalystAgent para extraer información de cualquier tipo de procedimiento de contratación en México (licitación pública, invitación restringida, adjudicación directa). El agente debe ser universal, funcionando con cualquier documento de bases de licitación sin hardcodear formatos específicos.

Esta mejora abarca tres áreas principales: solvencia técnica, condiciones contractuales, y consolidación mejorada del checklist con clasificación de requisitos.

## Glossary

- **AnalystAgent**: Agente del sistema LicitAI responsable de extraer y analizar requisitos de licitaciones a partir de documentos OCR.
- **Solvencia_Técnica**: Capacidad técnica de un licitante para ejecutar el contrato, demostrada mediante experiencia, recursos humanos, equipamiento y certificaciones.
- **Condiciones_Contractuales**: Términos legales y financieros del contrato incluyendo tipo, penalizaciones, pagos y garantías.
- **Requisito_Obligatorio**: Requisito que DEBE cumplirse para que la propuesta sea aceptada.
- **Requisito_Deseable**: Requisito que mejora la evaluación de la propuesta pero no es indispensable.
- **Requisito_Condicional**: Requisito que aplica solo bajo ciertas circunstancias específicas.
- **Procedimiento_Contratación**: Modalidad de adquisición (licitación pública, invitación restringida, adjudicación directa).
- **Base_Cláusula**: Sección numerada de las bases de licitación que especifica un requisito.
- **Checklist_Consolidado**: Lista estructurada de todos los requisitos extraídos con clasificación de prioridad.
- **Cédula_Profesional**: Documento oficial que acredita la formación académica de un profesional.
- **Carta_Referencia**: Documento emitido por un cliente anterior que certifica la experiencia del contratista.

## Requirements

### Requirement 1: Extracción de experiencia mínima en contratos similares

**User Story:** Como AnalystAgent, quiero extraer los requisitos de experiencia mínima en contratos similares para que el sistema pueda evaluar la capacidad del licitante.

#### Acceptance Criteria

1. WHEN el documento de bases contiene requisitos de experiencia, THE AnalystAgent SHALL extraer los años mínimos de experiencia requeridos.
2. WHEN el documento especifica un monto mínimo de contratos anteriores, THE AnalystAgent SHALL extraer dicho monto en la unidad monetaria especificada.
3. WHEN el documento requiere un número mínimo de contratos similares, THE AnalystAgent SHALL extraer la cantidad exacta de contratos solicitados.
4. THE AnalystAgent SHALL normalizar los valores extraídos a un formato estructurado con campos: `años_experiencia`, `monto_minimo`, `numero_contratos`, `unidad_monetaria`.
5. IF los requisitos de experiencia no aparecen en el documento, THE AnalystAgent SHALL marcar el campo correspondiente como "No especificado" en lugar de inventar valores.

---

### Requirement 2: Extracción de currículum empresarial y personal clave

**User Story:** Como AnalystAgent, quiero extraer los requisitos sobre currículum de la empresa y personal clave para identificar los recursos humanos necesarios.

#### Acceptance Criteria

1. WHEN las bases requieren presentación de currículum empresarial, THE AnalystAgent SHALL extraer la descripción de lo que debe incluir el currículum de la empresa.
2. WHEN las bases especifican personal clave requerido, THE AnalystAgent SHALL extraer la lista de posiciones o perfiles profesionales necesarios.
3. THE AnalystAgent SHALL identificar y extraer los años de experiencia específicos requeridos para cada posición de personal clave.
4. THE AnalystAgent SHALL detectar si se requieren títulos profesionales específicos para el personal clave.
5. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `curriculum_empresa_requerido` (bool), `personal_clave` (lista de objetos con `puesto`, `experiencia_años`, `titulo_requerido`).

---

### Requirement 3: Extracción de plantilla de personal técnico con certificaciones

**User Story:** Como AnalystAgent, quiero extraer los requisitos de plantilla de personal técnico incluyendo cédulas y certificaciones para evaluar la capacidad operativa.

#### Acceptance Criteria

1. WHEN las bases especifican personal técnico requerido, THE AnalystAgent SHALL extraer cada posición técnica con su cantidad de personas necesarias.
2. WHEN las bases requieren cédulas profesionales para el personal, THE AnalystAgent SHALL extraer el requisito de cédula indicando el tipo o nivel requerido.
3. WHEN las bases requieren certificaciones específicas para el personal técnico, THE AnalystAgent SHALL extraer los nombres de las certificaciones requeridas.
4. THE AnalystAgent SHALL normalizar la salida a una lista de objetos donde cada objeto contiene: `puesto`, `cantidad`, `cedula_requerida` (bool), `certificaciones` (lista).
5. IF no se especifica plantilla de personal técnico, THE AnalystAgent SHALL retornar una lista vacía con la clave `sin_requisitos_explícitos`.

---

### Requirement 4: Extracción de equipamiento e infraestructura requerida

**User Story:** Como AnalystAgent, quiero extraer los requisitos de equipamiento e infraestructura para evaluar los recursos materiales necesarios.

#### Acceptance Criteria

1. WHEN las bases mencionan equipamiento requerido, THE AnalystAgent SHALL extraer la lista de equipos o herramientas necesarias.
2. WHEN las bases especifican infraestructura física (oficinas, almacenes, plantas), THE AnalystAgent SHALL extraer los requisitos de infraestructura con ubicación y características si se especifican.
3. THE AnalystAgent SHALL extraer la cantidad o capacidad requerida para cada elemento de equipamiento cuando esté disponible.
4. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `equipamiento` (lista de objetos con `descripcion`, `cantidad`, `características`) e `infraestructura` (lista de objetos con `tipo`, `ubicacion`, `características`).

---

### Requirement 5: Extracción de normas y certificaciones requeridas

**User Story:** Como AnalystAgent, quiero extraer los requisitos de normas y certificaciones (ISO, NOM, etc.) para identificar los estándares de calidad requeridos.

#### Acceptance Criteria

1. WHEN las bases requieren certificaciones ISO, THE AnalystAgent SHALL extraer los números de norma ISO específicos (ej. ISO 9001, ISO 14001).
2. WHEN las bases requieren cumplimiento de normas NOM, THE AnalystAgent SHALL extraer las normas NOM mencionadas con su número completo.
3. THE AnalystAgent SHALL detectar otras certificaciones o normas mencionadas (NMX, ANSI, ASTM, etc.) y extraer sus identificadores exactos.
4. THE AnalystAgent SHALL indicar si las certificaciones deben estar vigentes al momento de la presentación o si pueden estar en proceso de obtención.
5. THE AnalystAgent SHALL normalizar la salida a una lista de objetos donde cada objeto contiene: `norma` (string), `tipo` (ISO/NOM/OTRA), `vigencia_requerida` (bool).

---

### Requirement 6: Extracción de contratos o cartas de referencia

**User Story:** Como AnalystAgent, quiero extraer los requisitos de contratos o cartas de referencia de trabajos previos para verificar la experiencia documentada.

#### Acceptance Criteria

1. WHEN las bases requieren contratos de trabajos previos, THE AnalystAgent SHALL extraer el número mínimo de contratos que deben presentarse.
2. THE AnalystAgent SHALL extraer el período máximo de antigüedad de los contratos que se aceptan como referencia.
3. WHEN las bases aceptan cartas de referencia en lugar de contratos, THE AnalystAgent SHALL extraer esta alternativa y sus condiciones.
4. THE AnalystAgent SHALL detectar si se requieren cartas de clientes específicos o si se aceptan cartas genéricas.
5. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `contratos_minimos`, `antigüedad_maxima_meses`, `cartas_referencia_aceptadas` (bool), `requisitos_adicionales`.

---

### Requirement 7: Extracción del tipo de contrato

**User Story:** Como AnalystAgent, quiero extraer el tipo de contrato (precio fijo, precio alzado, por administración) para entender el modelo comercial.

#### Acceptance Criteria

1. WHEN las bases especifican el tipo de contrato, THE AnalystAgent SHALL extraer el tipo exacto mencionado (precio fijo, precio alzado, por administración, tiempo y materiales, etc.).
2. THE AnalystAgent SHALL detectar menciones de "contrato abierto" versus "contrato cerrado" y clasificarlos apropiadamente.
3. IF el tipo de contrato no está explícitamente indicado, THE AnalystAgent SHALL inferirlo a partir de las reglas económicas y marcar la fuente como "inferido".
4. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `tipo_contrato`, `modalidad` (abierto/cerrado), `fuente` (explícito/inferido).

---

### Requirement 8: Extracción de penalizaciones y deducciones

**User Story:** Como AnalystAgent, quiero extraer las penalizaciones y deducciones aplicables al contrato para evaluar el riesgo financiero.

#### Acceptance Criteria

1. WHEN las bases mencionan penalizaciones por atraso, THE AnalystAgent SHALL extraer el porcentaje de penalización y el período al que aplica.
2. THE AnalystAgent SHALL extraer las deducciones específicas aplicables (por ejemplo: deducciones por incumplimiento de niveles de servicio).
3. THE AnalystAgent SHALL identificar el límite máximo de penalizaciones acumulables si está especificado.
4. THE AnalystAgent SHALL extraer las condiciones bajo las cuales se aplican las penalizaciones (días naturales vs días hábiles).
5. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `penalizacion_atraso` (porcentaje, período), `deducciones` (lista), `limite_maximo`, `condiciones_aplicación`.

---

### Requirement 9: Extracción de condiciones de pago

**User Story:** Como AnalystAgent, quiero extraer las condiciones de pago (anticipos, estimaciones, finiquito) para evaluar el flujo de efectivo requerido.

#### Acceptance Criteria

1. WHEN las bases permiten anticipo, THE AnalystAgent SHALL extraer el porcentaje máximo de anticipo autorizado.
2. THE AnalystAgent SHALL extraer los requisitos de garantía del anticipo si aplica (porcentaje de garantía requerida).
3. WHEN las bases especifican pagos por estimaciones, THE AnalystAgent SHALL extraer la periodicidad (quincenal, mensual, etc.) y el proceso de aprobación.
4. THE AnalystAgent SHALL extraer las condiciones de pago del finiquito incluyendo retenciones aplicables.
5. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `anticipo_permitido` (porcentaje), `garantia_anticipo` (porcentaje), `periodicidad_pagos`, `proceso_aprobación`, `retenciones_finiquito`.

---

### Requirement 10: Extracción de garantía de cumplimiento

**User Story:** Como AnalystAgent, quiero extraer los requisitos de garantía de cumplimiento (monto y tipo) para evaluar las garantías requeridas.

#### Acceptance Criteria

1. WHEN las bases requieren garantía de cumplimiento, THE AnalystAgent SHALL extraer el monto como porcentaje del contrato.
2. THE AnalystAgent SHALL extraer el tipo de garantía aceptada (fianza, garantía líquida, carta de crédito, etc.).
3. THE AnalystAgent SHALL identificar el plazo de presentación de la garantía después de la notificación de fallo.
4. THE AnalystAgent SHALL extraer el período de vigencia requerido de la garantía.
5. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `monto_porcentaje`, `tipo_garantía`, `plazo_presentación`, `vigencia_meses`.

---

### Requirement 11: Extracción de garantía de vicios ocultos

**User Story:** Como AnalystAgent, quiero extraer los requisitos de garantía de vicios ocultos para completar la evaluación de garantías.

#### Acceptance Criteria

1. WHEN las bases requieren garantía de vicios ocultos, THE AnalystAgent SHALL extraer el monto o porcentaje aplicable.
2. THE AnalystAgent SHALL extraer el período de garantía de vicios ocultos (típicamente 12 meses, 24 meses, etc.).
3. THE AnalystAgent SHALL identificar el tipo de garantía aceptada para vicios ocultos.
4. THE AnalystAgent SHALL normalizar la salida a un objeto con claves: `monto_porcentaje`, `tipo_garantía`, `periodo_meses`.

---

### Requirement 12: Clasificación de requisitos en el checklist

**User Story:** Como AnalystAgent, quiero clasificar cada requisito como obligatorio, deseable o condicional para facilitar la evaluación de cumplimiento.

#### Acceptance Criteria

1. THE AnalystAgent SHALL clasificar cada requisito extraído en una de tres categorías: `obligatorio`, `deseable`, o `condicional`.
2. THE AnalystAgent SHALL usar la siguiente lógica de clasificación:
   - Requisitos marcados con "deberá", "es obligatorio", "es requisito" → obligatorio
   - Requisitos marcados con "deseable", "preferible", "se valorará" → deseable
   - Requisitos con condiciones explícitas ("cuando...", "si...", "en caso de...") → condicional
3. THE AnalystAgent SHALL incluir la clasificación en cada objeto del checklist con la clave `clasificación`.
4. IF la clasificación no puede determinarse claramente, THE AnalystAgent SHALL usar "obligatorio" por defecto y marcar con `clasificación_incierta: true`.

---

### Requirement 13: Asociación de requisitos con página o cláusula de origen

**User Story:** Como AnalystAgent, quiero asociar cada requisito con su página o cláusula de origen en las bases para facilitar la verificación.

#### Acceptance Criteria

1. THE AnalystAgent SHALL identificar el número de página donde aparece cada requisito cuando esté disponible en el texto extraído.
2. THE AnalystAgent SHALL identificar el número de cláusula o inciso (ej. "Cláusula 8.3", "Inciso a)") donde se menciona el requisito.
3. THE AnalystAgent SHALL incluir en cada requisito las claves `pagina` y `cláusula` con los valores extraídos.
4. IF no es posible determinar la página o cláusula, THE AnalystAgent SHALL usar "No especificado" y registrar `fuente_localización: inferida`.
5. THE AnalystAgent SHALL mantener la trazabilidad entre el requisito extraído y su fuente original.

---

### Requirement 14: Ordenamiento del checklist por prioridad de entrega

**User Story:** Como AnalystAgent, quiero ordenar el checklist final por prioridad de entrega para que los licitantes puedan preparar primero los requisitos más críticos.

#### Acceptance Criteria

1. THE AnalystAgent SHALL ordenar los requisitos en el checklist consolidando primero los de clasificación `obligatorio`.
2. THE AnalystAgent SHALL mantener el orden dentro de cada clasificación según la siguiente prioridad:
   - Garantías (cumplimiento, vicios ocultos, anticipo)
   - Documentación legal (escrituras, poderes, RFC, INE)
   - Solvencia técnica (experiencia, personal, equipamiento)
   - Propuesta económica
   - Requisitos `deseable`
   - Requisitos `condicional`
3. THE AnalystAgent SHALL incluir un campo `orden_entrega` en cada requisito indicando su posición en el checklist ordenado.
4. THE AnalystAgent SHALL generar el checklist ordenado como parte de la salida estructurada del agente.

---

### Requirement 15: Universalidad del agente - independencia de formatos

**User Story:** Como sistema, quiero que el AnalystAgent funcione con cualquier documento de bases de licitación sin hardcodear formatos específicos.

#### Acceptance Criteria

1. THE AnalystAgent SHALL usar búsqueda semántica basada en palabras clave genéricas en lugar de formatos fijos de documentos.
2. THE AnalystAgent SHALL detectar el tipo de procedimiento de contratación (licitación pública, invitación restringida, adjudicación directa) a partir del contenido.
3. THE AnalystAgent SHALL manejar variaciones en la estructura de las bases sin asumir un orden específico de secciones.
4. THE AnalystAgent SHALL extraer información de documentos escaneados (OCR) con la misma calidad que de documentos digitales.
5. IF el documento contiene tablas, THE AnalystAgent SHALL parsear el contenido tabular correctamente identificando encabezados y filas.
6. THE AnalystAgent SHALL usar expresiones regulares solo para normalización de datos, nunca para identificar secciones del documento.

---

### Requirement 16: Consolidación de solvencia técnica en estructura unificada

**User Story:** Como AnalystAgent, quiero consolidar toda la información de solvencia técnica en una estructura unificada para facilitar su consumo por otros agentes.

#### Acceptance Criteria

1. THE AnalystAgent SHALL generar un objeto `solvencia_técnica` que contenga todos los datos extraídos de los requisitos 1 al 6.
2. THE objeto `solvencia_técnica` SHALL tener la siguiente estructura:
   ```
   {
     "experiencia_mínima": { "años": "", "monto": "", "num_contratos": "", "unidad": "" },
     "curriculum": { "empresa_requerido": bool, "personal_clave": [] },
     "plantilla_personal": [],
     "equipamiento": [],
     "infraestructura": [],
     "normas_certificaciones": [],
     "referencias": { "contratos_minimos": 0, "antigüedad_maxima": 0, "cartas_aceptadas": bool }
   }
   ```
3. THE AnalystAgent SHALL incluir metadatos de confianza para cada campo extraído (fuente, nivel de certeza).

---

### Requirement 17: Consolidación de condiciones contractuales en estructura unificada

**User Story:** Como AnalystAgent, quiero consolidar toda la información de condiciones contractuales en una estructura unificada.

#### Acceptance Criteria

1. THE AnalystAgent SHALL generar un objeto `condiciones_contractuales` que contenga todos los datos extraídos de los requisitos 7 al 11.
2. THE objeto `condiciones_contractuales` SHALL tener la siguiente estructura:
   ```
   {
     "tipo_contrato": { "modalidad": "", "fuente": "" },
     "penalizaciones": { "atraso": {}, "deducciones": [], "limite": "" },
     "pagos": { "anticipo": {}, "estimaciones": {}, "finiquito": {} },
     "garantía_cumplimiento": { "monto": "", "tipo": "", "plazo": "", "vigencia": "" },
     "garantía_vicios_ocultos": { "monto": "", "tipo": "", "periodo": "" }
   }
   ```
3. THE AnalystAgent SHALL incluir metadatos de confianza para cada campo extraído.

---

### Requirement 18: Generación del checklist consolidado final

**User Story:** Como AnalystAgent, quiero generar un checklist consolidado que incluya solvencia técnica, condiciones contractuales y todos los requisitos clasificados.

#### Acceptance Criteria

1. THE AnalystAgent SHALL generar un objeto `checklist_consolidado` que contenga la fusión de solvencia técnica y condiciones contractuales.
2. THE checklist_consolidado SHALL ser una lista de objetos donde cada objeto representa un requisito con:
   - `id`: identificador único del requisito
   - `categoría`: solvencia_técnica | condiciones_contractuales
   - `subcategoría`: experiencia | personal | equipamiento | normas | referencias | tipo_contrato | penalizaciones | pagos | garantías
   - `descripción`: texto literal del requisito
   - `clasificación`: obligatorio | deseable | condicional
   - `página`: número de página donde aparece
   - `cláusula`: número de cláusula o inciso
   - `orden_entrega`: posición en el checklist ordenado
3. THE AnalystAgent SHALL incluir el checklist_consolidado como parte de la salida estructurada del agente.
4. THE checklist_consolidado SHALL estar ordenado por `orden_entrega` de forma ascendente.