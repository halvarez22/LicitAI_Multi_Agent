from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_oracle_module():
    backend_root = Path(__file__).resolve().parents[1]
    module_path = backend_root / "scripts" / "oracle_validator.py"
    spec = importlib.util.spec_from_file_location("oracle_validator", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["oracle_validator"] = module
    spec.loader.exec_module(module)
    return module


def test_eval_case_ok_warn_blocking():
    ov = _load_oracle_module()
    payloads = {
        "analysis": {"cronograma": {"plazo_minimo_meses": "12 meses", "visita_instalaciones": None}},
        "compliance": {"causas_desechamiento": ["No firmar propuesta"]},
        "economic": {
            "proposal_items": [{"concepto": "Supervisor sin costo", "precio_unitario": 100}],
            "validation_result": {"validations": [{"regla": "consistencia_total_iva", "estado": "ok"}]},
        },
    }

    case_ok = {
        "case_id": "A01_min",
        "agent": "AnalystAgent",
        "agent_contract_path": "analysis.cronograma.plazo_minimo_meses",
        "expected_now": {"type": "string_or_null"},
        "criticality": "warn",
    }
    case_warn = {
        "case_id": "A02",
        "agent": "AnalystAgent",
        "agent_contract_path": "analysis.cronograma.visita_instalaciones",
        "expected_now": {"type": "string_or_null"},
        "criticality": "warn",
    }
    case_blocking = {
        "case_id": "E01",
        "agent": "EconomicAgent",
        "agent_contract_path": "economic.proposal_items",
        "expected_now": {"type": "array", "min_items": 1},
        "evidence_min": {"regex_pattern": "supervisor.*sin costo"},
        "criticality": "blocking",
    }

    r_ok = ov.eval_case(case_ok, payloads)
    r_warn = ov.eval_case(case_warn, payloads)
    r_block = ov.eval_case(case_blocking, payloads)

    assert r_ok.estado_actual == "ok"
    assert r_warn.estado_actual == "warn"
    assert r_block.estado_actual == "blocking"


def test_run_validation_exit_code_depends_on_blocking(tmp_path: Path):
    ov = _load_oracle_module()

    oracle = {
        "cases": [
            {
                "case_id": "E02",
                "agent": "EconomicAgent",
                "agent_contract_path": "economic.validation_result.validations",
                "expected_now": {"type": "array", "contains": {"regla": "consistencia_total_iva"}},
                "criticality": "blocking",
            }
        ]
    }
    analysis = {"data": {"cronograma": {}}}
    compliance = {"data": {"causas_desechamiento": []}}
    economic_warn = {
        "data": {"validation_result": {"validations": [{"regla": "consistencia_total_iva", "estado": "warn"}]}}
    }
    economic_blocking = {
        "data": {"validation_result": {"validations": [{"regla": "consistencia_total_iva", "estado": "blocking"}]}}
    }

    oracle_path = tmp_path / "oracle.json"
    analysis_path = tmp_path / "analysis.json"
    compliance_path = tmp_path / "compliance.json"
    economic_warn_path = tmp_path / "economic_warn.json"
    economic_blocking_path = tmp_path / "economic_blocking.json"

    oracle_path.write_text(json.dumps(oracle), encoding="utf-8")
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
    economic_warn_path.write_text(json.dumps(economic_warn), encoding="utf-8")
    economic_blocking_path.write_text(json.dumps(economic_blocking), encoding="utf-8")

    args_warn = SimpleNamespace(
        oracle=str(oracle_path),
        analysis=str(analysis_path),
        compliance=str(compliance_path),
        economic=str(economic_warn_path),
        max_fixes=5,
        save_report=True,
        report_dir=str(tmp_path / "out_warn"),
    )
    args_block = SimpleNamespace(
        oracle=str(oracle_path),
        analysis=str(analysis_path),
        compliance=str(compliance_path),
        economic=str(economic_blocking_path),
        max_fixes=5,
        save_report=True,
        report_dir=str(tmp_path / "out_block"),
    )

    assert ov.run_validation(args_warn) == 0
    assert ov.run_validation(args_block) == 1

    report_json = tmp_path / "out_block" / "oracle_report.json"
    report_txt = tmp_path / "out_block" / "oracle_report.txt"
    assert report_json.exists()
    assert report_txt.exists()

    report_data = json.loads(report_json.read_text(encoding="utf-8"))
    assert "timestamp" in report_data
    assert report_data["blocking_issues"] >= 1
