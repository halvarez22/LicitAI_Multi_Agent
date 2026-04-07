from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from app.memory.factory import MemoryAdapterFactory
from app.api.schemas.responses import GenericResponse
from app.checklist.models import MarkHitoPayload
from app.checklist.submission_checklist_service import (
    get_submission_checklist,
    mark_hito,
)
from app.post_clarification.models import (
    GenerateCarta33BisRequest,
    PostClarificationActaRequest,
)
from app.post_clarification.service import (
    generate_carta_33_bis,
    get_post_clarification_context,
    process_acta_document,
)
from app.economic_validation.service import (
    get_latest_analysis_and_economic,
    refresh_economic_validations_for_session,
)
import logging
from app.services.vector_service import VectorDbServiceClient

class DictamenRequest(BaseModel):
    dictamen: Dict[str, Any]

logger = logging.getLogger(__name__)
router = APIRouter()

async def get_repository():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    return memory

@router.get("", response_model=GenericResponse)
async def list_licitaciones():
    """Lista todas las licitaciones (sesiones) activas."""
    repo = await get_repository()
    try:
        sessions = await repo.list_sessions()
        return GenericResponse(
            success=True,
            message="Licitaciones recuperadas exitosamente",
            data={"licitaciones": sessions}
        )
    except Exception as e:
        logger.error(f"Error listando sesiones: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar licitaciones")
    finally:
        await repo.disconnect()

@router.post("/create", response_model=GenericResponse)
async def create_licitacion(name: str):
    """Crea una nueva licitacion (sesión)."""
    repo = await get_repository()
    # Limpiar nombre para id (ChromaDB compatible: 3-63 chars, alfanumérico + underscore/hyphen)
    import re
    session_id = re.sub(r'[^a-z0-9_-]', '', name.lower().replace(" ", "_"))
    # Asegurar longitud mínima y máxima
    if len(session_id) < 3:
        session_id = f"ses_{session_id}"
    session_id = session_id[:63]
    
    try:
        # Verificar si existe
        existing = await repo.get_session(session_id)
        if existing:
            return GenericResponse(success=False, message="Ya existe una licitación con ese nombre")
            
        await repo.save_session(session_id, {"created_by": "user", "name": name})
        return GenericResponse(
            success=True,
            message="Licitación creada",
            data={"session_id": session_id}
        )
    except Exception as e:
        logger.error(f"Error creando sesion: {e}")
        raise HTTPException(status_code=500, detail="Error al crear licitacion")
    finally:
        await repo.disconnect()

@router.delete("/{session_id}", response_model=GenericResponse)
async def delete_licitacion(session_id: str):
    repo = await get_repository()
    try:
        # 1. Borrar de Postgres
        success = await repo.delete_session(session_id)
        
        # 2. Borrar de ChromaDB
        if success:
            try:
                VectorDbServiceClient().delete_collection(session_id)
            except Exception as e:
                logger.warning(f"No se pudo borrar la colección Chroma para {session_id}: {e}")
                
        return GenericResponse(success=success, message="Licitación eliminada" if success else "No se pudo eliminar")
    finally:
        await repo.disconnect()

@router.get("/{session_id}/dictamen", response_model=GenericResponse)
async def get_dictamen(session_id: str):
    """Obtiene el dictamen consolidado de una sesión."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if session_data and "dictamen" in session_data:
            return GenericResponse(success=True, message="Dictamen recuperado", data={"dictamen": session_data["dictamen"]})
        return GenericResponse(success=False, message="No hay dictamen guardado")
    except Exception as e:
        logger.error(f"Error recuperando dictamen: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar dictamen")
    finally:
        await repo.disconnect()

@router.post("/{session_id}/dictamen", response_model=GenericResponse)
async def save_dictamen(session_id: str, request: DictamenRequest):
    """Guarda el dictamen consolidado en la sesión (Postgres)."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id) or {}
        session_data["dictamen"] = request.dictamen
        await repo.save_session(session_id, session_data)
        return GenericResponse(success=True, message="Dictamen guardado en Postgres exitosamente")
    except Exception as e:
        logger.error(f"Error guardando dictamen: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar dictamen en Postgres")
    finally:
        await repo.disconnect()

@router.get("/{session_id}/submission-checklist", response_model=GenericResponse)
async def get_submission_checklist_route(session_id: str):
    """Checklist de hitos del procedimiento (cronograma del Analista + marcas del usuario)."""
    repo = await get_repository()
    try:
        cl = await get_submission_checklist(repo, session_id, auto_sync=True)
        if not cl:
            return GenericResponse(
                success=False,
                message="No hay checklist: ejecute primero el análisis de bases o no existe la sesión.",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Submission checklist recuperado",
            data={"submission_checklist": cl.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recuperando submission checklist: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar submission checklist")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/submission-checklist/{hito_id}/mark", response_model=GenericResponse)
async def mark_submission_hito(session_id: str, hito_id: str, payload: MarkHitoPayload):
    """Marca un hito como completado o pendiente y opcional evidencia (texto/referencia)."""
    repo = await get_repository()
    try:
        updated = await mark_hito(repo, session_id, hito_id, payload)
        if not updated:
            return GenericResponse(
                success=False,
                message="No se pudo actualizar el hito (id no encontrado o sin checklist).",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Hito actualizado",
            data={"submission_checklist": updated.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error marcando hito: {e}")
        raise HTTPException(status_code=500, detail="Error al marcar hito")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/checklist", response_model=GenericResponse)
async def get_checklist(session_id: str):
    """Obtiene la lista de verificación (checklist) de una sesión (Hito 7)."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if session_data and "checklist" in session_data:
            return GenericResponse(
                success=True, 
                message="Checklist recuperado exitosamente", 
                data={"checklist": session_data["checklist"]}
            )
        return GenericResponse(success=False, message="No hay checklist generado para esta sesión")
    except Exception as e:
        logger.error(f"Error recuperando checklist: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar checklist")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/post-clarification/acta", response_model=GenericResponse)
async def post_clarification_process_acta(
    session_id: str,
    payload: PostClarificationActaRequest,
):
    """
    Disparador explícito: procesa el PDF de acta ya subido (document_id) y persiste
    post_clarification_context en sesión.
    """
    repo = await get_repository()
    try:
        ctx = await process_acta_document(
            repo,
            session_id,
            payload.document_id,
            tipo_junta=payload.tipo_junta,
            correlation_id=f"{session_id}:post_clarification",
        )
        return GenericResponse(
            success=True,
            message="Acta procesada y contexto de post-aclaración actualizado.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error procesando acta de post-aclaración: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar acta: {str(e)}")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/post-clarification", response_model=GenericResponse)
async def get_post_clarification(session_id: str):
    repo = await get_repository()
    try:
        ctx = await get_post_clarification_context(repo, session_id)
        if not ctx:
            return GenericResponse(
                success=False,
                message="No existe contexto de post-aclaración para esta sesión.",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Contexto de post-aclaración recuperado.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recuperando post-aclaración: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar post-aclaración")
    finally:
        await repo.disconnect()


@router.post(
    "/{session_id}/post-clarification/generate-carta-33-bis",
    response_model=GenericResponse,
)
async def post_clarification_generate_carta(
    session_id: str,
    payload: GenerateCarta33BisRequest,
):
    repo = await get_repository()
    try:
        ctx = await generate_carta_33_bis(
            repo,
            session_id,
            force_regenerate=payload.force_regenerate,
            correlation_id=f"{session_id}:carta_33_bis",
        )
        return GenericResponse(
            success=True,
            message="Carta 33 Bis generada/actualizada.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error generando carta 33 bis: {e}")
        raise HTTPException(status_code=500, detail=f"Error al generar carta: {str(e)}")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/economic-validations", response_model=GenericResponse)
async def get_economic_validations(session_id: str):
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        _analysis, economic = get_latest_analysis_and_economic(session)
        if not economic:
            return GenericResponse(
                success=False,
                message="No hay propuesta económica calculada en sesión.",
                data=None,
            )
        validation = economic.get("validation_result") if isinstance(economic, dict) else None
        return GenericResponse(
            success=bool(validation),
            message="Validaciones económicas recuperadas" if validation else "Sin validaciones económicas aún.",
            data={"validation_result": validation} if validation else None,
        )
    except Exception as e:
        logger.error(f"Error leyendo validaciones económicas: {e}")
        raise HTTPException(status_code=500, detail="Error al leer validaciones económicas")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/economic-validations/refresh", response_model=GenericResponse)
async def refresh_economic_validations(session_id: str):
    repo = await get_repository()
    try:
        result = await refresh_economic_validations_for_session(repo, session_id)
        return GenericResponse(
            success=True,
            message="Validaciones económicas recalculadas.",
            data={"validation_result": result.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recalculando validaciones económicas: {e}")
        raise HTTPException(status_code=500, detail=f"Error refrescando validaciones: {str(e)}")
    finally:
        await repo.disconnect()
