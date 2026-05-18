"""
router_prompts.py — Prompts versionados para el Router de Peritaje Legal.

Versiones:
  v1 — Prompts originales (mínimos, sin señales, sin doble obligatoriedad).
  v2 — Prompt hardening: señales auditables, doble obligatoriedad, few-shot, precedencia.

Rollback: setear ROUTER_PROMPT_VERSION=v1 en .env para revertir sin tocar código.
"""

# =============================================================================
# TRIAGE PROMPTS
# =============================================================================

TRIAGE_PROMPT_V1 = """
Actúa como un experto en Jurisprudencia de Licitaciones Mexicanas.
Analiza el siguiente extracto y determina el marco normativo.

TEXTO:
{first_pages_text}

Responde en JSON:
{{
    "law": "LAASSP | LOPSRM | LEY_QUERETARO | OTRA",
    "jurisdiction": "FEDERAL | ESTATAL",
    "tender_category": "SALUD | OBRA | BIENES | TECNOLOGIA",
    "confidence": 0.0
}}
"""

TRIAGE_PROMPT_V2 = """
Eres un JURISTA EXPERTO en licitaciones mexicanas. Tu única misión es clasificar
el marco normativo de este documento con evidencia literal — nunca por inferencia.

REGLAS DE CLASIFICACIÓN:
1. Para LEY_QUERETARO: requieres al menos DOS señales fuertes del siguiente catálogo:
   - Mención explícita de "Ley de Adquisiciones del Estado de Querétaro"
   - Mención de "CADPE" (Comité de Adquisiciones del Poder Ejecutivo)
   - Mención de "SESEQ", "CONCYTEQ" u organismo estatal queretano específico
   - Número de licitación con prefijo estatal (ej: QRO-...)
2. Para LAASSP: "Ley de Adquisiciones, Arrendamientos y Servicios del Sector Público"
   o expediente CompraNet federal.
3. Para LOPSRM: "Ley de Obras Públicas y Servicios Relacionados".
   Si detectas LOPSRM, tender_category SIEMPRE es "OBRA".
4. Para OBRA (tender_category): requieres al menos UNA señal:
   - Mención de "Ley de Obras Públicas" o "LOPSRM"
   - Presencia de formas AT- o AE- (AT-10, AT-13, AE-02, etc.)
   - Mención de "catálogo de conceptos de obra", "explosión de insumos", "programa de obra"
   - Mención de "contratista", "subcontratista", "superintendente de obra"
   - Mención de "obra pública", "construcción", "infraestructura", "edificación"
5. Si no hay evidencia suficiente → usa "OTRA" con confidence < 0.4.
6. NUNCA inventes señales. Si no están en el texto, no existen.

TEXTO (primeras páginas):
{first_pages_text}

Responde ÚNICAMENTE en este JSON (sin texto adicional):
{{
    "law": "LAASSP | LOPSRM | LEY_QUERETARO | OTRA",
    "jurisdiction": "FEDERAL | ESTATAL",
    "tender_category": "SALUD | OBRA | BIENES | TECNOLOGIA",
    "confidence": 0.0,
    "signals_detected": ["señal literal 1", "señal literal 2"]
}}
"""

# =============================================================================
# AUDIT CONTEXT INSTRUCTIONS (inyectadas en system_prompt de compliance)
# =============================================================================

AUDIT_TRIAGE_INSTRUCTIONS_V1 = """
CONTEXTO LEGAL DETECTADO:
- Ley Aplicable: {law}
- Categoría: {category}
- DOCUMENTOS OBLIGATORIOS (Must-Have): {must_have_list}
- REGLAS CRÍTICAS: {critical_rules}

TU MISIÓN ESPECIAL:
Si detectas cualquier fragmento que cumpla con un 'Must-Have' de la lista anterior,
DEBES clasificarlo con 'tipo_accion': 'generar' o 'presentar_fisico'.
No lo ignores como informativo.
"""

AUDIT_TRIAGE_INSTRUCTIONS_V2 = """
═══════════════════════════════════════════════════
CONTEXTO LEGAL DETECTADO POR ROUTER (NO MODIFICAR)
═══════════════════════════════════════════════════
- Ley Aplicable     : {law}
- Jurisdicción      : {jurisdiction}
- Categoría         : {category}
- Señales detectadas: {signals}
- Confianza triage  : {confidence}

DOCUMENTOS MUST-HAVE (obligatorios por ley {law}):
{must_have_numbered}

REGLAS CRÍTICAS (penalizables):
{critical_rules_numbered}

═══════════════════════════════════════════════════
JERARQUÍA DE PRECEDENCIA (en conflicto, respetar orden):
  1. Decisión HITL ya registrada por usuario
  2. Evidencia literal del documento (snippet concreto)
  3. Política Must-Have del marco normativo ({law})
  4. Inferencia libre del modelo (última opción)
═══════════════════════════════════════════════════

CONTRATO DE SALIDA OBLIGATORIO (por ítem extraído):
Cada ítem en el JSON debe incluir:
  - "tipo_accion"               : "generar" | "presentar_fisico" | "informativo"
  - "obligatorio_por_bases"     : true/false  (explícito en convocatoria)
  - "obligatorio_por_marco_normativo": true/false  (derivado de Must-Have {law})
  - "label_taxonomica"          : ej. "LEG_ACTA_CONSTITUTIVA", "FIS_SAT_OPINION"
  - "justificacion_clasificacion": string corto explicando la decisión
  - "snippet"                   : fragmento literal del texto fuente

REGLA ANTI-INFORMATIVO:
Si un ítem tiene label_taxonomica en la lista Must-Have de arriba,
'tipo_accion' NUNCA puede ser "informativo".
Usa "presentar_fisico" para documentos físicos existentes (acta, INE, constancias).
Usa "generar" para documentos que el licitante debe redactar (cartas, manifestaciones, propuestas).

EJEMPLOS FEW-SHOT:

✅ CORRECTO — Must-Have detectado:
{{
  "nombre": "Acta Constitutiva de la empresa",
  "tipo_accion": "presentar_fisico",
  "obligatorio_por_bases": true,
  "obligatorio_por_marco_normativo": true,
  "label_taxonomica": "LEG_ACTA_CONSTITUTIVA",
  "justificacion_clasificacion": "Documento legal de existencia jurídica requerido por {law} Art. 29",
  "snippet": "deberá presentar acta constitutiva vigente debidamente inscrita"
}}

✅ CORRECTO — Generado por licitante:
{{
  "nombre": "Carta de integridad bajo protesta de decir verdad",
  "tipo_accion": "generar",
  "obligatorio_por_bases": true,
  "obligatorio_por_marco_normativo": true,
  "label_taxonomica": "DECL_INTEGRIDAD",
  "justificacion_clasificacion": "Declaración que el licitante redacta y firma conforme Art. 29 fr. IX",
  "snippet": "manifestación bajo protesta de decir verdad de no encontrarse en supuestos"
}}

❌ INCORRECTO — Must-Have degradado a informativo:
{{
  "nombre": "Opinión del SAT",
  "tipo_accion": "informativo",    ← PROHIBIDO si FIS_SAT_OPINION está en Must-Have
  "snippet": "opinión de cumplimiento de obligaciones fiscales"
}}

❌ INCORRECTO — Hallazgo sin snippet:
{{
  "nombre": "Algún documento",
  "tipo_accion": "generar",
  "snippet": ""    ← SIEMPRE cita el texto literal; si no hay, marca quality_flags: ["non_literal_evidence"]
}}

OMISIONES MUST-HAVE:
Si terminas el análisis y no encontraste evidencia de un ítem Must-Have,
debes reportarlo con:
  "tipo_accion": "generar",
  "obligatorio_por_marco_normativo": true,
  "obligatorio_por_bases": false,
  "snippet": "",
  "quality_flags": ["must_have_not_found_in_text"],
  "justificacion_clasificacion": "Obligatorio por {law} aunque no aparece explícito en el texto analizado"
═══════════════════════════════════════════════════
"""


def build_triage_prompt(first_pages_text: str, version: str = "v2") -> str:
    """Retorna el prompt de triage según la versión configurada."""
    template = TRIAGE_PROMPT_V2 if version == "v2" else TRIAGE_PROMPT_V1
    return template.format(first_pages_text=first_pages_text[:10000])


def build_audit_triage_instructions(triage_context: dict, version: str = "v2") -> str:
    """
    Construye el bloque de instrucciones legales inyectado en el system_prompt del ComplianceAgent.
    Lee _flags del triage_context para activar/desactivar secciones de la v2:
      - signals_enabled:       si False, omite la línea de señales detectadas.
      - dual_obligation:       si False, omite los campos obligatorio_por_bases/marco_normativo.
      - justification_enabled: si False, omite justificacion_clasificacion del contrato de salida.
    """
    from app.services.tender_router_service import TenderRouterService

    law = triage_context.get("law", "LAASSP")
    jurisdiction = triage_context.get("jurisdiction", "FEDERAL")
    category = triage_context.get("tender_category", "BIENES")
    confidence = triage_context.get("confidence", 0.0)
    signals = triage_context.get("signals_detected", [])
    must_have = triage_context.get("must_have", [])
    critical_rules = triage_context.get("critical_rules", [])

    # Flags granulares (cargados por compliance.py desde settings)
    flags = triage_context.get("_flags", {})
    signals_enabled       = flags.get("signals_enabled", True)
    dual_obligation       = flags.get("dual_obligation", True)
    justification_enabled = flags.get("justification_enabled", True)

    allowlist = triage_context.get("taxonomy_allowlist") or TenderRouterService.get_taxonomy_allowlist(
        law, category
    )
    allowlist_numbered = "\n".join(f"  {i+1}. {lab}" for i, lab in enumerate(allowlist)) or "  (vacío)"
    anchor_hints = TenderRouterService.taxonomy_anchor_hints_markdown()

    if version == "v1":
        v1_extra = (
            "\nVOCABULARIO CERRADO (label_taxonomica): elige EXACTAMENTE una etiqueta de esta lista; "
            "si ninguna encaja usa OTRO. No inventes etiquetas nuevas.\n"
            f"{allowlist_numbered}\n"
            f"ANCLAJES:\n{anchor_hints}\n"
        )
        return AUDIT_TRIAGE_INSTRUCTIONS_V1.format(
            law=law,
            category=category,
            must_have_list=", ".join(must_have),
            critical_rules=", ".join(critical_rules),
        ) + v1_extra

    # --- v2: construir dinámicamente según flags ---
    must_have_numbered = "\n".join(
        f"  {i+1}. {label}" for i, label in enumerate(must_have)
    ) or "  (ninguno detectado)"

    critical_rules_numbered = "\n".join(
        f"  • {rule}" for rule in critical_rules
    ) or "  (ninguna)"

    signals_line = (
        f"- Señales detectadas: {', '.join(signals) if signals else 'ninguna registrada'}\n"
        if signals_enabled else ""
    )

    # Campos del contrato de salida (activados por flags)
    contract_fields = [
        '  - "tipo_accion"               : "generar" | "presentar_fisico" | "informativo"',
    ]
    if dual_obligation:
        contract_fields += [
            '  - "obligatorio_por_bases"     : true/false  (explícito en convocatoria)',
            f'  - "obligatorio_por_marco_normativo": true/false  (derivado de Must-Have {law})',
        ]
    contract_fields.append(
        '  - "label_taxonomica"          : una etiqueta EXACTA de la lista permitida arriba (u OTRO)'
    )
    if justification_enabled:
        contract_fields.append('  - "justificacion_clasificacion": razón corta de la clasificación')
    contract_fields.append('  - "snippet"                   : fragmento literal del texto fuente')
    contract_str = "\n".join(contract_fields)

    # Few-shot positivo/negativo (dual_obligation incluye campos extra)
    fewshot_pos_fields = '  "tipo_accion": "presentar_fisico",\n'
    if dual_obligation:
        fewshot_pos_fields += (
            '  "obligatorio_por_bases": true,\n'
            '  "obligatorio_por_marco_normativo": true,\n'
        )
    fewshot_pos_fields += '  "label_taxonomica": "LEG_ACTA_CONSTITUTIVA",\n'
    if justification_enabled:
        fewshot_pos_fields += f'  "justificacion_clasificacion": "Requerido por {law} Art. 29",\n'
    fewshot_pos_fields += '  "snippet": "deberá presentar acta constitutiva vigente"'

    instructions = f"""
═══════════════════════════════════════════════════
CONTEXTO LEGAL DETECTADO POR ROUTER (NO MODIFICAR)
═══════════════════════════════════════════════════
- Ley Aplicable     : {law}
- Jurisdicción      : {jurisdiction}
- Categoría         : {category}
{signals_line}- Confianza triage  : {round(confidence, 2)}

DOCUMENTOS MUST-HAVE (obligatorios por ley {law}):
{must_have_numbered}

REGLAS CRÍTICAS (penalizables):
{critical_rules_numbered}

═══════════════════════════════════════════════════
VOCABULARIO CERRADO — label_taxonomica (ANCLAJE DE TAXONOMÍA)
═══════════════════════════════════════════════════
Para CADA ítem extraído debes asignar EXACTAMENTE una etiqueta tomada de esta lista.
No inventes códigos nuevos ni variantes (ej. no uses "Carta nacionalidad"; usa la etiqueta canónica).
Si ninguna etiqueta encaja con evidencia literal del fragmento, usa únicamente: OTRO

ETIQUETAS PERMITIDAS:
{allowlist_numbered}

PISTAS DE MAPEO (solo si el texto lo respalda):
{anchor_hints}

═══════════════════════════════════════════════════
JERARQUÍA DE PRECEDENCIA (en conflicto, respetar orden):
  1. Decisión HITL ya registrada por usuario
  2. Evidencia literal del documento (snippet concreto)
  3. Política Must-Have del marco normativo ({law})
  4. Inferencia libre del modelo (última opción)
═══════════════════════════════════════════════════

CONTRATO DE SALIDA OBLIGATORIO (por ítem extraído):
{contract_str}

REGLA ANTI-INFORMATIVO:
Si un ítem tiene label_taxonomica en la lista Must-Have de arriba,
'tipo_accion' NUNCA puede ser "informativo".
Usa "presentar_fisico" para documentos físicos (acta, INE, constancias).
Usa "generar" para documentos que el licitante redacta (cartas, manifestaciones, propuestas).

EJEMPLO CORRECTO — Must-Have detectado:
{{
  "nombre": "Acta Constitutiva de la empresa",
{fewshot_pos_fields}
}}

EJEMPLO INCORRECTO — Must-Have degradado a informativo:
{{
  "nombre": "Opinión del SAT",
  "tipo_accion": "informativo",  ← PROHIBIDO si FIS_SAT_OPINION está en Must-Have
  "snippet": "opinión de cumplimiento de obligaciones fiscales"
}}

OMISIONES MUST-HAVE: Si no encuentras evidencia de un ítem obligatorio, repórtalo con:
  "tipo_accion": "generar", "obligatorio_por_marco_normativo": true,
  "quality_flags": ["must_have_not_found_in_text"], "snippet": ""
═══════════════════════════════════════════════════
"""
    return instructions



__all__ = [
    "TRIAGE_PROMPT_V1",
    "TRIAGE_PROMPT_V2",
    "AUDIT_TRIAGE_INSTRUCTIONS_V1",
    "AUDIT_TRIAGE_INSTRUCTIONS_V2",
    "build_triage_prompt",
    "build_audit_triage_instructions",
]
