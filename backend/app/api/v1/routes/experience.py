from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Any, Optional
from app.api.schemas.experience import OutcomeCreate, ExperienceResponse, ExperienceResult
from app.api.schemas.responses import GenericResponse
from app.services.experience_store import ExperienceStore
from app.config.settings import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

async def get_experience_store():
    store = ExperienceStore()
    try:
        yield store
    finally:
        # Aquí no hay desconexión física de Chroma, pero sí del repo si existiera
        if store.repo:
            await store.repo.disconnect()

@router.post("/outcome", response_model=GenericResponse)
async def register_outcome(outcome: OutcomeCreate, store: ExperienceStore = Depends(get_experience_store)):
    """Registra el resultado de una licitación y actualiza el índice de experiencia."""
    if not settings.EXPERIENCE_API_ENABLED:
        raise HTTPException(status_code=404, detail="Experience API disabled")
        
    try:
        # El outcome se registra en Postgres + Chroma
        success = await store.upsert_case_summary(
            session_id=outcome.session_id,
            sector=outcome.sector,
            tipo=outcome.tipo_licitacion,
            requirements=outcome.requirements,
            outcome=outcome.resultado
        )
        if success:
            logger.info(f"outcome_registered: session_id={outcome.session_id}, result={outcome.resultado}")
            return GenericResponse(success=True, message="Outcome registrado y experiencia indexada.")
        return GenericResponse(success=False, message="Error al registrar outcome.")
    except Exception as e:
        logger.error(f"Error registering outcome: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/similar", response_model=ExperienceResponse)
async def get_similar_cases(
    session_id: str, 
    query: str = Query(..., description="Query textual para búsqueda semántica"),
    top_k: int = Query(5, description="Número de casos similares"),
    store: ExperienceStore = Depends(get_experience_store)
):
    """Busca casos similares en el histórico (Fines de Debug/Admin)."""
    if not settings.EXPERIENCE_DEBUG:
        raise HTTPException(status_code=404, detail="Debug API disabled")
        
    try:
        cases = await store.find_similar(query_text=query, top_k=top_k)
        # Adapt list[ExperienceCase] to list[ExperienceResult]
        return ExperienceResponse(
            success=True, 
            data=[ExperienceResult(
                session_id=c.session_id,
                sector=c.sector,
                tipo_licitacion=c.tipo_licitacion,
                summary=c.summary,
                outcome=c.outcome,
                score=c.score,
                disclaimer=c.disclaimer
            ) for c in cases], 
            count=len(cases)
        )
    except Exception as e:
        logger.error(f"Error finding similar cases: {e}")
        raise HTTPException(status_code=500, detail="Error al buscar casos similares")
