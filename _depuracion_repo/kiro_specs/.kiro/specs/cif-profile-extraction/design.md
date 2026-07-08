# Diseño: extracción CIF en `analyze_company`

## Componentes

1. **`legal_representative_parser.is_constancia_cif_text(text)`**  
   Expone detección reutilizando el marcador existente `_CIF_DOC_MARKERS`.

2. **`cif_profile_extract.extract_cif_company_profile_patch(cif_blob, is_fisica)`**  
   Devuelve dict opcional con `domicilio_fiscal`, `razon_social` (moral), `strategy` / evidencia breve para logs.

## Estrategia de extracción (domicilio)

Orden de intento:

1. **Formato SAT reciente** — etiquetas `Nombre de vialidad`, `Número exterior/interior`, `Nombre de la colonia`, `Código postal`, `Nombre de la localidad`, `Nombre del municipio…`, `Nombre de la entidad federativa`; concatenación en una sola línea legible.
2. **Formato legado** — bloque tras la etiqueta `Domicilio fiscal` hasta la siguiente sección típica (`Régimen`, `Actividad económica`, `RFC`, etc.).

Si ninguno produce cadena ≥ umbral mínimo de longitud, no se rellena.

## Estrategia (razón social, moral)

Regex sobre etiquetas `Nombre, denominación o razón social` / `Denominación social` con lookahead a `RFC` / `Domicilio` / `Régimen` para acotar captura.

## Integración en `companies.analyze_company`

Durante el bucle OCR por documento `doc_title`:

- Acumular texto completo del documento en `cif_text_blobs` si `_company_doc_title_suggests_cif(doc_title)` **o** `is_constancia_cif_text(full_doc_text)`.

Tras parsear JSON del LLM:

- `_apply_cif_constancia_patch(profile_data, cif_blob, is_fisica, existing_profile)`  
  Aplica solo huecos / placeholders; respeta locks.

## Consultas RAG

Añadir a `_build_company_queries` (moral) una consulta que recupere fragmentos con “domicilio fiscal”, “código postal”, “constancia”, para que el LLM también vea CIF en el contexto concatenado.

## Tests

- Unitarios en `test_cif_profile_extract.py` con texto sintético tipo constancia (moderna y legada).
- Sin cambiar contrato HTTP del endpoint.
