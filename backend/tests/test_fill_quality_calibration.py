from __future__ import annotations

from pathlib import Path

from app.config.settings import settings as app_settings
from app.services.fill_quality_calibration import (
    load_calibration_cases,
    load_calibration_policy,
    run_fill_gate_calibration,
)


def test_fill_quality_calibration_runner_genera_metricas(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    dataset = Path(__file__).parent / "fixtures" / "fill_quality_calibration" / "dataset_v1.json"
    cases = load_calibration_cases(dataset)
    report = run_fill_gate_calibration(cases)

    assert report["cases_total"] >= 5
    assert "global_metrics" in report
    assert "metrics_by_error_type" in report
    assert "required_field_missing" in report["metrics_by_error_type"]
    assert "placeholder_detected" in report["metrics_by_error_type"]
    assert len(report["results"]) == report["cases_total"]


def test_fill_quality_calibration_detecta_edge_case_persona_fisica(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    dataset = Path(__file__).parent / "fixtures" / "fill_quality_calibration" / "dataset_v1.json"
    cases = load_calibration_cases(dataset)
    report = run_fill_gate_calibration(cases)
    edge = next(x for x in report["results"] if x["case_id"] == "formats_persona_fisica_edge_001")
    assert edge["fp"] >= 1


def test_fill_quality_calibration_policy_v1_mejora_precision(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    base = Path(__file__).parent / "fixtures" / "fill_quality_calibration"
    cases = load_calibration_cases(base / "dataset_v1.json")
    policy = load_calibration_policy(base / "policy_v1.json")
    baseline = run_fill_gate_calibration(cases)
    tuned = run_fill_gate_calibration(cases, policy=policy)
    assert tuned["global_metrics"]["precision"] >= baseline["global_metrics"]["precision"]


def test_fill_quality_calibration_policy_v1_1_mejora_sobre_v1(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    base = Path(__file__).parent / "fixtures" / "fill_quality_calibration"
    cases = load_calibration_cases(base / "dataset_v1.json")
    policy_v1 = load_calibration_policy(base / "policy_v1.json")
    policy_v1_1 = load_calibration_policy(base / "policy_v1_1.json")
    tuned_v1 = run_fill_gate_calibration(cases, policy=policy_v1)
    tuned_v1_1 = run_fill_gate_calibration(cases, policy=policy_v1_1)
    assert tuned_v1_1["global_metrics"]["precision"] >= tuned_v1["global_metrics"]["precision"]


def test_fill_quality_calibration_policy_v1_2_con_guardas_produccion(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    base = Path(__file__).parent / "fixtures" / "fill_quality_calibration"
    cases = load_calibration_cases(base / "dataset_v1.json")
    policy_v1_2 = load_calibration_policy(base / "policy_v1_2.json")
    baseline = run_fill_gate_calibration(cases)
    tuned = run_fill_gate_calibration(cases, policy=policy_v1_2)
    assert tuned["global_metrics"]["precision"] >= baseline["global_metrics"]["precision"]
    assert tuned["blocking_match_rate"] == 1.0


def test_fill_quality_calibration_policy_v1_2b_mejora_sobre_v1_2(monkeypatch):
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "audit")
    base = Path(__file__).parent / "fixtures" / "fill_quality_calibration"
    cases = load_calibration_cases(base / "dataset_v1.json")
    policy_v1_2 = load_calibration_policy(base / "policy_v1_2.json")
    policy_v1_2b = load_calibration_policy(base / "policy_v1_2b.json")
    tuned_v1_2 = run_fill_gate_calibration(cases, policy=policy_v1_2)
    tuned_v1_2b = run_fill_gate_calibration(cases, policy=policy_v1_2b)
    assert tuned_v1_2b["global_metrics"]["precision"] >= tuned_v1_2["global_metrics"]["precision"]
    econ_case = next(x for x in tuned_v1_2b["results"] if x["case_id"] == "economic_docx_valid_totals_001")
    assert econ_case["signals"]["consistency_pass"] is True
    assert econ_case["signals"]["arithmetic_match"] is True
