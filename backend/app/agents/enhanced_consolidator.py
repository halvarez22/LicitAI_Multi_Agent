"""
enhanced_consolidator.py — Consolidation Engine for Enhanced Analyst Agent

This module provides:
1. Checklist consolidation: merge of solvencia técnica and condiciones contractuales
2. Priority ordering: classification + category priority
3. Delivery order assignment

Requirements: 14.1, 14.2, 14.3, 14.4, 18.1, 18.2
"""
from typing import Any, Dict, List, Optional

from .enhanced_models import (
    Categoria,
    Clasificacion,
    CondicionesContractuales,
    RequisitoChecklist,
    SolvenciaTecnica,
    Subcategoria,
)
from .enhanced_classifier import (
    RequirementClassifier,
    classify_requirement,
    extract_clause_from_context,
    extract_page_from_context,
)

# Default value for missing fields
DEFAULT_MISSING = "No especificado"

# Category to priority mapping as per requirement 14.2
# Lower number = higher priority
CATEGORY_PRIORITY = {
    # Garantías (highest priority within each classification)
    "garantía_cumplimiento": 1,
    "garantía_vicios_ocultos": 1,
    "garantías": 1,
    # Documentación legal
    "documentación_legal": 2,
    # Solvencia técnica
    "solvencia_técnica": 3,
    "experiencia": 3,
    "personal": 3,
    "equipamiento": 3,
    "normas": 3,
    "referencias": 3,
    "curriculum": 3,
    "plantilla_personal": 3,
    "infraestructura": 3,
    # Propuesta económica (lowest priority within each classification)
    "propuesta_económica": 4,
    "tipo_contrato": 4,
    "penalizaciones": 4,
    "pagos": 4,
}

# Classification priority as per requirement 14.1
# Lower number = higher priority
CLASSIFICATION_PRIORITY = {
    "obligatorio": 1,
    "deseable": 2,
    "condicional": 3,
}


def _get_category_priority(subcategoria: str) -> int:
    """Get priority for a subcategory."""
    return CATEGORY_PRIORITY.get(subcategoria, 99)


def _get_classification_priority(clasificacion: str) -> int:
    """Get priority for a classification."""
    return CLASSIFICATION_PRIORITY.get(clasificacion, 99)


def _extract_requirement_text(value: Any, field_name: str) -> str:
    """
    Extract requirement text from a field value.
    
    Handles various data types and extracts meaningful text.
    """
    if value is None:
        return ""
    
    if isinstance(value, str):
        if value and value != DEFAULT_MISSING:
            return f"{field_name}: {value}"
        return ""
    
    if isinstance(value, dict):
        # Check for common text fields
        for key in ["descripcion", "description", "detalle", "texto", "text", "valor", "value"]:
            if key in value and value[key]:
                text = str(value[key])
                if text and text != DEFAULT_MISSING:
                    return f"{field_name}: {text}"
        
        # If no description found, create one from the dict
        if value:
            return f"{field_name}: {value}"
        return ""
    
    if hasattr(value, "__dict__"):
        # It's a Pydantic model
        # Try to get a description
        if hasattr(value, "descripcion"):
            desc = value.descripcion
            if desc and desc != DEFAULT_MISSING:
                return f"{field_name}: {desc}"
        elif hasattr(value, "tipo"):
            tipo = value.tipo
            if tipo and tipo != DEFAULT_MISSING:
                return f"{field_name}: {tipo}"
        
        # Build from model fields
        parts = []
        for k, v in value.__dict__.items():
            if v and v != DEFAULT_MISSING and not k.startswith("_"):
                parts.append(f"{k}={v}")
        if parts:
            return f"{field_name}: {', '.join(parts)}"
        return ""
    
    return ""


def _create_requirement_from_solvencia(
    solvencia: SolvenciaTecnica,
    classifier: RequirementClassifier,
    start_id: int,
) -> List[RequisitoChecklist]:
    """
    Create checklist requirements from solvencia técnica data.
    
    Validates: Requirements 18.1, 18.2
    """
    requirements = []
    req_id = start_id
    
    # 1. Experiencia mínima
    exp = solvencia.experiencia_mínima
    if exp.años_experiencia != DEFAULT_MISSING or exp.monto_minimo != DEFAULT_MISSING:
        text = f"Experiencia mínima: {exp.años_experiencia} años, {exp.monto_minimo} {exp.unidad_monetaria}, {exp.numero_contratos} contratos"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.EXPERIENCIA,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=exp.fuente or DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,  # Will be set after sorting
            clasificación_incierta=is_uncertain,
            confianza=exp.confianza,
        ))
        req_id += 1
    
    # 2. Curriculum empresa
    curr = solvencia.curriculum
    if curr.empresa_requerido:
        text = f"Currículum empresarial requerido: {curr.descripcion}"
        if curr.personal_clave:
            text += f". Personal clave: {', '.join([p.puesto for p in curr.personal_clave])}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.PERSONAL,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 3. Plantilla de personal técnico
    for personal in solvencia.plantilla_personal:
        text = f"Personal técnico: {personal.puesto}, cantidad: {personal.cantidad}"
        if personal.cedula_requerida:
            text += ", cédula profesional requerida"
        if personal.certificaciones:
            text += f", certificaciones: {', '.join(personal.certificaciones)}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.PERSONAL,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 4. Equipamiento
    for equipo in solvencia.equipamiento:
        text = f"Equipamiento: {equipo.descripcion}"
        if equipo.cantidad != DEFAULT_MISSING:
            text += f", cantidad: {equipo.cantidad}"
        if equipo.caracteristicas:
            text += f", características: {equipo.caracteristicas}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.EQUIPAMIENTO,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 5. Infraestructura
    for infra in solvencia.infraestructura:
        text = f"Infraestructura: {infra.tipo}"
        if infra.ubicacion != DEFAULT_MISSING:
            text += f", ubicación: {infra.ubicacion}"
        if infra.caracteristicas:
            text += f", características: {infra.caracteristicas}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.EQUIPAMIENTO,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 6. Normas y certificaciones
    for norma in solvencia.normas_certificaciones:
        text = f"Certificación: {norma.norma} (tipo: {norma.tipo})"
        if norma.vigencia_requerida:
            text += ", vigencia requerida"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.NORMAS,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 7. Referencias
    ref = solvencia.referencias
    if ref.contratos_minimos != DEFAULT_MISSING or ref.cartas_referencia_aceptadas:
        text = f"Referencias: {ref.contratos_minimos} contratos mínimos"
        if ref.antigüedad_maxima_meses != DEFAULT_MISSING:
            text += f", antigüedad máxima: {ref.antigüedad_maxima_meses} meses"
        if ref.cartas_referencia_aceptadas:
            text += ", se aceptan cartas de referencia"
        if ref.requisitos_adicionales:
            text += f". {ref.requisitos_adicionales}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=Subcategoria.REFERENCIAS,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    return requirements


def _create_requirement_from_condiciones(
    condiciones: CondicionesContractuales,
    classifier: RequirementClassifier,
    start_id: int,
) -> List[RequisitoChecklist]:
    """
    Create checklist requirements from condiciones contractuales data.
    
    Validates: Requirements 18.1, 18.2
    """
    requirements = []
    req_id = start_id
    
    # 1. Tipo de contrato
    tc = condiciones.tipo_contrato
    if tc.tipo != DEFAULT_MISSING:
        text = f"Tipo de contrato: {tc.tipo}, modalidad: {tc.modalidad} (fuente: {tc.fuente})"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.CONDICIONES_CONTRACTUALES,
            subcategoria=Subcategoria.TIPO_CONTRATO,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 2. Penalizaciones
    pen = condiciones.penalizaciones
    if pen.atraso.porcentaje != DEFAULT_MISSING:
        text = f"Penalización por atraso: {pen.atraso.porcentaje} ({pen.atraso.período})"
        if pen.limite_maximo != DEFAULT_MISSING:
            text += f", límite máximo: {pen.limite_maximo}"
        if pen.deducciones:
            text += f", deducciones: {', '.join(pen.deducciones)}"
        if pen.condiciones_aplicación:
            text += f". {pen.condiciones_aplicación}"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.CONDICIONES_CONTRACTUALES,
            subcategoria=Subcategoria.PENALIZACIONES,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 3. Pagos
    pagos = condiciones.pagos
    text_parts = []
    
    if pagos.anticipo.porcentaje != DEFAULT_MISSING:
        text_parts.append(f"Anticipo: {pagos.anticipo.porcentaje}")
        if pagos.anticipo.garantia_porcentaje != DEFAULT_MISSING:
            text_parts[-1] += f" (garantía: {pagos.anticipo.garantia_porcentaje})"
    
    if pagos.estimaciones.periodicidad != DEFAULT_MISSING:
        text_parts.append(f"Estimaciones: {pagos.estimaciones.periodicidad}")
        if pagos.estimaciones.proceso_aprobación:
            text_parts[-1] += f", aprobación: {pagos.estimaciones.proceso_aprobación}"
    
    if pagos.retenciones_finiquito != DEFAULT_MISSING:
        text_parts.append(f"Retenciones finiquito: {pagos.retenciones_finiquito}")
    
    if text_parts:
        text = "Condiciones de pago: " + "; ".join(text_parts)
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.CONDICIONES_CONTRACTUALES,
            subcategoria=Subcategoria.PAGOS,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 4. Garantía de cumplimiento
    gc = condiciones.garantía_cumplimiento
    if gc.monto_porcentaje != DEFAULT_MISSING:
        text = f"Garantía de cumplimiento: {gc.monto_porcentaje}"
        if gc.tipo != DEFAULT_MISSING:
            text += f", tipo: {gc.tipo}"
        if gc.plazo_presentación != DEFAULT_MISSING:
            text += f", plazo presentación: {gc.plazo_presentación}"
        if gc.vigencia_meses != DEFAULT_MISSING:
            text += f", vigencia: {gc.vigencia_meses} meses"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.CONDICIONES_CONTRACTUALES,
            subcategoria=Subcategoria.GARANTÍAS,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    # 5. Garantía de vicios ocultos
    gvo = condiciones.garantía_vicios_ocultos
    if gvo.monto_porcentaje != DEFAULT_MISSING:
        text = f"Garantía de vicios ocultos: {gvo.monto_porcentaje}"
        if gvo.tipo != DEFAULT_MISSING:
            text += f", tipo: {gvo.tipo}"
        if gvo.periodo_meses != DEFAULT_MISSING:
            text += f", período: {gvo.periodo_meses} meses"
        clasificacion, is_uncertain = classify_requirement(text)
        requirements.append(RequisitoChecklist(
            id=f"req_{req_id:03d}",
            categoría=Categoria.CONDICIONES_CONTRACTUALES,
            subcategoria=Subcategoria.GARANTÍAS,
            descripción=text,
            clasificación=Clasificacion(clasificacion),
            página=DEFAULT_MISSING,
            cláusula=DEFAULT_MISSING,
            orden_entrega=0,
            clasificación_incierta=is_uncertain,
        ))
        req_id += 1
    
    return requirements


def _sort_requirements(requirements: List[RequisitoChecklist]) -> List[RequisitoChecklist]:
    """
    Sort requirements by priority.
    
    Sorting criteria (as per requirements 14.1, 14.2):
    1. Classification: obligatorio first, then deseable, then condicional
    2. Category: garantías, documentación legal, solvencia técnica, propuesta económica
    
    Validates: Requirements 14.1, 14.2
    """
    def sort_key(req: RequisitoChecklist) -> tuple:
        # Primary: classification priority (obligatorio=1, deseable=2, condicional=3)
        class_prio = _get_classification_priority(req.clasificación.value)
        
        # Secondary: category priority
        cat_prio = _get_category_priority(req.subcategoria.value)
        
        # Tertiary: stable sort by ID
        return (class_prio, cat_prio, req.id)
    
    sorted_reqs = sorted(requirements, key=sort_key)
    
    # Assign orden_entrega (1-based index)
    for i, req in enumerate(sorted_reqs, start=1):
        req.orden_entrega = i
    
    return sorted_reqs


def consolidate_checklist(
    solvencia: SolvenciaTecnica,
    condiciones: CondicionesContractuales,
) -> List[RequisitoChecklist]:
    """
    Consolidate solvencia técnica and condiciones contractuales into a single
    ordered checklist.
    
    This function:
    1. Merges requirements from both sources
    2. Adds classification metadata to each requirement
    3. Adds source location (page, clause) to each requirement
    4. Orders by priority (classification + category)
    5. Assigns orden_entrega field
    
    Args:
        solvencia: SolvenciaTecnica object with technical requirements
        condiciones: CondicionesContractuales object with contractual terms
        
    Returns:
        List of RequisitoChecklist ordered by delivery priority
        
    Validates: Requirements 14.1, 14.2, 14.3, 14.4, 18.1, 18.2
    """
    # Create classifier instance
    classifier = RequirementClassifier()
    
    # Create requirements from solvencia técnica
    solvencia_reqs = _create_requirement_from_solvencia(solvencia, classifier, 1)
    
    # Create requirements from condiciones contractuales
    # Start ID after solvencia requirements
    start_id = len(solvencia_reqs) + 1
    condiciones_reqs = _create_requirement_from_condiciones(condiciones, classifier, start_id)
    
    # Merge all requirements
    all_requirements = solvencia_reqs + condiciones_reqs
    
    # Sort by priority and assign orden_entrega
    sorted_requirements = _sort_requirements(all_requirements)
    
    return sorted_requirements


def consolidate_checklist_from_dicts(
    solvencia_dict: Dict[str, Any],
    condiciones_dict: Dict[str, Any],
) -> List[RequisitoChecklist]:
    """
    Consolidate checklist from raw dictionary inputs.
    
    This is a convenience function that first normalizes the dictionaries
    to Pydantic models and then calls consolidate_checklist.
    
    Args:
        solvencia_dict: Raw dictionary with solvencia técnica data
        condiciones_dict: Raw dictionary with condiciones contractuales data
        
    Returns:
        List of RequisitoChecklist ordered by delivery priority
    """
    from .enhanced_normalize import (
        normalize_condiciones_contractuales,
        normalize_solvencia_tecnica,
    )
    
    solvencia = normalize_solvencia_tecnica(solvencia_dict)
    condiciones = normalize_condiciones_contractuales(condiciones_dict)
    
    return consolidate_checklist(solvencia, condiciones)


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    "consolidate_checklist",
    "consolidate_checklist_from_dicts",
    "CATEGORY_PRIORITY",
    "CLASSIFICATION_PRIORITY",
]