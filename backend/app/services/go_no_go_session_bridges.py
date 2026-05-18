"""
go_no_go_session_bridges.py — Alinea company_data del Go/No-Go con evidencia de sesión.

Usado en recálculos fuera del orquestador (chatbot, POST authorize recalculate_only)
para que el semáforo y la métrica de brechas atenuadas sean coherentes con el bridge.
"""
from __future__ import annotations

from typing import Any, Dict

from app.config.settings import settings


async def merge_company_data_with_session_evidence(
    memory: Any,
    session_id: str,
    company_data: Dict[str, Any],
    *,
    persist_evidence_snap: bool = True,
) -> Dict[str, Any]:
    """Fusiona master_profile con evidencia de documentos de sesión (si el bridge está activo).

    Args:
        memory: Repositorio de sesión (get_session, get_documents, save_session).
        session_id: ID de sesión.
        company_data: Payload entrante; se usa ``master_profile`` como línea base.
        persist_evidence_snap: Si True, persiste ``evidence_profile`` y provenance en sesión.

    Returns:
        ``company_data`` actualizado con ``master_profile`` efectivo y, si aplica,
        ``go_no_go_baseline_master_profile`` (copia superficial del maestro previo a la fusión).
    """
    out: Dict[str, Any] = dict(company_data or {})
    baseline = dict(out.get("master_profile") or {})
    if not settings.ENABLE_EVIDENCE_PROFILE_BRIDGE:
        return out
    try:
        from app.services.evidence_profile_service import (
            build_effective_profile,
            build_evidence_profile_from_documents,
        )

        session_snap = await memory.get_session(session_id) or {}
        overrides = session_snap.get("evidence_profile_overrides") or {}
        docs = await memory.get_documents(session_id)
        evidence_profile = build_evidence_profile_from_documents(docs or [])
        effective_profile, provenance = build_effective_profile(
            master_profile=baseline,
            evidence_profile=evidence_profile,
            user_overrides=overrides,
        )
        out["master_profile"] = effective_profile
        out["go_no_go_baseline_master_profile"] = baseline
        if persist_evidence_snap:
            snap = await memory.get_session(session_id) or {}
            snap["evidence_profile"] = evidence_profile
            snap["effective_profile_provenance"] = provenance
            await memory.save_session(session_id, snap)
        return out
    except Exception:
        out["master_profile"] = baseline
        return out
