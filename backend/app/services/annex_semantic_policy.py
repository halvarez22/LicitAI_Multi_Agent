"""
Política versionada de roles semánticos de anexos (HRU universal).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "annex_semantic_policy.json"
)


@lru_cache(maxsize=1)
def load_annex_semantic_policy() -> Dict[str, Any]:
    """Carga annex_semantic_policy.json."""
    raw = _POLICY_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("annex_semantic_policy.json inválido")
    return data


def policy_version() -> str:
    return str(load_annex_semantic_policy().get("policy_version") or "unknown")


def match_threshold() -> int:
    try:
        return int(load_annex_semantic_policy().get("match_threshold") or 65)
    except (TypeError, ValueError):
        return 65


def panel_buckets() -> List[str]:
    pol = load_annex_semantic_policy()
    buckets = pol.get("panel_buckets") or []
    return [str(b) for b in buckets if b]


def economic_role_ids() -> frozenset[str]:
    pol = load_annex_semantic_policy()
    return frozenset(str(r) for r in (pol.get("economic_role_ids") or []) if r)


def role_definitions() -> List[Dict[str, Any]]:
    pol = load_annex_semantic_policy()
    roles = pol.get("roles") or []
    return [r for r in roles if isinstance(r, dict)]


def _compile_list(key: str, container: Dict[str, Any]) -> List[re.Pattern[str]]:
    out: List[re.Pattern[str]] = []
    for pat in container.get(key) or []:
        if not pat:
            continue
        try:
            out.append(re.compile(str(pat)))
        except re.error:
            continue
    return out


def role_signal_patterns(role: Dict[str, Any]) -> List[re.Pattern[str]]:
    return _compile_list("signal_patterns", role)


def role_query_patterns(role: Dict[str, Any]) -> List[re.Pattern[str]]:
    return _compile_list("query_role_patterns", role)


def generated_file_patterns_for_role(role_id: str) -> List[re.Pattern[str]]:
    pol = load_annex_semantic_policy()
    for row in pol.get("generated_file_role_patterns") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("role_id") or "") != role_id:
            continue
        return _compile_list("patterns", row)
    return []


def role_label_es(role_id: str) -> str:
    for role in role_definitions():
        if str(role.get("id") or "") == role_id:
            return str(role.get("label_es") or role_id)
    return role_id


def dedupe_matches_role(dedupe_key: str, role: Dict[str, Any]) -> bool:
    dk = str(dedupe_key or "")
    if not dk:
        return False
    for prefix in role.get("dedupe_key_prefixes") or []:
        p = str(prefix)
        if dk == p or dk.startswith(p):
            return True
    for pat in role.get("dedupe_key_patterns") or []:
        try:
            if re.search(str(pat), dk):
                return True
        except re.error:
            continue
    return False


def infer_role_from_blob(label: str, snippet: str = "", dedupe_key: str = "") -> Optional[str]:
    """Inferencia de rol semántico desde etiqueta/snippet/dedupe_key."""
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    blob = f"{label} {snippet}".strip()
    dk = dedupe_key or pliego_format_dedupe_key(label)

    best_role: Optional[str] = None
    best_score = 0
    for role in role_definitions():
        role_id = str(role.get("id") or "")
        if not role_id:
            continue
        signal_hit = any(rx.search(blob) for rx in role_signal_patterns(role))
        dedupe_hit = dk and dedupe_matches_role(dk, role)
        if signal_hit and dedupe_hit:
            score = 3
        elif signal_hit:
            score = 2
        elif dedupe_hit:
            score = 1
        else:
            continue
        if score > best_score:
            best_score = score
            best_role = role_id
    return best_role


def infer_roles_from_query(query: str) -> List[str]:
    """Roles sugeridos por el texto de la pregunta del usuario."""
    q = str(query or "")
    if not q.strip():
        return []
    found: List[str] = []
    for role in role_definitions():
        role_id = str(role.get("id") or "")
        if not role_id:
            continue
        for rx in role_query_patterns(role):
            if rx.search(q):
                found.append(role_id)
                break
    return found
