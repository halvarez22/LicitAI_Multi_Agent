#!/usr/bin/env python3
"""
Smoke HTTP de artefactos UI (APIs ligeras + dictamen).

Uso:
  python scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001
  python scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001 --session vigilancia_issste

Exit codes:
  0 — todas las sesiones/endpoints OK
  1 — WARN (lento pero válido)
  2 — FAIL
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.reference_session_baseline import (
    REFERENCE_SESSION_IDS,
    load_baseline,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
API_PREFIX = "/api/v1/sessions"

WARN_MS = 10_000
DICTAMEN_TIMEOUT_S = 120.0
DEFAULT_TIMEOUT_S = 45.0


@dataclass
class EndpointCheck:
    """Resultado de un GET."""

    path_suffix: str
    ok: bool
    ms: int
    detail: str = ""
    warn_slow: bool = False


@dataclass
class SessionSmokeResult:
    session_id: str
    verdict: str
    checks: List[EndpointCheck] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)


def _api_url(base_url: str, session_id: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}{API_PREFIX}/{session_id}/{suffix}"


def _parse_generic(body: Dict[str, Any]) -> Tuple[bool, Any, str]:
    if not body.get("success"):
        return False, None, str(body.get("message") or "success=false")
    return True, body.get("data"), ""


def _check_submission_checklist(data: Any, mins: Dict[str, Any]) -> Tuple[bool, str]:
    cl = (data or {}).get("submission_checklist") if isinstance(data, dict) else None
    hitos = cl.get("hitos") if isinstance(cl, dict) else None
    n = len(hitos) if isinstance(hitos, list) else 0
    floor = int(mins.get("hitos") or 1)
    ok = n >= floor
    return ok, f"hitos={n} (min {floor})"


def _check_junta(data: Any, mins: Dict[str, Any]) -> Tuple[bool, str]:
    bundle = (data or {}).get("junta_aclaraciones_questions") if isinstance(data, dict) else None
    n = 0
    if isinstance(bundle, dict):
        items = bundle.get("items")
        if isinstance(items, list):
            n = len(items)
        else:
            summary = bundle.get("summary") or {}
            try:
                n = int(summary.get("total") or 0)
            except (TypeError, ValueError):
                n = 0
    floor = int(mins.get("junta_items") or 1)
    ok = n >= floor
    return ok, f"junta_items={n} (min {floor})"


def _check_corporate_docs(data: Any, mins: Dict[str, Any]) -> Tuple[bool, str]:
    corp = (data or {}).get("corporate_physical_document_candidates") if isinstance(data, dict) else None
    n = 0
    if isinstance(corp, dict):
        lst = corp.get("candidate_document_list")
        n = len(lst) if isinstance(lst, list) else 0
    floor = max(1, int(mins.get("corporate_physical") or 1))
    ok = n >= floor
    return ok, f"corporate_docs={n} (min {floor})"


def _check_formats_panel(data: Any, mins: Dict[str, Any]) -> Tuple[bool, str]:
    panel = (data or {}).get("pliego_formats_panel") if isinstance(data, dict) else None
    n = 0
    if isinstance(panel, dict):
        sobre = panel.get("sobre_1_tecnico")
        n = len(sobre) if isinstance(sobre, list) else 0
    floor = int(mins.get("pliego_formats_sobre_1_tecnico") or mins.get("sobre_1_tecnico") or 1)
    ok = n >= floor
    return ok, f"sobre_1_tecnico={n} (min {floor})"


def _check_dictamen(data: Any, mins: Dict[str, Any]) -> Tuple[bool, str]:
    dm = (data or {}).get("dictamen") if isinstance(data, dict) else None
    if not isinstance(dm, dict):
        return False, "dictamen_missing"
    if mins.get("has_dictamen") and not dm:
        return False, "dictamen_empty"
    zones = dm.get("zones")
    n_zones = len(zones) if isinstance(zones, list) else 0
    total = dm.get("totalRequisitos")
    ok = n_zones > 0 or (isinstance(total, (int, float)) and total > 0)
    return ok, f"zones={n_zones} totalRequisitos={total}"


ENDPOINT_SPECS: List[
    Tuple[str, str, Callable[[Any, Dict[str, Any]], Tuple[bool, str]], float]
] = [
    ("submission-checklist", "submission_checklist", _check_submission_checklist, DEFAULT_TIMEOUT_S),
    ("junta-aclaraciones-questions", "junta", _check_junta, DEFAULT_TIMEOUT_S),
    ("document-candidates-summary", "corporate_docs", _check_corporate_docs, DEFAULT_TIMEOUT_S),
    ("pliego-formats-panel", "formats_panel", _check_formats_panel, DEFAULT_TIMEOUT_S),
    ("dictamen", "dictamen", _check_dictamen, DICTAMEN_TIMEOUT_S),
]


def _mins_for_endpoint(mins: Dict[str, Any], key: str) -> Dict[str, Any]:
    if key == "corporate_docs":
        return {**mins, "corporate_physical": 1}
    return mins


def probe_endpoint(
    client: httpx.Client,
    base_url: str,
    session_id: str,
    suffix: str,
    validator_key: str,
    validator: Callable[[Any, Dict[str, Any]], Tuple[bool, str]],
    timeout_s: float,
    mins: Dict[str, Any],
) -> EndpointCheck:
    url = _api_url(base_url, session_id, suffix)
    t0 = time.perf_counter()
    try:
        resp = client.get(url, timeout=timeout_s)
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 500:
            return EndpointCheck(suffix, False, ms, f"HTTP {resp.status_code}")
        try:
            body = resp.json()
        except json.JSONDecodeError:
            return EndpointCheck(suffix, False, ms, "invalid_json")
        ok_resp, data, err = _parse_generic(body)
        if not ok_resp:
            return EndpointCheck(suffix, False, ms, err or "api_error")
        v_ok, detail = validator(data, _mins_for_endpoint(mins, validator_key))
        warn = ms > WARN_MS and suffix != "dictamen"
        return EndpointCheck(suffix, v_ok, ms, detail, warn_slow=warn and v_ok)
    except httpx.TimeoutException:
        ms = int((time.perf_counter() - t0) * 1000)
        return EndpointCheck(suffix, False, ms, "timeout")
    except httpx.HTTPError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return EndpointCheck(suffix, False, ms, str(exc)[:120])


def smoke_session_http(
    client: httpx.Client,
    base_url: str,
    session_id: str,
) -> SessionSmokeResult:
    try:
        baseline = load_baseline(session_id)
        mins = baseline.get("minimums") or {}
    except FileNotFoundError:
        mins = {"hitos": 6, "junta_items": 1, "sobre_1_tecnico": 1, "has_dictamen": True}

    checks: List[EndpointCheck] = []
    blockers: List[str] = []
    any_slow = False

    for suffix, vkey, validator, timeout_s in ENDPOINT_SPECS:
        chk = probe_endpoint(
            client, base_url, session_id, suffix, vkey, validator, timeout_s, mins
        )
        checks.append(chk)
        if not chk.ok:
            blockers.append(f"{suffix}:{chk.detail}")
        elif chk.warn_slow:
            any_slow = True

    if blockers:
        verdict = "FAIL"
    elif any_slow:
        verdict = "WARN"
    else:
        verdict = "OK"

    return SessionSmokeResult(
        session_id=session_id,
        verdict=verdict,
        checks=checks,
        blockers=blockers,
    )


def result_to_dict(r: SessionSmokeResult) -> Dict[str, Any]:
    return {
        "session_id": r.session_id,
        "verdict": r.verdict,
        "blockers": r.blockers,
        "checks": [
            {
                "endpoint": c.path_suffix,
                "ok": c.ok,
                "ms": c.ms,
                "detail": c.detail,
                "warn_slow": c.warn_slow,
            }
            for c in r.checks
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke HTTP artefactos UI")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--session", action="append", dest="sessions", default=[])
    ap.add_argument("--all-reference", action="store_true")
    args = ap.parse_args()

    targets = list(args.sessions)
    if args.all_reference or not targets:
        targets.extend(REFERENCE_SESSION_IDS)
    targets = sorted(set(t for t in targets if t))

    results: List[SessionSmokeResult] = []
    with httpx.Client() as client:
        for sid in targets:
            results.append(smoke_session_http(client, args.base_url.rstrip("/"), sid))

    payload = [result_to_dict(r) for r in results]
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if any(r.verdict == "FAIL" for r in results):
        sys.exit(2)
    if any(r.verdict == "WARN" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
