#!/usr/bin/env python3
"""
Smoke F10 — Piloto on-premise HRU (suite unificada F0–F10).

Valida contratos versionados, flags piloto, sub-smokes F1–F9 y E2E copiloto dual.
Opcional: health API si ``PILOT_API_BASE`` está definido (ej. http://127.0.0.1:8001/api/v1).

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_pilot_onprem_hru.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND_ROOT / "scripts"
CONTRACTS = BACKEND_ROOT / "app" / "contracts"


def check_contract_versions(errors: List[str]) -> None:
    from app.services.document_fill_deferral_policy import policy_version as defer_v
    from app.services.generation_concurrency_controller import policy_version as conc_v
    from app.services.generation_mode_policy import policy_version as gen_v
    from app.services.packaging_policy import policy_version as pack_v
    from app.services.pilot_onprem_policy import policy_version as pilot_v

    for label, ver in (
        ("deferral", defer_v()),
        ("generation_concurrency", conc_v()),
        ("generation_mode", gen_v()),
        ("packaging", pack_v()),
        ("pilot_onprem", pilot_v()),
    ):
        if not ver:
            errors.append(f"Sin policy_version: {label}")

    for name in (
        "document_fill_deferral_policy.json",
        "generation_mode_policy.json",
        "generation_concurrency_policy.json",
        "economic_capture_policy.json",
        "economic_canonical_v1.json",
        "economic_calculation_policy.json",
        "chat_copilot_ux_messages.json",
        "technical_capture_policy.json",
        "technical_canonical_v1.json",
        "document_quality_ux_messages.json",
        "expediente_mission_policy.json",
        "packaging_policy.json",
        "pilot_onprem_policy.json",
    ):
        if not (CONTRACTS / name).is_file():
            errors.append(f"Contrato faltante: {name}")


def check_pilot_runtime(errors: List[str], warnings: List[str]) -> None:
    from app.services.pilot_onprem_policy import evaluate_pilot_runtime

    report = evaluate_pilot_runtime()
    warnings.extend(report.get("warnings") or [])
    errors.extend(report.get("errors") or [])


def check_ux_samples(errors: List[str]) -> None:
    from app.services.chat_stop_reason_map import (
        assert_user_visible_clean,
        humanize_stop_reason,
    )
    from app.services.document_fill_ux_messages import build_fill_quality_user_brief

    for reason in (
        "IDLE",
        "MISSING_ECONOMIC_PROPOSAL",
        "ECONOMIC_PRICES_INCOMPLETE",
        "INCOMPLETE_FORMATS_DATA",
        "GENERATION_COMPLETED",
    ):
        msg = humanize_stop_reason(reason)
        try:
            assert_user_visible_clean(msg)
        except AssertionError as exc:
            errors.append(f"UX stop_reason {reason}: {exc}")

    brief = build_fill_quality_user_brief(
        "formats",
        [{"field_key": "tarifa_mensual", "severity": "warning", "message": "Tarifa pendiente"}],
    )
    try:
        assert_user_visible_clean(brief.get("full_message") or "")
    except AssertionError as exc:
        errors.append(f"UX fill brief: {exc}")


def run_subprocess_smoke(script_name: str, errors: List[str], extra_args: List[str] | None = None) -> None:
    script = SCRIPTS / script_name
    if not script.is_file():
        errors.append(f"Script smoke faltante: {script_name}")
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    cmd = [sys.executable, str(script), *(extra_args or [])]
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "")[-800:]
        errors.append(f"{script_name} falló (exit {proc.returncode}): {tail.strip()}")


async def optional_api_health(warnings: List[str]) -> None:
    base = (os.getenv("PILOT_API_BASE") or "").strip().rstrip("/")
    if not base:
        return
    try:
        import urllib.request

        url = f"{base}/health"
        with urllib.request.urlopen(url, timeout=8) as resp:
            if resp.status != 200:
                warnings.append(f"PILOT_API_BASE health HTTP {resp.status}")
    except Exception as exc:
        warnings.append(f"PILOT_API_BASE no alcanzable ({base}): {exc}")


async def _main_async() -> int:
    errors: List[str] = []
    warnings: List[str] = []

    check_contract_versions(errors)
    check_pilot_runtime(errors, warnings)
    check_ux_samples(errors)
    run_subprocess_smoke("smoke_economic_chat_capture.py", errors)
    run_subprocess_smoke("smoke_technical_chat_capture.py", errors)
    run_subprocess_smoke("smoke_decoupled_generation.py", errors)
    run_subprocess_smoke("smoke_dual_stream_concurrency.py", errors)
    run_subprocess_smoke("smoke_isapeg_dual_copilot_e2e.py", errors)
    run_subprocess_smoke("smoke_expediente_readiness_integrity.py", errors, ["--skip-pytest"])
    await optional_api_health(warnings)

    if warnings:
        print("ADVERTENCIAS PILOTO:")
        for w in warnings:
            print(f"  ⚠ {w}")

    if errors:
        print("SMOKE F10 FAIL:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print("SMOKE OK: pilot on-premise F10 (HRU suite F0–F10)")
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
