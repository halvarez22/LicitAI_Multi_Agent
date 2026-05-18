"""
enhanced_prompts.py — Search Keywords and Extraction Prompts for Enhanced Analyst Agent

This module provides:
1. SOLVENCIA_KEYWORDS: Semantic search patterns for technical solvency
2. CONTRACTUAL_KEYWORDS: Semantic search patterns for contractual conditions
3. ENHANCED_EXTRACTION_PROMPT: Main prompt template for enhanced extraction
4. SOLVENCIA_EXTRACTION_PROMPT: Prompt for solvencia técnica extraction
5. CONDICIONES_EXTRACTION_PROMPT: Prompt for condiciones contractuales extraction

Requirements: 15.1, 15.3
"""
from typing import Final, List, Dict

# =============================================================================
# Search Keywords for Semantic Search
# =============================================================================

# Semantic search patterns for solvencia técnica (technical capability)
# These keywords work across different document formats without hardcoding
SOLVENCIA_KEYWORDS: Final[List[str]] = [
    # Experiencia mínima (Universales)
    "experiencia mínima años contratos similares",
    "años de experiencia requeridos",
    "monto mínimo contratos anteriores",
    "historial profesional licitante",
    "contratos similares realizados",
    # Currículum empresarial y personal clave
    "currículum empresarial personal clave",
    "presentación currículum empresa",
    "personal clave requerido puesto",
    "experiencia personal años título",
    # Plantilla de personal técnico
    "plantilla personal técnico certificaciones",
    "personal técnico cantidad cédula",
    "certificaciones requeridas personal",
    "cédula profesional requerida",
    # Equipamiento e infraestructura
    "equipamiento infraestructura requerida",
    "maquinaria herramientas necesarias",
    "oficinas almacenes plantas",
    "infraestructura física ubicación",
    # Normas y certificaciones
    "normas ISO NOM certificaciones",
    "ISO 9001 ISO 14001 certificación",
    "cumplimiento normas técnicas",
    "certificaciones vigentes requeridas",
    # Referencias y contratos anteriores
    "cartas referencia contratos anteriores",
    "contratos mínimos referencia",
    "antigüedad máxima contratos",
    "cartas clientes anteriores",
]

# Industry-specific keywords to be injected dynamically based on detected sector
SECTOR_SPECIFIC_KEYWORDS: Final[Dict[str, List[str]]] = {
    "servicios": [
        "niveles de servicio SLA tiempos de respuesta",
        "entregables informes reportes periodicidad",
        "metodología de trabajo plan de ejecución",
        "personal profesional técnico calificado perfiles",
        "infraestructura técnica herramientas software plataformas",
        "propiedad intelectual confidencialidad protección datos"
    ],
    "obra_publica": [
        "maquinaria pesada equipo construcción",
        "registro de contratistas obra",
        "ingenieros civiles arquitectos cédula",
        "bitácora de obra experiencia"
    ],
    "salud": [
        "registro sanitario COFEPRIS",
        "licencia sanitaria vigente",
        "distribución de insumos médicos",
        "buenas prácticas de fabricación"
    ]
}

# Semantic search patterns for condiciones contractuales (contractual terms)
CONTRACTUAL_KEYWORDS: Final[List[str]] = [
    # Tipo de contrato
    "tipo contrato precio fijo alzado",
    "contrato administración tiempo materiales",
    "contrato abierto cerrado modalidad",
    "modalidad contratación observada",
    # Penalizaciones y deducciones
    "penalizaciones deducciones atraso",
    "porcentaje penalización incumplimiento",
    "límite máximo penalizaciones",
    "días naturales hábiles aplicación",
    # Condiciones de pago
    "anticipo pagos estimaciones finiquito",
    "porcentaje anticipo autorizado",
    "garantía anticipo requerida",
    "periodicidad pagos estimaciones",
    # Garantías
    "garantía cumplimiento vicios ocultos",
    "fianza garantía líquida carta crédito",
    "porcentaje garantía cumplimiento",
    "plazo presentación garantía",
    "vigencia garantía meses",
]

# Combined search string for smart_search
SOLVENCIA_SEARCH_STRING: Final[str] = " ".join(SOLVENCIA_KEYWORDS)
CONTRACTUAL_SEARCH_STRING: Final[str] = " ".join(CONTRACTUAL_KEYWORDS)


# =============================================================================
# Extraction Prompts
# =============================================================================

# Main enhanced extraction prompt template (LicitAI-Strategist-v1)
ENHANCED_EXTRACTION_PROMPT: Final[str] = """Eres el AUDITOR SENIOR DE ESTRATEGIA en LicitAI. Tu misión es garantizar que el cliente NO sea descalificado y encontrar ventajas competitivas.

MENTALIDAD DE OPERACIÓN:
1. CAZA-TRAMPAS: Busca ambigüedades, requisitos contradictorios o plazos imposibles que parezcan diseñados para beneficiar a un competidor específico.
2. FILTRO DE SUPERVIVENCIA: Tu prioridad absoluta son las "Causas de Descalificación".
3. ANÁLISIS DE BRECHA (GAP ANALYSIS): Compara cada requisito detectado con el "PERFIL DE LA EMPRESA" proporcionado.

EXTRACTOS DE LAS BASES:
{context}

PERFIL DE LA EMPRESA (Tus capacidades):
{company_profile}

TAREA ESTRATÉGICA:
Realiza una auditoría forense de SOLVENCIA TÉCNICA y CONDICIONES CONTRACTUALES.
Infiere riesgos estratégicos: si las bases piden algo que no está en el perfil de la empresa, o si el plazo es irracional, REPLÓRTALO.

Estructura de salida (JSON):
{{
  "audit_report": {{
    "pensamiento_estrategico": "Tu análisis de la 'malicia' o complejidad detectada en estas bases.",
    "alertas_descalificacion": [
      {{ "motivo": "...", "pagina": 0, "gravedad": "ALTA/MEDIA", "sugerencia": "Acción para mitigar o pregunta para la junta" }}
    ],
    "gap_analysis": [
      {{ "requisito": "...", "estado_empresa": "FALTANTE/VENCIDO/OK", "accion_requerida": "..." }}
    ]
  }},
  "solvencia_técnica": {{
    "experiencia_mínima": {{ "años_experiencia": "", "monto_minimo": "", "numero_contratos": "", "unidad_monetaria": "" }},
    "curriculum": {{ "empresa_requerido": bool, "descripcion": "", "personal_clave": [] }},
    "plantilla_personal": [],
    "equipamiento": [],
    "infraestructura": [],
    "normas_certificaciones": [],
    "referencias": {{ "contratos_minimos": "", "antigüedad_maxima_meses": "", "cartas_referencia_aceptadas": bool }}
  }},
  "condiciones_contractuales": {{
    "tipo_contrato": {{ "tipo": "", "modalidad": "", "fuente": "" }},
    "penalizaciones": {{ "atraso": {{ "porcentaje": "", "período": "" }}, "deducciones": [], "limite_maximo": "" }},
    "pagos": {{ "anticipo": {{ "porcentaje": "", "garantia_porcentaje": "" }}, "estimaciones": {{ "periodicidad": "", "proceso_aprobación": "" }}, "retenciones_finiquito": "" }},
    "garantía_cumplimiento": {{ "monto_porcentaje": "", "tipo": "", "plazo_presentación": "", "vigencia_meses": "" }},
    "garantía_vicios_ocultos": {{ "monto_porcentaje": "", "tipo": "", "periodo_meses": "" }}
  }}
}}
"""


# Prompt specifically for solvencia técnica extraction
SOLVENCIA_EXTRACTION_PROMPT: Final[str] = """Eres un experto ANALISTA FORENSE de licitaciones mexicanas. Tu misión es extraer requisitos de SOLVENCIA TÉCNICA de las bases de licitación.

REGLAS:
1. SI NO ESTÁ, NO EXISTE: Si un dato no aparece, responde 'No especificado'.
2. CERO ALUCINACIONES: Solo lo que dice el texto.
3. Responde ÚNICAMENTE en JSON válido.

EXTRACTOS:
{context}

Extrae los siguientes datos de SOLVENCIA TÉCNICA:

1. EXPERIENCIA MÍNIMA:
   - Años mínimos de experiencia requeridos
   - Monto mínimo de contratos anteriores
   - Número mínimo de contratos similares
   - Unidad monetaria

2. CURRÍCULUM EMPRESARIAL:
   - Si se requiere currículum de la empresa
   - Descripción de lo que debe incluir
   - Personal clave requerido (puesto, años de experiencia, título requerido)

3. PLANTILLA DE PERSONAL TÉCNICO:
   - Puesto técnico requerido
   - Cantidad de personas
   - Si se requiere cédula profesional
   - Certificaciones requeridas

4. EQUIPAMIENTO:
   - Descripción del equipo
   - Cantidad requerida
   - Características técnicas

5. INFRAESTRUCTURA:
   - Tipo (oficina, almacén, planta)
   - Ubicación
   - Características

6. NORMAS Y CERTIFICACIONES:
   - Norma o certificación (ISO, NOM, NMX, etc.)
   - Tipo de norma
   - Si se requiere vigencia

7. REFERENCIAS:
   - Número mínimo de contratos de referencia
   - Antigüedad máxima de los contratos
   - Si se aceptan cartas de referencia

Estructura de salida:
{{
  "experiencia_mínima": {{ "años_experiencia": "", "monto_minimo": "", "numero_contratos": "", "unidad_monetaria": "" }},
  "curriculum": {{ "empresa_requerido": false, "descripcion": "", "personal_clave": [] }},
  "plantilla_personal": [],
  "equipamiento": [],
  "infraestructura": [],
  "normas_certificaciones": [],
  "referencias": {{ "contratos_minimos": "", "antigüedad_maxima_meses": "", "cartas_referencia_aceptadas": false }}
}}
"""


# Prompt specifically for condiciones contractuales extraction
CONDICIONES_EXTRACTION_PROMPT: Final[str] = """Eres un experto ANALISTA FORENSE de licitaciones mexicanas. Tu misión es extraer CONDICIONES CONTRACTUALES de las bases de licitación.

REGLAS:
1. SI NO ESTÁ, NO EXISTE: Si un dato no aparece, responde 'No especificado'.
2. CERO ALUCINACIONES: Solo lo que dice el texto.
3. Responde ÚNICAMENTE en JSON válido.

EXTRACTOS:
{context}

Extrae los siguientes datos de CONDICIONES CONTRACTUALES:

1. TIPO DE CONTRATO:
   - Tipo (precio fijo, precio alzado, por administración, tiempo y materiales)
   - Modalidad (abierto/cerrado)
   - Fuente (explícito/inferido)

2. PENALIZACIONES:
   - Penalización por atraso (porcentaje y período)
   - Deducciones específicas
   - Límite máximo de penalizaciones
   - Condiciones de aplicación (días naturales/hábiles)

3. PAGOS:
   - Anticipo (porcentaje y garantía requerida)
   - Estimaciones (periodicidad y proceso de aprobación)
   - Retenciones de finiquito

4. GARANTÍA DE CUMPLIMIENTO:
   - Monto como porcentaje
   - Tipo de garantía (fianza, garantía líquida, carta de crédito)
   - Plazo de presentación
   - Vigencia en meses

5. GARANTÍA DE VICIOS OCULTOS:
   - Monto o porcentaje
   - Tipo de garantía
   - Período en meses

Estructura de salida:
{{
  "tipo_contrato": {{ "tipo": "", "modalidad": "", "fuente": "explícito" }},
  "penalizaciones": {{ "atraso": {{ "porcentaje": "", "período": "" }}, "deducciones": [], "limite_maximo": "" }},
  "pagos": {{ "anticipo": {{ "porcentaje": "", "garantia_porcentaje": "" }}, "estimaciones": {{ "periodicidad": "", "proceso_aprobación": "" }}, "retenciones_finiquito": "" }},
  "garantía_cumplimiento": {{ "monto_porcentaje": "", "tipo": "", "plazo_presentación": "", "vigencia_meses": "" }},
  "garantía_vicios_ocultos": {{ "monto_porcentaje": "", "tipo": "", "periodo_meses": "" }}
}}
"""


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    "SOLVENCIA_KEYWORDS",
    "CONTRACTUAL_KEYWORDS",
    "SOLVENCIA_SEARCH_STRING",
    "CONTRACTUAL_SEARCH_STRING",
    "ENHANCED_EXTRACTION_PROMPT",
    "SOLVENCIA_EXTRACTION_PROMPT",
    "CONDICIONES_EXTRACTION_PROMPT",
]