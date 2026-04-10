"""
Slots obligatorios del piloto Hito 4 (FormatsAgent — formatos administrativos).

Funciones puras para validación en tests y reutilización desde el agente.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Orden estable: mismo orden en missing_fields y pending_questions
PILOT_SLOT_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "rfc",
        "RFC oficial de la empresa",
        "Necesito el dato **RFC oficial de la empresa** para poder generar tus formatos administrativos correctamente.",
        "Consulta tu Constancia de Situación Fiscal o Acta Constitutiva.",
    ),
    (
        "domicilio_fiscal",
        "Domicilio Fiscal completo",
        "Necesito el dato **Domicilio Fiscal completo** para poder generar tus formatos administrativos correctamente.",
        "Consulta tu Constancia de Situación Fiscal o comprobante de domicilio.",
    ),
    (
        "representante_legal",
        "Nombre del Representante Legal",
        "Necesito el dato **Nombre del Representante Legal** para poder generar tus formatos administrativos correctamente.",
        "Consulta tu Acta Constitutiva o poder notarial.",
    ),
)


def _is_empty_profile_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def list_missing_formats_pilot_slots(master_profile: Optional[Dict[str, Any]]) -> List[str]:
    """
    Devuelve las claves de slots obligatorios que faltan en ``master_profile``.
    """
    mp = master_profile or {}
    missing: List[str] = []
    for field, _label, _q, _hint in PILOT_SLOT_SPECS:
        if _is_empty_profile_value(mp.get(field)):
            missing.append(field)
    return missing


def build_formats_pilot_missing_entries(
    master_profile: Optional[Dict[str, Any]],
    *,
    blocking_job_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Construye entradas para ``data.missing`` / ``pending_questions`` (Hito 4).

    Cada ítem incluye ``type: profile_field`` y opcionalmente ``blocking_job_id``.
    """
    mp = master_profile or {}
    out: List[Dict[str, Any]] = []
    for field, label, question, hint in PILOT_SLOT_SPECS:
        if not _is_empty_profile_value(mp.get(field)):
            continue
        entry: Dict[str, Any] = {
            "field": field,
            "label": label,
            "question": question,
            "document_hint": hint,
            "type": "profile_field",
        }
        if blocking_job_id:
            entry["blocking_job_id"] = blocking_job_id
        out.append(entry)
    return out
