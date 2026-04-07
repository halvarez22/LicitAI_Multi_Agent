"""
Persistencia y reglas de negocio del checklist de hitos (sesión → submission_checklist).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.checklist.hito_scheduler import (
    aplicar_estados_vencido,
    build_hitos_from_cronograma,
    calcular_porcentaje,
    merge_hitos_preservar_completados,
)
from app.checklist.models import HitoModel, MarkHitoPayload, SubmissionChecklistModel

logger = logging.getLogger(__name__)

SESSION_KEY = "submission_checklist"


def _cronograma_from_analysis_result(result: Any) -> Optional[Dict[str, Any]]:
    """Extrae cronograma del dict guardado en stage_completed:analysis."""
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    c = data.get("cronograma")
    return c if isinstance(c, dict) else None


def _hitos_to_model_list(hitos_data: List[Dict[str, Any]]) -> List[HitoModel]:
    return [HitoModel.model_validate(h) for h in hitos_data]


def _model_to_storable(m: SubmissionChecklistModel) -> Dict[str, Any]:
    return m.model_dump(mode="json")


async def upsert_checklist_from_cronograma(
    memory: Any,
    session_id: str,
    cronograma: Any,
    *,
    licitation_id: Optional[str] = None,
    merge: bool = True,
) -> SubmissionChecklistModel:
    """
    Construye o fusiona el checklist desde el cronograma del Analista y guarda en sesión.

    Args:
        memory: adaptador con get_session / save_session.
        session_id: id de licitación.
        cronograma: objeto crudo o normalizado.
        licitation_id: opcional (metadata).
        merge: si True, conserva hitos completados del checklist previo.
    """
    session = await memory.get_session(session_id) or {}
    prev_block = session.get(SESSION_KEY)
    prev_hitos: List[Dict[str, Any]] = []
    if isinstance(prev_block, dict) and isinstance(prev_block.get("hitos"), list):
        prev_hitos = [h for h in prev_block["hitos"] if isinstance(h, dict)]

    nuevos_raw = build_hitos_from_cronograma(cronograma)
    if merge and prev_hitos:
        merged = merge_hitos_preservar_completados(nuevos_raw, prev_hitos)
    else:
        merged = list(nuevos_raw)

    aplicar_estados_vencido(merged)
    pct = calcular_porcentaje(merged)

    lic_id = licitation_id
    if lic_id is None and isinstance(session.get("name"), str):
        lic_id = session.get("name")

    model = SubmissionChecklistModel(
        licitation_id=lic_id,
        hitos=_hitos_to_model_list(merged),
        ultima_actualizacion=datetime.utcnow(),
        porcentaje_completado=pct,
    )
    session[SESSION_KEY] = _model_to_storable(model)
    await memory.save_session(session_id, session)
    return model


async def get_submission_checklist(
    memory: Any,
    session_id: str,
    *,
    auto_sync: bool = True,
) -> Optional[SubmissionChecklistModel]:
    """
    Obtiene el checklist persistido. Si no existe y auto_sync, intenta generarlo desde
    el último stage_completed:analysis.
    """
    session = await memory.get_session(session_id)
    if not session:
        return None
    block = session.get(SESSION_KEY)
    if isinstance(block, dict) and block.get("hitos"):
        try:
            m = SubmissionChecklistModel.model_validate(block)
            # Refrescar vencidos al leer
            hitos_d = [h.model_dump() for h in m.hitos]
            aplicar_estados_vencido(hitos_d)
            m = SubmissionChecklistModel(
                licitation_id=m.licitation_id,
                hitos=_hitos_to_model_list(hitos_d),
                ultima_actualizacion=datetime.utcnow(),
                porcentaje_completado=calcular_porcentaje(hitos_d),
            )
            session[SESSION_KEY] = _model_to_storable(m)
            await memory.save_session(session_id, session)
            return m
        except Exception as e:
            logger.warning("submission_checklist_parse_failed", session_id=session_id, error=str(e))

    if auto_sync:
        return await sync_checklist_from_last_analysis(memory, session_id)
    return None


async def sync_checklist_from_last_analysis(
    memory: Any,
    session_id: str,
) -> Optional[SubmissionChecklistModel]:
    """Si hay análisis persistido con cronograma, crea el checklist (sin fusionar si no había previo)."""
    session = await memory.get_session(session_id)
    if not session:
        return None
    tasks = session.get("tasks_completed") or []
    for t in reversed(tasks):
        if t.get("task") != "stage_completed:analysis":
            continue
        cron = _cronograma_from_analysis_result(t.get("result"))
        if cron is None:
            return None
        had = bool(session.get(SESSION_KEY))
        return await upsert_checklist_from_cronograma(
            memory,
            session_id,
            cron,
            merge=had,
        )
    return None


async def mark_hito(
    memory: Any,
    session_id: str,
    hito_id: str,
    payload: MarkHitoPayload,
) -> Optional[SubmissionChecklistModel]:
    """Marca un hito (pendiente | completado) y opcional evidencia."""
    session = await memory.get_session(session_id)
    if not session or SESSION_KEY not in session:
        synced = await sync_checklist_from_last_analysis(memory, session_id)
        if not synced:
            return None
        session = await memory.get_session(session_id) or session

    block = session.get(SESSION_KEY)
    if not isinstance(block, dict):
        return None
    try:
        model = SubmissionChecklistModel.model_validate(block)
    except Exception:
        return None

    hitos_d = [h.model_dump() for h in model.hitos]
    found = False
    for h in hitos_d:
        if h.get("id") == hito_id:
            h["estado"] = payload.estado
            if payload.estado == "pendiente":
                h["evidencia"] = None
            elif payload.evidencia is not None:
                h["evidencia"] = payload.evidencia.strip() or None
            found = True
            break
    if not found:
        return None

    aplicar_estados_vencido(hitos_d)
    out = SubmissionChecklistModel(
        licitation_id=model.licitation_id,
        hitos=_hitos_to_model_list(hitos_d),
        ultima_actualizacion=datetime.utcnow(),
        porcentaje_completado=calcular_porcentaje(hitos_d),
    )
    session[SESSION_KEY] = _model_to_storable(out)
    await memory.save_session(session_id, session)
    return out
