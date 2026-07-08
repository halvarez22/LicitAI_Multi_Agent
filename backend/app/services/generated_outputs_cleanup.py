"""
Limpieza del expediente generado en disco y marcas de generación en la sesión.

No borra: dictamen, CCC, compliance, PDFs de bases (upload), ni la sesión en Postgres.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

# Tareas de pipeline que se invalidan al borrar Word/ZIP en /data/outputs.
# NO incluir ``economic_proposal``: es la cotización calculada (chat/economic agent), no un archivo en disco.
_GENERATION_TASK_EXACT = (
    "technical_writing_COMPLETED",
    "formats_generation_COMPLETED",
)
_GENERATION_TASK_PREFIXES = (
    "stage_completed:economic",
    "stage_completed:compranet_pack",
)

_SESSION_KEYS_TO_CLEAR = (
    "generation_state",
    "compranet_packaging",
    "last_document_quality_waiting_hints",
    "last_document_fill_quality_waiting_hints",
    "delivery_checklist",
)


def wipe_output_directory(session_path: str) -> Tuple[int, List[str]]:
    """
    Elimina todo el contenido bajo la carpeta de salida de la licitación.

    Returns:
        (cantidad de entradas eliminadas, nombres eliminados)
    """
    if not session_path or not os.path.isdir(session_path):
        return 0, []

    removed: List[str] = []
    for name in os.listdir(session_path):
        if name.startswith("."):
            continue
        full = os.path.join(session_path, name)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            elif os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
            else:
                continue
            removed.append(name)
        except OSError:
            raise
    return len(removed), removed


def reset_session_after_output_wipe(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Quita estado de generación/empaque para forzar una corrida limpia."""
    out = dict(session_data)
    for key in _SESSION_KEYS_TO_CLEAR:
        out.pop(key, None)

    tasks = out.get("tasks_completed")
    if isinstance(tasks, list):
        filtered: List[Dict[str, Any]] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_name = str(t.get("task") or "")
            if task_name in _GENERATION_TASK_EXACT:
                continue
            if any(task_name.startswith(p) for p in _GENERATION_TASK_PREFIXES):
                continue
            filtered.append(t)
        out["tasks_completed"] = filtered

    decision = out.get("last_orchestrator_decision")
    if isinstance(decision, dict):
        sr = str(decision.get("stop_reason") or "")
        if sr.startswith("INCOMPLETE_") or sr in (
            "PACKAGING_VALIDATION_FAILED",
            "DOCUMENT_QUALITY_GATE",
        ):
            out.pop("last_orchestrator_decision", None)

    return out


def wipe_output_directory_selective(
    session_path: str,
    *,
    preserve_subdirs: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    """
    Elimina contenido bajo la carpeta de salida preservando subcarpetas indicadas.

    Returns:
        (cantidad de entradas eliminadas, nombres eliminados)
    """
    preserve = {str(name).strip().lower() for name in (preserve_subdirs or []) if str(name).strip()}
    if not session_path or not os.path.isdir(session_path):
        return 0, []

    removed: List[str] = []
    for name in os.listdir(session_path):
        if name.startswith("."):
            continue
        if name.lower() in preserve:
            continue
        full = os.path.join(session_path, name)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            elif os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
            else:
                continue
            removed.append(name)
        except OSError:
            raise
    return len(removed), removed


async def wipe_session_output_disk_only(
    session_id: str,
    *,
    preserve_subdirs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Vacía archivos bajo ``/data/outputs/{sesión}`` sin tocar ``tasks_completed`` ni ``economic_proposal``.

    Usar al inicio de una corrida de generación para no mezclar Word/ZIP de intentos fallidos.
    Con ``preserve_subdirs``, conserva carpetas de otros modos (F2 desacople).
    """
    from app.api.v1.routes.downloads import resolve_outputs_root

    output_path = await resolve_outputs_root(session_id)
    removed_count = 0
    removed_names: List[str] = []
    if output_path:
        if preserve_subdirs:
            removed_count, removed_names = wipe_output_directory_selective(
                output_path,
                preserve_subdirs=preserve_subdirs,
            )
        else:
            removed_count, removed_names = wipe_output_directory(output_path)
    return {
        "session_id": session_id,
        "output_dir": output_path,
        "removed_count": removed_count,
        "removed_names": removed_names,
        "preserved_subdirs": list(preserve_subdirs or []),
    }


async def clear_generated_outputs_for_session(
    session_id: str,
    *,
    reset_session: bool = True,
) -> Dict[str, Any]:
    """
    Borra expediente en disco y opcionalmente resetea flags de generación en Postgres.

    Raises:
        FileNotFoundError: si la sesión no existe en persistencia.
    """
    from app.api.v1.routes.downloads import _session_exists, resolve_outputs_root

    if not await _session_exists(session_id):
        raise FileNotFoundError(f"Sesión no encontrada: {session_id}")

    output_path = await resolve_outputs_root(session_id)
    removed_count = 0
    removed_names: List[str] = []
    if output_path:
        removed_count, removed_names = wipe_output_directory(output_path)

    session_updated = False
    if reset_session:
        from app.api.deps import get_connected_memory

        repo = await get_connected_memory()
        try:
            for key in (session_id,):
                raw = await repo.get_session(key)
                if not isinstance(raw, dict) or not raw:
                    continue
                updated = reset_session_after_output_wipe(raw)
                await repo.save_session(session_id, updated)
                session_updated = True
                break
        finally:
            await repo.disconnect()

    return {
        "session_id": session_id,
        "output_dir": output_path,
        "removed_count": removed_count,
        "removed_names": removed_names,
        "session_generation_reset": session_updated,
    }
