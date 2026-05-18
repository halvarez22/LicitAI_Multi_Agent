"""
enhanced_models.py — Enhanced Analyst Agent Data Models

Pydantic models for:
- Solvencia Técnica (technical solvency requirements)
- Condiciones Contractuales (contractual conditions)
- Checklist Consolidado (consolidated checklist with classification)

Requirements: 16.1, 16.2, 17.1, 17.2, 18.1, 18.2
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Enums for Checklist Consolidado
# =============================================================================


class Categoria(str, Enum):
    """Categoría principal del requisito en el checklist consolidado."""
    SOLVENCIA_TÉCNICA = "solvencia_técnica"
    CONDICIONES_CONTRACTUALES = "condiciones_contractuales"


class Subcategoria(str, Enum):
    """Subcategoría específica del requisito."""
    # Solvencia técnica
    EXPERIENCIA = "experiencia"
    PERSONAL = "personal"
    EQUIPAMIENTO = "equipamiento"
    NORMAS = "normas"
    REFERENCIAS = "referencias"
    # Condiciones contractuales
    TIPO_CONTRATO = "tipo_contrato"
    PENALIZACIONES = "penalizaciones"
    PAGOS = "pagos"
    GARANTÍAS = "garantías"


class Clasificacion(str, Enum):
    """Clasificación de prioridad del requisito."""
    OBLIGATORIO = "obligatorio"
    DESEABLE = "deseable"
    CONDICIONAL = "condicional"


# =============================================================================
# Solvencia Técnica Models
# =============================================================================


class ExperienciaMinima(BaseModel):
    """
    Requisito de experiencia mínima en contratos similares.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
    """
    años_experiencia: str = Field(
        default="No especificado",
        description="Años mínimos de experiencia requeridos"
    )
    monto_minimo: str = Field(
        default="No especificado",
        description="Monto mínimo de contratos anteriores"
    )
    numero_contratos: str = Field(
        default="No especificado",
        description="Número mínimo de contratos similares requeridos"
    )
    unidad_monetaria: str = Field(
        default="No especificado",
        description="Unidad monetaria del monto mínimo (MXN, USD, etc.)"
    )
    confianza: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Nivel de confianza de la extracción [0-1]"
    )
    fuente: str = Field(
        default="",
        description="Fuente de la extracción (página, cláusula)"
    )


class PersonalClave(BaseModel):
    """
    Posición de personal clave requerida.
    
    Validates: Requirements 2.2, 2.3, 2.4
    """
    puesto: str = Field(..., description="Nombre del puesto o posición")
    experiencia_años: str = Field(
        default="No especificado",
        description="Años de experiencia requeridos para el puesto"
    )
    titulo_requerido: bool = Field(
        default=False,
        description="Indica si se requiere título profesional"
    )
    titulo_descripcion: str = Field(
        default="",
        description="Descripción del título o carrera requerida"
    )


class CurriculumEmpresa(BaseModel):
    """
    Requisitos de currículum empresarial y personal clave.
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
    """
    empresa_requerido: bool = Field(
        default=False,
        description="Indica si se requiere currículum de la empresa"
    )
    descripcion: str = Field(
        default="",
        description="Descripción de lo que debe incluir el currículum"
    )
    personal_clave: List[PersonalClave] = Field(
        default_factory=list,
        description="Lista de posiciones de personal clave requeridas"
    )


class PlantillaPersonal(BaseModel):
    """
    Plantilla de personal técnico con certificaciones.
    
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
    """
    puesto: str = Field(..., description="Nombre del puesto técnico")
    cantidad: str = Field(
        default="No especificado",
        description="Cantidad de personas requeridas para el puesto"
    )
    cedula_requerida: bool = Field(
        default=False,
        description="Indica si se requiere cédula profesional"
    )
    certificaciones: List[str] = Field(
        default_factory=list,
        description="Lista de certificaciones requeridas"
    )


class Equipamiento(BaseModel):
    """
    Equipo o herramienta requerida.
    
    Validates: Requirements 4.1, 4.3
    """
    descripcion: str = Field(..., description="Descripción del equipo o herramienta")
    cantidad: str = Field(
        default="No especificado",
        description="Cantidad o capacidad requerida"
    )
    caracteristicas: str = Field(
        default="",
        description="Características técnicas específicas"
    )


class Infraestructura(BaseModel):
    """
    Infraestructura física requerida.
    
    Validates: Requirements 4.2, 4.3
    """
    tipo: str = Field(
        ...,
        description="Tipo de infraestructura (oficina, almacén, planta, etc.)"
    )
    ubicacion: str = Field(
        default="No especificado",
        description="Ubicación requerida"
    )
    caracteristicas: str = Field(
        default="",
        description="Características de la infraestructura"
    )


class NormaCertificacion(BaseModel):
    """
    Norma o certificación requerida.
    
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
    """
    norma: str = Field(..., description="Identificador de la norma o certificación")
    tipo: str = Field(
        default="No especificado",
        description="Tipo de norma (ISO, NOM, NMX, etc.)"
    )
    vigencia_requerida: bool = Field(
        default=False,
        description="Indica si la certificación debe estar vigente"
    )


class Referencias(BaseModel):
    """
    Requisitos de contratos o cartas de referencia.
    
    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5
    """
    contratos_minimos: str = Field(
        default="No especificado",
        description="Número mínimo de contratos de referencia requeridos"
    )
    antigüedad_maxima_meses: str = Field(
        default="No especificado",
        description="Antigüedad máxima de los contratos aceptados como referencia"
    )
    cartas_referencia_aceptadas: bool = Field(
        default=False,
        description="Indica si se aceptan cartas de referencia en lugar de contratos"
    )
    requisitos_adicionales: str = Field(
        default="",
        description="Requisitos adicionales para las referencias"
    )


class SolvenciaTecnica(BaseModel):
    """
    Estructura unificada de solvencia técnica.
    
    Consolidates all technical capability requirements extracted from bidding documents.
    
    Validates: Requirements 16.1, 16.2, 16.3
    """
    experiencia_mínima: ExperienciaMinima = Field(
        default_factory=ExperienciaMinima,
        description="Requisitos de experiencia mínima en contratos similares"
    )
    curriculum: CurriculumEmpresa = Field(
        default_factory=CurriculumEmpresa,
        description="Requisitos de currículum empresarial y personal clave"
    )
    plantilla_personal: List[PlantillaPersonal] = Field(
        default_factory=list,
        description="Plantilla de personal técnico requerido"
    )
    equipamiento: List[Equipamiento] = Field(
        default_factory=list,
        description="Lista de equipamiento requerido"
    )
    infraestructura: List[Infraestructura] = Field(
        default_factory=list,
        description="Lista de infraestructura requerida"
    )
    normas_certificaciones: List[NormaCertificacion] = Field(
        default_factory=list,
        description="Lista de normas y certificaciones requeridas"
    )
    referencias: Referencias = Field(
        default_factory=Referencias,
        description="Requisitos de contratos o cartas de referencia"
    )


# =============================================================================
# Condiciones Contractuales Models
# =============================================================================


class TipoContrato(BaseModel):
    """
    Tipo de contrato especificado.
    
    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """
    tipo: str = Field(
        default="No especificado",
        description="Tipo de contrato (precio fijo, precio alzado, por administración, etc.)"
    )
    modalidad: str = Field(
        default="No especificado",
        description="Modalidad del contrato (abierto/cerrado)"
    )
    fuente: str = Field(
        default="explícito",
        description="Fuente de la información (explícito/inferido)"
    )


class PenalizacionAtraso(BaseModel):
    """
    Penalización por atraso.
    
    Validates: Requirements 8.1, 8.4
    """
    porcentaje: str = Field(
        default="No especificado",
        description="Porcentaje de penalización por atraso"
    )
    período: str = Field(
        default="No especificado",
        description="Período de aplicación (días naturales/hábiles)"
    )


class Penalizaciones(BaseModel):
    """
    Condiciones de penalizaciones y deducciones.
    
    Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
    """
    atraso: PenalizacionAtraso = Field(
        default_factory=PenalizacionAtraso,
        description="Penalización por atraso"
    )
    deducciones: List[str] = Field(
        default_factory=list,
        description="Lista de deducciones específicas aplicables"
    )
    limite_maximo: str = Field(
        default="No especificado",
        description="Límite máximo de penalizaciones acumulables"
    )
    condiciones_aplicación: str = Field(
        default="",
        description="Condiciones bajo las cuales se aplican las penalizaciones"
    )


class Anticipo(BaseModel):
    """
    Condiciones de anticipo.
    
    Validates: Requirements 9.1, 9.2
    """
    porcentaje: str = Field(
        default="No especificado",
        description="Porcentaje máximo de anticipo autorizado"
    )
    garantia_porcentaje: str = Field(
        default="No especificado",
        description="Porcentaje de garantía requerida para el anticipo"
    )


class Estimaciones(BaseModel):
    """
    Condiciones de pago por estimaciones.
    
    Validates: Requirements 9.3
    """
    periodicidad: str = Field(
        default="No especificado",
        description="Periodicidad de los pagos (quincenal, mensual, etc.)"
    )
    proceso_aprobación: str = Field(
        default="",
        description="Proceso de aprobación de estimaciones"
    )


class Pagos(BaseModel):
    """
    Condiciones de pago.
    
    Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
    """
    anticipo: Anticipo = Field(
        default_factory=Anticipo,
        description="Condiciones de anticipo"
    )
    estimaciones: Estimaciones = Field(
        default_factory=Estimaciones,
        description="Condiciones de pago por estimaciones"
    )
    retenciones_finiquito: str = Field(
        default="No especificado",
        description="Retenciones aplicables en el finiquito"
    )


class GarantiaCumplimiento(BaseModel):
    """
    Garantía de cumplimiento.
    
    Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
    """
    monto_porcentaje: str = Field(
        default="No especificado",
        description="Monto de la garantía como porcentaje del contrato"
    )
    tipo: str = Field(
        default="No especificado",
        description="Tipo de garantía (fianza, garantía líquida, carta de crédito, etc.)"
    )
    plazo_presentación: str = Field(
        default="No especificado",
        description="Plazo de presentación después de la notificación de fallo"
    )
    vigencia_meses: str = Field(
        default="No especificado",
        description="Período de vigencia requerido de la garantía"
    )


class GarantiaViciosOcultos(BaseModel):
    """
    Garantía de vicios ocultos.
    
    Validates: Requirements 11.1, 11.2, 11.3, 11.4
    """
    monto_porcentaje: str = Field(
        default="No especificado",
        description="Monto o porcentaje de la garantía"
    )
    tipo: str = Field(
        default="No especificado",
        description="Tipo de garantía para vicios ocultos"
    )
    periodo_meses: str = Field(
        default="No especificado",
        description="Período de garantía de vicios ocultos"
    )


class CondicionesContractuales(BaseModel):
    """
    Estructura unificada de condiciones contractuales.
    
    Consolidates all contractual terms extracted from bidding documents.
    
    Validates: Requirements 17.1, 17.2, 17.3
    """
    tipo_contrato: TipoContrato = Field(
        default_factory=TipoContrato,
        description="Tipo de contrato especificado"
    )
    penalizaciones: Penalizaciones = Field(
        default_factory=Penalizaciones,
        description="Condiciones de penalizaciones"
    )
    pagos: Pagos = Field(
        default_factory=Pagos,
        description="Condiciones de pago"
    )
    garantía_cumplimiento: GarantiaCumplimiento = Field(
        default_factory=GarantiaCumplimiento,
        description="Garantía de cumplimiento"
    )
    garantía_vicios_ocultos: GarantiaViciosOcultos = Field(
        default_factory=GarantiaViciosOcultos,
        description="Garantía de vicios ocultos"
    )


# =============================================================================
# Checklist Consolidado Models
# =============================================================================


class RequisitoChecklist(BaseModel):
    """
    Un requisito individual en el checklist consolidado.
    
    Validates: Requirements 18.1, 18.2, 18.3
    """
    id: str = Field(..., description="Identificador único del requisito")
    categoría: Categoria = Field(
        ...,
        description="Categoría principal del requisito"
    )
    subcategoria: Subcategoria = Field(
        ...,
        description="Subcategoría específica del requisito"
    )
    descripción: str = Field(..., description="Texto literal del requisito")
    clasificación: Clasificacion = Field(
        default=Clasificacion.OBLIGATORIO,
        description="Clasificación de prioridad del requisito"
    )
    página: str = Field(
        default="No especificado",
        description="Número de página donde aparece el requisito"
    )
    cláusula: str = Field(
        default="No especificado",
        description="Número de cláusula o inciso"
    )
    orden_entrega: int = Field(
        ...,
        ge=0,
        description="Posición en el checklist ordenado para entrega"
    )
    clasificación_incierta: bool = Field(
        default=False,
        description="Indica si la clasificación no pudo determinarse claramente"
    )
    confianza: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Nivel de confianza de la extracci��n [0-1]"
    )


# =============================================================================
# Strategic Audit Models
# =============================================================================


class AlertaDescalificacion(BaseModel):
    """
    Alerta proactiva sobre una posible causa de descalificación detectada.
    """
    motivo: str = Field(..., description="Motivo del riesgo de descalificación")
    pagina: int = Field(default=0, description="Página donde se detectó el riesgo")
    gravedad: str = Field(..., description="Nivel de gravedad: ALTA/MEDIA")
    sugerencia: str = Field(..., description="Acción sugerida para mitigar el riesgo o aclarar")


class GapAnalysisItem(BaseModel):
    """
    Resultado de contrastar un requisito de las bases contra el perfil de la empresa.
    """
    requisito: str = Field(..., description="Requisito extraído de las bases")
    estado_empresa: str = Field(..., description="Estado actual en el perfil: FALTANTE/VENCIDO/OK")
    accion_requerida: str = Field(..., description="Acción recomendada para el usuario")


class AuditReport(BaseModel):
    """
    Reporte estratégico consolidado del Auditor de LicitAI.
    """
    pensamiento_estrategico: str = Field(..., description="Análisis breve de la 'malicia' o complejidad de las bases")
    indice_de_viabilidad: int = Field(default=0, description="Índice de viabilidad de ganar (1-100)")
    alertas_descalificacion: List[AlertaDescalificacion] = Field(
        default_factory=list,
        description="Lista de alertas críticas de descalificación"
    )
    gap_analysis: List[GapAnalysisItem] = Field(
        default_factory=list,
        description="Contraste de requisitos vs. perfil de empresa"
    )
    preguntas_junta_aclaraciones: List[str] = Field(
        default_factory=list,
        description="Lista de preguntas sugeridas para la junta de aclaraciones"
    )


# =============================================================================
# Helper Functions
# =============================================================================


def create_default_solvencia_tecnica() -> SolvenciaTecnica:
    """Creates a SolvenciaTecnica with all default values."""
    return SolvenciaTecnica()


def create_default_condiciones_contractuales() -> CondicionesContractuales:
    """Creates a CondicionesContractuales with all default values."""
    return CondicionesContractuales()


def create_empty_checklist() -> List[RequisitoChecklist]:
    """Creates an empty checklist list."""
    return []