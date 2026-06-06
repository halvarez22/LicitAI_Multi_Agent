"""
Propuesta técnica principal (TE-01 / equivalente) en perspectiva concursante, sin LLM.
"""
from __future__ import annotations

import re
from typing import Any, Dict

_TE01_ID_RE = re.compile(r"(?i)TE[\s_.-]*0*1(?!\d)")
_PROPUESTA_TECNICA_RE = re.compile(
    r"(?i)propuesta\s+t[eé]cnica|modelo.*propuesta\s+t[eé]cnica|forma\s+te[\s_-]*01"
)


def is_primary_technical_proposal(*text_parts: str) -> bool:
    """
    True si el requisito corresponde al documento principal de propuesta técnica.

    Universal: TE-01, nombre con «propuesta técnica», sin hardcode por licitación.
    """
    blob = " ".join(str(p or "") for p in text_parts)
    if _TE01_ID_RE.search(blob):
        return True
    if _PROPUESTA_TECNICA_RE.search(blob):
        # Excluir carta de presentación (documento aparte)
        if re.search(r"(?i)carta\s+de\s+presentaci[oó]n|presentaci[oó]n\s+de\s+propuesta", blob):
            return False
        return True
    return False


def _clean_snippet(text: str, *, max_len: int = 1800) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    raw = re.sub(r"\[(?:COMPLETAR|completar|Insertar)[^\]]*\]", "", raw, flags=re.I)
    return raw[:max_len]


def build_propuesta_tecnica_body(
    *,
    razon_social: str,
    rfc: str,
    representante: str,
    domicilio: str,
    tender_name: str,
    req_nombre: str,
    req_desc: str,
    req_context: str,
    experience_block: str = "",
) -> str:
    """
    Cuerpo de propuesta técnica (sin bloque LUGAR Y FECHA; lo añade _save_docx).

    Perspectiva licitante; usa fragmento de bases como referencia, sin voz evaluador.
    """
    dom_line = _clean_snippet(domicilio) or "el señalado en el expediente"
    scope = _clean_snippet(req_desc) or _clean_snippet(req_nombre)
    bases = _clean_snippet(req_context)
    parts = [
        f"Por conducto de su representante legal, **{representante}**, la empresa "
        f"**{razon_social}**, con R.F.C. **{rfc}**, con domicilio en {dom_line}, "
        f"presenta su propuesta técnica para **{tender_name}**.\n\n",
        f"**Objeto del documento:** {scope}\n\n",
        "Manifestamos bajo protesta de decir verdad que la solución ofertada cumple con "
        "las especificaciones, anexos y requisitos técnicos establecidos en las bases "
        "del procedimiento, y que contamos con capacidad legal, técnica, operativa y "
        "material para ejecutar el objeto del contrato en caso de resultar adjudicados.\n\n",
    ]
    if bases:
        parts.append(
            "**Referencia de bases (extracto):** "
            f"{bases}\n\n"
        )
    if experience_block and experience_block.strip():
        parts.append(f"{experience_block.strip()}\n\n")
    parts.append(
        "Nos comprometemos a sostener el contenido de esta propuesta durante el proceso "
        "de evaluación y, en su caso, a atender las aclaraciones que formule la convocante "
        "conforme a la normatividad aplicable.\n\n"
        "Sin otro particular, quedamos a sus órdenes."
    )
    return "".join(parts)
