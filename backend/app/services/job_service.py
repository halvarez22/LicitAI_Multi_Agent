import json
import redis
from datetime import datetime, timezone
from typing import Any, Dict
from app.config.settings import settings
from app.core.observability import get_logger

logger = get_logger(__name__)

# Inicialización de Redis para seguimiento de Jobs
redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    decode_responses=True
)

def update_job_status(job_id: str, status: str, progress: Dict[str, Any] = None, error: str = None, result: Dict[str, Any] = None, forensic_traceback: Dict[str, Any] = None):
    """Actualiza el estado de un job en Redis para seguimiento asíncrono."""
    if not job_id:
        return
        
    job_data = redis_client.get(f"job:{job_id}")
    if job_data:
        job = json.loads(job_data)
    else:
        job = {"job_id": job_id, "created_at": datetime.now(timezone.utc).isoformat()}
    
    job["status"] = status
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    if progress:
        if "progress" not in job: job["progress"] = {}
        job["progress"].update(progress)
    if error:
        job["error"] = error
    if forensic_traceback:
        job["forensic_traceback"] = forensic_traceback
    if result:
        job["result"] = result
        
    redis_client.set(f"job:{job_id}", json.dumps(job), ex=86400) # 24h TTL
    
    # Observabilidad: Loggear transición de estado para fácil correlación
    logger.info(
        "job_status_transition",
        job_id=job_id,
        status=status,
        has_error=bool(error),
        has_result=bool(result)
    )
