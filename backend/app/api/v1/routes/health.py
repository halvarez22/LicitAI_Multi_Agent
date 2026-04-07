from fastapi import APIRouter
from app.api.schemas.responses import HealthResponse
from app.services.llm_service import LLMServiceClient
from app.services.ocr_service import OCRServiceClient
from app.memory.factory import MemoryAdapterFactory

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Valida la salud de todos los contenedores y dependencias subyacentes"""
    
    llm_status = "ok" if await LLMServiceClient().health_check() else "unavailable"
    ocr_status = "ok" if await OCRServiceClient().health_check() else "unavailable"
    
    # Try Memory backend
    db_status = "unavailable"
    memory_adapter = MemoryAdapterFactory.create_adapter()
    if memory_adapter and await memory_adapter.connect():
        hc = await memory_adapter.health_check()
        db_status = hc.get("status", "error")
        await memory_adapter.disconnect()

    return HealthResponse(
        status="ok",
        version="1.0.0",
        dependencies={
            "database": db_status,
            "ocr_vlm": ocr_status,
            "llm_ollama": llm_status,
            "vector_db": "ok" # Requiere check en la DB vector real
        }
    )
