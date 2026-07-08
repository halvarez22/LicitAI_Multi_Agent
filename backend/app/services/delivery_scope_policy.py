"""
Política HRU versionada para descarga contextual post-generación (F5.1).

Fuentes canónicas:
  - ``app/contracts/delivery_scope_policy.json``
  - ``app/contracts/delivery_ux_messages.json``

El flag ``CONTEXTUAL_DOWNLOAD_ENABLED`` solo habilita/deshabilita operación en UI/API.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.contracts.delivery_scopes import DeliveryScope

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
_SCOPE_POLICY_PATH = _CONTRACTS_DIR / "delivery_scope_policy.json"
_UX_MESSAGES_PATH = _CONTRACTS_DIR / "delivery_ux_messages.json"


@lru_cache(maxsize=1)
def load_delivery_scope_policy() -> Dict[str, Any]:
    """Carga la política de alcances desde JSON versionado."""
    with _SCOPE_POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_delivery_ux_messages() -> Dict[str, Any]:
    """Carga mensajes UX centralizados para descarga contextual."""
    with _UX_MESSAGES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_delivery_scope_policy().get("policy_version") or "")


def ux_messages_version() -> str:
    return str(load_delivery_ux_messages().get("messages_version") or "")


def contextual_download_enabled() -> bool:
    """True si la descarga contextual F5 está habilitada por feature flag."""
    return bool(getattr(settings, "CONTEXTUAL_DOWNLOAD_ENABLED", True))


def normalize_delivery_scope(raw: Optional[str]) -> str:
    """
    Normaliza alias y valores externos al alcance canónico.

    Si la feature está deshabilitada, retorna ``full`` (vista entrega legacy).
    """
    if not contextual_download_enabled():
        return DeliveryScope.FULL.value

    policy = load_delivery_scope_policy()
    aliases = policy.get("aliases") if isinstance(policy.get("aliases"), dict) else {}
    default_scope = str(policy.get("default_scope") or DeliveryScope.FULL.value)

    token = str(raw or "").strip().lower()
    if not token:
        return default_scope
    if token in aliases:
        token = str(aliases[token]).strip().lower()
    if token in DeliveryScope.values():
        return token
    return default_scope


def valid_delivery_scopes() -> frozenset[str]:
    policy = load_delivery_scope_policy()
    scopes = policy.get("scopes")
    if not isinstance(scopes, dict):
        return frozenset()
    return frozenset(str(k) for k in scopes.keys() if str(k).strip())


def _scope_cfg(scope: str) -> Dict[str, Any]:
    modes = load_delivery_scope_policy().get("scopes")
    if not isinstance(modes, dict):
        return {}
    key = normalize_delivery_scope(scope)
    cfg = modes.get(key)
    return cfg if isinstance(cfg, dict) else {}


def scope_label(scope: str) -> str:
    return str(_scope_cfg(scope).get("label") or normalize_delivery_scope(scope))


def scope_short_label(scope: str) -> str:
    cfg = _scope_cfg(scope)
    return str(cfg.get("short_label") or cfg.get("label") or normalize_delivery_scope(scope))


def scope_cta_download(scope: str) -> str:
    return str(_scope_cfg(scope).get("cta_download") or "Descargar archivos generados")


def scope_cta_download_all(scope: str) -> str:
    return str(_scope_cfg(scope).get("cta_download_all") or "Descargar todo (ZIP)")


def generation_jobs_hint_for_scope(scope: str) -> List[str]:
    raw = _scope_cfg(scope).get("generation_jobs_hint") or []
    return [str(j).strip() for j in raw if str(j).strip()]


def include_directories_for_scope(scope: str) -> List[str]:
    raw = _scope_cfg(scope).get("include_directories") or []
    return [str(d).strip() for d in raw if str(d).strip()]


def include_compranet_sobres_for_scope(scope: str) -> List[str]:
    raw = _scope_cfg(scope).get("include_compranet_sobres") or []
    return [str(s).strip() for s in raw if str(s).strip()]


def include_root_logistics_for_scope(scope: str) -> List[str]:
    raw = _scope_cfg(scope).get("include_root_logistics") or []
    return [str(f).strip() for f in raw if str(f).strip()]


def prefer_compranet_validated_for_scope(scope: str) -> bool:
    return bool(_scope_cfg(scope).get("prefer_compranet_validated"))


def allowed_delivery_extensions() -> frozenset[str]:
    policy = load_delivery_scope_policy()
    raw = policy.get("allowed_extensions") or []
    return frozenset(str(ext).strip().lower() for ext in raw if str(ext).strip())


def max_artifacts_list() -> int:
    policy = load_delivery_scope_policy()
    try:
        value = int(policy.get("max_artifacts_list") or 100)
    except (TypeError, ValueError):
        value = 100
    return max(1, min(value, 500))


def empty_reason_message(reason_key: str) -> str:
    """Mensaje humano para ``empty_reason`` estable (API → UI)."""
    ux = load_delivery_ux_messages()
    reasons = ux.get("empty_reasons") if isinstance(ux.get("empty_reasons"), dict) else {}
    key = str(reason_key or "").strip()
    fallback = "No hay archivos listos para descargar en este alcance."
    return str(reasons.get(key) or fallback)


def ux_banner_message(banner_key: str) -> str:
    ux = load_delivery_ux_messages()
    banners = ux.get("banners") if isinstance(ux.get("banners"), dict) else {}
    return str(banners.get(str(banner_key or "").strip()) or "")


def scope_for_generation_mode(generation_mode: Optional[str]) -> str:
    """
    Mapea modo de generación F2 al alcance de descarga F5.

    Usa ``generation_mode_to_scope`` en policy; fallback al modo normalizado.
    """
    policy = load_delivery_scope_policy()
    mapping = (
        policy.get("generation_mode_to_scope")
        if isinstance(policy.get("generation_mode_to_scope"), dict)
        else {}
    )
    from app.services.generation_mode_policy import normalize_generation_mode

    mode = normalize_generation_mode(generation_mode)
    mapped = mapping.get(mode)
    if mapped:
        return normalize_delivery_scope(str(mapped))
    if mode in DeliveryScope.values():
        return mode
    return normalize_delivery_scope(None)


def directory_display_name(directory_key: str) -> str:
    """Etiqueta humana para carpeta o sobre CompraNet (sin rutas técnicas en UI)."""
    policy = load_delivery_scope_policy()
    mapping = (
        policy.get("directory_display_names")
        if isinstance(policy.get("directory_display_names"), dict)
        else {}
    )
    key = str(directory_key or "").strip()
    if key in mapping:
        return str(mapping[key])
    return key.replace("_", " ").strip() or "Documento"


def directory_sort_order() -> List[str]:
    policy = load_delivery_scope_policy()
    raw = policy.get("directory_sort_order") or []
    return [str(d).strip() for d in raw if str(d).strip()]
