"""
Verdad canónica de readiness — captura, generación y entrega segura (HRU).

Fuente normativa: ``expediente_readiness_policy.json``, ``expediente_readiness_ux_messages.json``.

Ningún módulo debe calcular «¿está listo?» por su cuenta; debe delegar aquí.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.economic_capture_matrix_service import economic_capture_status
from app.services.expediente_guided_service import economic_capture_honest_status

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "expediente_readiness_policy.json"
)
_UX_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "expediente_readiness_ux_messages.json"
)

_ECON_PENDING_TYPES = frozenset(
    {"economic_price", "economic_price_matrix", "economic_validation_blocking"}
)


@lru_cache(maxsize=1)
def load_expediente_readiness_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_expediente_readiness_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_expediente_readiness_policy().get("policy_version") or "")


def ux_message_for_error_type(error_type: str, **fmt: Any) -> str:
    """Mensaje humano centralizado por ``error_type``."""
    blockers = (load_expediente_readiness_ux_messages().get("blockers") or {})
    tpl = str(blockers.get(error_type) or error_type)
    try:
        return tpl.format(**fmt)
    except (KeyError, ValueError):
        return tpl


def _blocker(
    error_type: str,
    *,
    scope: str,
    field: Optional[str] = None,
    detail: Optional[str] = None,
    provenance_source: str = "readiness",
    **fmt: Any,
) -> Dict[str, Any]:
    msg = ux_message_for_error_type(error_type, **fmt)
    row: Dict[str, Any] = {
        "error_type": error_type,
        "scope": scope,
        "message": msg,
        "provenance_ui": {"source": provenance_source, "badge": "readiness"},
    }
    if field:
        row["field"] = field
    if detail:
        row["detail"] = detail
    return row


def _session_hint(session_state: Dict[str, Any]) -> str:
    parts = [
        str(session_state.get("session_id") or ""),
        str(session_state.get("licitacion_id") or ""),
        str((session_state.get("triage_context") or {}).get("tender_id") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _is_fsr_vertical(session_state: Dict[str, Any]) -> bool:
    policy = load_expediente_readiness_policy()
    markers = [str(m).lower() for m in (policy.get("fsr_vertical_markers") or [])]
    blob = json.dumps(session_state.get("triage_context") or {}, ensure_ascii=False).lower()
    blob += " " + _session_hint(session_state).lower()
    return any(m in blob for m in markers)


def _detect_cross_tender_inputs(session_state: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """True si ``economic_user_inputs`` contiene señales de otra licitación."""
    hint = _session_hint(session_state)
    if not hint:
        return False, None
    hint_norm = re.sub(r"[^A-Z0-9]", "", hint.upper())
    inputs = session_state.get("economic_user_inputs") or {}
    if not isinstance(inputs, dict):
        return False, None

    try:
        from app.services.document_fill_quality_gate import detect_cross_tender_marker

        blob_parts: List[str] = [json.dumps(inputs, ensure_ascii=False)]
        marker = detect_cross_tender_marker(blob_parts, hint)
        if marker:
            return True, marker
    except Exception:
        pass

    concept_prices = inputs.get("concept_prices")
    if isinstance(concept_prices, dict):
        for key in concept_prices:
            key_norm = re.sub(r"[^A-Z0-9]", "", str(key).upper())
            for token in re.findall(r"[A-Z]{2,}-\d{2,}-[A-Z0-9\-]{4,}", str(key).upper()):
                tok_norm = re.sub(r"[^A-Z0-9]", "", token)
                if tok_norm and tok_norm not in hint_norm and len(tok_norm) >= 8:
                    return True, token

    for key in inputs:
        if str(key).startswith("price_"):
            ref = str(key)[6:]
            ref_norm = re.sub(r"[^A-Z0-9]", "", ref.upper())
            if ref_norm and ref_norm not in hint_norm and len(ref_norm) >= 8:
                return True, ref
    return False, None


def _legacy_fsr_keys_in_inputs(session_state: Dict[str, Any]) -> bool:
    if _is_fsr_vertical(session_state):
        return False
    policy = load_expediente_readiness_policy()
    legacy = frozenset(str(k) for k in (policy.get("legacy_fsr_input_keys") or []))
    inputs = session_state.get("economic_user_inputs") or {}
    if not isinstance(inputs, dict):
        return False
    return any(str(k) in legacy for k in inputs)


def _economic_proposal_snapshot(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for task in reversed(list(session_state.get("tasks_completed") or [])):
        if not isinstance(task, dict):
            continue
        if str(task.get("task") or "") == "economic_proposal":
            res = task.get("result")
            return res if isinstance(res, dict) else None
    return None


def _snapshot_complete(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    status = str(snapshot.get("status") or "").lower()
    if status not in ("complete", "success", "ok"):
        total = float(snapshot.get("total_base") or 0.0)
        if total >= 0.01:
            return True
        return False
    total = float(snapshot.get("total_base") or 0.0)
    inputs = snapshot  # snapshot may carry line items
    items = inputs.get("line_items") or inputs.get("items") or []
    if total >= 0.01 or (isinstance(items, list) and len(items) > 0):
        return True
    return total >= 0.01


def _economic_snapshot_hash(snapshot: Optional[Dict[str, Any]]) -> str:
    if not snapshot:
        return ""
    policy = load_expediente_readiness_policy()
    n = int((policy.get("fingerprint") or {}).get("hash_truncated_hex_len") or 16)
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:n]


def _bases_fingerprint(session_state: Dict[str, Any]) -> str:
    snap = session_state.get("bases_analysis_snapshot") or {}
    if isinstance(snap, dict):
        fp = str(snap.get("fingerprint") or "").strip()
        if fp:
            return fp
    return str(session_state.get("bases_analysis_fingerprint") or "").strip()


def _profile_rfc(profile: Optional[Dict[str, Any]]) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("rfc") or "").strip().upper()


def _profile_label(profile: Optional[Dict[str, Any]]) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(
        profile.get("razon_social") or profile.get("nombre") or profile.get("name") or ""
    ).strip()


def _resolve_company_binding(
    session_state: Dict[str, Any],
    *,
    company_profile: Optional[Dict[str, Any]] = None,
    company_exists: Optional[bool] = None,
) -> Dict[str, Any]:
    company_id = str(session_state.get("company_id") or "").strip() or None
    session_mp = session_state.get("master_profile")
    session_mp = session_mp if isinstance(session_mp, dict) else {}

    orphan = bool(company_id and company_exists is False)
    db_profile = company_profile if isinstance(company_profile, dict) and company_profile else {}
    session_rfc = _profile_rfc(session_mp)
    active_rfc = _profile_rfc(db_profile) or _profile_rfc(session_mp)
    profile_stale = bool(
        company_id
        and db_profile
        and session_rfc
        and active_rfc
        and session_rfc != active_rfc
    )

    binding_valid = bool(company_id and not orphan and active_rfc)

    return {
        "company_id": company_id,
        "company_rfc": active_rfc or None,
        "company_label": _profile_label(db_profile) or _profile_label(session_mp) or None,
        "binding_valid": binding_valid,
        "orphan_company_id": orphan,
        "session_profile_stale": profile_stale,
    }


def _motor_pending_fields(session_state: Dict[str, Any]) -> List[str]:
    types = frozenset(
        str(x)
        for x in (load_expediente_readiness_policy().get("economic_pending_types") or [])
    )
    out: List[str] = []
    for q in session_state.get("pending_questions") or []:
        if not isinstance(q, dict):
            continue
        if str(q.get("type") or "") not in types:
            continue
        field = str(q.get("field") or q.get("label") or "pending").strip()
        if field and field not in out:
            out.append(field)
    return out


def _has_analysis(session_state: Dict[str, Any]) -> bool:
    task = str(load_expediente_readiness_policy().get("analysis_task") or "stage_completed:analysis")
    return any(
        isinstance(t, dict) and str(t.get("task") or "") == task
        for t in (session_state.get("tasks_completed") or [])
    )


def _job_status(session_state: Dict[str, Any], job_id: str) -> str:
    gen = session_state.get("generation_state") or {}
    if not isinstance(gen, dict):
        return ""
    for job in gen.get("jobs") or []:
        if isinstance(job, dict) and str(job.get("id") or "") == job_id:
            return str(job.get("status") or "").strip().lower()
    return ""


def _has_quality_gate_pending(session_state: Dict[str, Any]) -> bool:
    for q in session_state.get("pending_questions") or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "").strip().lower()
        field = str(q.get("field") or "").strip().lower()
        if qtype == "document_quality_gate_blocking" or field == "document_quality_gate":
            return True
    return False


def _expected_fingerprint(
    session_state: Dict[str, Any],
    binding: Dict[str, Any],
    *,
    scope: str,
) -> Dict[str, Any]:
    snap = _economic_proposal_snapshot(session_state)
    return {
        "schema_version": "artifact_fingerprint_v1",
        "scope": scope,
        "company_id": binding.get("company_id"),
        "company_rfc": binding.get("company_rfc"),
        "bases_fingerprint": _bases_fingerprint(session_state),
        "economic_snapshot_hash": _economic_snapshot_hash(snap) if scope == "economic" else "",
    }


def _read_disk_fingerprint(output_root: str, subdirs: Sequence[str]) -> Optional[Dict[str, Any]]:
    policy = load_expediente_readiness_policy()
    sidecar = str((policy.get("fingerprint") or {}).get("sidecar_filename") or "_LICITAI_FINGERPRINT.json")
    root = Path(output_root)
    if not root.is_dir():
        return None
    for sub in subdirs:
        candidate = root / sub / sidecar
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _scope_has_deliverable_files(output_root: str, subdirs: Sequence[str]) -> bool:
    root = Path(output_root)
    if not root.is_dir():
        return False
    office = frozenset({".doc", ".docx", ".pdf", ".xlsx", ".xls"})
    for sub in subdirs:
        d = root / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in office:
                return True
    return False


def _fingerprint_match(expected: Dict[str, Any], on_disk: Optional[Dict[str, Any]]) -> bool:
    if not on_disk:
        return False
    for key in ("company_id", "company_rfc", "economic_snapshot_hash"):
        exp = str(expected.get(key) or "").strip()
        if not exp:
            continue
        got = str(on_disk.get(key) or "").strip()
        if got and exp.upper() != got.upper():
            return False
    exp_bases = str(expected.get("bases_fingerprint") or "").strip()
    got_bases = str(on_disk.get("bases_fingerprint") or "").strip()
    if exp_bases and got_bases and exp_bases != got_bases:
        return False
    return True


def _resolve_delivery_scope_safe(
    session_state: Dict[str, Any],
    binding: Dict[str, Any],
    *,
    scope_key: str,
    session_output_path: Optional[str],
    capture_ready: bool,
) -> Tuple[bool, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    policy = load_expediente_readiness_policy()
    scopes = policy.get("delivery_scopes") or {}
    scope_cfg = scopes.get(scope_key) if isinstance(scopes, dict) else None
    if not isinstance(scope_cfg, dict):
        return False, [], None

    blockers: List[Dict[str, Any]] = []
    subdirs = [str(s) for s in (scope_cfg.get("output_subdirs") or [])]
    job_id = str(scope_cfg.get("writer_job") or "")

    if not binding.get("binding_valid"):
        blockers.append(
            _blocker(
                "COMPANY_BINDING_INVALID" if not binding.get("orphan_company_id") else "COMPANY_ORPHAN_ID",
                scope="delivery",
            )
        )
        return False, blockers, None

    job_st = _job_status(session_state, job_id)
    if job_st == "blocked":
        blockers.append(
            _blocker("GENERATION_JOB_BLOCKED", scope="delivery", job_id=job_id)
        )

    if scope_key == "economic" and not capture_ready:
        if any(
            str(q.get("field") or "") == "economic_price_source"
            for q in (session_state.get("pending_questions") or [])
            if isinstance(q, dict)
        ):
            blockers.append(
                _blocker("ECONOMIC_PRICE_SOURCE_PENDING", scope="delivery", field="economic_price_source")
            )

    expected_fp = _expected_fingerprint(session_state, binding, scope=scope_key)
    on_disk_fp = None
    has_files = False
    if session_output_path:
        on_disk_fp = _read_disk_fingerprint(session_output_path, subdirs)
        has_files = _scope_has_deliverable_files(session_output_path, subdirs)

    fp_info: Optional[Dict[str, Any]] = None
    if scope_key == "economic" and has_files:
        fp_info = {"expected": expected_fp, "on_disk": on_disk_fp, "match": False}
        if on_disk_fp and _fingerprint_match(expected_fp, on_disk_fp):
            fp_info["match"] = True
        elif on_disk_fp:
            blockers.append(
                _blocker(
                    "ARTIFACT_FINGERPRINT_MISMATCH",
                    scope="delivery",
                    expected_rfc=expected_fp.get("company_rfc"),
                    on_disk_rfc=on_disk_fp.get("company_rfc"),
                )
            )
        else:
            exp_rfc = str(expected_fp.get("company_rfc") or "").upper()
            session_rfc = _profile_rfc(
                session_state.get("master_profile")
                if isinstance(session_state.get("master_profile"), dict)
                else {}
            )
            if binding.get("session_profile_stale"):
                blockers.append(_blocker("SESSION_PROFILE_STALE", scope="delivery"))
                fp_info["on_disk"] = {
                    "company_rfc": session_rfc,
                    "source": "session_master_profile_stale",
                }
            blockers.append(
                _blocker("ARTIFACT_FINGERPRINT_MISMATCH", scope="delivery")
            )

    if not has_files and job_st not in ("done", "resumed"):
        blockers.append(_blocker("GENERATION_NOT_RUN", scope="delivery"))

    safe = not blockers and (has_files or job_st in ("done", "resumed"))
    if scope_key == "economic" and has_files and fp_info and not fp_info.get("match"):
        safe = False
    return safe, blockers, fp_info


def _recommended_action(
    binding: Dict[str, Any],
    capture: Dict[str, Any],
    generation_blockers: List[Dict[str, Any]],
    delivery_blockers: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if binding.get("orphan_company_id") or not binding.get("binding_valid"):
        return {"error_type": "BIND_COMPANY", "cta_kind": "api", "cta_id": "BIND_COMPANY"}
    gen_types = {str(b.get("error_type") or "") for b in generation_blockers}
    del_types = {str(b.get("error_type") or "") for b in delivery_blockers}
    if "ECONOMIC_CROSS_TENDER_INPUTS" in gen_types or capture.get("cross_tender_contamination"):
        return {"error_type": "CAPTURE_PRICES", "cta_kind": "chat", "cta_id": "CAPTURE_PRICES"}
    if not capture.get("ready") or "ECONOMIC_PRICE_SOURCE_PENDING" in gen_types:
        return {"error_type": "CAPTURE_PRICES", "cta_kind": "chat", "cta_id": "CAPTURE_PRICES"}
    if "ARTIFACT_FINGERPRINT_MISMATCH" in del_types or "ARTIFACT_RFC_CONTAMINATION" in del_types:
        return {"error_type": "REGENERATE_ECONOMIC", "cta_kind": "api", "cta_id": "REGENERATE_ECONOMIC"}
    if "FORMATS_DATA_INCOMPLETE" in gen_types or "DOCUMENT_QUALITY_GATE_PENDING" in gen_types:
        return {"error_type": "REGENERATE_FORMATS", "cta_kind": "api", "cta_id": "REGENERATE_FORMATS"}
    return None


def resolve_expediente_readiness(
    session_state: Dict[str, Any],
    *,
    company_profile: Optional[Dict[str, Any]] = None,
    company_exists: Optional[bool] = None,
    session_output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resuelve readiness canónico para captura, generación y entrega.

    Args:
        session_state: Estado de sesión PostgreSQL.
        company_profile: Perfil fresco de ``companies`` (si disponible).
        company_exists: False si ``company_id`` no existe en catálogo.
        session_output_path: Raíz ``/data/outputs/{session_id}`` para integridad disco.

    Returns:
        Payload ``expediente_readiness_v1``.
    """
    session_id = str(session_state.get("session_id") or session_state.get("id") or "").strip()
    binding = _resolve_company_binding(
        session_state,
        company_profile=company_profile,
        company_exists=company_exists,
    )

    honest = economic_capture_honest_status(session_state)
    cap_status = economic_capture_status(session_state)
    motor_fields = _motor_pending_fields(session_state)
    cross_tender, cross_marker = _detect_cross_tender_inputs(session_state)
    legacy_fsr = _legacy_fsr_keys_in_inputs(session_state)

    capture_ready = bool(honest.get("capture_complete")) and not cross_tender and not legacy_fsr
    capture_blockers: List[Dict[str, Any]] = []
    if cross_tender:
        capture_blockers.append(
            _blocker(
                "ECONOMIC_CROSS_TENDER_INPUTS",
                scope="capture",
                detected_marker=cross_marker or "otra_licitacion",
            )
        )
    if legacy_fsr:
        capture_blockers.append(
            _blocker("ECONOMIC_CROSS_TENDER_INPUTS", scope="capture", detected_marker="legacy_fsr_inputs")
        )
    if honest.get("motor_pending_count", 0) > 0:
        if any(f == "economic_price_source" for f in motor_fields):
            capture_blockers.append(
                _blocker("ECONOMIC_PRICE_SOURCE_PENDING", scope="capture", field="economic_price_source")
            )
        else:
            capture_blockers.append(
                _blocker(
                    "ECONOMIC_MOTOR_HITL_PENDING",
                    scope="capture",
                    motor_pending_count=honest.get("motor_pending_count"),
                    motor_pending_fields=", ".join(motor_fields[:3]),
                )
            )
    if not honest.get("capture_complete") and not capture_blockers:
        capture_blockers.append(
            _blocker(
                "ECONOMIC_CAPTURE_INCOMPLETE",
                scope="capture",
                matrix_filled=honest.get("filled", 0),
                matrix_total=honest.get("total", 0),
            )
        )

    snapshot = _economic_proposal_snapshot(session_state)
    snapshot_ok = _snapshot_complete(snapshot)

    generation_blockers: List[Dict[str, Any]] = []
    if not binding.get("binding_valid"):
        if binding.get("orphan_company_id"):
            generation_blockers.append(_blocker("COMPANY_ORPHAN_ID", scope="generation"))
        else:
            generation_blockers.append(_blocker("COMPANY_BINDING_INVALID", scope="generation"))
    if binding.get("session_profile_stale"):
        generation_blockers.append(_blocker("SESSION_PROFILE_STALE", scope="generation"))

    if _has_quality_gate_pending(session_state):
        generation_blockers.append(
            _blocker("DOCUMENT_QUALITY_GATE_PENDING", scope="generation", field="document_quality_gate")
        )

    formats_job = _job_status(session_state, "formats")
    if formats_job == "blocked":
        generation_blockers.append(
            _blocker("FORMATS_DATA_INCOMPLETE", scope="generation", job_id="formats")
        )

    analysis_ok = _has_analysis(session_state)
    quality_pending = _has_quality_gate_pending(session_state)
    binding_ok = bool(binding.get("binding_valid"))

    technical_allowed = analysis_ok and binding_ok and not quality_pending
    formats_allowed = (
        technical_allowed
        and _job_status(session_state, "technical") in ("done", "resumed", "skipped", "")
        and formats_job not in ("blocked", "error")
    )

    economic_blockers = list(capture_blockers)
    economic_allowed = (
        capture_ready
        and binding_ok
        and snapshot_ok
        and not economic_blockers
    )
    if capture_ready and binding_ok and not snapshot_ok:
        economic_blockers.append(_blocker("ECONOMIC_SNAPSHOT_MISSING", scope="generation"))
        economic_allowed = False

    generation_blockers.extend(economic_blockers)

    packager_allowed = (
        formats_allowed
        and economic_allowed
        and _job_status(session_state, "formats") in ("done", "resumed")
        and _job_status(session_state, "economic_writer") in ("done", "resumed")
    )

    delivery_blockers: List[Dict[str, Any]] = []
    artifact_fps: Dict[str, Any] = {}

    tech_safe, tech_blockers, _ = _resolve_delivery_scope_safe(
        session_state, binding, scope_key="technical", session_output_path=session_output_path, capture_ready=capture_ready
    )
    admin_safe, admin_blockers, _ = _resolve_delivery_scope_safe(
        session_state, binding, scope_key="admin", session_output_path=session_output_path, capture_ready=capture_ready
    )
    eco_safe, eco_blockers, eco_fp = _resolve_delivery_scope_safe(
        session_state, binding, scope_key="economic", session_output_path=session_output_path, capture_ready=capture_ready
    )
    delivery_blockers.extend(tech_blockers + admin_blockers + eco_blockers)
    if eco_fp:
        artifact_fps["economic"] = eco_fp

    capture_payload = {
        "matrix_filled": int(honest.get("filled") or 0),
        "matrix_total": int(honest.get("total") or 0),
        "motor_pending_count": int(honest.get("motor_pending_count") or 0),
        "motor_pending_fields": motor_fields,
        "pending_economic": int(cap_status.get("pending_economic") or 0),
        "cross_tender_contamination": cross_tender or legacy_fsr,
        "cross_tender_marker": cross_marker,
        "legacy_fsr_inputs_detected": legacy_fsr,
        "ready": capture_ready,
    }

    return {
        "schema_version": "expediente_readiness_v1",
        "policy_version": policy_version(),
        "session_id": session_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "company_binding": binding,
        "capture": capture_payload,
        "generation": {
            "technical_writer_allowed": technical_allowed,
            "formats_allowed": formats_allowed,
            "economic_writer_allowed": economic_allowed,
            "packager_allowed": packager_allowed,
            "blockers": _dedupe_blockers(generation_blockers),
        },
        "delivery": {
            "technical_scope_safe": tech_safe,
            "admin_scope_safe": admin_safe,
            "economic_scope_safe": eco_safe,
            "blockers": _dedupe_blockers(delivery_blockers),
        },
        "artifact_fingerprints": artifact_fps,
        "recommended_action": _recommended_action(
            binding, capture_payload, generation_blockers, delivery_blockers
        ),
    }


def _dedupe_blockers(blockers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for b in blockers:
        key = str(b.get("error_type") or "") + "|" + str(b.get("scope") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


_SCOPE_DELIVERY_SAFE_KEYS: Dict[str, List[str]] = {
    "economic": ["economic_scope_safe"],
    "technical": ["technical_scope_safe", "admin_scope_safe"],
    "full": ["technical_scope_safe", "admin_scope_safe", "economic_scope_safe"],
}

_STEP_GENERATION_ALLOWED_KEYS: Dict[str, str] = {
    "technical": "technical_writer_allowed",
    "formats": "formats_allowed",
    "economic_writer": "economic_writer_allowed",
    "packager": "packager_allowed",
    "delivery": "packager_allowed",
}

_ERROR_TYPE_TO_EMPTY_REASON: Dict[str, str] = {
    "ARTIFACT_FINGERPRINT_MISMATCH": "artifact_fingerprint_mismatch",
    "ARTIFACT_RFC_CONTAMINATION": "artifact_fingerprint_mismatch",
    "ECONOMIC_PRICE_SOURCE_PENDING": "prices_required",
    "DOCUMENT_QUALITY_GATE_PENDING": "document_quality_gate",
    "GENERATION_JOB_BLOCKED": "job_blocked",
    "COMPANY_BINDING_INVALID": "company_binding_invalid",
    "COMPANY_ORPHAN_ID": "company_binding_invalid",
}


def readiness_gates_enabled() -> bool:
    from app.config.settings import settings

    return bool(getattr(settings, "READINESS_GATES_ENABLED", True))


def delivery_ready_for_scope(readiness: Dict[str, Any], scope: str) -> bool:
    """True si el alcance de descarga es seguro según readiness."""
    delivery = readiness.get("delivery") if isinstance(readiness.get("delivery"), dict) else {}
    keys = _SCOPE_DELIVERY_SAFE_KEYS.get(str(scope or "").strip().lower(), [])
    if not keys:
        return bool(delivery.get("economic_scope_safe", True))
    return all(bool(delivery.get(k)) for k in keys)


def generation_step_allowed(readiness: Dict[str, Any], step: str) -> bool:
    """True si el orquestador puede ejecutar el writer indicado."""
    generation = readiness.get("generation") if isinstance(readiness.get("generation"), dict) else {}
    key = _STEP_GENERATION_ALLOWED_KEYS.get(str(step or "").strip().lower())
    if not key:
        return True
    return bool(generation.get(key))


def primary_blocker_for_step(readiness: Dict[str, Any], step: str) -> Optional[Dict[str, Any]]:
    """Primer blocker de generación relevante para un writer."""
    generation = readiness.get("generation") if isinstance(readiness.get("generation"), dict) else {}
    blockers = generation.get("blockers") if isinstance(generation.get("blockers"), list) else []
    if not blockers:
        return None
    step_scope = {
        "technical": frozenset({"capture", "generation", "binding"}),
        "formats": frozenset({"generation", "binding"}),
        "economic_writer": frozenset({"capture", "generation", "binding"}),
        "packager": frozenset({"generation", "binding"}),
        "delivery": frozenset({"generation"}),
    }.get(str(step or "").strip().lower(), frozenset({"generation"}))
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        if str(blocker.get("scope") or "") in step_scope:
            return blocker
    return blockers[0] if isinstance(blockers[0], dict) else None


def delivery_empty_reason_for_scope(
    readiness: Dict[str, Any],
    scope: str,
    *,
    artifact_count: int,
) -> Optional[str]:
    """
    ``empty_reason`` estable para API de descargas.

    Si hay archivos en disco pero el alcance no es seguro, devuelve razón de bloqueo.
    """
    if delivery_ready_for_scope(readiness, scope):
        return None if artifact_count > 0 else "no_files_on_disk"
    delivery = readiness.get("delivery") if isinstance(readiness.get("delivery"), dict) else {}
    blockers = delivery.get("blockers") if isinstance(delivery.get("blockers"), list) else []

    # Contaminación en disco prevalece sobre estado de job (CONTAM01).
    if artifact_count > 0:
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            if str(blocker.get("error_type") or "") in (
                "ARTIFACT_FINGERPRINT_MISMATCH",
                "ARTIFACT_RFC_CONTAMINATION",
            ):
                return "artifact_fingerprint_mismatch"
        return "artifact_fingerprint_mismatch"

    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        error_type = str(blocker.get("error_type") or "")
        mapped = _ERROR_TYPE_TO_EMPTY_REASON.get(error_type)
        if mapped:
            return mapped
    return "job_blocked"


def stop_reason_for_blocker(blocker: Optional[Dict[str, Any]]) -> str:
    """Mapea blocker readiness → stop_reason orquestador."""
    if not isinstance(blocker, dict):
        return "READINESS_GATE_BLOCKED"
    return str(blocker.get("error_type") or "READINESS_GATE_BLOCKED")
