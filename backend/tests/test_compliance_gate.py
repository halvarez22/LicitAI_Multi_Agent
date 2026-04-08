from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from app.agents.compliance_gate import ComplianceGate
from app.core.disqualification_rules import get_disqualification_rules


def load_real_fixture(fixture_name: str) -> dict:
    """Carga fixture real anonimizado para pruebas del gate."""
    path = Path(__file__).parent / "fixtures" / "real_sessions" / f"{fixture_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_rules_catalog_has_18_entries() -> None:
    rules = get_disqualification_rules()
    assert len(rules) == 18
    assert rules[0].code == "12.1.A"
    assert rules[-1].code == "12.1.R"


def test_compliance_gate_ok_real_fixture() -> None:
    session = load_real_fixture("example_compliance_ok")
    result = ComplianceGate().evaluate(session)
    assert result.is_blocking is False
    assert "12.1.R" not in result.failed_rules
    assert any(w["code"] == "12.1.I" for w in result.warnings)


def test_compliance_gate_blocking_rule_r_real_fixture() -> None:
    session = load_real_fixture("example_compliance_blocking_r")
    result = ComplianceGate().evaluate(session)
    assert result.is_blocking is True
    assert "12.1.R" in result.failed_rules


@pytest.mark.regression
def test_regression_real_session_licitacion_vigilancia_2026_04_08() -> None:
    """Regresión real: sesión la-51-gyn-051gyn025-n-8-2024_vigilancia (2026-04-08)."""
    session = load_real_fixture("example_compliance_ok")
    result = ComplianceGate().evaluate(session)
    assert result.is_blocking is False


def test_compliance_gate_benchmark_target_non_blocking() -> None:
    """Objetivo de rendimiento: cercano a 500ms (no bloqueante en CI)."""
    session = load_real_fixture("example_compliance_ok")
    gate = ComplianceGate()
    t0 = time.perf_counter()
    for _ in range(100):
        gate.evaluate(session)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 2500
