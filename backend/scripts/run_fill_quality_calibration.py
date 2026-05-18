from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.services.fill_quality_calibration import (
    load_calibration_cases,
    load_calibration_policy,
    run_fill_gate_calibration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta calibracion del Fill Quality Gate.")
    parser.add_argument(
        "--dataset",
        default="tests/fixtures/fill_quality_calibration/dataset_v1.json",
        help="Ruta al dataset JSON de calibracion",
    )
    parser.add_argument(
        "--out",
        default="scratch/fill_quality_calibration_report.json",
        help="Ruta de salida del reporte JSON",
    )
    parser.add_argument(
        "--policy",
        default="",
        help="Ruta opcional de policy JSON para tuning",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    cases = load_calibration_cases(dataset_path)
    baseline = run_fill_gate_calibration(cases)
    baseline["dataset_path"] = str(dataset_path)
    report = {"baseline": baseline}
    if args.policy:
        policy = load_calibration_policy(Path(args.policy))
        tuned = run_fill_gate_calibration(cases, policy=policy)
        report["tuned"] = tuned
        report["comparison"] = {
            "precision_delta": round(
                float(tuned["global_metrics"]["precision"]) - float(baseline["global_metrics"]["precision"]), 4
            ),
            "recall_delta": round(
                float(tuned["global_metrics"]["recall"]) - float(baseline["global_metrics"]["recall"]), 4
            ),
            "blocking_match_delta": round(
                float(tuned["blocking_match_rate"]) - float(baseline["blocking_match_rate"]), 4
            ),
        }
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "cases": baseline["cases_total"], "out": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
