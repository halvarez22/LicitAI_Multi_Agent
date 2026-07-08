#!/usr/bin/env python3
"""
Smoke R5 — integridad expediente HRU (readiness + binding + fingerprint + CONTAM01).

Valida contratos versionados, escenario CONTAM01 sintético, oracles de readiness
y (opcional) endpoints API en sesión piloto.

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_expediente_readiness_integrity.py
  cd backend && PYTHONPATH=. python scripts/smoke_expediente_readiness_integrity.py --session vigilancia_issste
  PILOT_API_BASE=http://127.0.0.1:8001/api/v1 python scripts/smoke_expediente_readiness_integrity.py --session vigilancia_issste_mayo_v1

Normativa: docs/SPEC_EXPEDIENTE_READINESS_AND_INTEGRITY_HRU.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = BACKEND_ROOT / "app" / "contracts"


def _errors() -> List[str]:
    return []


def check_contract_versions(errors: List[str]) -> None:
    """Contratos HRU R1–R4 deben existir y exponer policy_version."""
    from app.services.artifact_fingerprint_service import policy_version as fp_v
    from app.services.company_binding_service import policy_version as bind_v
    from app.services.expediente_readiness_service import policy_version as ready_v

    for label, ver in (
        ("expediente_readiness", ready_v()),
        ("company_binding", bind_v()),
        ("artifact_integrity", fp_v()),
    ):
        if not str(ver or "").strip():
            errors.append(f"Sin policy_version: {label}")

    for name in (
        "expediente_readiness_policy.json",
        "expediente_readiness_v1.json",
        "expediente_readiness_ux_messages.json",
        "company_binding_policy.json",
        "artifact_integrity_policy.json",
    ):
        if not (CONTRACTS / name).is_file():
            errors.append(f"Contrato faltante: {name}")


def check_ux_blockers_clean(errors: List[str]) -> None:
    """Mensajes UX centralizados — sin códigos internos crudos."""
    from app.services.expediente_readiness_service import load_expediente_readiness_ux_messages

    blockers = (load_expediente_readiness_ux_messages().get("blockers") or {})
    forbidden = ("INCOMPLETE_", "MISSING_", "COMPANY_ORPHAN", "READINESS_GATE")
    for key, msg in blockers.items():
        text = str(msg or "")
        if not text.strip():
            errors.append(f"blocker UX vacío: {key}")
            continue
        upper = text.upper()
        for bad in forbidden:
            if bad in upper:
                errors.append(f"blocker {key} expone código interno: {bad}")


def check_contam01_offline(errors: List[str]) -> None:
    """CONTAM01 sintético — archivos Manavil + sesión Mayo → lista vacía."""
    from app.services.artifact_fingerprint_service import write_disk_fingerprint
    from app.services.delivery_scope_resolver import resolve_scope_artifacts

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        econ = root / "2.propuesta_economica"
        econ.mkdir()
        (econ / "ANEXO_ECONOMICO.docx").write_bytes(b"manavil-stale")
        write_disk_fingerprint(
            str(root),
            "economic",
            {"company_rfc": "SPI060200AG5", "economic_snapshot_hash": "deadbeef"},
        )
        session_state = {
            "session_id": "smoke_contam01",
            "company_id": "co_mayo",
            "master_profile": {"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
            "tasks_completed": [
                {"task": "stage_completed:analysis"},
                {
                    "task": "economic_proposal",
                    "result": {
                        "status": "complete",
                        "total_base": 5800.0,
                        "line_items": [{"concepto": "vigilancia"}],
                    },
                },
            ],
            "generation_state": {
                "jobs": [
                    {"id": "technical", "status": "done"},
                    {"id": "formats", "status": "done"},
                    {"id": "economic_writer", "status": "blocked"},
                ]
            },
        }
        out = resolve_scope_artifacts(
            session_id="smoke_contam01",
            scope="economic",
            session_path=str(root),
            session_state=session_state,
            company_profile={"rfc": "CMT160107S83"},
            company_exists=True,
        )
        if out.get("artifact_count") != 0:
            errors.append("CONTAM01: artifact_count debería ser 0")
        if not out.get("readiness_integrity_blocked"):
            errors.append("CONTAM01: readiness_integrity_blocked debería ser true")
        if out.get("empty_reason") != "artifact_fingerprint_mismatch":
            errors.append(f"CONTAM01: empty_reason={out.get('empty_reason')}")


def check_fingerprint_match_offline(errors: List[str]) -> None:
    """Control positivo — fingerprint coherente permite entrega."""
    from app.services.artifact_fingerprint_service import build_fingerprint, write_disk_fingerprint
    from app.services.delivery_scope_resolver import resolve_scope_artifacts

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        econ = root / "2.propuesta_economica"
        econ.mkdir()
        (econ / "cotizacion.xlsx").write_bytes(b"eco-ok")
        session_state = {
            "company_id": "co_ok",
            "master_profile": {"rfc": "CMT160107S83"},
            "tasks_completed": [
                {
                    "task": "economic_proposal",
                    "result": {"status": "complete", "total_base": 100.0, "line_items": [{"a": 1}]},
                }
            ],
            "generation_state": {"jobs": [{"id": "economic_writer", "status": "done"}]},
        }
        write_disk_fingerprint(str(root), "economic", build_fingerprint(session_state, scope="economic"))
        out = resolve_scope_artifacts(
            session_id="smoke_ok",
            scope="economic",
            session_path=str(root),
            session_state=session_state,
            company_profile={"rfc": "CMT160107S83"},
            company_exists=True,
        )
        if out.get("artifact_count") != 1:
            errors.append("fingerprint OK: artifact_count debería ser 1")
        if out.get("readiness_integrity_blocked"):
            errors.append("fingerprint OK: no debería bloquear integridad")


def check_readiness_gates_default(errors: List[str]) -> None:
    """Gates activos por defecto (HRU R4)."""
    from app.config.settings import settings

    if not getattr(settings, "READINESS_GATES_ENABLED", False):
        errors.append("READINESS_GATES_ENABLED debería ser true por defecto")


def run_oracle_pytest(errors: List[str]) -> None:
    """Subconjunto oracle + integridad en CI."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    targets = [
        "tests/oracle/test_expediente_readiness_oracle.py",
        "tests/test_delivery_scope_integrity.py",
        "tests/test_company_binding_service.py",
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--tb=line"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "")[-1200:]
        errors.append(f"pytest oracle/integridad falló:\n{tail.strip()}")


def _api_get(base: str, path: str) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=12) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def check_api_session(base: str, session_id: str, errors: List[str], warnings: List[str]) -> None:
    """Validación live opcional contra API levantada."""
    sid = session_id.strip()
    if not sid:
        return
    try:
        ready = _api_get(base, f"/sessions/{sid}/readiness")
        if not ready.get("success"):
            errors.append(f"API readiness success=false: {ready.get('message')}")
            return
        data = ready.get("data") if isinstance(ready.get("data"), dict) else {}
        if data.get("schema_version") != "expediente_readiness_v1":
            errors.append(f"API readiness schema_version inesperado: {data.get('schema_version')}")

        binding = data.get("company_binding") if isinstance(data.get("company_binding"), dict) else {}
        if not binding.get("binding_valid"):
            warnings.append(
                f"Sesión {sid}: binding_valid=false — ejecutar POST bind-company antes de generar"
            )

        arts = _api_get(base, f"/downloads/artifacts?session_id={sid}&scope=economic")
        art_data = arts.get("data") if isinstance(arts.get("data"), dict) else {}
        if art_data.get("readiness_integrity_blocked") and art_data.get("artifact_count", 0) > 0:
            errors.append(
                f"API CONTAM01: integrity_blocked=true pero artifact_count={art_data.get('artifact_count')}"
            )
        if art_data.get("readiness_integrity_blocked"):
            reason = art_data.get("empty_reason")
            if reason not in ("artifact_fingerprint_mismatch", "company_binding_invalid", "job_blocked", "prices_required"):
                warnings.append(f"Sesión {sid}: empty_reason={reason}")
    except HTTPError as exc:
        if exc.code == 404:
            warnings.append(f"Sesión {sid} no encontrada en API (404) — omitiendo checks live")
        else:
            errors.append(f"API HTTP {exc.code} para sesión {sid}")
    except URLError as exc:
        errors.append(f"API no alcanzable ({base}): {exc}")
    except Exception as exc:
        errors.append(f"API check falló: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke R5 integridad expediente HRU")
    parser.add_argument(
        "--session",
        default="",
        help="ID sesión piloto para checks API opcionales (ej. vigilancia_issste_mayo_v1)",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Omitir subprocess pytest (más rápido en dev iterativo)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: List[str] = []
    warnings: List[str] = []

    check_contract_versions(errors)
    check_ux_blockers_clean(errors)
    check_readiness_gates_default(errors)
    check_contam01_offline(errors)
    check_fingerprint_match_offline(errors)
    if not args.skip_pytest:
        run_oracle_pytest(errors)

    api_base = (os.getenv("PILOT_API_BASE") or "").strip().rstrip("/")
    session_id = (args.session or os.getenv("PILOT_INTEGRITY_SESSION") or "").strip()
    if api_base and session_id:
        check_api_session(api_base, session_id, errors, warnings)
    elif session_id and not api_base:
        warnings.append(
            f"--session={session_id} ignorado sin PILOT_API_BASE (solo checks offline)"
        )

    if warnings:
        print("ADVERTENCIAS R5:")
        for w in warnings:
            print(f"  ⚠ {w}")

    if errors:
        print("SMOKE R5 FAIL:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print("SMOKE OK: expediente readiness + integridad HRU (R5)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
