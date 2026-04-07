from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

from app.post_clarification.acta_extractor_service import extract_acta_text
from app.post_clarification.carta_33_bis_generator import (
    build_carta_33_bis_text,
    build_questions_anexo10_from_text,
    write_carta_docx,
)
from app.post_clarification.models import PostClarificationContextModel, TipoJunta

logger = logging.getLogger(__name__)

SESSION_KEY = "post_clarification_context"


def _is_pdf(filename: str) -> bool:
    return (filename or "").lower().endswith(".pdf")


def _storable(model: PostClarificationContextModel) -> Dict[str, Any]:
    return model.model_dump(mode="json")


def _resolve_post_clarification_output_dir(session_id: str) -> str:
    """
    Resuelve directorio de salida para post-aclaraciones.

    Prioriza `LICITAI_OUTPUTS_DIR` (si existe), luego `/data/outputs` y si no es
    escribible en el entorno (p.ej. CI runner), cae a un directorio temporal.
    """
    preferred_base = os.getenv("LICITAI_OUTPUTS_DIR", os.path.join("/data", "outputs"))
    relative = os.path.join(session_id, "4.post_aclaraciones")

    preferred_dir = os.path.join(preferred_base, relative)
    try:
        os.makedirs(preferred_dir, exist_ok=True)
        return preferred_dir
    except PermissionError:
        fallback_base = os.path.join(tempfile.gettempdir(), "licitai_outputs")
        fallback_dir = os.path.join(fallback_base, relative)
        os.makedirs(fallback_dir, exist_ok=True)
        logger.warning(
            "post_clarification_output_fallback_tmp",
            extra={"preferred_dir": preferred_dir, "fallback_dir": fallback_dir},
        )
        return fallback_dir


async def get_post_clarification_context(
    memory: Any, session_id: str
) -> Optional[PostClarificationContextModel]:
    session = await memory.get_session(session_id)
    if not session:
        return None
    raw = session.get(SESSION_KEY)
    if isinstance(raw, dict):
        try:
            return PostClarificationContextModel.model_validate(raw)
        except Exception as e:
            logger.warning("post_clarification_context_parse_failed: %s", e)
    return None


async def process_acta_document(
    memory: Any,
    session_id: str,
    document_id: str,
    *,
    tipo_junta: TipoJunta = TipoJunta.PRIMERA,
    correlation_id: str = "",
) -> PostClarificationContextModel:
    """
    Rama A: PDF de acta → extracción automática → preguntas + borrador carta.
    Fallback B: si confianza < 0.7 o extracción vacía, usa plantilla.
    """
    doc = await memory.get_document(document_id)
    if not doc:
        raise ValueError(f"No existe document_id={document_id}")
    content = doc.get("content") or {}
    filename = str(content.get("filename") or "")
    file_path = str(content.get("file_path") or "")
    if not file_path or not _is_pdf(filename):
        raise ValueError("El documento debe ser PDF de acta de junta.")

    ext = await extract_acta_text(file_path=file_path, filename=filename)
    text = ext.text
    confidence = ext.confidence

    preguntas = await build_questions_anexo10_from_text(
        text, correlation_id=correlation_id
    ) if text else []

    session = await memory.get_session(session_id) or {}
    session_name = str(session.get("name") or session_id)

    if ext.needs_fallback_template:
        draft = (
            "BORRADOR (Fallback por baja confianza de extracción)\n\n"
            "Por medio de la presente manifestamos conformidad con las aclaraciones emitidas "
            "en la junta correspondiente, sujetas a validación humana.\n\n"
            "Revise y complete datos de sesión, referencias de acta y firma del representante."
        )
        estado = "extraida"
    else:
        draft = await build_carta_33_bis_text(
            session_name=session_name,
            tipo_junta=tipo_junta.value,
            preguntas=preguntas,
            acta_excerpt=text[:12000],
            correlation_id=correlation_id,
        )
        estado = "borrador_listo"

    output_dir = _resolve_post_clarification_output_dir(session_id)
    out_path = os.path.join(output_dir, "CARTA_CONFORMIDAD_33_BIS_BORRADOR.docx")
    write_carta_docx(out_path, draft)

    model = PostClarificationContextModel(
        acta_id=document_id,
        tipo_junta=tipo_junta,
        archivo_original=filename,
        texto_extraido=text[:60000] if text else None,
        confianza_extraccion=confidence,
        preguntas_aclaracion=preguntas,
        carta_33_bis_draft=draft,
        carta_33_bis_docx_path=out_path,
        estado=estado,
        extraido_por=ext.method,
        ultima_actualizacion=datetime.utcnow(),
    )

    session[SESSION_KEY] = _storable(model)
    await memory.save_session(session_id, session)
    return model


async def generate_carta_33_bis(
    memory: Any,
    session_id: str,
    *,
    force_regenerate: bool = False,
    correlation_id: str = "",
) -> PostClarificationContextModel:
    """
    Genera o regenera borrador de carta a partir del contexto persistido.
    """
    session = await memory.get_session(session_id) or {}
    raw = session.get(SESSION_KEY)
    if not isinstance(raw, dict):
        raise ValueError("No existe contexto de post-aclaración para esta sesión.")
    ctx = PostClarificationContextModel.model_validate(raw)
    if ctx.carta_33_bis_draft and not force_regenerate:
        return ctx

    session_name = str(session.get("name") or session_id)
    draft = await build_carta_33_bis_text(
        session_name=session_name,
        tipo_junta=ctx.tipo_junta.value,
        preguntas=ctx.preguntas_aclaracion,
        acta_excerpt=(ctx.texto_extraido or "")[:12000],
        correlation_id=correlation_id,
    )
    output_dir = _resolve_post_clarification_output_dir(session_id)
    out_path = os.path.join(output_dir, "CARTA_CONFORMIDAD_33_BIS_BORRADOR.docx")
    write_carta_docx(out_path, draft)

    ctx.carta_33_bis_draft = draft
    ctx.carta_33_bis_docx_path = out_path
    ctx.estado = "borrador_listo"
    ctx.ultima_actualizacion = datetime.utcnow()
    session[SESSION_KEY] = _storable(ctx)
    await memory.save_session(session_id, session)
    return ctx
