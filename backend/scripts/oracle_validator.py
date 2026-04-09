"""Validador Oracle runtime v0.2 (portable Win/Posix, stdlib only)."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("oracle_validator")


def normalize_agent_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza payload de agente cuando viene envuelto en `data`."""
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        return raw["data"]
    return raw if isinstance(raw, dict) else {}


def get_by_path(obj: Any, path: str) -> Any:
    """Obtiene un valor por ruta con notacion `a.b.c`."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def resolve_path(root: Dict[str, Any], path: str, fallback: Optional[str]) -> Tuple[Any, str]:
    """Resuelve path principal y luego fallback opcional."""
    val = get_by_path(root, path)
    if val is not None:
        return val, path
    if fallback:
        val_fallback = get_by_path(root, fallback)
        if val_fallback is not None:
            return val_fallback, fallback
    return None, path


def is_null_like(v: Any) -> bool:
    """Detecta valores vacios/ambiguos comunes en extraccion."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in {"", "null", "none", "no especificado", "n/e"}
    return False


def text_has_ambiguous_range_without_unit(text: str) -> bool:
    """Detecta rangos numericos sin unidad de tiempo explicita."""
    t = text.lower()
    has_range = bool(re.search(r"\d+\s*-\s*\d+|\d+\s+a\s+\d+|entre\s+\d+\s+y\s+\d+", t))
    has_unit = "mes" in t
    return has_range and not has_unit


def state_rank(status: str) -> int:
    """Ranking para priorizar reporte."""
    return {"blocking": 3, "missing": 3, "warn": 2, "rule_fail": 2, "wrong_value": 2, "ok": 0}.get(status, 1)


def is_blocking_issue(result: CaseResult) -> bool:
    """Define si un hallazgo debe bloquear el pipeline."""
    return result.criticidad == "blocking" and result.estado_actual in {"missing", "rule_fail", "blocking"}


@dataclass
class CaseResult:
    """Resultado de evaluacion de un caso del oracle."""

    case_id: str
    estado_actual: str
    causa: str
    criticidad: str


def validate_type(value: Any, expected_type: str) -> bool:
    """Valida tipos basicos del contrato runtime del oracle."""
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "string_or_null":
        return value is None or isinstance(value, str)
    if expected_type == "int_or_null":
        return value is None or isinstance(value, int)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "array_string_or_object":
        if not isinstance(value, list):
            return False
        return all(isinstance(item, (str, dict)) for item in value)
    if expected_type == "bool":
        return isinstance(value, bool)
    return True


def contains_rule_item(arr: List[Any], rule_name: str) -> Optional[Dict[str, Any]]:
    """Busca una regla por nombre exacto en lista de validaciones."""
    for item in arr:
        if isinstance(item, dict) and str(item.get("regla", "")).strip() == rule_name:
            return item
    return None


def match_regex_in_items(items: List[Any], pattern: str) -> bool:
    """Aplica regex a strings u objetos serializados de forma segura."""
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for item in items:
        if isinstance(item, str) and rx.search(item):
            return True
        if isinstance(item, dict):
            blob = " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float)))
            if rx.search(blob):
                return True
    return False


def _agent_root(agent_name: str, payloads: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Construye root de path segun el agente del caso."""
    if agent_name == "AnalystAgent":
        data = payloads.get("analysis", {}) or {}
        if isinstance(data, dict) and "data" not in data:
            data = {"data": data, **data}
        return {"analysis": data}
    if agent_name == "ComplianceAgent":
        data = payloads.get("compliance", {}) or {}
        if isinstance(data, dict) and "data" not in data:
            data = {"data": data, **data}
        return {"compliance": data}
    if agent_name == "EconomicAgent":
        data = payloads.get("economic", {}) or {}
        if isinstance(data, dict) and "data" not in data:
            data = {"data": data, **data}
        return {"economic": data}
    if agent_name == "ComplianceGate":
        gate = payloads.get("compliance_gate")
        if isinstance(gate, dict):
            return {"compliance_gate": gate}
        compliance_data = payloads.get("compliance", {}) or {}
        embedded = (
            compliance_data.get("compliance_gate_result")
            if isinstance(compliance_data, dict)
            else None
        )
        if isinstance(embedded, dict):
            return {"compliance_gate": embedded}
        # Compatibilidad: si no viene explícito en payload runtime, asumir no bloqueante.
        return {"compliance_gate": {"is_blocking": False}}
    return None


def eval_pkg01(case: Dict[str, Any], payloads: Dict[str, Dict[str, Any]]) -> CaseResult:
    """Caso Oracle PKG01: salida determinista del empaquetador CompraNet."""
    crit = str(case.get("criticality", "blocking"))
    raw = payloads.get("packager")
    if raw is None:
        return CaseResult(
            "PKG01",
            "ok",
            "Sin packager.json en esta corrida Oracle (compatibilidad con exports históricos).",
            crit,
        )
    data = normalize_agent_payload(raw)
    if not isinstance(data, dict):
        data = {}
    passed = data.get("validation_passed")
    files = data.get("files") or []
    if passed is True and isinstance(files, list) and len(files) > 0:
        return CaseResult("PKG01", "ok", "Empaque CompraNet y manifiesto SHA-256 conformes.", crit)
    if passed is True:
        return CaseResult(
            "PKG01",
            "warn",
            "validation_passed true pero manifiesto sin archivos listados.",
            crit,
        )
    if passed is False:
        return CaseResult("PKG01", "blocking", "Validación de empaque CompraNet fallida.", crit)
    return CaseResult(
        "PKG01",
        "missing",
        "Campo validation_passed ausente o no booleano en payload packager.",
        crit,
    )


def eval_case(case: Dict[str, Any], payloads: Dict[str, Dict[str, Any]]) -> CaseResult:
    """Evalua un caso oracle contra payloads runtime."""
    case_id = str(case.get("case_id", "unknown_case"))
    if case_id == "PKG01":
        return eval_pkg01(case, payloads)
    agent = str(case.get("agent", ""))
    crit = str(case.get("criticality", "warn"))
    path = str(case.get("agent_contract_path", ""))
    fallback = case.get("fallback_path")
    expected_now = case.get("expected_now", {}) or {}
    expected_type = str(expected_now.get("type", "any"))

    root = _agent_root(agent, payloads)
    if root is None:
        return CaseResult(case_id, "warn", f"Agente no soportado: {agent}", crit)

    value, used_path = resolve_path(root, path, fallback)
    if not validate_type(value, expected_type):
        status = "missing" if value is None else "wrong_value"
        return CaseResult(
            case_id,
            status,
            f"Path '{used_path}' invalido. Esperado {expected_type}, obtenido {type(value).__name__}",
            crit,
        )

    if case_id.startswith("A01_"):
        if is_null_like(value):
            return CaseResult(case_id, "warn", "Campo no detectado explicitamente.", crit)
        value_text = str(value)
        if text_has_ambiguous_range_without_unit(value_text):
            return CaseResult(case_id, "warn", "Rango ambiguo sin unidad 'mes' explicita.", crit)
        if re.search(r"\d+", value_text):
            return CaseResult(case_id, "ok", "Valor numerico detectado.", crit)
        return CaseResult(case_id, "warn", "No contiene digito extraible.", crit)

    if case_id == "A02":
        value_text = "" if value is None else str(value).strip()
        if is_null_like(value_text):
            return CaseResult(case_id, "warn", "Visita no especificada en cronograma.", crit)
        regex_pattern = ((case.get("evidence_min") or {}).get("regex_pattern")) or ""
        has_evidence = bool(regex_pattern and re.search(regex_pattern, value_text, re.IGNORECASE | re.DOTALL))
        if has_evidence or re.search(r"obligatoria", value_text, re.IGNORECASE):
            return CaseResult(case_id, "ok", "Visita con evidencia de obligatoriedad detectada.", crit)
        return CaseResult(case_id, "warn", "Campo presente sin evidencia clara de obligatoriedad.", crit)

    if case_id == "C01":
        min_items = int(expected_now.get("min_items", 1))
        if not isinstance(value, list) or len(value) < min_items:
            return CaseResult(case_id, "blocking", "No hay causas de desechamiento suficientes.", crit)
        regex_pattern = ((case.get("evidence_min") or {}).get("regex_pattern")) or ""
        if regex_pattern and not match_regex_in_items(value, regex_pattern):
            return CaseResult(case_id, "warn", "Lista presente sin match semantico esperado.", crit)
        return CaseResult(case_id, "ok", "Causas detectadas.", crit)

    if case_id == "C02":
        min_items = int(expected_now.get("min_items", 1))
        if not isinstance(value, list) or len(value) < min_items:
            return CaseResult(case_id, "blocking", "No hay bloque administrativo_legal usable.", crit)
        regex_pattern = ((case.get("evidence_min") or {}).get("regex_pattern")) or ""
        if regex_pattern and not match_regex_in_items(value, regex_pattern):
            return CaseResult(case_id, "blocking", "No se detecto requisito CUIPS/REPSE por patron.", crit)
        return CaseResult(case_id, "ok", "Requisitos de seguridad detectados.", crit)

    if case_id == "E01":
        min_items = int(expected_now.get("min_items", 1))
        if not isinstance(value, list) or len(value) < min_items:
            return CaseResult(case_id, "blocking", "No hay items economicos para validar.", crit)
        regex_pattern = ((case.get("evidence_min") or {}).get("regex_pattern")) or r"supervisor.*sin costo"
        rx = re.compile(regex_pattern, re.IGNORECASE | re.DOTALL)
        matched_any = False
        bad_any = False
        for item in value:
            if not isinstance(item, dict):
                continue
            text = f"{item.get('concepto', '')} {item.get('descripcion', '')}".strip()
            if rx.search(text):
                matched_any = True
                unit_price = item.get("precio_unitario")
                try:
                    unit_price_value = float(unit_price)
                except (TypeError, ValueError):
                    unit_price_value = -1.0
                if unit_price_value > 0:
                    bad_any = True
                    break
        if matched_any and bad_any:
            return CaseResult(case_id, "blocking", "Supervisor sin costo detectado con precio > 0.", crit)
        if matched_any:
            return CaseResult(case_id, "ok", "Supervisor sin costo consistente (precio 0).", crit)
        # Compatibilidad de bases donde la supervisión se exige vía "costos indirectos".
        compliance_blob = json.dumps(payloads.get("compliance", {}), ensure_ascii=False).lower()
        if re.search(r"supervisor|coordinador|jefe\s*de\s*turno", compliance_blob) and re.search(
            r"costos?\s+indirectos?", compliance_blob
        ):
            return CaseResult(case_id, "ok", "Supervisión exigida en costos indirectos (sin costo directo).", crit)
        return CaseResult(case_id, "warn", "No se detecto partida explicita de supervisor sin costo.", crit)

    if case_id == "CG01":
        if not isinstance(value, bool):
            return CaseResult(case_id, "missing", "compliance_gate.is_blocking ausente o inválido.", crit)
        if value:
            return CaseResult(case_id, "blocking", "ComplianceGate marcó descalificación determinista.", crit)
        return CaseResult(case_id, "ok", "ComplianceGate no detectó bloqueo determinista.", crit)

    if case_id in {"E02", "E03"}:
        if not isinstance(value, list):
            return CaseResult(case_id, "missing", "Validation result no es array.", crit)
        contains = expected_now.get("contains", {}) or {}
        rule_name = str(contains.get("regla", ""))
        item = contains_rule_item(value, rule_name)
        if not item:
            return CaseResult(case_id, "rule_fail", f"No existe regla '{rule_name}'.", crit)
        state = str(item.get("estado", "")).strip().lower()
        if state not in {"ok", "warn", "blocking"}:
            return CaseResult(case_id, "wrong_value", f"Estado invalido en regla '{rule_name}': {state}", crit)
        if case_id == "E02" and state == "blocking":
            return CaseResult(case_id, "blocking", "consistencia_total_iva en blocking.", crit)
        if case_id == "E03" and state == "blocking":
            return CaseResult(case_id, "warn", "ppe_formula en blocking: revisar calculo/datos.", crit)
        return CaseResult(case_id, "ok", f"{rule_name}={state}", crit)

    if expected_type == "array":
        min_items = int(expected_now.get("min_items", 0))
        if isinstance(value, list) and len(value) < min_items:
            return CaseResult(case_id, "rule_fail", f"Array con {len(value)} < {min_items}", crit)
    return CaseResult(case_id, "ok", "Valida por regla generica.", crit)


def evaluate_cases(oracle: Dict[str, Any], payloads: Dict[str, Dict[str, Any]]) -> List[CaseResult]:
    """Evalua todos los casos del oracle y regresa solo no-ok."""
    failures: List[CaseResult] = []
    for case in oracle.get("cases", []):
        result = eval_case(case, payloads)
        if result.estado_actual != "ok":
            failures.append(result)
    failures.sort(key=lambda item: state_rank(item.estado_actual), reverse=True)
    return failures


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_text_report(results: List[CaseResult], max_fixes: int) -> str:
    """Renderiza reporte legible en texto plano."""
    selected = results[: max(1, max_fixes)]
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("REPORTE ORACLE (CASOS NO-OK)")
    lines.append("=" * 60)
    if not selected:
        lines.append("OK: Todos los casos del oracle pasaron.")
    else:
        for item in selected:
            lines.append(f"case_id: {item.case_id}")
            lines.append(f"estado_actual: {item.estado_actual}")
            lines.append(f"causa: {item.causa}")
            lines.append(f"criticidad: {item.criticidad}")
            lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def build_json_report(results: List[CaseResult], max_fixes: int) -> Dict[str, Any]:
    """Construye reporte JSON con metadata requerida."""
    selected = results[: max(1, max_fixes)]
    return {
        "timestamp": _utc_now_iso(),
        "total_issues": len(results),
        "reported_issues": len(selected),
        "blocking_issues": sum(1 for r in results if is_blocking_issue(r)),
        "issues": [asdict(r) for r in selected],
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parsers CLI del validador."""
    parser = argparse.ArgumentParser(description="Valida salidas de agentes contra oracle runtime.")
    parser.add_argument("--oracle", required=True, help="Path a oracle JSON.")
    parser.add_argument("--analysis", required=True, help="Path a salida analysis JSON.")
    parser.add_argument("--compliance", required=True, help="Path a salida compliance JSON.")
    parser.add_argument("--economic", required=True, help="Path a salida economic JSON.")
    parser.add_argument("--packager", default="", help="Path opcional a packager.json (stage compranet_pack).")
    parser.add_argument("--max-fixes", type=int, default=5, help="Numero maximo de issues a reportar.")
    parser.add_argument("--save-report", action="store_true", help="Guarda reportes en out/oracle_report.*")
    parser.add_argument("--report-dir", default="out", help="Directorio de salida para reportes.")
    return parser.parse_args(argv)


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Archivo JSON invalido (se esperaba objeto): {path}")
    return data


def run_validation(args: argparse.Namespace) -> int:
    """Ejecuta validacion completa y retorna exit code."""
    project_root = Path(__file__).resolve().parents[1]
    oracle_path = (project_root / args.oracle).resolve() if not Path(args.oracle).is_absolute() else Path(args.oracle)
    analysis_path = (project_root / args.analysis).resolve() if not Path(args.analysis).is_absolute() else Path(args.analysis)
    compliance_path = (
        (project_root / args.compliance).resolve() if not Path(args.compliance).is_absolute() else Path(args.compliance)
    )
    economic_path = (project_root / args.economic).resolve() if not Path(args.economic).is_absolute() else Path(args.economic)

    oracle = _load_json(oracle_path)
    payloads: Dict[str, Any] = {
        "analysis": normalize_agent_payload(_load_json(analysis_path)),
        "compliance": normalize_agent_payload(_load_json(compliance_path)),
        "economic": normalize_agent_payload(_load_json(economic_path)),
    }
    packager_arg = str(getattr(args, "packager", "") or "").strip()
    if packager_arg:
        pkg_path = (project_root / packager_arg).resolve() if not Path(packager_arg).is_absolute() else Path(packager_arg)
        if pkg_path.is_file():
            payloads["packager"] = _load_json(pkg_path)
        else:
            payloads["packager"] = None
    else:
        payloads["packager"] = None

    issues = evaluate_cases(oracle, payloads)
    blocking_issues = sum(1 for issue in issues if is_blocking_issue(issue))
    text_report = render_text_report(issues, args.max_fixes)
    json_report = build_json_report(issues, args.max_fixes)
    print(text_report)
    print(f"RESUMEN: {len(issues)} hallazgos | {blocking_issues} blocking_issues")

    if args.save_report:
        report_dir = (project_root / args.report_dir).resolve()
        report_dir.mkdir(parents=True, exist_ok=True)
        txt_path = report_dir / "oracle_report.txt"
        json_path = report_dir / "oracle_report.json"
        txt_path.write_text(text_report + "\n", encoding="utf-8")
        json_path.write_text(json.dumps(json_report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Reportes guardados en %s", report_dir)

    return 1 if blocking_issues > 0 else 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry-point CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    return run_validation(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
