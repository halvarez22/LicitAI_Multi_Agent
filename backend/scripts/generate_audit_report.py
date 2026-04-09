"""Genera reporte de auditoría de sesión (JSON + CSV) para revisión legal/operativa.

Lee artefactos bajo ``out/`` y ``out/metadata/``, reevalúa el ComplianceGate con los
mismos payloads exportados (analysis/compliance/economic) y compone un resumen
determinista. Entrada/salida en JSON/CSV vía biblioteca estándar.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_app_path(backend_root: Path) -> None:
    root_s = str(backend_root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("No se pudo leer JSON %s: %s", path, e)
        return None


def _find_latest_job(backend_root: Path, session_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    candidates = [
        backend_root / "out" / "metadata" / "latest_job.json",
        backend_root / "out" / "latest_job.json",
    ]
    for p in candidates:
        data = _load_json(p)
        if not data:
            continue
        sid = str(data.get("session_id") or "")
        if sid and sid != session_id:
            logger.warning(
                "latest_job.json en %s es de otra sesión (%s != %s); se ignora.",
                p,
                sid,
                session_id,
            )
            continue
        if not sid:
            logger.warning(
                "latest_job.json en %s no define session_id; se usa para session_id=%s asumiendo correlación manual.",
                p,
                session_id,
            )
        return data, p
    return None, None


def _find_inputs_dir(backend_root: Path, session_id: str) -> Optional[Path]:
    """Directorio que contiene analysis.json, compliance.json, economic.json."""
    rels = [
        backend_root / "out" / "oracle_real",
        backend_root / "out" / session_id,
        backend_root / "out" / "oracle_inputs" / session_id,
    ]
    for d in rels:
        if (d / "analysis.json").is_file() and (d / "compliance.json").is_file() and (d / "economic.json").is_file():
            return d
    return None


def _collect_artifacts(session_id: str) -> List[str]:
    """Lista nombres de archivo bajo rutas típicas de salida (host)."""
    names: List[str] = []
    roots: List[Path] = []
    for base in (
        Path("C:/data/outputs") / session_id,
        Path("/data/outputs") / session_id,
        _backend_root().parent / "data" / "outputs" / session_id,
    ):
        if base.is_dir():
            roots.append(base)
    seen: set[str] = set()
    for root in roots:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
    return sorted(names)


def _normalize_pipeline_status(raw: Optional[str]) -> str:
    if not raw:
        return "UNKNOWN"
    u = str(raw).strip().upper()
    return u.replace(" ", "_")


def _run_compliance_gate(
    backend_root: Path, session_id: str, analysis: Dict[str, Any], compliance: Dict[str, Any], economic: Dict[str, Any]
) -> Dict[str, Any]:
    _ensure_app_path(backend_root)
    from app.agents.compliance_gate import ComplianceGate

    gate_payload = {
        "session_id": session_id,
        "analysis": analysis,
        "compliance": compliance,
        "economic": economic,
    }
    result = ComplianceGate().evaluate(gate_payload)
    return ComplianceGate.to_dict(result)


def _oracle_validation_block(
    oracle_report: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if oracle_report is None:
        return {
            "blocking_issues": None,
            "exit_code": None,
            "status": "MISSING",
            "note": "oracle_report.json no encontrado o ilegible; ejecutar run_oracle.py con --save-report.",
        }
    bi = oracle_report.get("blocking_issues")
    try:
        blocking = int(bi) if bi is not None else 0
    except (TypeError, ValueError):
        blocking = 0
    exit_code = 1 if blocking > 0 else 0
    status = "OK" if blocking == 0 else "FAIL"
    return {
        "blocking_issues": blocking,
        "exit_code": exit_code,
        "status": status,
        "oracle_timestamp": oracle_report.get("timestamp"),
        "total_issues": oracle_report.get("total_issues"),
    }


def _telemetry_from_latest_job(latest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "analysis_duration_s": None,
        "compliance_duration_s": None,
        "economic_duration_s": None,
    }
    if not latest:
        return out
    meta = latest.get("metadata")
    if not isinstance(meta, dict):
        return out
    tel = meta.get("telemetry")
    if not isinstance(tel, dict):
        return out
    stages = tel.get("stages")
    if not isinstance(stages, dict):
        return out
    for key, out_key in (
        ("analysis", "analysis_duration_s"),
        ("compliance", "compliance_duration_s"),
        ("economic", "economic_duration_s"),
    ):
        st = stages.get(key)
        if isinstance(st, dict):
            dur = st.get("duration_seconds")
            if isinstance(dur, (int, float)):
                out[out_key] = float(dur)
            elif dur is not None:
                try:
                    out[out_key] = float(dur)
                except (TypeError, ValueError):
                    pass
    return out


def _next_steps_recommendation(
    pipeline_status: str, gate_blocking: bool, stop_reason: Optional[str],
) -> str:
    if pipeline_status == "HARD_DISQUALIFICATION" and gate_blocking:
        return (
            "Descalificación determinista (12.1): revisar reglas fallidas y la evidencia citada; "
            "corregir propuesta o documentación y reejecutar el pipeline."
        )
    if pipeline_status in {"SUCCESS", "COMPLETED", "OK"}:
        return "Pipeline completado sin descalificación dura por gate; proceder con revisión humana y empaque/export."
    if stop_reason:
        return f"Estado {pipeline_status}: motivo registrado `{stop_reason}`; revisar logs y artefactos de agentes."
    return "Revisar telemetría y reportes Oracle para decidir siguientes pasos."


def build_audit_report(
    backend_root: Path,
    session_id: str,
    out_audit: Path,
) -> Tuple[int, Dict[str, Any]]:
    """Construye el dict del reporte y escribe JSON + CSV en ``out_audit``."""
    out_audit.mkdir(parents=True, exist_ok=True)

    latest, latest_path = _find_latest_job(backend_root, session_id)
    if latest_path:
        logger.info("latest_job: %s", latest_path)
    else:
        logger.warning("No se encontró latest_job.json coherente con session_id=%s", session_id)

    inputs_dir = _find_inputs_dir(backend_root, session_id)
    if not inputs_dir:
        logger.error(
            "No hay analysis.json/compliance.json/economic.json para session_id=%s "
            "(buscado en out/oracle_real, out/<session>, out/oracle_inputs/<session>).",
            session_id,
        )
        return 2, {}

    analysis = _load_json(inputs_dir / "analysis.json") or {}
    compliance = _load_json(inputs_dir / "compliance.json") or {}
    economic = _load_json(inputs_dir / "economic.json") or {}

    gate_dict = _run_compliance_gate(backend_root, session_id, analysis, compliance, economic)
    failed_rules: List[str] = list(gate_dict.get("failed_rules") or [])
    is_blocking = bool(gate_dict.get("is_blocking"))

    evidence_rules = gate_dict.get("evidence", {}).get("rules") if isinstance(gate_dict.get("evidence"), dict) else []
    evidence_summary: List[str] = []
    if isinstance(evidence_rules, list):
        for item in evidence_rules:
            if not isinstance(item, dict):
                continue
            if str(item.get("decision")) == "block":
                code = str(item.get("code", ""))
                reason = str(item.get("reason", ""))
                evidence_summary.append(f"{code}: {reason}".strip())

    oracle_path = backend_root / "out" / "oracle_report.json"
    oracle_report = _load_json(oracle_path)
    if oracle_report is None:
        logger.warning("oracle_report.json ausente en %s; se continúa sin validación Oracle en disco.", oracle_path)
    oracle_block = _oracle_validation_block(oracle_report)

    packager_path = inputs_dir / "packager.json"
    packaging = "present" if packager_path.is_file() else "skipped"

    pipeline_status = _normalize_pipeline_status(latest.get("status") if latest else None)
    stop_reason: Optional[str] = None
    if latest and isinstance(latest.get("orchestrator_decision"), dict):
        stop_reason = str(latest["orchestrator_decision"].get("stop_reason") or "") or None

    telemetry = _telemetry_from_latest_job(latest)
    artifacts = _collect_artifacts(session_id)

    report: Dict[str, Any] = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": pipeline_status,
        "stop_reason": stop_reason,
        "telemetry": telemetry,
        "compliance_gate": {
            "is_blocking": is_blocking,
            "failed_rules": failed_rules,
            "evidence_summary": evidence_summary,
        },
        "oracle_validation": oracle_block,
        "packaging": packaging,
        "artifacts_generated": artifacts,
        "inputs_dir_used": str(inputs_dir.relative_to(backend_root)).replace("\\", "/"),
        "next_steps_recommendation": _next_steps_recommendation(pipeline_status, is_blocking, stop_reason),
    }

    json_path = out_audit / "audit_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = out_audit / "audit_summary.csv"
    _write_audit_csv(csv_path, oracle_report, evidence_rules if isinstance(evidence_rules, list) else [])

    logger.info("Escrito %s y %s", json_path, csv_path)
    return 0, report


def _write_audit_csv(
    csv_path: Path,
    oracle_report: Optional[Dict[str, Any]],
    gate_rules: List[Any],
) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "estado", "criticidad", "evidencia_snippet", "recomendacion"])

        if oracle_report and isinstance(oracle_report.get("issues"), list):
            for item in oracle_report["issues"]:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("case_id", ""))
                est = str(item.get("estado_actual", ""))
                crit = str(item.get("criticidad", ""))
                causa = str(item.get("causa", ""))[:2000]
                w.writerow([cid, est, crit, causa, ""])

        for item in gate_rules:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", ""))
            decision = str(item.get("decision", ""))
            reason = str(item.get("reason", ""))[:2000]
            path = str(item.get("evidence_path", ""))
            crit = "blocking" if decision == "block" else ("warn" if decision == "warn" else "info")
            rec = f"Revisar fuente en `{path}`" if path else ""
            if decision in {"block", "warn"}:
                w.writerow([code, decision, crit, reason, rec])


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Genera audit_report.json y audit_summary.csv para una sesión.")
    p.add_argument("--session-id", required=True, help="Identificador de sesión (debe coincidir con exports).")
    p.add_argument(
        "--out",
        default="out/audit",
        help="Directorio base bajo backend (por defecto out/audit); se crea out/audit/<session_id>/.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    backend_root = _backend_root()
    out_base = backend_root / args.out
    session_dir = out_base / args.session_id
    code, _ = build_audit_report(backend_root, args.session_id, session_dir)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
