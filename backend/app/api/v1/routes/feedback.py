from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
from app.api.schemas.feedback import FeedbackCreate, FeedbackRead, FeedbackListResponse
from app.api.schemas.responses import GenericResponse
from app.services.feedback_service import FeedbackService
from app.config.settings import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

async def get_feedback_service():
    service = FeedbackService()
    try:
        yield service
    finally:
        await service.disconnect()

@router.post("", response_model=GenericResponse)
async def create_feedback(feedback: FeedbackCreate, service: FeedbackService = Depends(get_feedback_service)):
    if not settings.FEEDBACK_API_ENABLED:
        raise HTTPException(status_code=404, detail="Feedback API disabled by feature flag")
        
    try:
        result = await service.submit_feedback(feedback)
        if result["success"]:
            return GenericResponse(success=True, message=result["message"])
        raise HTTPException(status_code=500, detail=result["message"])
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error creating feedback: {e}")
        raise HTTPException(status_code=500, detail="Error inesperado al enviar feedback")

@router.get("/session/{session_id}", response_model=FeedbackListResponse)
async def list_feedback(session_id: str, service: FeedbackService = Depends(get_feedback_service)):
    if not settings.FEEDBACK_API_ENABLED:
        raise HTTPException(status_code=404, detail="Feedback API disabled by feature flag")
        
    try:
        items = await service.list_feedback_for_session(session_id)
        # Adapt list[dict] to list[FeedbackRead]
        return FeedbackListResponse(success=True, data=items)
    except Exception as e:
        logger.error(f"Error listing feedback for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar feedback")
