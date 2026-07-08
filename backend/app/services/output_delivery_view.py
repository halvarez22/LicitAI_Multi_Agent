"""
Vista de entrega deduplicada: listado/ZIP alineados al manifiesto CompraNet.

Tras empaquetado, los writers dejan copias en carpetas de generación y SOBRE_*;
esta capa expone solo ``_compranet_validated`` + logística en raíz y puede podar duplicados.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from typing import Any, Dict, Iterable, List, Optional, Tuple

COMPRANET_VALIDATED_DIR = "_compranet_validated"
MANIFEST_NAME = "MANIFIESTO_SHA256.json"

# Carpetas intermedias que no deben contarse ni incluirse en ZIP de entrega.
PRUNE_DIRECTORY_NAMES = (
    "1.propuesta tecnica",
    "2.propuesta_economica",
    "economic_proposal",
    "3.documentos administrativos",
    "SOBRE_1_ADMINISTRATIVO",
    "SOBRE_2_TECNICO",
    "SOBRE_3_ECONOMICO",
)

# Archivos auxiliares en raíz (no entregables CompraNet).
PRUNE_ROOT_FILENAMES = frozenset({"descriptions.json"})

OFFICE_EXTENSIONS = frozenset({".docx", ".pdf", ".xlsx", ".doc", ".xls"})

SOBRE_DISPLAY_NAMES = {
    "SobreComplementaria": "Sobre 1 — Administrativo (CompraNet)",
    "SobreTecnica": "Sobre 2 — Técnico (CompraNet)",
    "SobreEconomica": "Sobre 3 — Económico (CompraNet)",
    "GENERAL": "General / logística",
}


def _nfc_path(rel: str) -> str:
    return rel.replace("\\", "/")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compranet_validated_root(session_path: str) -> str:
    return os.path.join(session_path, COMPRANET_VALIDATED_DIR)


def has_compranet_validated(session_path: str) -> bool:
    root = compranet_validated_root(session_path)
    manifest = os.path.join(root, MANIFEST_NAME)
    return os.path.isdir(root) and (
        os.path.isfile(manifest) or any(_iter_files_under(root))
    )


def _iter_files_under(directory: str) -> Iterable[str]:
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name.startswith("~$") or name.startswith("."):
                continue
            yield os.path.join(root, name)


def _is_office_delivery_file(name: str) -> bool:
    low = name.lower()
    return any(low.endswith(ext) for ext in OFFICE_EXTENSIONS) and not low.endswith(".json")


def prune_duplicate_output_copies(session_path: str) -> Dict[str, Any]:
    """
    Elimina carpetas intermedias y JSON auxiliar tras un empaquetado CompraNet exitoso.

    Conserva: ``_compranet_validated/``, PDF/logística en raíz, ZIP preconstruido en raíz.
    """
    if not session_path or not os.path.isdir(session_path):
        return {"removed_count": 0, "removed_names": [], "session_path": session_path}

    removed: List[str] = []
    for name in PRUNE_DIRECTORY_NAMES:
        full = os.path.join(session_path, name)
        if not os.path.isdir(full):
            continue
        shutil.rmtree(full)
        removed.append(name)

    for name in PRUNE_ROOT_FILENAMES:
        full = os.path.join(session_path, name)
        if os.path.isfile(full):
            os.remove(full)
            removed.append(name)

    return {
        "session_path": session_path,
        "removed_count": len(removed),
        "removed_names": removed,
        "compranet_preserved": has_compranet_validated(session_path),
    }


def _collect_root_logistics_files(session_path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name in os.listdir(session_path):
        full = os.path.join(session_path, name)
        if not os.path.isfile(full):
            continue
        if name.lower().endswith(".pdf"):
            out.append(
                {
                    "name": name,
                    "path": name,
                    "size": os.path.getsize(full),
                    "description": "Guía logística y checklist de entrega.",
                }
            )
    return sorted(out, key=lambda x: x["name"])


def _load_validated_index(session_path: str) -> Dict[str, Dict[str, Any]]:
    index_path = os.path.join(session_path, COMPRANET_VALIDATED_DIR, "INDICE_ENTREGA.json")
    if not os.path.isfile(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    files = data.get("files") or []
    out: Dict[str, Dict[str, Any]] = {}
    for row in files:
        if not isinstance(row, dict):
            continue
        rel = _nfc_path(str(row.get("path") or ""))
        if rel:
            out[rel] = row
            out.setdefault(f"{COMPRANET_VALIDATED_DIR}/{rel}", row)
    return out


def _compute_inventory(
    session_path: str,
    structure: List[Dict[str, Any]],
    delivery_view: str,
) -> Dict[str, Any]:
    """Métricas de conteo a partir del árbol ya construido (evita recursión)."""
    if not session_path or not os.path.isdir(session_path):
        return {
            "delivery_view": "empty",
            "total_files_physical": 0,
            "deliverable_files": 0,
            "unique_sha256": 0,
            "duplicate_extra_files": 0,
            "has_compranet_validated": False,
        }

    physical = 0
    for _root, _dirs, files in os.walk(session_path):
        for name in files:
            if name.startswith("~$") or name.startswith("."):
                continue
            physical += 1

    deliverable_paths: List[str] = []
    for folder in structure:
        for f in folder.get("files") or []:
            rel = str(f.get("path") or "")
            if rel:
                deliverable_paths.append(os.path.join(session_path, rel))

    sha_counts: Dict[str, int] = {}
    for fp in deliverable_paths:
        if not os.path.isfile(fp):
            continue
        try:
            digest = _sha256_file(fp)
        except OSError:
            continue
        sha_counts[digest] = sha_counts.get(digest, 0) + 1

    effective_view = delivery_view
    if not deliverable_paths and physical == 0:
        effective_view = "empty"

    return {
        "delivery_view": effective_view,
        "total_files_physical": physical,
        "deliverable_files": len(deliverable_paths),
        "unique_sha256": len(sha_counts),
        "duplicate_extra_files": sum(c - 1 for c in sha_counts.values() if c > 1),
        "has_compranet_validated": has_compranet_validated(session_path),
        **_read_packaging_coverage(session_path),
    }


def _read_packaging_coverage(session_path: str) -> Dict[str, Any]:
    """Lee cobertura parcial/completa del manifiesto CompraNet (F3.4)."""
    manifest_path = os.path.join(session_path, COMPRANET_VALIDATED_DIR, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {}
        return {
            "packaging_coverage_status": data.get("coverage_status"),
            "packaging_sobres_present": data.get("sobres_present"),
            "packaging_sobres_missing": data.get("sobres_missing"),
            "packaging_partial_note": data.get("partial_note"),
        }
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def build_delivery_structure(session_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Árbol para UI: prioriza ``_compranet_validated``; si no existe, deduplica por SHA-256.
    """
    if not session_path or not os.path.isdir(session_path):
        inv = _compute_inventory(session_path or "", [], "empty")
        return [], inv

    structure: List[Dict[str, Any]] = []
    validated = compranet_validated_root(session_path)
    if has_compranet_validated(session_path):
        by_folder: Dict[str, List[Dict[str, Any]]] = {}
        index_rows = _load_validated_index(session_path)
        for file_path in sorted(_iter_files_under(validated)):
            basename = os.path.basename(file_path)
            if basename == MANIFEST_NAME or not _is_office_delivery_file(basename):
                continue
            rel = _nfc_path(os.path.relpath(file_path, session_path))
            rel_inner = _nfc_path(os.path.relpath(file_path, validated))
            top = rel_inner.split("/")[0] if "/" in rel_inner else rel_inner
            display = SOBRE_DISPLAY_NAMES.get(top, top)
            idx = index_rows.get(rel) or {}
            by_folder.setdefault(display, []).append(
                {
                    "name": basename,
                    "path": rel,
                    "size": os.path.getsize(file_path),
                    "description": "Documento validado (nomenclatura CompraNet).",
                    "sha256": idx.get("sha256"),
                    "source_doc_id": idx.get("source_doc_id"),
                    "source_filename": idx.get("source_filename"),
                    "template_id": idx.get("template_id"),
                    "mirror_mode": idx.get("mirror_mode"),
                    "materialization_route": idx.get("materialization_route"),
                    "provenance_ui": idx.get("provenance_ui"),
                }
            )
        for folder_name in sorted(by_folder.keys()):
            structure.append({"folder": folder_name, "files": by_folder[folder_name]})

        logistics = _collect_root_logistics_files(session_path)
        if logistics:
            structure.insert(
                0,
                {"folder": SOBRE_DISPLAY_NAMES["GENERAL"], "files": logistics},
            )
        return structure, _compute_inventory(session_path, structure, "compranet_validated")

    # Sin manifiesto: deduplicar por hash en todo el árbol (compatibilidad)
    descriptions: Dict[str, str] = {}
    meta_path = os.path.join(session_path, "descriptions.json")
    if os.path.isfile(meta_path):
        try:
            import json

            with open(meta_path, "r", encoding="utf-8") as f:
                descriptions = json.load(f)
        except Exception:
            pass

    seen_sha: Dict[str, str] = {}
    by_folder: Dict[str, List[Dict[str, Any]]] = {}
    for file_path in sorted(_iter_files_under(session_path)):
        basename = os.path.basename(file_path)
        if not _is_office_delivery_file(basename):
            continue
        rel = _nfc_path(os.path.relpath(file_path, session_path))
        if rel.startswith(f"{COMPRANET_VALIDATED_DIR}/"):
            continue
        if any(rel.startswith(f"{d}/") or rel == d for d in PRUNE_DIRECTORY_NAMES):
            continue
        try:
            digest = _sha256_file(file_path)
        except OSError:
            continue
        if digest in seen_sha:
            continue
        seen_sha[digest] = rel
        top = rel.split("/")[0] if "/" in rel else SOBRE_DISPLAY_NAMES["GENERAL"]
        by_folder.setdefault(top, []).append(
            {
                "name": basename,
                "path": rel,
                "size": os.path.getsize(file_path),
                "description": descriptions.get(
                    basename,
                    "Documento generado automáticamente.",
                ),
            }
        )
    for folder_name in sorted(by_folder.keys()):
        structure.append({"folder": folder_name, "files": by_folder[folder_name]})
    return structure, _compute_inventory(session_path, structure, "deduplicated_fallback")


def summarize_delivery_inventory(session_path: str) -> Dict[str, Any]:
    """Métricas de conteo para UI y auditoría (sin duplicar triplicados)."""
    _structure, inventory = build_delivery_structure(session_path)
    return inventory


def iter_delivery_zip_entries(session_path: str) -> List[Tuple[str, str]]:
    """
    Pares (ruta_absoluta, arcname) para construir ZIP de entrega sin duplicados.
    """
    entries: List[Tuple[str, str]] = []
    validated = compranet_validated_root(session_path)
    if has_compranet_validated(session_path):
        for file_path in sorted(_iter_files_under(validated)):
            arc = _nfc_path(
                os.path.relpath(file_path, session_path)
            )
            entries.append((file_path, arc))
        for item in _collect_root_logistics_files(session_path):
            full = os.path.join(session_path, item["path"])
            entries.append((full, item["path"]))
        return entries

    structure, _ = build_delivery_structure(session_path)
    for folder in structure:
        for f in folder.get("files") or []:
            rel = str(f.get("path") or "")
            if not rel:
                continue
            full = os.path.join(session_path, rel)
            if os.path.isfile(full):
                entries.append((full, rel))
    return entries


def delivery_zip_available(session_path: str) -> bool:
    if not session_path or not os.path.isdir(session_path):
        return False
    if iter_delivery_zip_entries(session_path):
        return True
    return _find_prebuilt_zip_path(session_path) is not None


def _find_prebuilt_zip_path(session_path: str) -> Optional[str]:
    try:
        candidates: List[Tuple[float, str]] = []
        for name in os.listdir(session_path):
            if not name.lower().endswith(".zip"):
                continue
            full = os.path.join(session_path, name)
            if os.path.isfile(full) and os.path.getsize(full) > 0:
                candidates.append((os.path.getmtime(full), full))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except OSError:
        return None
