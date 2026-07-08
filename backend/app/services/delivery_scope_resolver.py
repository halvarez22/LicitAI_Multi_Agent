"""
Resolución HRU de artefactos descargables por alcance (F5.2).

Traduce disco + sesión → lista canónica para ``GET /downloads/artifacts``.
Sin reglas por licitación; política en ``delivery_scope_policy.json``.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

from app.services.delivery_scope_policy import (
    allowed_delivery_extensions,
    contextual_download_enabled,
    directory_display_name,
    directory_sort_order,
    empty_reason_message,
    generation_jobs_hint_for_scope,
    include_compranet_sobres_for_scope,
    include_directories_for_scope,
    include_root_logistics_for_scope,
    max_artifacts_list,
    normalize_delivery_scope,
    policy_version,
    prefer_compranet_validated_for_scope,
    scope_label,
    load_delivery_ux_messages,
)
from app.services.output_delivery_view import (
    COMPRANET_VALIDATED_DIR,
    _iter_files_under,
    _read_packaging_coverage,
    _sha256_file,
    has_compranet_validated,
)

_JOB_LABELS = {
    "technical": "Propuesta técnica",
    "formats": "Formatos administrativos",
    "economic_writer": "Propuesta económica",
    "packager": "Empaquetado CompraNet",
    "delivery": "Guía de entrega",
}

_JOB_BY_DIR_PREFIX = {
    "1.propuesta tecnica": "technical",
    "1.propuesta_tecnica": "technical",
    "3.documentos administrativos": "formats",
    "2.propuesta_economica": "economic_writer",
    "2.propuesta economica": "economic_writer",
}

_SOBRE_TO_JOB = {
    "SobreComplementaria": "formats",
    "SobreTecnica": "technical",
    "SobreEconomica": "economic_writer",
}


def _nfc_rel(path: str) -> str:
    return path.replace("\\", "/")


def _ext_allowed(filename: str, allowed: Set[str]) -> bool:
    low = filename.lower()
    return any(low.endswith(ext) for ext in allowed)


def _infer_job_id(relative_path: str) -> str:
    rel = _nfc_rel(relative_path)
    if rel.startswith(f"{COMPRANET_VALIDATED_DIR}/"):
        inner = rel[len(COMPRANET_VALIDATED_DIR) + 1 :]
        top = inner.split("/")[0] if "/" in inner else inner
        return _SOBRE_TO_JOB.get(top, "packager")
    top = rel.split("/")[0] if "/" in rel else rel
    return _JOB_BY_DIR_PREFIX.get(top, "delivery")


def _sort_key(relative_path: str) -> Tuple[int, str]:
    rel = _nfc_rel(relative_path)
    top = rel.split("/")[0] if "/" in rel else rel
    if rel.startswith(f"{COMPRANET_VALIDATED_DIR}/"):
        parts = rel.split("/")
        top = parts[1] if len(parts) > 1 else top
    order = directory_sort_order()
    try:
        idx = order.index(top)
    except ValueError:
        idx = len(order) + 1
    return (idx, rel.lower())


def _collect_from_directories(
    session_path: str,
    directories: List[str],
    allowed: Set[str],
) -> List[Tuple[str, str, int, str]]:
    """Retorna tuplas (rel_path, sha256, size, top_dir)."""
    out: List[Tuple[str, str, int, str]] = []
    for directory in directories:
        base = os.path.join(session_path, directory)
        if not os.path.isdir(base):
            continue
        for file_path in sorted(_iter_files_under(base)):
            name = os.path.basename(file_path)
            if not _ext_allowed(name, allowed):
                continue
            rel = _nfc_rel(os.path.relpath(file_path, session_path))
            try:
                digest = _sha256_file(file_path)
                size = os.path.getsize(file_path)
            except OSError:
                continue
            out.append((rel, digest, size, directory))
    return out


def _collect_from_compranet_sobres(
    session_path: str,
    sobres: List[str],
    allowed: Set[str],
) -> List[Tuple[str, str, int, str]]:
    validated_root = os.path.join(session_path, COMPRANET_VALIDATED_DIR)
    if not os.path.isdir(validated_root):
        return []
    wanted = set(sobres)
    out: List[Tuple[str, str, int, str]] = []
    for file_path in sorted(_iter_files_under(validated_root)):
        rel_inner = _nfc_rel(os.path.relpath(file_path, validated_root))
        top = rel_inner.split("/")[0] if "/" in rel_inner else rel_inner
        if wanted and top not in wanted:
            continue
        name = os.path.basename(file_path)
        if not _ext_allowed(name, allowed):
            continue
        rel = _nfc_rel(os.path.join(COMPRANET_VALIDATED_DIR, rel_inner))
        try:
            digest = _sha256_file(file_path)
            size = os.path.getsize(file_path)
        except OSError:
            continue
        out.append((rel, digest, size, top))
    return out


def _collect_root_logistics(
    session_path: str,
    filenames: List[str],
    allowed: Set[str],
) -> List[Tuple[str, str, int, str]]:
    out: List[Tuple[str, str, int, str]] = []
    for name in filenames:
        full = os.path.join(session_path, name)
        if not os.path.isfile(full):
            continue
        if not _ext_allowed(name, allowed):
            continue
        try:
            digest = _sha256_file(full)
            size = os.path.getsize(full)
        except OSError:
            continue
        out.append((name, digest, size, "logistics"))
    return out


def _dedupe_rows(rows: List[Tuple[str, str, int, str]]) -> List[Tuple[str, str, int, str]]:
    seen: Set[str] = set()
    out: List[Tuple[str, str, int, str]] = []
    for rel, digest, size, top in rows:
        if digest in seen:
            continue
        seen.add(digest)
        out.append((rel, digest, size, top))
    out.sort(key=lambda r: _sort_key(r[0]))
    return out[: max_artifacts_list()]


def _generation_jobs_for_scope(session_state: Optional[Dict[str, Any]], scope: str) -> List[str]:
    hints = generation_jobs_hint_for_scope(scope)
    if not isinstance(session_state, dict):
        return []
    gen_state = session_state.get("generation_state")
    if not isinstance(gen_state, dict):
        return []
    jobs = gen_state.get("jobs")
    if not isinstance(jobs, list):
        return []
    done_ids = {
        str(j.get("id"))
        for j in jobs
        if isinstance(j, dict) and str(j.get("status") or "") in ("done", "resumed")
    }
    return [h for h in hints if h in done_ids]


def _infer_empty_reason(
    *,
    scope: str,
    session_state: Optional[Dict[str, Any]],
    artifact_count: int,
) -> Optional[str]:
    if artifact_count > 0:
        return None
    if not contextual_download_enabled():
        return "scope_disabled"
    if scope in ("technical", "full") and _session_has_document_quality_gate_pending(session_state):
        return "document_quality_gate"
    if scope == "economic" and _session_has_price_source_pending(session_state):
        return "prices_required"

    hints = generation_jobs_hint_for_scope(scope)
    if isinstance(session_state, dict):
        gen_state = session_state.get("generation_state")
        if isinstance(gen_state, dict) and isinstance(gen_state.get("jobs"), list):
            statuses = {
                str(j.get("id")): str(j.get("status") or "")
                for j in gen_state["jobs"]
                if isinstance(j, dict) and j.get("id")
            }
            for hint in hints:
                st = statuses.get(hint, "")
                if st == "error":
                    return "job_failed"
                if st == "blocked":
                    return "job_blocked"
            if hints and not any(statuses.get(h) in ("done", "resumed") for h in hints):
                return "generation_not_run"
    return "no_files_on_disk"


def _session_has_document_quality_gate_pending(session_state: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(session_state, dict):
        return False
    pending = session_state.get("pending_questions")
    if not isinstance(pending, list):
        return False
    for q in pending:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "").strip().lower()
        field = str(q.get("field") or "").strip().lower()
        if qtype == "document_quality_gate_blocking" or field == "document_quality_gate":
            return True
    return False


def _session_has_price_source_pending(session_state: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(session_state, dict):
        return False
    pending = session_state.get("pending_questions")
    if not isinstance(pending, list):
        return False
    for q in pending:
        if not isinstance(q, dict):
            continue
        if str(q.get("input_mode") or "").strip().lower() == "price_source":
            return True
        if str(q.get("field") or "").strip() == "economic_price_source":
            return True
    return False


def _build_artifact_row(
    *,
    session_id: str,
    relative_path: str,
    digest: str,
    size: int,
    top_dir: str,
) -> Dict[str, Any]:
    filename = os.path.basename(relative_path)
    job_id = _infer_job_id(relative_path)
    display = directory_display_name(top_dir)
    media_type, _ = mimetypes.guess_type(filename)
    encoded_path = quote(_nfc_rel(relative_path), safe="/")
    sid = quote(session_id, safe="")
    return {
        "id": f"sha256:{digest}",
        "filename": filename,
        "display_name": display,
        "relative_path": _nfc_rel(relative_path),
        "size_bytes": size,
        "content_type": media_type or "application/octet-stream",
        "download_url": f"/api/v1/downloads/file?session_id={sid}&path={encoded_path}",
        "provenance_ui": {
            "source": "generation_job",
            "source_label": _JOB_LABELS.get(job_id, "Generación"),
            "job_id": job_id,
            "confidence": 1.0,
        },
    }


def resolve_scope_artifacts(
    *,
    session_id: str,
    scope: Optional[str],
    session_path: Optional[str],
    session_state: Optional[Dict[str, Any]] = None,
    company_profile: Optional[Dict[str, Any]] = None,
    company_exists: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Lista artefactos descargables para un alcance HRU.

    Args:
        session_id: ID de sesión (para URLs de descarga).
        scope: Alcance solicitado (normalizado internamente).
        session_path: Raíz resuelta en ``/data/outputs`` o None.
        session_state: Estado de sesión opcional (cola generación / pendientes).

    Returns:
        Payload ``data`` para respuesta API ``/downloads/artifacts``.
    """
    normalized = normalize_delivery_scope(scope)
    allowed = allowed_delivery_extensions()
    rows: List[Tuple[str, str, int, str]] = []

    if session_path and os.path.isdir(session_path):
        prefer_validated = prefer_compranet_validated_for_scope(normalized)
        compranet_ok = has_compranet_validated(session_path)
        dirs = include_directories_for_scope(normalized)
        sobres = include_compranet_sobres_for_scope(normalized)

        if prefer_validated and compranet_ok:
            rows.extend(_collect_from_compranet_sobres(session_path, sobres, allowed))
            rows.extend(
                _collect_root_logistics(
                    session_path,
                    include_root_logistics_for_scope(normalized),
                    allowed,
                )
            )
        else:
            rows.extend(_collect_from_directories(session_path, dirs, allowed))
            if compranet_ok and sobres:
                rows.extend(_collect_from_compranet_sobres(session_path, sobres, allowed))
            rows.extend(
                _collect_root_logistics(
                    session_path,
                    include_root_logistics_for_scope(normalized),
                    allowed,
                )
            )

    deduped = _dedupe_rows(rows)
    raw_count = len(deduped)

    readiness_block: Optional[Dict[str, Any]] = None
    integrity_blocked = False
    try:
        from app.services.expediente_readiness_service import (
            delivery_empty_reason_for_scope,
            delivery_ready_for_scope,
            readiness_gates_enabled,
            resolve_expediente_readiness,
        )

        if readiness_gates_enabled() and isinstance(session_state, dict):
            readiness_block = resolve_expediente_readiness(
                {**session_state, "session_id": session_id},
                company_profile=company_profile,
                company_exists=company_exists,
                session_output_path=session_path,
            )
            if not delivery_ready_for_scope(readiness_block, normalized):
                integrity_blocked = True
                deduped = []
    except Exception:
        readiness_block = None

    empty_reason = _infer_empty_reason(
        scope=normalized,
        session_state=session_state,
        artifact_count=len(deduped),
    )
    if integrity_blocked and readiness_block:
        from app.services.expediente_readiness_service import delivery_empty_reason_for_scope

        empty_reason = delivery_empty_reason_for_scope(
            readiness_block,
            normalized,
            artifact_count=raw_count,
        ) or empty_reason
    packaging = _read_packaging_coverage(session_path) if session_path else {}

    modal = load_delivery_ux_messages().get("modal")
    refresh_hint = "Actualizar lista"
    if isinstance(modal, dict) and modal.get("refresh_hint"):
        refresh_hint = str(modal["refresh_hint"])

    artifacts = [
        _build_artifact_row(
            session_id=session_id,
            relative_path=rel,
            digest=digest,
            size=size,
            top_dir=top,
        )
        for rel, digest, size, top in deduped
    ]

    return {
        "scope": normalized,
        "scope_label": scope_label(normalized),
        "ready": len(artifacts) > 0,
        "artifact_count": len(artifacts),
        "generation_jobs": _generation_jobs_for_scope(session_state, normalized),
        "packaging_coverage_status": packaging.get("packaging_coverage_status"),
        "artifacts": artifacts,
        "actions": {
            "download_all_zip_url": None,
            "refresh_hint": refresh_hint,
        },
        "empty_reason": empty_reason,
        "empty_reason_message": empty_reason_message(empty_reason) if empty_reason else None,
        "policy_version": policy_version(),
        "readiness_integrity_blocked": integrity_blocked,
    }
