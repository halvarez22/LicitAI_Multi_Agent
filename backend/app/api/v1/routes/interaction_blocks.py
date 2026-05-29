"""
Rutas Hito A1: vista previa de bloque de interacción y guardado masivo validado.
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_connected_memory
from app.core.logging_config import get_logger

logger = get_logger(__name__)
from app.api.schemas.responses import GenericResponse
from app.config.settings import settings
from app.contracts.interaction_block import (
    InteractionBlockMassSaveRequest,
    InteractionBlockMassSaveResponse,
)
from app.services.interaction_block_mass_save import mass_save_economic_block
from app.services.requirement_grouper import build_interaction_block

router = APIRouter(prefix="/interaction-blocks", tags=["interaction-blocks"])


@router.post("/preview", response_model=GenericResponse)
async def preview_interaction_block(
    session_id: str,
    company_id: str,
    memory=Depends(get_connected_memory),
) -> GenericResponse:
    """
    Construye un InteractionBlock económico anclado a analisis_bases y pending_questions.
    Requiere ENABLE_BLOCK_RESOLUTION y cluster mínimo según BLOCK_RESOLUTION_MIN_ITEMS.
    """
    try:
        if not settings.ENABLE_BLOCK_RESOLUTION:
            return GenericResponse(
                success=False,
                message="Resolución por bloques desactivada (ENABLE_BLOCK_RESOLUTION=false).",
                data=None,
            )
        session_state = await memory.get_session(session_id)
        if session_state is None:
            return GenericResponse(
                success=False,
                message="Sesión no encontrada.",
                data=None,
            )
        company = await memory.get_company(company_id) or {}
        catalog = company.get("catalog") if isinstance(company.get("catalog"), list) else []
        cur = int(session_state.get("current_question_index") or 0)
        from app.services.economic_capture_matrix_service import economic_capture_status

        cap = economic_capture_status(session_state)
        block = build_interaction_block(
            session_id=session_id,
            session_state=session_state,
            company_catalog=catalog,
            current_idx=cur,
        )
        if block is None:
            if cap.get("capture_complete"):
                return GenericResponse(
                    success=True,
                    message=(
                        f"Cotización económica registrada ({cap.get('filled')}/{cap.get('total')} precios). "
                        "Usa **Generar propuesta** — no hace falta rellenar el bloque manualmente."
                    ),
                    data={
                        "capture_complete": True,
                        "capture_status": cap,
                    },
                )
            return GenericResponse(
                success=False,
                message="No hay bloque económico agrupable (pendientes insuficientes o cluster por debajo del mínimo).",
                data={"capture_status": cap},
            )
        return GenericResponse(
            success=True,
            message="Bloque generado.",
            data=block.model_dump(mode="json"),
        )
    except Exception as exc:
        logger.exception(
            "interaction_block_preview_failed",
            session_id=session_id,
            company_id=company_id,
        )
        return GenericResponse(
            success=False,
            message=f"Error al generar vista previa del bloque: {str(exc)[:240]}",
            data=None,
        )
    finally:
        await memory.disconnect()


@router.post("/mass-save", response_model=GenericResponse)
async def mass_save_interaction_block(
    body: InteractionBlockMassSaveRequest,
    memory=Depends(get_connected_memory),
) -> GenericResponse:
    """
    Guarda valores económicos fila a fila con validación; solo persiste filas válidas.
    """
    try:
        if not settings.ENABLE_BLOCK_RESOLUTION:
            return GenericResponse(
                success=False,
                message="Resolución por bloques desactivada (ENABLE_BLOCK_RESOLUTION=false).",
                data=None,
            )
        session_state = await memory.get_session(body.session_id)
        if session_state is None:
            return GenericResponse(
                success=False,
                message="Sesión no encontrada.",
                data=None,
            )
        company = await memory.get_company(body.company_id) or {}
        catalog = company.get("catalog") if isinstance(company.get("catalog"), list) else []
        cur = int(session_state.get("current_question_index") or 0)
        expected = build_interaction_block(
            session_id=body.session_id,
            session_state=session_state,
            company_catalog=catalog,
            current_idx=cur,
        )
        # Permitir guardado aunque el block_id haya cambiado (p.ej. el chat ya capturo
        # algunas filas y modifico pending_questions). Solo rechazamos si ya no hay
        # ningun bloque economico activo en la sesion.
        if expected is None and body.block_id:
            # Intentamos igualmente — la sesion puede tener preguntas recien capturadas
            # por chat y el bloque ya fue consumido. En ese caso mass_save devolvera
            # success_count=0 limpiamente si no hay nada que guardar.
            pass
        if expected and expected.block_id != body.block_id:
            import logging
            logging.getLogger(__name__).warning(
                "block_id obsoleto aceptado: frontend=%s sesion=%s session_id=%s",
                body.block_id, expected.block_id, body.session_id,
            )


        raw = await mass_save_economic_block(
            memory,
            session_id=body.session_id,
            company_id=body.company_id,
            block_id=body.block_id,
            correlation_id=body.correlation_id,
            rows=body.rows,
        )
        resp = InteractionBlockMassSaveResponse.model_validate(raw)
        n_ok = resp.success_count
        n_fail = len(resp.failed_items)
        if n_ok and n_fail:
            msg = f"Persistidas {n_ok} fila(s); {n_fail} rechazada(s) por validación o catálogo."
        elif n_ok:
            msg = f"Persistidas {n_ok} fila(s)."
        elif n_fail:
            msg = f"Ninguna fila persistida; {n_fail} error(es)."
        else:
            msg = "Sin filas en la solicitud."
        return GenericResponse(
            success=n_ok > 0,
            message=msg,
            data=resp.model_dump(mode="json"),
        )
    finally:
        await memory.disconnect()
