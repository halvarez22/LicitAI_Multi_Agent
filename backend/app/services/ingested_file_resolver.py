"""
Resolución universal de nombres de archivo (compliance / catálogo) → ruta en disco.

Usa documentos persistidos en sesión (``content.file_path``, ``content.filename``).
Sin listas por licitación.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.session_template_catalog import normalize_filename_key


@dataclass(frozen=True)
class IngestedFileRef:
    """Referencia a un archivo subido y analizado."""

    doc_id: Optional[str]
    filename: str
    file_path: str
    filename_key: str
    extracted_text: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.file_path) and os.path.isfile(self.file_path)


def _path_lookup_key(path: str) -> str:
    """Normaliza rutas para indexado/resolución estable entre host y contenedor."""
    raw = str(path or "").strip()
    if not raw:
        return ""
    norm = raw.replace("\\", "/").rstrip("/")
    return f"path:{norm.lower()}"


def build_ingested_file_index(documents: List[Dict[str, Any]]) -> Dict[str, IngestedFileRef]:
    """
    Índice por clave normalizada, nombre literal, ``doc_id`` y ruta.

    Si hay duplicados de clave, conserva el primero con ``file_path`` existente.
    """
    by_key: Dict[str, IngestedFileRef] = {}
    by_literal: Dict[str, IngestedFileRef] = {}
    by_doc_id: Dict[str, IngestedFileRef] = {}
    by_path: Dict[str, IngestedFileRef] = {}

    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        content = doc.get("content") if isinstance(doc.get("content"), dict) else {}
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        filename = str(content.get("filename") or meta.get("filename") or "").strip()
        file_path = str(content.get("file_path") or "").strip()
        if not filename:
            continue
        ref = IngestedFileRef(
            doc_id=doc.get("id"),
            filename=filename,
            file_path=file_path,
            filename_key=normalize_filename_key(filename),
            extracted_text=str(content.get("extracted_text") or content.get("text") or ""),
        )
        if ref.filename_key and ref.filename_key not in by_key:
            by_key[ref.filename_key] = ref
        low = filename.lower()
        if low and low not in by_literal:
            by_literal[low] = ref
        doc_id = str(doc.get("id") or "").strip()
        if doc_id and f"doc_id:{doc_id}" not in by_doc_id:
            by_doc_id[f"doc_id:{doc_id}"] = ref
        path_key = _path_lookup_key(file_path)
        if path_key and path_key not in by_path:
            by_path[path_key] = ref

    # Unión: claves normalizadas + literales + referencias fuertes
    index: Dict[str, IngestedFileRef] = dict(by_key)
    for lit, ref in by_literal.items():
        index.setdefault(lit, ref)
    for doc_id, ref in by_doc_id.items():
        index.setdefault(doc_id, ref)
    for path_key, ref in by_path.items():
        index.setdefault(path_key, ref)
    return index


def _score_match(query_key: str, ref: IngestedFileRef) -> float:
    """Puntuación 0–1 entre consulta y archivo ingestado."""
    if not query_key:
        return 0.0
    q = query_key
    k = ref.filename_key
    if q == k:
        return 1.0
    if q in k or k in q:
        return 0.85
    qt = set(q.split())
    kt = set(k.split())
    if not qt or not kt:
        return 0.0
    inter = len(qt & kt)
    union = len(qt | kt)
    return inter / union if union else 0.0


def resolve_ingested_file(
    query: str,
    index: Dict[str, IngestedFileRef],
    *,
    doc_id: Optional[str] = None,
    source_path: Optional[str] = None,
    min_score: float = 0.42,
) -> Optional[IngestedFileRef]:
    """
    Resuelve ``archivo_fuente`` o nombre de requisito al archivo ingestado.

    Args:
        query: Texto de archivo_fuente, nombre de anexo o título de requisito.
        index: Salida de ``build_ingested_file_index``.
        min_score: Umbral mínimo de similitud por tokens.

    Returns:
        Referencia con ruta absoluta si existe en disco; si no, None.
    """
    strong_doc_id = str(doc_id or "").strip()
    if strong_doc_id:
        ref = index.get(f"doc_id:{strong_doc_id}")
        if ref and ref.exists:
            return ref

    strong_path = _path_lookup_key(str(source_path or ""))
    if strong_path:
        ref = index.get(strong_path)
        if ref and ref.exists:
            return ref

    raw = (query or "").strip()
    if not raw:
        return None

    low = raw.lower()
    if low in index:
        ref = index[low]
        return ref if ref.exists else None

    key = normalize_filename_key(raw)
    if key in index:
        ref = index[key]
        return ref if ref.exists else None

    # Basename si viene ruta
    base = os.path.basename(raw.replace("\\", "/"))
    if base.lower() in index:
        ref = index[base.lower()]
        return ref if ref.exists else None
    bk = normalize_filename_key(base)
    if bk in index:
        ref = index[bk]
        return ref if ref.exists else None

    best: Optional[IngestedFileRef] = None
    best_score = 0.0
    for ref in index.values():
        sc = _score_match(key, ref)
        if sc > best_score:
            best_score = sc
            best = ref
    if best and best_score >= min_score and best.exists:
        return best
    return None
