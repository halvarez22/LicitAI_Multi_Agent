"""
Plantilla mínima universal cuando el LLM no produce cuerpo legal sustantivo.

Delega en ``administrative_letter_clauses`` (determinístico por familia de anexo).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.administrative_letter_clauses import build_administrative_letter_markdown


def build_administrative_fallback_markdown(
    *,
    req_nombre: str,
    req_desc: str = "",
    req_snippet: str = "",
    master_profile: Dict[str, Any],
    doc_metadata: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Redacta carta/declaración bajo protesta de decir verdad (universal).

    Args:
        req_nombre: Título del requisito o anexo.
        req_desc: Descripción del ítem en compliance/panel.
        req_snippet: Fragmento literal de bases (opcional).
        master_profile: Perfil maestro de la empresa.
        doc_metadata: Metadatos de fecha, licitación, destinatario, etc.
        session_state: Estado de sesión para convocante/comité.

    Returns:
        Markdown con párrafos sustantivos listo para ``_save_docx``.
    """
    return build_administrative_letter_markdown(
        req_nombre=req_nombre,
        req_desc=req_desc,
        req_snippet=req_snippet,
        master_profile=master_profile,
        doc_metadata=doc_metadata,
        session_state=session_state,
    )
