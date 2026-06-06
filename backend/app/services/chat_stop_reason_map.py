"""
Mapa ``stop_reason`` → mensaje humano (SUPER ISSUE / Ítem S).
"""

from __future__ import annotations

import re
from typing import Dict, Optional

STOP_REASON_HUMAN: Dict[str, str] = {
    "FINAL_OK": "La generación del expediente terminó correctamente. Puedes revisar y descargar los sobres.",
    "GENERATION_COMPLETED": "La generación del expediente terminó correctamente.",
    "ANALYSIS_COMPLETED": "El análisis de bases está listo. Puedes continuar con la captura de precios o generar documentos.",
    "INCOMPLETE_DATA": "Faltan datos de tu empresa en el perfil (RFC, domicilio, etc.).",
    "INCOMPLETE_FORMAT_DATA": "Faltan campos obligatorios para los formatos administrativos.",
    "MISSING_PRICES": "Hay conceptos económicos sin precio. Completa la cotización en el chat o en resolución por bloque.",
    "MISSING_ECONOMIC_PROPOSAL": "Aún no hay propuesta económica consolidada. Captura los precios pendientes y vuelve a generar.",
    "ECONOMIC_GAP": "Hay discrepancias en el análisis económico que debemos resolver.",
    "COMPLIANCE_ERROR": "Hubo un problema al analizar cumplimiento. Intenta de nuevo en unos minutos.",
    "COMPLIANCE_GATE_BLOCKING": "Hay reglas críticas de cumplimiento que bloquean la generación. Revisa el dictamen en el panel.",
    "PACKAGING_VALIDATION_FAILED": "La validación de empaquetado CompraNet no pasó. Revisa extensiones y archivos en entrega.",
    "IDLE": "Aún no hay un proceso en curso. Puedes subir bases o pedir generar la propuesta.",
    "ECONOMIC_COVERAGE_GAP": (
        "Faltan precios o plantillas económicas por materializar antes de cerrar el expediente. "
        "Completa la matriz de precios y vuelve a generar."
    ),
    "DELIVERY_COVERAGE_GAP": (
        "El paquete validado no incluye todos los anexos exigidos por las bases. "
        "Regenera los formatos faltantes antes de descargar el expediente."
    ),
    "INCOMPLETE_FORMATS_DATA": (
        "Faltan formatos administrativos por generar o contienen datos incompletos. "
        "Revisa los anexos omitidos y vuelve a ejecutar la generación."
    ),
}


def humanize_stop_reason(stop_reason: Optional[str]) -> str:
    key = str(stop_reason or "IDLE").strip()
    return STOP_REASON_HUMAN.get(
        key,
        "El proceso está en pausa. Indica si quieres **cotizar precios** o **generar el expediente**.",
    )


_BANNED_USER_PATTERNS = (
    re.compile(r"Gate\s*12\.1", re.I),
    re.compile(r"\b12\.1\.", re.I),
    re.compile(r"MISSING_[A-Z0-9_]+"),
    re.compile(r"COMPLIANCE_GATE(?:_BLOCKING)?"),
    re.compile(r"_compliance_truth"),
    re.compile(r"\bstop_reason\b", re.I),
    re.compile(r"\b\d{2,4}\s+ítems\b", re.I),
    re.compile(r"\b\d{2,4}\s+items\b", re.I),
)


def sanitize_user_visible_text(text: str) -> str:
    """Elimina códigos internos que no deben mostrarse al licitante."""
    if not text:
        return text
    out = str(text)
    for pat in _BANNED_USER_PATTERNS:
        out = pat.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def single_cta_for_context(
    *,
    stop_reason: Optional[str] = None,
    has_economic_pending: bool = False,
) -> str:
    """Un solo siguiente paso en lenguaje humano."""
    if has_economic_pending:
        return "Responde el precio pendiente en el chat o completa la matriz de precios."
    key = str(stop_reason or "IDLE").strip()
    if key in ("MISSING_ECONOMIC_PROPOSAL", "MISSING_PRICES", "ECONOMIC_COVERAGE_GAP"):
        return "Captura los precios pendientes y vuelve a generar la propuesta económica."
    if key in ("COMPLIANCE_GATE_BLOCKING", "COMPLIANCE_ERROR"):
        return "Revisa el dictamen en el panel central y corrige los hallazgos críticos."
    if key in ("FINAL_OK", "GENERATION_COMPLETED"):
        return "Revisa y descarga los sobres desde el panel de entrega."
    return "Usa el panel **Generar** o escribe «generar propuesta económica» cuando estés listo."


def assert_user_visible_clean(text: str) -> None:
    """CI: falla si el texto visible al usuario contiene códigos internos."""
    sample = text or ""
    banned_check = (
        "Gate 12.1",
        "12.1.",
        "MISSING_",
        "COMPLIANCE_GATE",
        "_compliance_truth",
        "stop_reason",
    )
    for frag in banned_check:
        if frag in sample:
            raise AssertionError(f"Texto de usuario contiene fragmento prohibido: {frag!r}")
