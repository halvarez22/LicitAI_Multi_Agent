import os
import re
import unicodedata
import zipfile
import io
import json
import mimetypes
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Optional

from app.api.deps import get_connected_memory

router = APIRouter()

BASE_OUTPUT_DIR = "/data/outputs"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").strip())


def _slugify_like_create(name: str) -> str:
    """Misma regla que POST /sessions/create (Chroma-friendly)."""
    s = re.sub(r"[^a-z0-9_-]", "", (name or "").lower().replace(" ", "_"))
    if len(s) < 3:
        s = f"ses_{s}"
    return s[:63]


def _output_dir_candidates(session_key: str, state_name: Optional[str]) -> List[str]:
    """Rutas absolutas candidatas, sin duplicados. Prioridad: session_id (canónico) → legado por name."""
    raw = (session_key or "").strip()
    sid = _nfc(raw)
    out: List[str] = []
    seen = set()

    def add(rel: str) -> None:
        if not rel:
            return
        p = os.path.join(BASE_OUTPUT_DIR, rel)
        if p not in seen:
            seen.add(p)
            out.append(p)

    if raw:
        add(raw)
    if sid and sid != raw:
        add(sid)
    if sid:
        add(_slugify_like_create(sid))
    if state_name and str(state_name).strip():
        sn = str(state_name).strip()
        add(sn)
        add(_nfc(sn))
        add(_slugify_like_create(sn))
    return out


async def resolve_outputs_root(session_id: str) -> Optional[str]:
    """
    Resuelve la carpeta real bajo /data/outputs para una licitación.

    Incoherencias históricas:
    - Agentes usan session_state.get('name', session_id) como nombre de carpeta.
    - El id en BD puede ser slug (create) o texto largo (legado / otras rutas).
    - El cliente puede enviar un id con encoding distinto al nombre en disco (acentos).
    Por eso se prueban varias candidatas, incluido slug como en sessions/create.
    """
    if not session_id or not session_id.strip():
        return None
    raw = session_id.strip()
    sid = _nfc(raw)
    state_name: Optional[str] = None

    repo = await get_connected_memory()
    try:
        for key in (raw, sid):
            if not key:
                continue
            state = await repo.get_session(key)
            if isinstance(state, dict):
                n = state.get("name")
                if n is not None and str(n).strip():
                    state_name = str(n).strip()
                    break
    finally:
        await repo.disconnect()

    for p in _output_dir_candidates(raw, state_name):
        if os.path.isdir(p):
            return p

    if not os.path.isdir(BASE_OUTPUT_DIR):
        return None
    want_slug = _slugify_like_create(sid)
    for entry in os.listdir(BASE_OUTPUT_DIR):
        full = os.path.join(BASE_OUTPUT_DIR, entry)
        if not os.path.isdir(full):
            continue
        if entry == raw or entry == sid:
            return full
        if _nfc(entry) == sid:
            return full
        if _slugify_like_create(entry) == want_slug:
            return full
    return None


def _walk_output_structure(session_path: str):
    descriptions = {}
    meta_path = os.path.join(session_path, "descriptions.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                descriptions = json.load(f)
        except Exception:
            pass

    structure = []
    for root, dirs, files in os.walk(session_path):
        rel_path = os.path.relpath(root, session_path)
        display_name = rel_path if rel_path != "." else "GENERAL / LOGÍSTICA"

        folder_files = []
        for file in files:
            if file.endswith((".docx", ".pdf", ".xlsx")) and not file.startswith("~$"):
                file_path = os.path.join(root, file)
                folder_files.append(
                    {
                        "name": file,
                        "path": os.path.join(rel_path, file) if rel_path != "." else file,
                        "size": os.path.getsize(file_path),
                        "description": descriptions.get(
                            file,
                            "Documento generado automáticamente para cumplir con los requisitos logísticos y técnicos.",
                        ),
                    }
                )

        if folder_files:
            structure.append({"folder": display_name, "files": folder_files})

    return structure


@router.get("/list")
async def list_generated_files_query(session_id: str = Query(..., min_length=1)):
    session_path = await resolve_outputs_root(session_id)
    if not session_path:
        return {"success": True, "data": []}
    return {"success": True, "data": _walk_output_structure(session_path)}


@router.get("/list/{session_id:path}")
async def list_generated_files_path(session_id: str):
    session_path = await resolve_outputs_root(session_id)
    if not session_path:
        return {"success": True, "data": []}
    return {"success": True, "data": _walk_output_structure(session_path)}


@router.get("/file")
async def download_file(path: str, session_id: str):
    """Descarga un archivo; session_id identifica la licitación (resolución de carpeta como en /list)."""
    if ".." in path or path.startswith("/") or path.startswith("\\"):
        raise HTTPException(status_code=400, detail="Ruta de archivo inválida")

    root = await resolve_outputs_root(session_id)
    if not root:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    full_path = os.path.normpath(os.path.join(root, path))
    if not full_path.startswith(os.path.normpath(root)):
        raise HTTPException(status_code=400, detail="Ruta de archivo inválida")

    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    media_type, _ = mimetypes.guess_type(full_path)
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(
        path=full_path,
        filename=os.path.basename(full_path),
        media_type=media_type,
    )


def _zip_streaming_response(session_path: str, filename_hint: str):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for root, dirs, files in os.walk(session_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, session_path)
                zip_file.write(file_path, rel_path)
    zip_buffer.seek(0)
    safe = re.sub(r"[^\w.\-]+", "_", filename_hint, flags=re.UNICODE)[:120] or "licitacion"
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename=Propuesta_{safe}.zip"},
    )


@router.get("/zip")
async def download_all_zip_query(session_id: str = Query(..., min_length=1)):
    session_path = await resolve_outputs_root(session_id)
    if not session_path:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return _zip_streaming_response(session_path, os.path.basename(session_path.rstrip(os.sep)))


@router.get("/zip/{session_id:path}")
async def download_all_zip_path(session_id: str):
    session_path = await resolve_outputs_root(session_id)
    if not session_path:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return _zip_streaming_response(session_path, session_id)
