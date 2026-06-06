"""
Invalidación universal de artefactos de análisis cuando cambian las bases de la sesión.

Evita reutilizar ``stage_completed:analysis/compliance`` de un PDF distinto o ausente.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.document_catalog import DocumentCatalogRole

_BASES_FILENAME_RE = re.compile(
    r"(?i)(^bases\b|\bbases\b|convocatoria|pliego|licitacion|licitaci[oó]n|"
    r"la-\d+|lpn-|n-\d+-\d{4})"
)

_ANALYSIS_TASK_EXACT = frozenset(
    {
        "stage_completed:analysis",
        "stage_completed:compliance",
        "analisis_bases",
        "master_compliance_list",
        "go_no_go_result",
    }
)

_SESSION_KEYS_TO_CLEAR = (
    "compliance_master_list",
    "compliance_recovery_source",
    "document_inventory",
    "intake_plan",
    "analyst_result",
    "analysis_result",
    "forensic_dictamen",
    "dictamen_forense",
    "go_no_go_result",
    "mini_dictamen_anexos",
    "delivery_coverage_report",
    "junta_aclaraciones_questions",
    "last_orchestrator_decision",
)
# Capturas HITL y progreso de generación NO se borran aquí (por diseño):
#   economic_user_inputs, session_line_items, generation_state, pending_questions
# (salvo invalidación explícita vía orquestador cuando cambian las bases).


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _catalog_by_doc_id(session_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    catalog = session_state.get("document_catalog") or {}
    items = catalog.get("items") or []
    out: Dict[str, Dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict) and it.get("doc_id"):
            out[str(it["doc_id"])] = it
    return out


def _template_catalog_by_doc_id(session_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    cat = session_state.get("session_template_catalog") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for it in cat.get("items") or []:
        if isinstance(it, dict) and it.get("doc_id"):
            out[str(it["doc_id"])] = it
    return out


def is_bases_pliego_document(
    doc: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """True si el documento es la convocatoria/bases (universal, sin mapa por licitación)."""
    if not isinstance(doc, dict):
        return False
    doc_id = str(doc.get("id") or "")
    state = session_state or {}
    cat = _catalog_by_doc_id(state).get(doc_id) or {}
    role = str(cat.get("role") or "")
    if role == DocumentCatalogRole.TENDER_BASES.value:
        return True
    tmpl = _template_catalog_by_doc_id(state).get(doc_id) or {}
    if str(tmpl.get("document_class") or "") == "pliego_referencia":
        return True
    content = doc.get("content") or {}
    fn = str(content.get("filename") or doc.get("metadata", {}).get("filename") or "")
    if not fn.lower().endswith(".pdf"):
        return False
    blob = fn.lower()
    if _BASES_FILENAME_RE.search(blob):
        return True
    text_len = len(str(content.get("extracted_text") or ""))
    if text_len >= 8000 and re.search(r"(?i)\b(convocatoria|bases|anexo\s+no\.?)\b", blob):
        return True
    return False


def collect_bases_documents(
    documents: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Documentos de bases de la sesión; si no hay rol, el PDF analizado más sustancial."""
    state = session_state or {}
    tagged = [d for d in documents if is_bases_pliego_document(d, state)]
    if tagged:
        return tagged
    pdfs = [
        d
        for d in documents
        if str((d.get("content") or {}).get("filename") or "").lower().endswith(".pdf")
        and str((d.get("content") or {}).get("status") or "") == "ANALYZED"
    ]
    if not pdfs:
        return []
    pdfs.sort(
        key=lambda d: len(str((d.get("content") or {}).get("extracted_text") or "")),
        reverse=True,
    )
    return [pdfs[0]]


def compute_bases_fingerprint(
    documents: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Huella estable del set de bases analizadas."""
    bases = collect_bases_documents(documents, session_state)
    if not bases:
        return ""
    parts: List[Dict[str, Any]] = []
    for d in sorted(bases, key=lambda x: str(x.get("id") or "")):
        c = d.get("content") or {}
        parts.append(
            {
                "id": str(d.get("id") or ""),
                "filename": str(c.get("filename") or ""),
                "text_len": len(str(c.get("extracted_text") or "")),
                "status": str(c.get("status") or ""),
                "path_tail": os.path.basename(str(c.get("file_path") or "")),
            }
        )
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _has_analysis_artifacts(session_state: Dict[str, Any]) -> bool:
    if any(session_state.get(k) for k in ("compliance_master_list", "analyst_result", "forensic_dictamen", "dictamen_forense")):
        return True
    for task in session_state.get("tasks_completed") or []:
        if not isinstance(task, dict):
            continue
        tn = str(task.get("task") or "")
        if tn in _ANALYSIS_TASK_EXACT or tn.startswith("stage_completed:analysis") or tn.startswith("stage_completed:compliance"):
            return True
    return False


def strip_analysis_artifacts(session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Elimina hitos y artefactos de análisis/compliance obsoletos."""
    out = dict(session_state)
    audit: Dict[str, Any] = {"tasks_removed": [], "keys_cleared": []}

    tasks = out.get("tasks_completed")
    if isinstance(tasks, list):
        filtered: List[Dict[str, Any]] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tn = str(t.get("task") or "")
            if tn in _ANALYSIS_TASK_EXACT:
                audit["tasks_removed"].append(tn)
                continue
            filtered.append(t)
        out["tasks_completed"] = filtered

    for key in _SESSION_KEYS_TO_CLEAR:
        if key in out:
            out.pop(key, None)
            audit["keys_cleared"].append(key)

    return out, audit


def bases_analysis_committed(session_state: Dict[str, Any]) -> bool:
    """True si el análisis/compliance quedó confirmado para la huella actual."""
    snap = session_state.get("bases_analysis_snapshot") or {}
    return bool(snap.get("fingerprint")) and not bool(snap.get("pending_reanalysis"))


def bases_fingerprint_matches_stored(
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> bool:
    """True si la huella actual coincide con la última análisis confirmada."""
    current = compute_bases_fingerprint(documents, session_state)
    if not current:
        return True
    snap = session_state.get("bases_analysis_snapshot") or {}
    stored = str(snap.get("fingerprint") or "")
    return bool(stored) and stored == current


def should_hard_reset_session_artifacts(
    *,
    mode: str,
    resume_generation: bool,
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> bool:
    """
    True si conviene limpiar cola/inventario/capturas al iniciar análisis ``full``.

    ``analysis_only`` y ``generation*`` nunca hard-resetean.
    Con bases sin cambio se preservan ``economic_user_inputs`` y progreso HITL.
    """
    if mode != "full" or resume_generation:
        return False
    return not bases_fingerprint_matches_stored(session_state, documents)


def should_invalidate_analysis_artifacts(
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> bool:
    """True si hay artefactos de análisis desalineados con las bases actuales."""
    current = compute_bases_fingerprint(documents, session_state)
    if not current:
        return False
    snap = session_state.get("bases_analysis_snapshot") or {}
    stored = str(snap.get("fingerprint") or "")
    if stored == current:
        return False
    if not _has_analysis_artifacts(session_state):
        return False
    return True


def apply_analysis_invalidation(
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    reason: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Limpia artefactos stale y marca re-análisis pendiente."""
    cleaned, audit = strip_analysis_artifacts(session_state)
    current = compute_bases_fingerprint(documents, session_state)
    cleaned["bases_analysis_snapshot"] = {
        "fingerprint": current,
        "pending_reanalysis": True,
        "invalidated_at": _utc_now_iso(),
        "reason": reason,
    }
    audit["invalidated"] = True
    audit["reason"] = reason
    audit["fingerprint"] = current
    return cleaned, audit


def commit_bases_analysis_snapshot(
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Confirma huella tras análisis/compliance exitoso sobre las bases actuales."""
    current = compute_bases_fingerprint(documents, session_state)
    snap = dict(session_state.get("bases_analysis_snapshot") or {})
    if current:
        snap["fingerprint"] = current
    snap["pending_reanalysis"] = False
    snap["committed_at"] = _utc_now_iso()
    return snap


async def sync_bases_analysis_state(
    memory: Any,
    session_id: str,
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    persist: bool = True,
    reason: str = "bases_fingerprint_changed",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Invalida análisis obsoleto si las bases cambiaron. Persiste en sesión si ``persist``.
    """
    meta: Dict[str, Any] = {"action": "unchanged", "invalidated": False}
    if should_invalidate_analysis_artifacts(session_state, documents):
        cleaned, audit = apply_analysis_invalidation(session_state, documents, reason=reason)
        meta = {"action": "invalidated", **audit}
        if persist:
            await memory.save_session(session_id, cleaned)
        return cleaned, meta
    current = compute_bases_fingerprint(documents, session_state)
    if current and not session_state.get("bases_analysis_snapshot"):
        snap = {
            "fingerprint": current,
            "pending_reanalysis": True,
            "initialized_at": _utc_now_iso(),
        }
        session_state = {**session_state, "bases_analysis_snapshot": snap}
        meta = {"action": "snapshot_initialized", "fingerprint": current}
        if persist:
            await memory.save_session(session_id, {"bases_analysis_snapshot": snap})
    return session_state, meta


async def force_invalidate_analysis_artifacts(
    memory: Any,
    session_id: str,
    *,
    reason: str = "manual_force_reanalysis",
) -> Dict[str, Any]:
    """Fuerza limpieza de artefactos de análisis (p. ej. re-análisis manual)."""
    session_state = await memory.get_session(session_id) or {}
    documents = await memory.get_documents(session_id) or []
    cleaned, audit = apply_analysis_invalidation(session_state, documents, reason=reason)
    await memory.save_session(session_id, cleaned)
    return audit
