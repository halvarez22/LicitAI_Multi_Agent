"""
Detección de intención de corrección de precios post-entrega (chat HITL Ítem B).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

_CORRECTION_VERBS = (
    "corrige",
    "corregir",
    "cambiar precio",
    "actualiza precio",
    "actualizar precio",
    "recalcular",
    "re-calcular",
    "ajusta el precio",
    "ajustar precio",
)

_CORRECTION_CONTEXT = (
    "precio esta mal",
    "precio está mal",
    "precio incorrecto",
    "precio equivocado",
    "error en mi calculo",
    "error en el calculo",
    "error en mi cálculo",
    "me equivoque",
    "me equivoqué",
    "quiero corregir",
    "como lo corregimos",
    "cómo lo corregimos",
    "regenerar propuesta economica",
    "regenerar propuesta económica",
    "propuesta economica con el precio",
    "propuesta económica con el precio",
    "el precio que te di",
    "precio que te di",
    "precio que les di",
    "corregirlo para regenerar",
)


def _normalize(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def session_ready_for_price_correction(session_state: Dict[str, Any], session_id: str = "") -> bool:
    """
    True si ya hubo propuesta económica materializada (no solo intake inicial).
    """
    stop = str((session_state.get("last_orchestrator_decision") or {}).get("stop_reason") or "")
    if stop in ("FINAL_OK", "GENERATION_COMPLETED"):
        return True
    mps = session_state.get("master_proposal_state") or {}
    if isinstance(mps, dict) and (
        (mps.get("items") and float(mps.get("total_base") or 0) >= 0.01)
        or float(mps.get("total_base") or 0) >= 0.01
    ):
        if mps.get("items"):
            return True
        for task in reversed(session_state.get("tasks_completed") or []):
            if isinstance(task, dict) and task.get("task") in (
                "economic_proposal",
                "stage_completed:economic",
            ):
                return True
        if session_id:
            econ_dir = os.path.join("/data/outputs", session_id, "2.propuesta_economica")
            if os.path.isdir(econ_dir) and any(
                f.lower().endswith((".xlsx", ".docx")) for f in os.listdir(econ_dir)
            ):
                return True
    return False


def detect_price_correction_intent(query: str) -> Optional[Dict[str, Any]]:
    """
    Detecta corrección de precio en lenguaje natural.

    Returns:
        dict con ``new_value`` (float|None), ``needs_price`` (bool), ``raw``.
    """
    q = (query or "").strip()
    if not q:
        return None
    low = _normalize(q)

    has_context = any(m in low for m in _CORRECTION_CONTEXT)
    has_verb = any(v in low for v in _CORRECTION_VERBS)
    if not has_context and not has_verb:
        return None

    m = re.search(
        r"(?:a|en|por|es|de)\s*[\$]?\s*([\d,]+(?:\.\d+)?|\d+\s*mil(?:\s*\d+)?)",
        q,
        flags=re.I,
    )
    new_value = None
    needs_price = True
    if m:
        from app.services.conversational_price_normalizer import normalize_conversational_price

        val, err, _conf = normalize_conversational_price(m.group(1))
        if not err and val:
            new_value = float(val)
            needs_price = False

    field_hint = ""
    fm = re.search(r"zona\s+([a-d])", low)
    if fm:
        field_hint = f"price_struct_service_{fm.group(1).upper()}"

    return {
        "new_value": new_value,
        "needs_price": needs_price,
        "field_hint": field_hint,
        "raw": q,
    }


def build_price_correction_guidance_message(*, needs_price: bool, session_ready: bool) -> str:
    """Mensaje UX cuando falta precio o falta generación previa."""
    if not session_ready:
        return (
            "Sí, puedes corregir precios por chat después de generar la propuesta económica.\n\n"
            "**Paso 1:** Genera la propuesta (botón **Generar Propuesta** o escribe "
            "`generar propuesta económica`).\n"
            "**Paso 2:** Corrige con una frase que incluya el **nuevo importe**, por ejemplo:\n"
            "«**Corrige el precio a 2,600,000**»\n\n"
            "La app recalculará tabla Excel, Anexo AE, APU y carta compromiso para reimprimir."
        )
    if needs_price:
        return (
            "Entendido: quieres corregir un precio ya capturado en la propuesta.\n\n"
            "Escríbelo en una sola línea con el **importe nuevo**, por ejemplo:\n"
            "«**Corrige el precio a 2,600,000**» o «**Cambiar precio a $2,595,000.00**»\n\n"
            "Con eso regenero automáticamente los archivos del sobre económico (sin repetir "
            "técnico ni administrativo)."
        )
    return ""
