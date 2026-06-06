import json
import redis
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config.settings import settings
from app.core.observability import get_logger

logger = get_logger(__name__)

# Inicialización de Redis para seguimiento de Jobs
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True,
)

_ACTIVE_JOB_STATUSES = frozenset({"RUNNING", "QUEUED"})


def _parse_job_timestamp(value: Any) -> Optional[datetime]:
    """Parsea ISO8601 de Redis; devuelve None si no es interpretable."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def job_idle_seconds(job: Dict[str, Any]) -> Optional[float]:
    """Segundos desde el último ``updated_at`` (o ``created_at``) del job."""
    if not job:
        return None
    ts = _parse_job_timestamp(job.get("updated_at") or job.get("created_at"))
    if ts is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def is_job_stale(job: Dict[str, Any]) -> bool:
    """
    True si un job RUNNING/QUEUED lleva demasiado tiempo sin heartbeat en Redis.
    """
    status = str(job.get("status") or "").upper()
    if status not in _ACTIVE_JOB_STATUSES:
        return False
    idle = job_idle_seconds(job)
    if idle is None:
        return False
    threshold = int(getattr(settings, "AGENTS_JOB_STALE_SECONDS", 5400) or 5400)
    return idle >= threshold


def mark_job_stale(
    job_id: str,
    job: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Marca el job como FAILED por inactividad y limpia el vínculo con la sesión."""
    idle = job_idle_seconds(job) or 0.0
    threshold = int(getattr(settings, "AGENTS_JOB_STALE_SECONDS", 5400) or 5400)
    error_msg = (
        f"Análisis interrumpido: sin actividad durante {int(idle // 60)} min "
        f"(límite {threshold // 60} min). "
        "Relanza «Analizar bases» desde el panel."
    )
    update_job_status(
        job_id,
        "FAILED",
        error=error_msg,
        forensic_traceback={
            "reason": "stale_job_timeout",
            "idle_seconds": round(idle, 1),
            "threshold_seconds": threshold,
            "last_progress": job.get("progress"),
        },
    )
    if session_id:
        clear_session_job(session_id)
    logger.warning(
        "job_marked_stale",
        job_id=job_id,
        session_id=session_id,
        idle_seconds=round(idle, 1),
        threshold_seconds=threshold,
    )
    return get_job_status(job_id)


def reconcile_job_if_stale(
    job_id: str,
    job: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Si el job está colgado, lo marca FAILED y devuelve el estado actualizado."""
    current = job if job is not None else get_job_status(job_id)
    if not current:
        return {}
    if is_job_stale(current):
        return mark_job_stale(job_id, current, session_id=session_id)
    return current


def update_job_status(job_id: str, status: str, progress: Dict[str, Any] = None, error: str = None, result: Dict[str, Any] = None, forensic_traceback: Dict[str, Any] = None):
    """Actualiza el estado de un job en Redis para seguimiento asíncrono."""
    if not job_id:
        return

    job_data = redis_client.get(f"job:{job_id}")
    if job_data:
        job = json.loads(job_data)
    else:
        job = {"job_id": job_id, "created_at": datetime.now(timezone.utc).isoformat()}

    prev_status = str(job.get("status") or "").upper()
    new_status = str(status or "").upper()

    # No degradar un job terminal; evita RUNNING + error tras marcar stale/FAILED.
    if prev_status in ("COMPLETED", "FAILED") and new_status in _ACTIVE_JOB_STATUSES:
        logger.warning(
            "job_status_update_ignored_terminal_downgrade",
            job_id=job_id,
            prev_status=prev_status,
            attempted_status=new_status,
        )
        return

    job["status"] = status
    job["updated_at"] = datetime.now(timezone.utc).isoformat()

    if progress:
        if "progress" not in job:
            job["progress"] = {}
        job["progress"].update(progress)
    if error:
        job["error"] = error
    if forensic_traceback:
        job["forensic_traceback"] = forensic_traceback
    if result:
        job["result"] = result

    if new_status in _ACTIVE_JOB_STATUSES:
        job.pop("error", None)
        job.pop("forensic_traceback", None)

    redis_client.set(f"job:{job_id}", json.dumps(job), ex=86400)  # 24h TTL
    
    # Observabilidad: Loggear transición de estado para fácil correlación
    logger.info(
        "job_status_transition",
        job_id=job_id,
        status=status,
        has_error=bool(error),
        has_result=bool(result)
    )

def get_job_status(job_id: str, *, reconcile_stale: bool = False) -> Dict[str, Any]:
    """
    Recupera la información completa de un job desde Redis.

    ``reconcile_stale=True`` solo debe usarse desde ``get_active_session_job``;
    el polling periódico del frontend no debe marcar FAILED un job vivo pero lento.
    """
    if not job_id:
        return {}
    job_data = redis_client.get(f"job:{job_id}")
    if not job_data:
        return {}
    job = json.loads(job_data)
    # Reparar estado corrupto (FAILED escrito pero status quedó RUNNING).
    if str(job.get("status") or "").upper() in _ACTIVE_JOB_STATUSES and job.get("error"):
        ft = job.get("forensic_traceback") if isinstance(job.get("forensic_traceback"), dict) else {}
        if ft.get("reason") == "stale_job_timeout" or "interrumpido" in str(job.get("error") or "").lower():
            job["status"] = "FAILED"
            redis_client.set(f"job:{job_id}", json.dumps(job), ex=86400)
    if reconcile_stale:
        return reconcile_job_if_stale(job_id, job)
    return job


def link_session_job(session_id: str, job_id: str) -> None:
    """Asocia el job activo de análisis con la sesión (para UX del chatbot)."""
    if not session_id or not job_id:
        return
    redis_client.set(f"session_job:{session_id}", job_id, ex=86400)


def clear_session_job(session_id: str) -> None:
    """Quita el vínculo sesión↔job al terminar el pipeline."""
    if not session_id:
        return
    redis_client.delete(f"session_job:{session_id}")


def link_session_maintenance_job(session_id: str, job_id: str) -> None:
    """Asocia job de rehidratación/mantenimiento (no compite con análisis)."""
    if not session_id or not job_id:
        return
    redis_client.set(f"session_maintenance_job:{session_id}", job_id, ex=86400)


def clear_session_maintenance_job(session_id: str) -> None:
    if not session_id:
        return
    redis_client.delete(f"session_maintenance_job:{session_id}")


def get_active_session_maintenance_job(session_id: str) -> Dict[str, Any]:
    """Job de rehidratación en curso, si existe."""
    if not session_id:
        return {}
    job_id = redis_client.get(f"session_maintenance_job:{session_id}")
    if not job_id:
        return {}
    job = get_job_status(job_id, reconcile_stale=False)
    if not job:
        clear_session_maintenance_job(session_id)
        return {}
    status = str(job.get("status") or "").upper()
    if status in ("COMPLETED", "FAILED"):
        clear_session_maintenance_job(session_id)
        return {}
    return {"job_id": job_id, **job}


def get_active_session_job(session_id: str) -> Dict[str, Any]:
    """
    Job de análisis en curso para la sesión, si existe y no terminó.
    Devuelve {} si no hay job activo.
    Jobs RUNNING/QUEUED sin heartbeat reciente se marcan FAILED automáticamente.
    """
    if not session_id:
        return {}
    job_id = redis_client.get(f"session_job:{session_id}")
    if not job_id:
        return {}
    job = get_job_status(job_id, reconcile_stale=True)
    if not job:
        clear_session_job(session_id)
        return {}
    status = str(job.get("status") or "").upper()
    if status in ("COMPLETED", "FAILED"):
        clear_session_job(session_id)
        return {}
    return {"job_id": job_id, **job}
