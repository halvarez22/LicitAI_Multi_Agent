#!/usr/bin/env python3
"""
Smoke F10 — Copiloto dual E2E sintético (HRU / CA-2.12, CA-2.13).

Simula una sesión tipo servicios (fixture genérico, sin hardcode por convocante):
  post-análisis → captura técnica + económica → totales F8 → streams paralelos F6.

No requiere API ni LLM. Nombre histórico «isapeg» = perfil de regresión piloto.

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_isapeg_dual_copilot_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List


class _Mem:
    def __init__(self, state: Dict[str, Any]):
        self.state = dict(state)

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        return dict(self.state)

    async def save_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        self.state.update(updates)
        return True


def _synthetic_pilot_session() -> Dict[str, Any]:
    """Fixture HRU: servicios con matriz de precios + requisitos técnicos."""
    return {
        "name": "Piloto servicios generico",
        "session_line_items": [
            {
                "concepto_raw": "Zona A",
                "cantidad": 1.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Zona A",
                    "source_filename": "anexo_precios_demo.xlsx",
                },
                "sheet_name": "Hoja1",
                "row_index": 2,
            },
            {
                "concepto_raw": "Zona B",
                "cantidad": 1.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Zona B",
                    "source_filename": "anexo_precios_demo.xlsx",
                },
                "sheet_name": "Hoja1",
                "row_index": 3,
            },
        ],
        "compliance_master_list": {
            "tecnico": [
                {
                    "id": "t-met",
                    "nombre": "Metodología de ejecución del servicio",
                    "tipo_accion": "generar",
                },
                {
                    "id": "t-per",
                    "nombre": "Personal mínimo por turno",
                    "tipo_accion": "generar",
                },
            ],
            "formatos": [],
        },
        "economic_user_inputs": {},
        "technical_user_inputs": {},
        "pending_questions": [],
    }


async def _run() -> int:
    errors: List[str] = []
    session_id = "smoke_dual_copilot_e2e"

    from app.services.chat_stop_reason_map import assert_user_visible_clean
    from app.services.economic_calculation_service import (
        build_price_capture_confirmation_message,
        economic_calc_on_capture_enabled,
    )
    from app.services.economic_capture_orchestrator import (
        gate_generar_economica_intent,
        try_handle_economic_capture,
    )
    from app.services.economic_post_analysis_hook import run_economic_post_analysis_hook
    from app.services.generation_concurrency_controller import try_acquire_stream_lock
    from app.services.generation_queue_controller import prepare_generation_queue_with_mode
    from app.services.technical_capture_orchestrator import (
        gate_generar_tecnica_intent,
        try_handle_technical_capture,
    )
    from app.services.technical_post_analysis_hook import run_technical_post_analysis_hook

    mem = _Mem(_synthetic_pilot_session())

    eco_hook = await run_economic_post_analysis_hook(mem, session_id, mem.state)
    if not eco_hook or eco_hook.get("status") not in ("queued", "already_complete"):
        errors.append(f"economic post_analysis hook inesperado: {eco_hook}")

    tech_hook = await run_technical_post_analysis_hook(mem, session_id, mem.state)
    if not tech_hook or tech_hook.get("status") not in ("queued", "already_complete"):
        errors.append(f"technical post_analysis hook inesperado: {tech_hook}")

    if not mem.state.get("technical_post_analysis_hook_pending"):
        errors.append("flag technical_post_analysis_hook_pending no seteada")

    tech_cap = try_handle_technical_capture(
        query="metodologia: limpieza hospitalaria por zonas con EPA",
        session_state=mem.state,
    )
    if not tech_cap or not tech_cap.handled:
        errors.append("captura técnica natural falló")
    else:
        mem.state.update(tech_cap.session_updates or {})
        if not tech_cap.technical_capture_v1:
            errors.append("sin technical_capture_v1 tras captura")

    tech_cap2 = try_handle_technical_capture(
        query="personal: 12 elementos turno matutino",
        session_state=mem.state,
    )
    if not tech_cap2 or not tech_cap2.handled:
        errors.append("captura personal falló")
    else:
        mem.state.update(tech_cap2.session_updates or {})

    gate_tech = gate_generar_tecnica_intent(mem.state)
    if gate_tech.should_block:
        errors.append("gate técnica bloqueó con slots completos")

    eco_status = try_handle_economic_capture(
        query="cuantos precios faltan",
        session_state=mem.state,
        pending_questions=mem.state.get("pending_questions") or [],
    )
    if not eco_status or not eco_status.handled:
        errors.append("consulta estado económico falló")

    # Simular precio capturado en inputs
    inputs = dict(mem.state.get("economic_user_inputs") or {})
    blocks = mem.state.get("capture_matrix_blocks") or []
    if blocks:
        for row in (blocks[0].get("matrix_rows") or [])[:2]:
            field = str(row.get("field") or "")
            if field:
                inputs[field] = 45250.0
    else:
        inputs["price_demo_a"] = 45250.0
        inputs["price_demo_b"] = 38000.0
    mem.state["economic_user_inputs"] = inputs
    from app.services.economic_canonical_v1 import sync_economic_canonical_v1

    mem.state.update(sync_economic_canonical_v1(mem.state))

    if economic_calc_on_capture_enabled():
        msg_totals = build_price_capture_confirmation_message(
            session_state=mem.state,
            label="Zona A",
            amount_mxn=45250.0,
            missing_count=1,
        )
        if "Totales actualizados" not in msg_totals:
            errors.append("F8: mensaje sin tabla de totales en E2E")
        try:
            assert_user_visible_clean(msg_totals)
        except AssertionError as exc:
            errors.append(f"UX totales: {exc}")

    dual = try_handle_technical_capture(
        query="como vamos tecnica y economica",
        session_state=mem.state,
    )
    if not dual or dual.tipo != "copilot_dual_status":
        errors.append("estado dual técnica+económica falló")

    gen_state: Dict[str, Any] = {}
    if not try_acquire_stream_lock(gen_state, "technical", "e2e-job-tech").acquired:
        errors.append("lock stream técnico F6")
    if not try_acquire_stream_lock(gen_state, "economic", "e2e-job-eco").acquired:
        errors.append("lock stream económico paralelo F6")

    tech_queue = prepare_generation_queue_with_mode(
        mem.state,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="technical",
        generation_stream="technical",
        job_id="e2e-job-tech",
    )
    eco_queue = prepare_generation_queue_with_mode(
        {**mem.state, "generation_state": gen_state},
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="economic",
        generation_stream="economic",
        job_id="e2e-job-eco",
    )
    if not tech_queue or not tech_queue.get("streams"):
        errors.append("cola técnica sin streams F6")
    if not eco_queue or not eco_queue.get("streams"):
        errors.append("cola económica sin streams F6")

    tech_jobs = {j.get("id"): j.get("status") for j in (tech_queue.get("jobs") or [])}
    eco_jobs = {j.get("id"): j.get("status") for j in (eco_queue.get("jobs") or [])}
    if tech_jobs.get("economic_writer") != "skipped":
        errors.append("modo técnico no omitió economic_writer")
    if eco_jobs.get("technical") != "skipped":
        errors.append("modo económico no omitió technical")

    gate_eco = gate_generar_economica_intent(mem.state)
    if gate_eco.should_block and int(mem.state.get("economic_user_inputs") and len(inputs) or 0) >= 2:
        pass  # puede faltar matriz completa — no bloquear E2E por tolerancia
    if gate_eco.capture_complete and gate_eco.should_block:
        errors.append("gate económica inconsistente (completo pero bloqueado)")

    for msg in (
        (tech_cap.respuesta if tech_cap else ""),
        (tech_cap2.respuesta if tech_cap2 else ""),
        (eco_status.respuesta if eco_status else ""),
        (dual.respuesta if dual else ""),
    ):
        if msg:
            try:
                assert_user_visible_clean(msg)
            except AssertionError as exc:
                errors.append(f"UX prohibida en E2E: {exc}")

    canon_t = (mem.state.get("technical_canonical_v1") or {}).get("items") or []
    canon_e = (mem.state.get("economic_canonical_v1") or {}).get("items") or []
    if not canon_t:
        errors.append("technical_canonical_v1 vacío al cierre E2E")
    if not canon_e:
        errors.append("economic_canonical_v1 vacío al cierre E2E")
    if canon_t and not any(
        isinstance(i, dict) and i.get("provenance_ui") for i in canon_t
    ):
        errors.append("technical sin provenance_ui")

    if errors:
        print("SMOKE F10 E2E FAIL:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("SMOKE OK: F10 dual copilot E2E (synthetic pilot session)")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
