"""
go_no_go_scorer.py — Módulo stateless puro para el Semáforo Go/No-Go.

Calcula brechas críticas, estado del semáforo y score de cumplimiento técnico
de forma determinista, sin LLM, sin acceso a base de datos y sin efectos secundarios.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Dataclasses de salida
# ---------------------------------------------------------------------------

@dataclass
class Brecha:
    """Representa una brecha entre un requisito de las bases y el perfil maestro."""

    id: str
    categoria: str          # certificacion_faltante | capital_insuficiente |
                            # experiencia_insuficiente | documento_faltante |
                            # requisito_no_acreditado
    descripcion: str
    requisito_bases: str    # Texto literal del requisito en las bases
    valor_empresa: Optional[str]
    is_knockout: bool
    zona_origen: str


@dataclass
class CriterioDetalle:
    """Detalle de un criterio de la rúbrica de evaluación."""

    criterio: str
    cumple: bool
    evidencia: Optional[str]
    peso: Optional[str]


@dataclass
class ScoreResult:
    """Resultado del cálculo del score de cumplimiento técnico."""

    score: Optional[int]
    detalle: List[CriterioDetalle] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constantes de clasificación
# ---------------------------------------------------------------------------

_CATEGORIA_PATRONES: List[tuple[str, str]] = [
    (r"certificaci|norma\s|iso\s|nom\s|acreditaci", "certificacion_faltante"),
    (r"capital|patrimonio|financiero|balance|solvencia", "capital_insuficiente"),
    (r"experiencia|años\s|contratos\s+similares|trayectoria", "experiencia_insuficiente"),
    (r"documento|acta|constancia|carta|escrito|poder\s", "documento_faltante"),
]

_ZONA_FALLBACK = "ADMINISTRATIVO/LEGAL"

_ZONAS_VALIDAS = {
    "administrativo": "ADMINISTRATIVO/LEGAL",
    "tecnico": "TÉCNICO/OPERATIVO",
    "formatos": "FORMATOS/ANEXOS",
}

# Campos del master_profile que se mapean a criterios de evaluación comunes
_PROFILE_FIELD_KEYWORDS: List[tuple[str, str]] = [
    (r"rfc|fiscal|sat", "rfc"),
    (r"capital|patrimonio|financiero", "capital_contable"),
    (r"contratos?\s+similares|constancia\s+de\s+contrato|contrato\s+n", "contratos_previos"),
    (r"experiencia|años|trayectoria", "anos_experiencia"),
    (r"empleados|plantilla|trabajadores", "numero_empleados"),
    (r"certificaci|iso|nom|acreditaci", "certificaciones"),
    (r"representante|apoderado|firma", "representante_legal"),
    (r"domicilio|direcci|fiscal", "domicilio_fiscal"),
    (r"imss|patronal|seguro\s+social", "registro_patronal"),
]


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def detect_brechas(
    compliance_data: Dict[str, Any],
    master_profile: Dict[str, Any],
) -> List[Brecha]:
    """Detecta brechas entre los datos de compliance y el perfil maestro.

    Args:
        compliance_data: Salida del ComplianceAgent (claves: administrativo, tecnico,
            formatos, summary con causas_desechamiento).
        master_profile: Perfil maestro de la empresa (master_profile del modelo Company).

    Returns:
        Lista de objetos Brecha ordenada: primero knock-outs, luego el resto.
    """
    brechas: List[Brecha] = []
    profile = master_profile or {}

    # 1. Knock-outs desde causas_desechamiento
    summary = compliance_data.get("summary") or {}
    causas = summary.get("causas_desechamiento") or []
    for item in causas:
        texto = _extract_text(item)
        if not texto:
            continue
        brechas.append(Brecha(
            id=str(uuid.uuid4()),
            categoria=_classify_categoria(texto),
            descripcion=_build_descripcion(texto, profile, is_knockout=True),
            requisito_bases=texto,
            valor_empresa=_lookup_profile_value(texto, profile),
            is_knockout=True,
            zona_origen=_ZONA_FALLBACK,
        ))

    # 2. Requisitos por zona
    for bucket_key, zona_label in _ZONAS_VALIDAS.items():
        items = compliance_data.get(bucket_key) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            texto = _extract_text(item)
            if not texto:
                continue
            valor = _lookup_profile_value(texto, profile)
            if valor is not None:
                continue  # El perfil cubre este requisito — no es brecha
            brechas.append(Brecha(
                id=str(uuid.uuid4()),
                categoria=_classify_categoria(texto),
                descripcion=_build_descripcion(texto, profile, is_knockout=False),
                requisito_bases=texto,
                valor_empresa=None,
                is_knockout=False,
                zona_origen=zona_label,
            ))

    # Knock-outs primero
    brechas.sort(key=lambda b: (0 if b.is_knockout else 1))
    return brechas


def calculate_semaforo(
    brechas: List[Brecha],
) -> Literal["RED", "YELLOW", "GREEN"]:
    """Calcula el estado del semáforo según las brechas detectadas.

    Args:
        brechas: Lista de objetos Brecha producida por detect_brechas.

    Returns:
        "RED" si hay knock-outs, "YELLOW" si hay brechas sin knock-out, "GREEN" si no hay brechas.
    """
    if any(b.is_knockout for b in brechas):
        return "RED"
    if brechas:
        return "YELLOW"
    return "GREEN"


def calculate_score_tecnico(
    criterios_evaluacion: Any,
    master_profile: Dict[str, Any],
    brechas: Optional[List["Brecha"]] = None,
) -> "ScoreResult":
    """Calcula el score de cumplimiento técnico frente a la rúbrica de evaluación.

    Si hay criterios estructurados los usa directamente.
    Si no (ej: "Puntos y Porcentajes"), calcula el score en base a las brechas:
    score = (1 - brechas_no_knockout / total_requisitos) * 100.

    Returns:
        ScoreResult con score 0-100 y detalle por criterio. Si no hay datos, score=None.
    """
    profile = master_profile or {}
    criterios = _normalize_criterios(criterios_evaluacion)

    # Criterios estructurados reales (más de un string genérico)
    criterios_utiles = [
        c for c in criterios
        if not (isinstance(c, str) and c.strip().lower() in (
            "puntos y porcentajes", "puntos", "porcentajes",
            "binario", "costo-beneficio", "no especificado",
        ))
    ]

    if criterios_utiles:
        detalle: List[CriterioDetalle] = []
        cumplidos = 0
        for c in criterios_utiles:
            texto = _extract_text(c)
            peso = _extract_peso(c)
            evidencia_field = _find_profile_field(texto, profile)
            cumple = evidencia_field is not None
            if cumple:
                cumplidos += 1
            detalle.append(CriterioDetalle(
                criterio=texto,
                cumple=cumple,
                evidencia=evidencia_field,
                peso=peso,
            ))
        score = round((cumplidos / len(criterios_utiles)) * 100)
        return ScoreResult(score=score, detalle=detalle)

    # Fallback: calcular desde brechas cuando no hay criterios estructurados
    if brechas:
        total = len(brechas)
        knockouts = sum(1 for b in brechas if b.is_knockout)
        no_acreditados = total - knockouts
        # Score = porcentaje de requisitos sin brecha crítica
        # Penalizar más los knockouts (peso doble)
        penalizacion = (knockouts * 2 + no_acreditados) / max(total * 2, 1)
        score = max(0, round((1 - penalizacion) * 100))
        detalle_brecha = [
            CriterioDetalle(
                criterio=b.requisito_bases[:120] if b.requisito_bases else b.descripcion[:120],
                cumple=False,
                evidencia=None,
                peso="knockout" if b.is_knockout else "normal",
            )
            for b in brechas[:20]  # muestra hasta 20 en detalle
        ]
        return ScoreResult(score=score, detalle=detalle_brecha)

    return ScoreResult(score=None, detalle=[])


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _extract_text(item: Any) -> str:
    """Extrae texto legible de un ítem que puede ser dict o string."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return (
            item.get("descripcion")
            or item.get("nombre")
            or item.get("texto_crudo")
            or item.get("snippet")
            or ""
        ).strip()
    return ""


def _classify_categoria(texto: str) -> str:
    """Clasifica la categoría de una brecha por heurísticas de texto."""
    t = texto.lower()
    for patron, categoria in _CATEGORIA_PATRONES:
        if re.search(patron, t):
            return categoria
    return "requisito_no_acreditado"


def _lookup_profile_value(texto: str, profile: Dict[str, Any]) -> Optional[str]:
    """Busca en el perfil maestro el campo más relevante para el texto del requisito."""
    field_key = _find_profile_field(texto, profile)
    if field_key is None:
        return None
    val = profile.get(field_key)
    if val is None:
        return None
    return str(val)[:200]  # Truncar para presentación


def _find_profile_field(texto: str, profile: Dict[str, Any]) -> Optional[str]:
    """Retorna la clave del perfil maestro que cubre el requisito, o None."""
    if not profile:
        return None
    t = texto.lower()
    for patron, field_key in _PROFILE_FIELD_KEYWORDS:
        if re.search(patron, t) and profile.get(field_key):
            return field_key
    return None


def _build_descripcion(texto: str, profile: Dict[str, Any], *, is_knockout: bool) -> str:
    """Construye la descripción legible de la brecha."""
    prefix = "⛔ Causa de descalificación: " if is_knockout else "⚠️ Requisito no acreditado: "
    return prefix + (texto[:200] if len(texto) > 200 else texto)


def _normalize_criterios(criterios: Any) -> List[Any]:
    """Normaliza criterios_evaluacion a lista, manejando None y strings vacíos."""
    if not criterios:
        return []
    if isinstance(criterios, str):
        if criterios.strip().lower() in ("no especificado", "no especifica", ""):
            return []
        return [criterios]
    if isinstance(criterios, list):
        return [c for c in criterios if c]
    if isinstance(criterios, dict):
        return [{"descripcion": k, "peso": str(v)} for k, v in criterios.items() if v]
    return []


def _extract_peso(item: Any) -> Optional[str]:
    """Extrae el peso/porcentaje de un criterio si está disponible."""
    if isinstance(item, dict):
        peso = item.get("peso") or item.get("puntaje") or item.get("porcentaje")
        return str(peso) if peso is not None else None
    return None
