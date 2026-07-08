# Documento de Requisitos

## Introducción

LicitAI debe generar automáticamente el paquete completo de documentos necesarios para participar en una licitación pública mexicana, una vez que el usuario ha completado su expediente y el Semáforo Go/No-Go ha sido autorizado. El sistema utiliza los agentes existentes (TechnicalWriterAgent, FormatsAgent, EconomicWriterAgent, DocumentPackagerAgent, CompraNetPackager, DeliveryAgent) para producir documentos en formato DOCX/XLSX con logo corporativo, datos fiscales, firma del representante legal y todos los elementos requeridos por las bases. El resultado final es un paquete descargable desde la UI, organizado en sobres (técnico, económico, administrativo), con carátulas y un checklist de verificación.

## Glosario

- **Pipeline_Generacion**: Secuencia de agentes del orquestador en modo `generation_only` o `full` que produce todos los documentos de la propuesta.
- **Expediente_Completo**: Estado de sesión donde el master_profile tiene todos los campos obligatorios y la propuesta económica ha sido calculada por EconomicAgent.
- **Go_No_Go_Autorizado**: Condición en la que el usuario ha confirmado participación tras el semáforo (campo `go_no_go_override.authorized_by == "user"` en el estado de sesión).
- **TechnicalWriterAgent**: Agente que genera la propuesta técnica en DOCX (carta de presentación + documentos por requisito técnico).
- **FormatsAgent**: Agente que genera documentos administrativos y formatos obligatorios (declaraciones, manifiestos, anexos) usando templates Jinja2 con verificación de integridad.
- **EconomicWriterAgent**: Agente que genera la propuesta económica (Excel de precios, Anexo AE, Carta Compromiso) a partir de los ítems calculados por EconomicAgent.
- **DocumentPackagerAgent**: Agente que organiza los documentos en carpetas de sobres y genera carátulas DOCX.
- **CompraNetPackager**: Componente que valida extensiones, renombra archivos con nomenclatura canónica y genera manifiesto SHA-256.
- **DeliveryAgent**: Agente que genera la guía de entrega y el checklist final en PDF.
- **Sobre_Tecnico**: Carpeta `SOBRE_2_TECNICO/` con propuesta técnica y documentos técnicos.
- **Sobre_Economico**: Carpeta `SOBRE_3_ECONOMICO/` con propuesta económica.
- **Sobre_Administrativo**: Carpeta `SOBRE_1_ADMINISTRATIVO/` con documentos administrativos y formatos.
- **Caratula_Sobre**: Documento DOCX generado por DocumentPackagerAgent con título del sobre, datos de la licitación, empresa, RFC, representante e índice de contenido.
- **Checklist_Final**: Documento PDF generado por DeliveryAgent con la lista de todos los documentos generados, su estado y las instrucciones de entrega.
- **Master_Profile**: Perfil maestro de la empresa con campos: `razon_social`, `rfc`, `representante_legal`, `domicilio_fiscal`, `tipo` (moral/física), `logo` (ruta al archivo de imagen).
- **WAITING_FOR_DATA**: Estado `AgentStatus.WAITING_FOR_DATA` que retorna un agente cuando faltan datos obligatorios del Master_Profile para generar un documento.
- **Session_ID**: Identificador único de la sesión que corresponde al número/nombre de la licitación y define la ruta de salida `/data/outputs/{session_id}/`.
- **Numero_Licitacion**: Identificador oficial de la licitación (ej. `LA-050GYR019-E123-2024`) extraído de las bases por TechnicalWriterAgent vía RAG.

---

## Requisitos

### Requisito 1: Activación del Pipeline de Generación

**User Story:** Como usuario de LicitAI, quiero que la generación de documentos se active automáticamente cuando mi expediente esté completo y haya autorizado la participación, para no tener que iniciar el proceso manualmente.

#### Criterios de Aceptación

1. WHEN el usuario confirma participación en el Semáforo Go/No-Go, THE Pipeline_Generacion SHALL activarse en modo `generation_only` con todos los agentes de generación en la cola de jobs.
2. WHILE el campo `go_no_go_override.authorized_by` sea distinto de `"user"` en el estado de sesión, THE Pipeline_Generacion SHALL rechazar la ejecución de los agentes de generación y retornar estado `go_no_go_pending`.
3. WHEN el Pipeline_Generacion se activa, THE Orquestador SHALL verificar que el Expediente_Completo esté disponible antes de invocar a TechnicalWriterAgent, FormatsAgent y EconomicWriterAgent.
4. IF el Master_Profile no contiene los campos `razon_social`, `rfc` o `representante_legal`, THEN THE Pipeline_Generacion SHALL retornar estado `WAITING_FOR_DATA` con la lista de campos faltantes antes de generar cualquier documento.
5. WHEN el Pipeline_Generacion se ejecuta en modo `generation_only`, THE Orquestador SHALL reutilizar los resultados de análisis y compliance ya persistidos en `tasks_completed` sin volver a ejecutar esas etapas.

---

### Requisito 2: Generación de la Propuesta Técnica

**User Story:** Como licitante, quiero que LicitAI genere automáticamente mi propuesta técnica completa en DOCX, para presentarla en el sobre técnico sin redactar cada documento manualmente.

#### Criterios de Aceptación

1. WHEN TechnicalWriterAgent se ejecuta, THE TechnicalWriterAgent SHALL generar un archivo DOCX de Carta de Presentación como primer documento de la propuesta técnica.
2. WHEN TechnicalWriterAgent se ejecuta, THE TechnicalWriterAgent SHALL generar un archivo DOCX por cada requisito técnico identificado por ComplianceAgent en la zona `tecnico` de la lista maestra.
3. THE TechnicalWriterAgent SHALL incluir en el encabezado de cada DOCX el logo corporativo (si existe en Master_Profile), el Numero_Licitacion y la fecha de generación.
4. THE TechnicalWriterAgent SHALL incluir en el pie de página de cada DOCX la razón social, RFC y domicilio fiscal del Master_Profile.
5. THE TechnicalWriterAgent SHALL incluir al final de cada DOCX el bloque de firma con nombre del representante legal, línea de firma y cargo "REPRESENTANTE LEGAL".
6. THE TechnicalWriterAgent SHALL guardar todos los archivos en la carpeta `/data/outputs/{session_id}/1.propuesta tecnica/` con nomenclatura `{orden:02d}_{req_id}_{nombre_corto}.docx`.
7. IF la lista de requisitos técnicos está vacía, THEN THE TechnicalWriterAgent SHALL retornar estado `SUCCESS` con mensaje informativo sin generar archivos de requisitos (solo la carta de presentación).
8. WHEN el logo especificado en Master_Profile no existe en disco, THE TechnicalWriterAgent SHALL omitir el logo del encabezado y continuar la generación sin interrumpir el proceso.

---

### Requisito 3: Generación de Documentos Administrativos y Formatos Obligatorios

**User Story:** Como licitante, quiero que LicitAI genere automáticamente todas las declaraciones, manifiestos y formatos obligatorios de las bases, para no omitir ningún documento administrativo requerido.

#### Criterios de Aceptación

1. WHEN FormatsAgent se ejecuta, THE FormatsAgent SHALL generar un archivo DOCX por cada requisito de las zonas `administrativo` y `formatos` de la lista maestra de ComplianceAgent.
2. WHEN un requisito corresponde a un template legal bloqueado (Anexo 7, Anexo 11, Anexo 15), THE FormatsAgent SHALL renderizar el template Jinja2 correspondiente y verificar su integridad antes de guardar el archivo.
3. IF la verificación de integridad de un template legal falla, THEN THE FormatsAgent SHALL lanzar `TemplateIntegrityError` y detener la generación de ese documento sin afectar los demás.
4. WHEN un requisito no tiene template legal bloqueado, THE FormatsAgent SHALL generar el contenido mediante LLM con el system prompt de redactor legal experto.
5. THE FormatsAgent SHALL incluir en cada DOCX el encabezado con logo y datos de licitación, el bloque de lugar y fecha, el destinatario "COMITÉ DE ADQUISICIONES", el cuerpo del documento y el bloque de firma con RFC.
6. THE FormatsAgent SHALL guardar todos los archivos en `/data/outputs/{session_id}/3.documentos administrativos/` con nomenclatura `{req_id}_{nombre_corto}.docx`.
7. IF el Master_Profile no contiene `razon_social`, `rfc` o `representante_legal`, THEN THE FormatsAgent SHALL retornar estado `WAITING_FOR_DATA` con la lista de campos faltantes sin generar ningún archivo.
8. THE FormatsAgent SHALL deduplicar requisitos por ID antes de generar documentos, de modo que cada requisito produzca exactamente un archivo DOCX.

---

### Requisito 4: Generación de la Propuesta Económica

**User Story:** Como licitante, quiero que LicitAI genere automáticamente la tabla de precios, el anexo económico y la carta de compromiso, para presentar mi propuesta económica con el formato correcto.

#### Criterios de Aceptación

1. WHEN EconomicWriterAgent se ejecuta, THE EconomicWriterAgent SHALL generar un archivo XLSX con la tabla de precios unitarios a partir de los ítems calculados por EconomicAgent en Fase 1.
2. WHEN EconomicWriterAgent se ejecuta, THE EconomicWriterAgent SHALL generar un archivo DOCX con el Anexo AE (propuesta económica detallada) que incluya tabla de partidas, subtotal, IVA al 16% y total.
3. WHEN EconomicWriterAgent se ejecuta, THE EconomicWriterAgent SHALL generar un archivo DOCX de Carta Compromiso de Precios con declaración bajo protesta de decir verdad, monto total y vigencia de 30 días naturales.
4. THE EconomicWriterAgent SHALL calcular el IVA como el 16% del subtotal de las líneas renderizadas y el total como la suma de subtotal más IVA.
5. THE EconomicWriterAgent SHALL guardar los tres archivos en `/data/outputs/{session_id}/2.propuesta_economica/` con los nombres `TABLA_PRECIOS_UNITARIOS.xlsx`, `ANEXO_AE_PROPUESTA_ECONOMICA.docx` y `CARTA_COMPROMISO_PRECIOS.docx`.
6. IF EconomicAgent no generó ítems de precio en Fase 1 (campo `items` vacío o ausente), THEN THE EconomicWriterAgent SHALL retornar estado `ERROR` con mensaje descriptivo sin generar archivos.
7. THE EconomicWriterAgent SHALL incluir en el XLSX el nombre de la empresa en la celda de encabezado y aplicar estilos de formato (fuente, bordes, alineación) para que el archivo sea legible sin edición adicional.

---

### Requisito 5: Organización en Sobres y Generación de Carátulas

**User Story:** Como licitante, quiero que LicitAI organice todos los documentos en la estructura de sobres requerida por las bases y genere las carátulas correspondientes, para presentar el expediente correctamente ordenado.

#### Criterios de Aceptación

1. WHEN DocumentPackagerAgent se ejecuta, THE DocumentPackagerAgent SHALL clasificar cada documento generado en uno de los tres sobres estándar: `SOBRE_1_ADMINISTRATIVO`, `SOBRE_2_TECNICO` o `SOBRE_3_ECONOMICO`.
2. WHEN las bases especifican una estructura de sobres diferente al estándar, THE DocumentPackagerAgent SHALL usar el LLM para determinar la clasificación correcta basándose en el contexto RAG de las bases.
3. IF el LLM falla o devuelve JSON inválido al clasificar sobres, THEN THE DocumentPackagerAgent SHALL aplicar el fallback determinístico que asigna documentos por categoría (`administrativa`, `tecnica`, `economica`).
4. WHEN DocumentPackagerAgent genera una carátula, THE DocumentPackagerAgent SHALL incluir en el DOCX: título del sobre en mayúsculas, número de licitación (Session_ID), razón social, RFC, nombre del representante legal, índice numerado de documentos contenidos y fecha de generación.
5. THE DocumentPackagerAgent SHALL nombrar cada carátula `00_CARATULA_SOBRE.docx` y colocarla como primer archivo dentro de la carpeta del sobre correspondiente.
6. THE DocumentPackagerAgent SHALL copiar cada documento fuente al directorio del sobre con nomenclatura `{orden:02d}_{nombre_original}` preservando la extensión original.
7. THE DocumentPackagerAgent SHALL retornar en su output la estructura `estructura_sobres` con la ruta de cada carpeta, la lista de documentos y el total de documentos por sobre.

---

### Requisito 6: Validación y Empaquetado para CompraNet

**User Story:** Como licitante, quiero que LicitAI valide que todos los documentos tienen extensiones permitidas y genere el manifiesto SHA-256, para asegurar la integridad del paquete antes de subirlo a CompraNet.

#### Criterios de Aceptación

1. WHEN CompraNetPackager ejecuta el empaquetado, THE CompraNetPackager SHALL validar que cada archivo tenga una extensión permitida (`.doc`, `.docx`, `.pdf`, `.jpg`, `.jpeg`, `.png`, `.xlsx`).
2. IF algún archivo tiene una extensión no permitida, THEN THE CompraNetPackager SHALL retornar `PackResult` con `success=False` y la lista de archivos con extensión inválida sin empaquetar ningún archivo.
3. WHEN la validación es exitosa, THE CompraNetPackager SHALL renombrar cada archivo con la nomenclatura canónica `{RFC}_{licitacion_id}_{sobre_label}_{orden:02d}{ext}`.
4. WHEN la validación es exitosa, THE CompraNetPackager SHALL generar el archivo `MANIFIESTO_SHA256.json` en el directorio `_compranet_validated/` con el hash SHA-256, tamaño en bytes y ruta relativa de cada archivo.
5. WHEN el tamaño total del paquete supera 50 MiB, THE CompraNetPackager SHALL generar adicionalmente un archivo ZIP con compresión DEFLATE nivel 6.
6. IF `output_root`, `rfc` o `licitacion_id` no están presentes en `session_data`, THEN THE CompraNetPackager SHALL retornar `PackResult` con `success=False` y mensaje descriptivo del campo faltante.

---

### Requisito 7: Checklist Final y Guía de Entrega

**User Story:** Como licitante, quiero recibir un checklist final con todos los documentos generados y sus instrucciones de entrega, para verificar que no falta nada antes de presentar mi propuesta.

#### Criterios de Aceptación

1. WHEN DeliveryAgent se ejecuta, THE DeliveryAgent SHALL generar un archivo PDF con el checklist de seguridad que liste todos los documentos del expediente con su estado inicial "Pendiente".
2. WHEN DeliveryAgent se ejecuta, THE DeliveryAgent SHALL detectar la modalidad de entrega (electrónica vía CompraNet o presencial) mediante análisis RAG de las bases de licitación.
3. WHEN la modalidad de entrega es electrónica, THE DeliveryAgent SHALL incluir en el PDF el nombre del portal, la URL y los pasos para subir la propuesta.
4. WHEN la modalidad de entrega es presencial, THE DeliveryAgent SHALL incluir en el PDF la dirección física, el horario de recepción y los pasos para la entrega en ventanilla.
5. THE DeliveryAgent SHALL incluir en el PDF la fecha y hora límite de presentación extraída de las bases.
6. THE DeliveryAgent SHALL incluir en el PDF una sección de alertas críticas con los puntos de mayor riesgo identificados en las bases.
7. THE DeliveryAgent SHALL guardar el PDF en `/data/outputs/{session_id}/LOGISTICA_Y_GUIA_DE_ENTREGA.pdf`.
8. IF el LLM falla al analizar la modalidad de entrega, THEN THE DeliveryAgent SHALL generar el PDF con el fallback determinístico que indica "DETERMINACIÓN_MANUAL_REQUERIDA" y una alerta para consultar las bases manualmente.

---

### Requisito 8: Descarga desde la UI

**User Story:** Como usuario de LicitAI, quiero poder descargar todos los documentos generados desde la interfaz web, para obtener el paquete completo sin acceder al servidor directamente.

#### Criterios de Aceptación

1. WHEN el Pipeline_Generacion completa exitosamente, THE Sistema SHALL exponer los archivos generados en `/data/outputs/{session_id}/` a través del endpoint de descarga existente de la API.
2. THE Sistema SHALL permitir la descarga individual de cada documento generado por su ruta relativa dentro del directorio de salida de la sesión.
3. THE Sistema SHALL permitir la descarga del paquete completo como un archivo ZIP cuando el CompraNetPackager haya generado el bundle.
4. WHEN el Pipeline_Generacion retorna estado `WAITING_FOR_DATA`, THE Sistema SHALL mostrar al usuario la lista de campos faltantes del Master_Profile antes de habilitar el botón de descarga.
5. THE Sistema SHALL reflejar en la UI el estado de cada job de generación (`pending`, `running`, `completed`, `failed`) a través del campo `generation_state` del response del orquestador.

---

### Requisito 9: Manejo de Datos Faltantes

**User Story:** Como usuario de LicitAI, quiero que el sistema me informe exactamente qué datos faltan en mi expediente antes de intentar generar documentos, para completar mi perfil sin errores de generación.

#### Criterios de Aceptación

1. WHEN FormatsAgent detecta campos obligatorios faltantes en el Master_Profile, THE FormatsAgent SHALL retornar estado `WAITING_FOR_DATA` con un array `missing` que contenga el campo (`field`), la etiqueta legible (`label`) y el job_id bloqueante.
2. WHEN cualquier agente de generación retorna `WAITING_FOR_DATA`, THE Orquestador SHALL detener el pipeline y persistir las preguntas pendientes en el estado de sesión bajo la clave `pending_questions`.
3. WHEN el usuario proporciona los datos faltantes a través del chatbot, THE Sistema SHALL reanudar el Pipeline_Generacion desde el agente que estaba bloqueado sin re-ejecutar los agentes ya completados.
4. THE Sistema SHALL validar que los campos `razon_social`, `rfc`, `representante_legal` y `domicilio_fiscal` estén presentes en el Master_Profile antes de invocar a cualquier agente de generación de documentos.
5. IF el campo `logo` del Master_Profile apunta a una ruta inexistente en disco, THEN THE Sistema SHALL continuar la generación sin logo y registrar una advertencia en el log sin retornar `WAITING_FOR_DATA`.
