"""
Política HRU universal para parámetros FSR (Factor de Salario Real).

Fuente canónica: ``app/contracts/economic_fsr_policy.json``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "economic_fsr_policy.json"


@lru_cache(maxsize=1)
def load_economic_fsr_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_economic_fsr_policy().get("policy_version") or "")


def required_fsr_param_keys() -> Tuple[str, ...]:
    raw = load_economic_fsr_policy().get("required_param_keys") or []
    return tuple(str(k) for k in raw if str(k).strip())


def fsr_param_label(key: str) -> str:
    labels = load_economic_fsr_policy().get("param_labels") or {}
    return str(labels.get(key) or key)


def fsr_param_labels_human(keys: List[str]) -> str:
    if not keys:
        return "parámetros FSR"
    return ", ".join(fsr_param_label(str(k)) for k in keys)


def chat_capture_patterns() -> Dict[str, str]:
    raw = load_economic_fsr_policy().get("chat_capture_patterns") or {}
    return {str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v).strip()}


def ingest_concept_aliases() -> Dict[str, List[str]]:
    raw = load_economic_fsr_policy().get("ingest_concept_aliases") or {}
    out: Dict[str, List[str]] = {}
    for key, aliases in raw.items():
        if not isinstance(aliases, list):
            continue
        out[str(key)] = [str(a).strip().lower() for a in aliases if str(a).strip()]
    return out


def optional_fallback_defaults() -> Dict[str, str]:
    raw = load_economic_fsr_policy().get("optional_fallback_defaults") or {}
    return {str(k): str(v) for k, v in raw.items()}


def match_ingest_concept_to_fsr_key(concept_lower: str) -> str:
    """Resuelve fila Excel → clave canónica FSR; vacío si no aplica."""
    text = str(concept_lower or "").strip().lower()
    if not text:
        return ""
    for key, aliases in ingest_concept_aliases().items():
        if text == key or text in aliases:
            return key
        if any(text.startswith(a) or a in text for a in aliases):
            return key
    return ""


def extract_fsr_params_from_reglas(reglas_economicas: Dict[str, str]) -> Dict[str, Any]:
    """
    Extrae parámetros FSR desde reglas de bases (formato ``clave=valor``).
    Aplica fallbacks solo desde política versionada (nunca inventa imss ni aguinaldo).
    """
    policy = load_economic_fsr_policy()
    priority_keys = policy.get("reglas_blob_key_priority") or []
    blobs: List[str] = []
    reglas = reglas_economicas or {}
    for pk in priority_keys:
        val = reglas.get(pk)
        if val:
            blobs.append(str(val))
    if not blobs:
        blobs.append(" ".join(str(v or "") for v in reglas.values()))
    blob = " ".join(blobs)
    out: Dict[str, Any] = {}
    fallbacks = optional_fallback_defaults()
    for key in required_fsr_param_keys():
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", blob, flags=re.I)
        if m:
            out[key] = m.group(1)
        elif key in fallbacks:
            out[key] = fallbacks[key]
    return out
