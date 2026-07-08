# Writer Agent Specifications

## Objetivo
Definir el alcance, comportamiento y directrices del `WriterAgent` (El Brazo Ejecutor) dentro de LicitAI. Su misión es generar borradores (drafts) de anexos legales y administrativos bajo demanda, basándose en los "Gaps" detectados por el `AnalystAgent`.

## Requisitos Funcionales
1. **Contexto Tripartito:** El agente debe recibir y utilizar tres fuentes de verdad simultáneas:
   - **Identidad de la Empresa:** El `master_profile` del repositorio (RFC, Razón Social, Representante Legal Vigente validado, Domicilio).
   - **Intención (Gap):** El ID o texto del requerimiento específico que falta.
   - **Contexto Convocante (Bases):** Fragmentos recuperados vía Búsqueda Semántica (RAG) en la Base Vectorial usando la consulta de "Formato o anexo requerido para...".

2. **Generación Anti-Placeholder:**
   - Prohibido el uso de muletillas o espacios vacíos tipo `[Nombre de la Empresa]`. Si el dato existe en el Perfil Maestro, debe insertarse obligatoriamente.
   
3. **Formato Agnóstico:**
   - Todo borrador debe ser devuelto en formato Markdown (`.md`) nativo, incluyendo estructura de títulos (`#`, `##`) y espacios para firmas para ser consumido uniformemente por la UI.

4. **Resiliencia ante Datos Faltantes (Fallback):**
   - El agente debe ser capaz de procesar la solicitud incluso si algunos campos del perfil no se encuentran, siendo explícito en el log interno sin fallar la ejecución.

## Integración
- Expone el método `draft_annex(session_id, requirement_id, company_id)` que orquesta el RAG y la generación vía `ResilientLLMClient`.
