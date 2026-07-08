"""
Resolución de empresa activa para copy de chat y bootstrap.

Precedencia: perfil de ``company_id`` (UI) > ``master_profile`` en sesión > ``company_id`` crudo.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def company_label_from_profile(profile: Optional[Dict[str, Any]]) -> str:
    """Extrae etiqueta visible desde un master_profile o dict equivalente."""
    if not isinstance(profile, dict):
        return ""
    return str(
        profile.get("razon_social")
        or profile.get("nombre")
        or profile.get("name")
        or ""
    ).strip()


def resolve_company_label_from_state(
    state: Dict[str, Any],
    *,
    company_profile: Optional[Dict[str, Any]] = None,
    company_name: Optional[str] = None,
) -> str:
    """
    Resuelve el nombre de empresa para mensajes HRU.

    Args:
        state: Estado de sesión canónico.
        company_profile: Master profile de la empresa seleccionada en UI.
        company_name: Nombre comercial de la empresa (fallback si no hay razón social).
    """
    label = company_label_from_profile(company_profile)
    if label:
        return label
    name = str(company_name or "").strip()
    if name:
        return name
    session_mp = state.get("master_profile")
    if isinstance(session_mp, dict):
        label = company_label_from_profile(session_mp)
        if label:
            return label
    return str(state.get("company_id") or "").strip()


async def resolve_active_company_context(
    memory: Any,
    session_state: Dict[str, Any],
    company_id: str,
) -> Dict[str, Any]:
    """
    Contexto de empresa activa para chat/bootstrap.

    Returns:
        dict con ``company_id``, ``master_profile`` (opcional) y ``company_label``.
    """
    cid = str(company_id or "").strip()
    profile: Optional[Dict[str, Any]] = None
    company_name = ""

    if cid and memory is not None:
        try:
            company = await memory.get_company(cid)
        except Exception:
            company = None
        if isinstance(company, dict):
            raw_profile = company.get("master_profile")
            if isinstance(raw_profile, dict):
                profile = raw_profile
            company_name = str(company.get("name") or "").strip()

    label = resolve_company_label_from_state(
        session_state,
        company_profile=profile,
        company_name=company_name,
    )
    return {
        "company_id": cid,
        "master_profile": profile,
        "company_label": label,
    }
