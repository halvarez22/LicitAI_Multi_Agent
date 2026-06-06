"""P2-02: regresión por baseline anonimizado de sesiones referencia."""
from __future__ import annotations

import os

import pytest

from app.services.reference_session_baseline import (
    REFERENCE_SESSION_IDS,
    compare_counts_to_baseline,
    extract_session_counts,
    list_baseline_sessions,
    load_baseline,
)


def test_all_reference_baselines_exist():
    found = set(list_baseline_sessions())
    for sid in REFERENCE_SESSION_IDS:
        assert sid in found, f"Falta baseline JSON para {sid}"
        bl = load_baseline(sid)
        assert bl["schema_version"]
        mins = bl["minimums"]
        assert mins["hitos"] >= 1
        assert mins["junta_items"] >= 1


def test_compare_detects_regression():
    bl = load_baseline("vigilancia_issste")
    ok_counts = {
        "hitos": bl["minimums"]["hitos"],
        "junta_items": bl["minimums"]["junta_items"],
        "sobre_1_tecnico": bl["minimums"]["sobre_1_tecnico"],
        "compliance": dict(bl["minimums"]["compliance"]),
        "has_dictamen": True,
        "bases_committed": True,
    }
    assert compare_counts_to_baseline(ok_counts, bl) == []

    bad = dict(ok_counts)
    bad["hitos"] = 0
    violations = compare_counts_to_baseline(bad, bl)
    assert any(v.startswith("hitos:") for v in violations)


def test_extract_session_counts_from_mock_state():
    state = {
        "submission_checklist": {"hitos": [{}] * 6},
        "junta_aclaraciones_questions": {"summary": {"total": 4}, "items": [{}] * 4},
        "document_candidates_consolidated": {"sobre_1_tecnico": [{}] * 20},
        "compliance_master_list": {
            "administrativo": [{}] * 90,
            "tecnico": [{}] * 5,
            "formatos": [{}] * 26,
        },
        "dictamen": {"zones": []},
        "bases_analysis_snapshot": {
            "fingerprint": "abc",
            "pending_reanalysis": False,
        },
    }
    counts = extract_session_counts(state)
    bl = load_baseline("isapeg_servicios_de_limpieza")
    # Mock cumple mínimos ISAPEG en hitos/junta/dictamen; compliance puede variar
    assert counts["hitos"] >= bl["minimums"]["hitos"]
    assert counts["junta_items"] >= bl["minimums"]["junta_items"]
    assert counts["has_dictamen"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_reference_sessions_meet_baseline():
    """
    Requiere Postgres/Docker con las 3 sesiones cargadas.
    Ejecutar: LICITAI_REFERENCE_BASELINE_LIVE=1 pytest -m integration tests/test_reference_sessions_baseline.py
    """
    if os.environ.get("LICITAI_REFERENCE_BASELINE_LIVE") != "1":
        pytest.skip("Set LICITAI_REFERENCE_BASELINE_LIVE=1 para validar contra DB viva")

    from app.api.deps import get_connected_memory

    memory = await get_connected_memory()
    try:
        for sid in REFERENCE_SESSION_IDS:
            state = await memory.get_session(sid)
            assert state, f"Sesión {sid} no encontrada en Postgres"
            bl = load_baseline(sid)
            counts = extract_session_counts(state)
            violations = compare_counts_to_baseline(counts, bl)
            assert not violations, f"{sid} regresión vs baseline: {violations}"
    finally:
        await memory.disconnect()
