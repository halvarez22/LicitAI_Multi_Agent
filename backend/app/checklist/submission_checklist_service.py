"""
Persistencia y reglas de negocio del checklist de hitos (sesión → submission_checklist).
"""
from __future__ import annotations

import asyncio
import logging
from app.core.logging_config import get_logger
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.checklist.hito_scheduler import (
    aplicar_estados_vencido,
    build_hitos_from_cronograma,
    calcular_porcentaje,
    merge_hitos_preservar_completados,
)
from app.checklist.models import HitoModel, MarkHitoPayload, SubmissionChecklistModel

logger = get_logger(__name__)

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


async def _load_bases_corpus_text(
    memory: Any,
    session_id: str,
    session: Optional[Dict[str, Any]] = None,
) -> str:
    """Texto concatenado de bases/convocatoria para extracción determinista de fechas."""
    state = session if session is not None else await memory.get_session(session_id)
    if not state:
        return ""
    try:
        from app.services.junta_bases_corpus import build_bases_corpus

        docs = await memory.get_documents(session_id) or []
        corpus = build_bases_corpus(session_id, docs, session_state=state)
        return str(corpus.combined or "")
    except Exception as exc:
        logger.warning(
            "cronograma_bases_corpus_failed session=%s err=%s",
            session_id,
            str(exc)[:200],
        )
        return ""


def _cronograma_from_bases_text(bases_text: str) -> Optional[Dict[str, str]]:
    """
    Cronograma determinista cuando el Analyst no persistió ``cronograma`` (p. ej. JSON parse error).
    """
    from app.services.cronograma_bases_extract import (
        cronograma_has_extracted_dates,
        extract_cronograma_from_bases_text,
    )

    blob = str(bases_text or "").strip()
    if not blob:
        return None
    extracted = extract_cronograma_from_bases_text(blob)
    if not cronograma_has_extracted_dates(extracted):
        return None
    return extracted


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

    cronograma_merged = cronograma
    try:
        from app.services.cronograma_bases_extract import merge_cronograma_with_bases
        from app.services.junta_bases_corpus import build_bases_corpus

        docs = await memory.get_documents(session_id) or []
        corpus = build_bases_corpus(session_id, docs, session_state=session)
        if (corpus.combined or "").strip():
            cronograma_merged = merge_cronograma_with_bases(cronograma, corpus.combined)
    except Exception as exc:
        logger.warning(
            "checklist_cronograma_merge_failed session=%s err=%s",
            session_id,
            str(exc)[:200],
        )

    nuevos_raw = build_hitos_from_cronograma(cronograma_merged)
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


async def _persist_cronograma_in_session(
    memory: Any,
    session_id: str,
    cronograma: Dict[str, str],
) -> None:
    """Actualiza cronograma en ``tasks_completed:analysis`` y reconstruye checklist."""
    session = await memory.get_session(session_id) or {}
    tasks = session.get("tasks_completed") or []
    updated_tasks: List[Dict[str, Any]] = []
    touched = False
    for t in tasks:
        if not isinstance(t, dict):
            updated_tasks.append(t)
            continue
        if t.get("task") != "stage_completed:analysis":
            updated_tasks.append(t)
            continue
        result = t.get("result")
        if not isinstance(result, dict):
            updated_tasks.append(t)
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            updated_tasks.append(t)
            continue
        new_data = dict(data)
        new_data["cronograma"] = dict(cronograma)
        new_result = dict(result)
        new_result["data"] = new_data
        updated_tasks.append({**t, "result": new_result})
        touched = True
    if touched:
        session["tasks_completed"] = updated_tasks
        await memory.save_session(session_id, session)
    await upsert_checklist_from_cronograma(
        memory,
        session_id,
        cronograma,
        licitation_id=session.get("name"),
        merge=bool(session.get("submission_checklist")),
    )


def _checklist_has_placeholder_dates(block: Dict[str, Any]) -> bool:
    """True si la mayoría de hitos guardados no tienen fecha utilizable."""
    from app.services.cronograma_enrichment_service import is_placeholder_cronograma_value

    hitos = block.get("hitos") if isinstance(block.get("hitos"), list) else []
    if not hitos:
        return True
    bad = sum(
        1
        for h in hitos
        if isinstance(h, dict) and is_placeholder_cronograma_value(h.get("fecha_texto_raw"))
    )
    return bad >= max(2, (len(hitos) + 1) // 2)


async def ensure_session_cronograma_and_checklist(
    memory: Any,
    session_id: str,
) -> Optional[SubmissionChecklistModel]:
    """
    Enriquece cronograma desde RAG si quedó en placeholders y sincroniza checklist.
    """
    from app.services.cronograma_enrichment_service import (
        cronograma_improved,
        cronograma_needs_enrichment,
        enrich_cronograma_from_rag,
    )

    session = await memory.get_session(session_id)
    if not session:
        return None

    cron: Optional[Dict[str, Any]] = None
    tasks = session.get("tasks_completed") or []
    for t in reversed(tasks):
        if t.get("task") != "stage_completed:analysis":
            continue
        cron = _cronograma_from_analysis_result(t.get("result"))
        break

    if cron is None and isinstance(session.get("submission_checklist"), dict):
        # Sin cronograma en analysis pero checklist persistido: devolver tal cual.
        # refresh_placeholders=False evita reentrar aquí vía get_submission_checklist (RecursionError).
        return await get_submission_checklist(
            memory, session_id, auto_sync=False, refresh_placeholders=False
        )

    bases_text = await _load_bases_corpus_text(memory, session_id, session)

    if cron is None and bases_text.strip():
        cron = _cronograma_from_bases_text(bases_text)
        if cron:
            logger.info(
                "cronograma_bases_fallback_applied",
                session_id=session_id,
                hitos_con_fecha=sum(
                    1 for v in cron.values() if str(v or "").strip()
                ),
            )

    if cron is not None and bases_text.strip():
        from app.services.cronograma_bases_extract import merge_cronograma_with_bases
        from app.services.cronograma_enrichment_service import cronograma_dates_changed

        merged = merge_cronograma_with_bases(cron, bases_text)
        if cronograma_improved(cron, merged) or cronograma_dates_changed(cron, merged):
            await _persist_cronograma_in_session(memory, session_id, merged)
            cron = merged

    if cron is not None and cronograma_needs_enrichment(cron):
        from app.config.settings import settings
        from app.services.cronograma_enrichment_service import cronograma_dates_changed

        timeout_s = float(settings.CRONOGRAMA_ENRICHMENT_TIMEOUT_S or 12.0)
        try:
            enriched = await asyncio.wait_for(
                asyncio.to_thread(
                    enrich_cronograma_from_rag,
                    session_id,
                    cron,
                    bases_text=bases_text or None,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "cronograma_enrichment_timeout",
                session_id=session_id,
                timeout_s=timeout_s,
            )
            return await get_submission_checklist(
                memory, session_id, auto_sync=False, refresh_placeholders=False
            )
        if cronograma_improved(cron, enriched) or cronograma_dates_changed(cron, enriched):
            await _persist_cronograma_in_session(memory, session_id, enriched)
            logger.info(
                "cronograma_enriched_from_rag",
                session_id=session_id,
                hitos_con_fecha=sum(
                    1 for v in enriched.values() if str(v).strip() and str(v) != "No especificado"
                ),
            )
    return await get_submission_checklist(
        memory, session_id, auto_sync=True, refresh_placeholders=False
    )


def _checklist_has_untrusted_dates(block: Dict[str, Any], bases_text: str) -> bool:
    """True si algún hito tiene año no verificable en el corpus (p. ej. 2023 en bases 2026)."""
    from app.services.cronograma_bases_extract import _cronograma_year_unsupported_by_corpus

    if not str(bases_text or "").strip():
        return False
    hitos = block.get("hitos") if isinstance(block.get("hitos"), list) else []
    for h in hitos:
        if not isinstance(h, dict):
            continue
        raw = str(h.get("fecha_texto_raw") or h.get("nombre") or "")
        if _cronograma_year_unsupported_by_corpus(raw, bases_text):
            return True
    return False


def checklist_ready_without_enrichment(
    session: Dict[str, Any],
    *,
    bases_text: str = "",
) -> bool:
    """
    True si el checklist persistido puede servirse sin enrichment RAG del cronograma.
    Usado por GET /dictamen para evitar trabajo síncrono pesado en el worker único.
    """
    block = session.get(SESSION_KEY)
    if not isinstance(block, dict) or not block.get("hitos"):
        return False
    if _checklist_has_placeholder_dates(block):
        return False
    if _checklist_has_untrusted_dates(block, bases_text):
        return False
    return True


async def get_submission_checklist(
    memory: Any,
    session_id: str,
    *,
    auto_sync: bool = True,
    refresh_placeholders: bool = True,
) -> Optional[SubmissionChecklistModel]:
    """
    Obtiene el checklist persistido. Si no existe y auto_sync, intenta generarlo desde
    el último stage_completed:analysis.
    """
    session = await memory.get_session(session_id)
    if not session:
        return None
    block = session.get(SESSION_KEY)
    bases_text = await _load_bases_corpus_text(memory, session_id, session)
    if (
        refresh_placeholders
        and isinstance(block, dict)
        and block.get("hitos")
        and (
            _checklist_has_placeholder_dates(block)
            or _checklist_has_untrusted_dates(block, bases_text)
        )
    ):
        # Solo re-enriquecer si aún hay cronograma en el último análisis; si no, usar checklist persistido.
        tasks = session.get("tasks_completed") or []
        has_analysis_cron = any(
            t.get("task") == "stage_completed:analysis"
            and _cronograma_from_analysis_result(t.get("result")) is not None
            for t in reversed(tasks)
            if isinstance(t, dict)
        )
        if has_analysis_cron:
            await ensure_session_cronograma_and_checklist(memory, session_id)
        session = await memory.get_session(session_id) or session
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
            bases_text = await _load_bases_corpus_text(memory, session_id, session)
            cron = _cronograma_from_bases_text(bases_text)
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
