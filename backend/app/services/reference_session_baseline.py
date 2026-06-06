"""
Baseline anonimizado de artefactos por sesión referencia (solo conteos, sin PII).

Usado por tests de regresión P2-02 y smoke ampliado.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

BASELINE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real_sessions"
BASELINE_GLOB = "baseline_artifacts_*.json"

REFERENCE_SESSION_IDS = (
    "isapeg_servicios_de_limpieza",
    "unaq-2026_paneles_solares",
    "vigilancia_issste",
)


def baseline_path_for_session(session_id: str) -> Path:
    return BASELINE_DIR / f"baseline_artifacts_{session_id}.json"


def load_baseline(session_id: str) -> Dict[str, Any]:
    path = baseline_path_for_session(session_id)
    if not path.is_file():
        raise FileNotFoundError(f"Baseline no encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("session_id") != session_id:
        raise ValueError(f"session_id mismatch en {path.name}")
    return data


def list_baseline_sessions() -> List[str]:
    if not BASELINE_DIR.is_dir():
        return []
    out: List[str] = []
    for p in sorted(BASELINE_DIR.glob(BASELINE_GLOB)):
        sid = p.stem.replace("baseline_artifacts_", "", 1)
        if sid:
            out.append(sid)
    return out


def extract_session_counts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae conteos comparables al baseline desde session_data."""
    from scripts.smoke_session_stability import (
        count_hitos,
        count_junta_items,
        count_sobre_tecnico,
    )
    from app.services.session_bases_analysis_invalidation import bases_analysis_committed

    cml = state.get("compliance_master_list") or {}
    compliance = {}
    if isinstance(cml, dict):
        for zone in ("administrativo", "tecnico", "formatos"):
            rows = cml.get(zone)
            compliance[zone] = len(rows) if isinstance(rows, list) else 0

    return {
        "hitos": count_hitos(state),
        "junta_items": count_junta_items(state),
        "sobre_1_tecnico": count_sobre_tecnico(state),
        "compliance": compliance,
        "has_dictamen": bool(state.get("dictamen")),
        "bases_committed": bases_analysis_committed(state),
    }


def compare_counts_to_baseline(
    actual: Dict[str, Any],
    baseline: Dict[str, Any],
) -> List[str]:
    """
    Devuelve lista de violaciones si algún conteo actual < mínimo del baseline.
    """
    mins = baseline.get("minimums") or {}
    violations: List[str] = []

    for key in ("hitos", "junta_items", "sobre_1_tecnico"):
        floor = mins.get(key)
        if floor is None:
            continue
        cur = actual.get(key, 0)
        if cur < floor:
            violations.append(f"{key}:{cur}<{floor}")

    bc = mins.get("compliance") or {}
    ac = actual.get("compliance") or {}
    for zone in ("administrativo", "tecnico", "formatos"):
        floor = bc.get(zone)
        if floor is None:
            continue
        cur = ac.get(zone, 0)
        if cur < floor:
            violations.append(f"compliance.{zone}:{cur}<{floor}")

    if mins.get("has_dictamen") and not actual.get("has_dictamen"):
        violations.append("dictamen:missing")

    if mins.get("bases_committed") and not actual.get("bases_committed"):
        violations.append("bases_committed:false")

    return violations


def build_baseline_document(
    session_id: str,
    counts: Dict[str, Any],
    *,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Construye documento baseline anonimizado (para scripts de refresh)."""
    doc: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "session_id": session_id,
        "minimums": {
            "hitos": counts.get("hitos", 0),
            "junta_items": counts.get("junta_items", 0),
            "sobre_1_tecnico": counts.get("sobre_1_tecnico", 0),
            "compliance": dict(counts.get("compliance") or {}),
            "has_dictamen": bool(counts.get("has_dictamen")),
            "bases_committed": bool(counts.get("bases_committed")),
        },
    }
    if note:
        doc["note"] = note
    return doc
