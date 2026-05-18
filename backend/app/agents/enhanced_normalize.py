"""
enhanced_normalize.py — Normalization Layer for Enhanced Analyst Agent

Functions to normalize raw LLM responses into Pydantic structures.
Takes raw dictionary responses from LLM and normalizes to the defined data models.

Requirements: 1.4, 1.5, 2.5, 3.4, 3.5, 4.4, 5.5, 6.5, 7.4, 8.5, 9.5, 10.5, 11.4, 16.1, 16.2, 17.1, 17.2
"""
from typing import Any, Dict, List, Optional, Union

from .enhanced_models import (
    # Solvencia Técnica
    ExperienciaMinima,
    PersonalClave,
    CurriculumEmpresa,
    PlantillaPersonal,
    Equipamiento,
    Infraestructura,
    NormaCertificacion,
    Referencias,
    SolvenciaTecnica,
    # Condiciones Contractuales
    TipoContrato,
    PenalizacionAtraso,
    Penalizaciones,
    Anticipo,
    Estimaciones,
    Pagos,
    GarantiaCumplimiento,
    GarantiaViciosOcultos,
    CondicionesContractuales,
)

# Default value for missing fields as per requirement 1.5
DEFAULT_MISSING = "No especificado"


# =============================================================================
# Helper Functions
# =============================================================================


def safe_get(data: Dict[str, Any], *keys: str, default: str = DEFAULT_MISSING) -> str:
    """
    Safely get a value from a dictionary trying multiple alternative keys.
    
    Args:
        data: Dictionary to search
        *keys: Alternative keys to try (first match wins)
        default: Default value if no key is found
        
    Returns:
        The value at the first matching key or default
    """
    if not isinstance(data, dict):
        return default
    
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            return str(value) if not isinstance(value, str) else value
    
    return default


def safe_get_bool(data: Dict[str, Any], *keys: str, default: bool = False) -> bool:
    """
    Safely get a boolean value from a dictionary trying multiple alternative keys.
    
    Args:
        data: Dictionary to search
        *keys: Alternative keys to try (first match wins)
        default: Default value if no key is found
        
    Returns:
        The boolean value at the first matching key or default
    """
    if not isinstance(data, dict):
        return default
    
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "si", "1", "sí")
    
    return default


def safe_get_float(data: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    """
    Safely get a float value from a dictionary trying multiple alternative keys.
    
    Args:
        data: Dictionary to search
        *keys: Alternative keys to try (first match wins)
        default: Default value if no key is found or not convertible
        
    Returns:
        The float value at the first matching key or default
    """
    if not isinstance(data, dict):
        return default
    
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            try:
                return float(value)
            except (ValueError, TypeError):
                continue
    
    return default


def safe_get_list(data: Dict[str, Any], *keys: str, default: Optional[List] = None) -> List:
    """
    Safely get a list value from a dictionary trying multiple alternative keys.
    
    Args:
        data: Dictionary to search
        *keys: Alternative keys to try (first match wins)
        default: Default value if no key is found
        
    Returns:
        The list value at the first matching key or default
    """
    if default is None:
        default = []
    
    if not isinstance(data, dict):
        return default
    
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(value, list):
                return value
    
    return default


# =============================================================================
# 2.1 Normalization Functions for Solvencia Técnica
# =============================================================================


def normalize_experiencia_minima(raw: Dict[str, Any]) -> ExperienciaMinima:
    """
    Normalize experiencia mínima data from raw LLM response.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
    """
    return ExperienciaMinima(
        años_experiencia=safe_get(raw, "años", "años_experiencia", "anios", "anios_experiencia"),
        monto_minimo=safe_get(raw, "monto", "monto_minimo", "monto_min"),
        numero_contratos=safe_get(raw, "numero_contratos", "num_contratos", "número_contratos"),
        unidad_monetaria=safe_get(raw, "unidad", "unidad_monetaria", "moneda"),
        confianza=safe_get_float(raw, "confianza", "confidence", default=0.0),
        fuente=safe_get(raw, "fuente", "source", "pagina", "page", default=""),
    )


def normalize_personal_clave(raw: Union[Dict, List]) -> List[PersonalClave]:
    """Normalize a list of personal clave entries."""
    if not raw:
        return []
    
    items = raw if isinstance(raw, list) else [raw]
    result = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(PersonalClave(
            puesto=safe_get(item, "puesto", "position", "rol"),
            experiencia_años=safe_get(item, "experiencia", "experiencia_años", "anios", "anios_experiencia"),
            titulo_requerido=safe_get_bool(item, "titulo_requerido", "titulo", "title_required"),
            titulo_descripcion=safe_get(item, "titulo_descripcion", "title_description", "carrera"),
        ))
    
    return result


def normalize_curriculum_empresa(raw: Dict[str, Any]) -> CurriculumEmpresa:
    """
    Normalize curriculum empresa data from raw LLM response.
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
    """
    personal_clave_data = safe_get_list(raw, "personal_clave", "personal_clave_requerido")
    
    return CurriculumEmpresa(
        empresa_requerido=safe_get_bool(raw, "empresa_requerido", "curriculum_empresa_requerido", "requerido"),
        descripcion=safe_get(raw, "descripcion", "description", "detalle"),
        personal_clave=normalize_personal_clave(personal_clave_data),
    )


def normalize_plantilla_personal(raw: Union[Dict, List]) -> List[PlantillaPersonal]:
    """
    Normalize plantilla de personal data from raw LLM response.
    
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
    """
    if not raw:
        return []
    
    items = raw if isinstance(raw, list) else [raw]
    result = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        # Handle "sin_requisitos_explícitos" case (requirement 3.5)
        if item.get("sin_requisitos_explícitos") or item.get("sin_requisitos") or item.get("no_requerido"):
            continue
        
        # Get certificaciones as list
        certs = item.get("certificaciones") or item.get("certifications") or []
        if isinstance(certs, str):
            certs = [certs] if certs and certs != DEFAULT_MISSING else []
        
        result.append(PlantillaPersonal(
            puesto=safe_get(item, "puesto", "position", "rol", "personal"),
            cantidad=safe_get(item, "cantidad", "quantity", "numero", "número"),
            cedula_requerida=safe_get_bool(item, "cedula_requerida", "cedula", "license_required"),
            certificaciones=certs if isinstance(certs, list) else [],
        ))
    
    return result


def normalize_equipamiento(raw: Union[Dict, List]) -> List[Equipamiento]:
    """
    Normalize equipamiento data from raw LLM response.
    
    Validates: Requirements 4.1, 4.3
    """
    if not raw:
        return []
    
    items = raw if isinstance(raw, list) else [raw]
    result = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        result.append(Equipamiento(
            descripcion=safe_get(item, "descripcion", "description", "equipo", "equipment"),
            cantidad=safe_get(item, "cantidad", "quantity", "numero", "número"),
            caracteristicas=safe_get(item, "caracteristicas", "characteristics", "especificaciones", "specs"),
        ))
    
    return result


def normalize_infraestructura(raw: Union[Dict, List]) -> List[Infraestructura]:
    """
    Normalize infraestructura data from raw LLM response.
    
    Validates: Requirements 4.2, 4.3
    """
    if not raw:
        return []
    
    items = raw if isinstance(raw, list) else [raw]
    result = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        result.append(Infraestructura(
            tipo=safe_get(item, "tipo", "type", "infraestructura", "infrastructure"),
            ubicacion=safe_get(item, "ubicacion", "location", "ubicación"),
            caracteristicas=safe_get(item, "caracteristicas", "characteristics", "especificaciones"),
        ))
    
    return result


def normalize_normas_certificaciones(raw: Union[Dict, List]) -> List[NormaCertificacion]:
    """
    Normalize normas y certificaciones data from raw LLM response.
    
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
    """
    if not raw:
        return []
    
    items = raw if isinstance(raw, list) else [raw]
    result = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        result.append(NormaCertificacion(
            norma=safe_get(item, "norma", "standard", "certificacion", "certification"),
            tipo=safe_get(item, "tipo", "type", "norma_tipo"),
            vigencia_requerida=safe_get_bool(item, "vigencia_requerida", "vigente", "current", "required"),
        ))
    
    return result


def normalize_referencias(raw: Dict[str, Any]) -> Referencias:
    """
    Normalize referencias data from raw LLM response.
    
    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5
    """
    return Referencias(
        contratos_minimos=safe_get(raw, "contratos_minimos", "num_contratos", "número_contratos"),
        antigüedad_maxima_meses=safe_get(raw, "antigüedad_maxima", "antiguedad_maxima", "antigüedad", "antiguedad"),
        cartas_referencia_aceptadas=safe_get_bool(raw, "cartas_referencia_aceptadas", "cartas_aceptadas", "cartas"),
        requisitos_adicionales=safe_get(raw, "requisitos_adicionales", "additional_requirements", "notas"),
    )


def normalize_solvencia_tecnica(raw: Dict[str, Any]) -> SolvenciaTecnica:
    """
    Main normalization function for solvencia técnica.
    
    Takes raw LLM response dictionary and normalizes to SolvenciaTecnica Pydantic model.
    Fills missing fields with "No especificado" as per requirement 1.5.
    
    Validates: Requirements 16.1, 16.2
    """
    # Handle case where raw is empty or None
    if not raw:
        return SolvenciaTecnica()
    
    # Extract each section with fallback to empty dict
    experiencia_data = raw.get("experiencia_mínima", raw.get("experiencia_minima", raw.get("experiencia", {})))
    if isinstance(experiencia_data, dict):
        experiencia = normalize_experiencia_minima(experiencia_data)
    else:
        experiencia = ExperienciaMinima()
    
    curriculum_data = raw.get("curriculum", raw.get("curriculum_empresa", {}))
    if isinstance(curriculum_data, dict):
        curriculum = normalize_curriculum_empresa(curriculum_data)
    else:
        curriculum = CurriculumEmpresa()
    
    plantilla_data = raw.get("plantilla_personal", raw.get("plantilla", []))
    plantilla = normalize_plantilla_personal(plantilla_data)
    
    equipamiento_data = raw.get("equipamiento", raw.get("equipos", []))
    equipamiento = normalize_equipamiento(equipamiento_data)
    
    infraestructura_data = raw.get("infraestructura", raw.get("infraestructura", []))
    infraestructura = normalize_infraestructura(infraestructura_data)
    
    normas_data = raw.get("normas_certificaciones", raw.get("normas", raw.get("certificaciones", [])))
    normas_certificaciones = normalize_normas_certificaciones(normas_data)
    
    referencias_data = raw.get("referencias", raw.get("referencias", {}))
    if isinstance(referencias_data, dict):
        referencias = normalize_referencias(referencias_data)
    else:
        referencias = Referencias()
    
    return SolvenciaTecnica(
        experiencia_mínima=experiencia,
        curriculum=curriculum,
        plantilla_personal=plantilla,
        equipamiento=equipamiento,
        infraestructura=infraestructura,
        normas_certificaciones=normas_certificaciones,
        referencias=referencias,
    )


# =============================================================================
# 2.2 Normalization Functions for Condiciones Contractuales
# =============================================================================


def normalize_tipo_contrato(raw: Dict[str, Any]) -> TipoContrato:
    """
    Normalize tipo de contrato data from raw LLM response.
    
    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """
    return TipoContrato(
        tipo=safe_get(raw, "tipo", "tipo_contrato", "type"),
        modalidad=safe_get(raw, "modalidad", "mode", "modalidad_contrato"),
        fuente=safe_get(raw, "fuente", "source", "fuente_tipo", default="explícito"),
    )


def normalize_penalizacion_atraso(raw: Dict[str, Any]) -> PenalizacionAtraso:
    """Normalize penalización por atraso data."""
    return PenalizacionAtraso(
        porcentaje=safe_get(raw, "porcentaje", "percentage", "tasa"),
        período=safe_get(raw, "período", "periodo", "period", "tipo_dias", "dias"),
    )


def normalize_penalizaciones(raw: Dict[str, Any]) -> Penalizaciones:
    """
    Normalize penalizaciones data from raw LLM response.
    
    Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
    """
    atraso_data = raw.get("atraso", raw.get("penalizacion_atraso", {}))
    if isinstance(atraso_data, dict):
        atraso = normalize_penalizacion_atraso(atraso_data)
    else:
        atraso = PenalizacionAtraso()
    
    deducciones = safe_get_list(raw, "deducciones", "deductions")
    if isinstance(deducciones, str):
        deducciones = [deducciones] if deducciones and deducciones != DEFAULT_MISSING else []
    
    return Penalizaciones(
        atraso=atraso,
        deducciones=deducciones if isinstance(deducciones, list) else [],
        limite_maximo=safe_get(raw, "limite_maximo", "limite", "max_limit", "límite"),
        condiciones_aplicación=safe_get(raw, "condiciones", "condiciones_aplicacion", "conditions"),
    )


def normalize_anticipo(raw: Dict[str, Any]) -> Anticipo:
    """Normalize anticipo data."""
    return Anticipo(
        porcentaje=safe_get(raw, "porcentaje", "percentage", "monto"),
        garantia_porcentaje=safe_get(raw, "garantia_porcentaje", "garantia", "garantia_anticipo"),
    )


def normalize_estimaciones(raw: Dict[str, Any]) -> Estimaciones:
    """Normalize estimaciones data."""
    return Estimaciones(
        periodicidad=safe_get(raw, "periodicidad", "periodicity", "frecuencia", "frequency"),
        proceso_aprobación=safe_get(raw, "proceso_aprobacion", "proceso", "approval_process"),
    )


def normalize_pagos(raw: Dict[str, Any]) -> Pagos:
    """
    Normalize pagos data from raw LLM response.
    
    Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
    """
    anticipo_data = raw.get("anticipo", {})
    if isinstance(anticipo_data, dict):
        anticipo = normalize_anticipo(anticipo_data)
    else:
        anticipo = Anticipo()
    
    estimaciones_data = raw.get("estimaciones", {})
    if isinstance(estimaciones_data, dict):
        estimaciones = normalize_estimaciones(estimaciones_data)
    else:
        estimaciones = Estimaciones()
    
    return Pagos(
        anticipo=anticipo,
        estimaciones=estimaciones,
        retenciones_finiquito=safe_get(raw, "retenciones_finiquito", "retenciones", "retainages"),
    )


def normalize_garantia_cumplimiento(raw: Dict[str, Any]) -> GarantiaCumplimiento:
    """
    Normalize garantía de cumplimiento data from raw LLM response.
    
    Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
    """
    return GarantiaCumplimiento(
        monto_porcentaje=safe_get(raw, "monto_porcentaje", "monto", "percentage", "porcentaje"),
        tipo=safe_get(raw, "tipo", "type", "tipo_garantia"),
        plazo_presentación=safe_get(raw, "plazo_presentacion", "plazo", "deadline"),
        vigencia_meses=safe_get(raw, "vigencia_meses", "vigencia", "months", "meses"),
    )


def normalize_garantia_vicios_ocultos(raw: Dict[str, Any]) -> GarantiaViciosOcultos:
    """
    Normalize garantía de vicios ocultos data from raw LLM response.
    
    Validates: Requirements 11.1, 11.2, 11.3, 11.4
    """
    return GarantiaViciosOcultos(
        monto_porcentaje=safe_get(raw, "monto_porcentaje", "monto", "percentage", "porcentaje"),
        tipo=safe_get(raw, "tipo", "type", "tipo_garantia"),
        periodo_meses=safe_get(raw, "periodo_meses", "periodo", "period", "meses", "months"),
    )


def normalize_condiciones_contractuales(raw: Dict[str, Any]) -> CondicionesContractuales:
    """
    Main normalization function for condiciones contractuales.
    
    Takes raw LLM response dictionary and normalizes to CondicionesContractuales Pydantic model.
    Fills missing fields with "No especificado" as per requirement 1.5.
    
    Validates: Requirements 17.1, 17.2
    """
    # Handle case where raw is empty or None
    if not raw:
        return CondicionesContractuales()
    
    # Extract each section with fallback to empty dict
    tipo_contrato_data = raw.get("tipo_contrato", raw.get("tipo_contrato", {}))
    if isinstance(tipo_contrato_data, dict):
        tipo_contrato = normalize_tipo_contrato(tipo_contrato_data)
    else:
        tipo_contrato = TipoContrato()
    
    penalizaciones_data = raw.get("penalizaciones", raw.get("penalizaciones", {}))
    if isinstance(penalizaciones_data, dict):
        penalizaciones = normalize_penalizaciones(penalizaciones_data)
    else:
        penalizaciones = Penalizaciones()
    
    pagos_data = raw.get("pagos", raw.get("pagos", {}))
    if isinstance(pagos_data, dict):
        pagos = normalize_pagos(pagos_data)
    else:
        pagos = Pagos()
    
    garantia_cumplimiento_data = raw.get("garantía_cumplimiento", raw.get("garantia_cumplimiento", raw.get("garantia_cumplimiento", {})))
    if isinstance(garantia_cumplimiento_data, dict):
        garantia_cumplimiento = normalize_garantia_cumplimiento(garantia_cumplimiento_data)
    else:
        garantia_cumplimiento = GarantiaCumplimiento()
    
    garantia_vicios_data = raw.get("garantía_vicios_ocultos", raw.get("garantia_vicios_ocultos", raw.get("garantia_vicios", {})))
    if isinstance(garantia_vicios_data, dict):
        garantia_vicios_ocultos = normalize_garantia_vicios_ocultos(garantia_vicios_data)
    else:
        garantia_vicios_ocultos = GarantiaViciosOcultos()
    
    return CondicionesContractuales(
        tipo_contrato=tipo_contrato,
        penalizaciones=penalizaciones,
        pagos=pagos,
        garantía_cumplimiento=garantia_cumplimiento,
        garantía_vicios_ocultos=garantia_vicios_ocultos,
    )


# =============================================================================
# 2.3 Main Normalization Orchestrator (exported functions)
# =============================================================================


def normalize_all(raw_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main orchestrator that normalizes the complete LLM response.
    
    Takes the full raw response from LLM containing both solvencia técnica
    and condiciones contractuales, and returns a dictionary with both
    normalized structures.
    
    Args:
        raw_response: Raw dictionary from LLM with potential variations in key names
        
    Returns:
        Dictionary with:
            - solvencia_tecnica: SolvenciaTecnica object
            - condiciones_contractuales: CondicionesContractuales object
    """
    # Extract solvencia técnica section
    solvencia_raw = raw_response.get("solvencia_técnica", raw_response.get("solvencia_tecnica", raw_response.get("solvencia", {})))
    
    # Extract condiciones contractuales section
    condiciones_raw = raw_response.get("condiciones_contractuales", raw_response.get("condiciones_contractuales", raw_response.get("condiciones", {})))
    
    # Normalize both sections
    solvencia_tecnica = normalize_solvencia_tecnica(solvencia_raw) if isinstance(solvencia_raw, dict) else SolvenciaTecnica()
    condiciones_contractuales = normalize_condiciones_contractuales(condiciones_raw) if isinstance(condiciones_raw, dict) else CondicionesContractuales()
    
    return {
        "solvencia_tecnica": solvencia_tecnica,
        "condiciones_contractuales": condiciones_contractuales,
    }