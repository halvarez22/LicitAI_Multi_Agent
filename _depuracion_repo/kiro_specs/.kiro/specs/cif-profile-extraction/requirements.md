# Requisitos: análisis explícito de CIF / constancia SAT en expediente de empresa

## Problema

El flujo `POST /companies/{id}/analyze` construía contexto RAG con consultas orientadas a acta y representante, pero **no aplicaba un paso explícito** de lectura estructurada de la **Constancia de Situación Fiscal (CIF)**. En particular, **`domicilio_fiscal` no formaba parte del esquema JSON** del LLM para persona moral, por lo que el perfil quedaba incompleto aunque el usuario hubiera subido CIF.

## Objetivo

1. **Detectar** documentos que correspondan a CIF/constancia (por título de carga y/o marcadores de texto SAT).
2. **Extraer** de ese texto (determinista, tolerante a OCR) al menos **`domicilio_fiscal`** y, para persona moral, **`razon_social`** cuando venga en el bloque de denominación de la constancia.
3. **Fusionar** en `master_profile` con precedencia HITL existente (`_manual_locked_fields`, merge con LLM sin pisar valores ya válidos).
4. **Ampliar** el JSON solicitado al LLM en persona moral para incluir `domicilio_fiscal` como respaldo cuando el regex no alcance.

## Criterios de aceptación

- **R1:** Si el OCR de un documento clasificado como CIF contiene bloque tipo SAT (vialidad, CP, colonia, entidad), `master_profile.domicilio_fiscal` debe poblarse tras analizar (salvo campo bloqueado manualmente).
- **R2:** Persona moral: si aparece “Nombre, denominación o razón social” / “Denominación social” con valor corporativo, debe reforzar `razon_social` cuando el LLM no haya devuelto valor útil.
- **R3:** No sobrescribir valores ya presentes y válidos ni campos en `_manual_locked_fields`.
- **R4:** Documentos solo logo u OCR inválido no deben romper el análisis; si no hay CIF útil, comportamiento degradado igual que hoy.

## Fuera de alcance

- OCR nuevo o proveedor distinto.
- Representante legal desde CIF (puede añadirse en iteración posterior).
- UI de “vista previa CIF”.
