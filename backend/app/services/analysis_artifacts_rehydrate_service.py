"""
Rehidratación idempotente de artefactos de análisis (post invalidación / re-análisis).

Reconstruye candidatos, checklist de hitos y preguntas de junta sin borrar HITL económico
ni estado de generación.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)

PRESERVED_TOP_LEVEL_KEYS = (
    "economic_user_inputs",
    "generation_state",
    "go_no_go_override",
    "go_no_go_result",
    "session_line_items",
    "economic_user_overrides",
)


@dataclass
class RehydrateStepResult:
    """Resultado de un paso individual de rehidratación."""

    step: str
    ok: bool
    detail: str = ""


@dataclass
class RehydrateAnalysisArtifactsResult:
    """Resultado agregado de ``rehydrate_analysis_artifacts``."""

    session_id: str
    success: bool
    steps: List[RehydrateStepResult] = field(default_factory=list)
    counts: Dict[str, Any] = field(default_factory=dict)
    snapshot_committed: bool = False
    preserved_keys_intact: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "success": self.success,
            "steps": [
                {"step": s.step, "ok": s.ok, "detail": s.detail} for s in self.steps
            ],
            "counts": self.counts,
            "snapshot_committed": self.snapshot_committed,
            "preserved_keys_intact": self.preserved_keys_intact,
            "error": self.error,
        }


def _count_candidates(state: Dict[str, Any]) -> Dict[str, int]:
    cand = (
        state.get("document_candidates_consolidated")
        or state.get("document_candidates_v1")
        or state.get("document_candidates_final")
        or {}
    )
    if not isinstance(cand, dict):
        return {"sobre_1_tecnico": 0, "candidate_document_list": 0}
    flat = cand.get("candidate_document_list") or []
    return {
        "sobre_1_tecnico": len(cand.get("sobre_1_tecnico") or []),
        "candidate_document_list": len(flat) if isinstance(flat, list) else 0,
    }


def _count_junta(state: Dict[str, Any]) -> int:
    bundle = state.get("junta_aclaraciones_questions") or {}
    if not isinstance(bundle, dict):
        return 0
    items = bundle.get("items") or []
    return len(items) if isinstance(items, list) else 0


def _count_hitos(state: Dict[str, Any]) -> int:
    block = state.get("submission_checklist") or {}
    if not isinstance(block, dict):
        return 0
    hitos = block.get("hitos") or []
    return len(hitos) if isinstance(hitos, list) else 0


def _preserved_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in PRESERVED_TOP_LEVEL_KEYS:
        val = state.get(key)
        if isinstance(val, dict):
            out[key] = len(val)
        elif isinstance(val, list):
            out[key] = len(val)
        elif val is not None:
            out[key] = 1
        else:
            out[key] = 0
    return out


def _preserved_intact(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    for key in PRESERVED_TOP_LEVEL_KEYS:
        if before.get(key, 0) != after.get(key, 0):
            return False
    return True


REHYDRATE_STOP_REASON = "ANALYSIS_REHYDRATE_INCOMPLETE"


async def rehydrate_after_analysis_pipeline(
    memory: Any,
    session_id: str,
    *,
    company_id: Optional[str] = None,
    commit_snapshot: bool = True,
    force_junta_refresh: bool = False,
) -> RehydrateAnalysisArtifactsResult:
    """
    Hook estándar tras compliance exitoso en orquestador o re-análisis manual.

    Si falla, persiste ``last_orchestrator_decision`` con ``ANALYSIS_REHYDRATE_INCOMPLETE``
    y no confirma snapshot (delegado a ``rehydrate_analysis_artifacts``).
    """
    result = await rehydrate_analysis_artifacts(
        memory,
        session_id,
        company_id=company_id,
        commit_snapshot=commit_snapshot,
        force_junta_refresh=force_junta_refresh,
    )
    if not result.success:
        await memory.save_session(
            session_id,
            {
                "last_orchestrator_decision": {
                    "stop_reason": REHYDRATE_STOP_REASON,
                    "aggregate_health": "degraded",
                    "rehydrate_error": result.error,
                    "rehydrate_failed_steps": [
                        s.step for s in result.steps if not s.ok
                    ],
                },
            },
        )
    return result


async def rehydrate_analysis_artifacts(
    memory: Any,
    session_id: str,
    *,
    company_id: Optional[str] = None,
    include_mini_dictamen: bool = True,
    commit_snapshot: bool = True,
    force_junta_refresh: bool = False,
) -> RehydrateAnalysisArtifactsResult:
    """
    Reconstruye artefactos derivados del análisis de bases.

    Pasos:
      1. ``ensure_session_document_candidates``
      2. ``ensure_session_cronograma_and_checklist``
      3. ``build_and_persist_junta_aclaraciones_questions`` (+ mini dictamen si aplica)
      4. Mini dictamen explícito si ``include_mini_dictamen`` y aún falta
      5. ``commit_bases_analysis_snapshot`` si pasos 1–3 OK y ``commit_snapshot``

    Idempotente: puede invocarse varias veces sin borrar capturas HITL ni generación.
    """
    steps: List[RehydrateStepResult] = []
    session = await memory.get_session(session_id)
    if not session:
        return RehydrateAnalysisArtifactsResult(
            session_id=session_id,
            success=False,
            error="session_not_found",
        )

    preserved_before = _preserved_snapshot(session)
    cml = session.get("compliance_master_list")
    has_compliance = isinstance(cml, dict) and any(
        cml.get(z) for z in ("administrativo", "tecnico", "formatos")
    )
    if not has_compliance:
        return RehydrateAnalysisArtifactsResult(
            session_id=session_id,
            success=False,
            steps=[
                RehydrateStepResult(
                    step="precheck",
                    ok=False,
                    detail="compliance_master_list_missing",
                )
            ],
            error="compliance_master_list_missing",
            preserved_keys_intact=True,
        )

    # --- 1. Candidatos de documentos ---
    candidates_ok = False
    try:
        from app.services.document_candidate_list_service import (
            ensure_session_document_candidates,
        )

        session = await memory.get_session(session_id) or session
        rebuilt = await ensure_session_document_candidates(
            memory, session_id, session
        )
        session = await memory.get_session(session_id) or session
        counts_c = _count_candidates(session)
        candidates_ok = bool(
            rebuilt
            or counts_c["sobre_1_tecnico"] > 0
            or counts_c["candidate_document_list"] > 0
        )
        steps.append(
            RehydrateStepResult(
                step="document_candidates",
                ok=candidates_ok,
                detail=f"sobre_1={counts_c['sobre_1_tecnico']} flat={counts_c['candidate_document_list']}",
            )
        )
    except Exception as exc:
        logger.warning(
            "rehydrate_document_candidates_failed session=%s err=%s",
            session_id,
            str(exc)[:200],
        )
        steps.append(
            RehydrateStepResult(
                step="document_candidates",
                ok=False,
                detail=str(exc)[:200],
            )
        )

    # --- 2. Checklist / hitos ---
    checklist_ok = False
    try:
        from app.checklist.submission_checklist_service import (
            ensure_session_cronograma_and_checklist,
        )

        cl = await ensure_session_cronograma_and_checklist(memory, session_id)
        session = await memory.get_session(session_id) or session
        n_hitos = len(cl.hitos) if cl else _count_hitos(session)
        checklist_ok = n_hitos > 0
        steps.append(
            RehydrateStepResult(
                step="submission_checklist",
                ok=checklist_ok,
                detail=f"hitos={n_hitos}",
            )
        )
    except Exception as exc:
        logger.warning(
            "rehydrate_checklist_failed session=%s err=%s",
            session_id,
            str(exc)[:200],
        )
        steps.append(
            RehydrateStepResult(
                step="submission_checklist",
                ok=False,
                detail=str(exc)[:200],
            )
        )

    # --- 3. Junta de aclaraciones (incluye mini dictamen si hace falta) ---
    junta_ok = False
    try:
        from app.services.junta_aclaraciones_questions_service import (
            build_and_persist_junta_aclaraciones_questions,
        )

        bundle = await build_and_persist_junta_aclaraciones_questions(
            memory,
            session_id,
            company_id=company_id,
            force_refresh=force_junta_refresh,
        )
        session = await memory.get_session(session_id) or session
        n_junta = len(bundle.items) if bundle else _count_junta(session)
        junta_ok = n_junta > 0
        steps.append(
            RehydrateStepResult(
                step="junta_aclaraciones_questions",
                ok=junta_ok,
                detail=f"items={n_junta}",
            )
        )
    except Exception as exc:
        logger.warning(
            "rehydrate_junta_failed session=%s err=%s",
            session_id,
            str(exc)[:200],
        )
        steps.append(
            RehydrateStepResult(
                step="junta_aclaraciones_questions",
                ok=False,
                detail=str(exc)[:200],
            )
        )

    # --- 4. Mini dictamen (opcional explícito) ---
    if include_mini_dictamen:
        mini_ok = False
        try:
            session = await memory.get_session(session_id) or session
            if isinstance(session.get("mini_dictamen_anexos"), dict):
                mini_ok = True
                steps.append(
                    RehydrateStepResult(
                        step="mini_dictamen_anexos",
                        ok=True,
                        detail="already_present",
                    )
                )
            else:
                from app.services.mini_dictamen_anexos_service import (
                    build_and_persist_mini_dictamen,
                )

                await build_and_persist_mini_dictamen(memory, session_id)
                session = await memory.get_session(session_id) or session
                mini_ok = isinstance(session.get("mini_dictamen_anexos"), dict)
                steps.append(
                    RehydrateStepResult(
                        step="mini_dictamen_anexos",
                        ok=mini_ok,
                        detail="built" if mini_ok else "missing_after_build",
                    )
                )
        except Exception as exc:
            logger.warning(
                "rehydrate_mini_dictamen_failed session=%s err=%s",
                session_id,
                str(exc)[:200],
            )
            steps.append(
                RehydrateStepResult(
                    step="mini_dictamen_anexos",
                    ok=False,
                    detail=str(exc)[:200],
                )
            )

    core_ok = candidates_ok and checklist_ok and junta_ok
    snapshot_committed = False

    session = await memory.get_session(session_id) or session
    preserved_after = _preserved_snapshot(session)
    preserved_intact = _preserved_intact(preserved_before, preserved_after)

    if core_ok and commit_snapshot:
        try:
            from app.services.session_bases_analysis_invalidation import (
                commit_bases_analysis_snapshot,
            )

            documents = await memory.get_documents(session_id) or []
            snap = commit_bases_analysis_snapshot(session, documents)
            patch: Dict[str, Any] = {
                "bases_analysis_snapshot": snap,
                "rehydrate_last_error": None,
                "rehydrate_last_success_at": snap.get("committed_at"),
            }
            await memory.save_session(session_id, patch)
            snapshot_committed = True
            steps.append(
                RehydrateStepResult(
                    step="bases_analysis_snapshot",
                    ok=True,
                    detail="pending_reanalysis=false",
                )
            )
        except Exception as exc:
            logger.warning(
                "rehydrate_snapshot_commit_failed session=%s err=%s",
                session_id,
                str(exc)[:200],
            )
            steps.append(
                RehydrateStepResult(
                    step="bases_analysis_snapshot",
                    ok=False,
                    detail=str(exc)[:200],
                )
            )
    elif not core_ok:
        err_msg = "core_steps_incomplete"
        await memory.save_session(
            session_id,
            {
                "rehydrate_last_error": {
                    "error": err_msg,
                    "steps": [s.step for s in steps if not s.ok],
                }
            },
        )
    else:
        await memory.save_session(
            session_id,
            {"rehydrate_last_error": None},
        )

    session = await memory.get_session(session_id) or session
    counts = {
        "compliance": {
            k: len((session.get("compliance_master_list") or {}).get(k) or [])
            for k in ("administrativo", "tecnico", "formatos")
            if isinstance(session.get("compliance_master_list"), dict)
        },
        "candidates": _count_candidates(session),
        "hitos": _count_hitos(session),
        "junta_items": _count_junta(session),
        "mini_dictamen": bool(session.get("mini_dictamen_anexos")),
    }

    result = RehydrateAnalysisArtifactsResult(
        session_id=session_id,
        success=core_ok and preserved_intact,
        steps=steps,
        counts=counts,
        snapshot_committed=snapshot_committed,
        preserved_keys_intact=preserved_intact,
        error=None if core_ok else "core_steps_incomplete",
    )
    logger.info(
        "analysis_artifacts_rehydrated",
        session_id=session_id,
        success=result.success,
        hitos=counts.get("hitos"),
        junta=counts.get("junta_items"),
        snapshot_committed=snapshot_committed,
    )
    return result
