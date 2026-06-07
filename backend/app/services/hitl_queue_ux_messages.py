"""
Mensajes UX centralizados para cola HITL (Ítem C.14 / C.11).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.chat_gate5_formatter import format_gate5_message
from app.services.chat_stop_reason_map import single_cta_for_context


def message_for_economic_pending_redirect(
    question: Dict[str, Any],
    *,
    total: int,
    index: int,
) -> str:
    """Cuando hay precio pendiente y el usuario pregunta algo que no es bases."""
    label = str(question.get("label") or question.get("question") or "Precio pendiente")
    return format_gate5_message(
        status="Hay captura económica activa; priorizo tus precios antes de consultas generales.",
        detail=f"Concepto actual ({index + 1}/{total}): **{label}**.",
        cta=single_cta_for_context(has_economic_pending=True),
    )


def message_queue_empty_ready(*, stop_reason: Optional[str] = None) -> str:
    """Cola vacía y listo para siguiente acción."""
    return format_gate5_message(
        status="No hay datos pendientes en la cola conversacional.",
        cta=single_cta_for_context(stop_reason=stop_reason, has_economic_pending=False),
    )


def message_physical_checklist_only(count: int) -> str:
    """Credenciales físicas van al panel, no al chat."""
    suffix = f" ({count} ítems)" if count else ""
    return format_gate5_message(
        status=f"Los documentos de presentación física{suffix} están en el panel de credenciales empresariales.",
        cta="Revísalos ahí y continúa con la captura de precios o generación cuando corresponda.",
    )
