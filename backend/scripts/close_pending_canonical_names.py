#!/usr/bin/env python3
"""
Renombra archivos que quedaron con patrón ``{RFC}_{sesión}_Sobre_*`` usando metadatos de tareas.

Sin listas por licitación: solo RFC del manifiesto + nombres persistidos en ``tasks_completed``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _docx_head_text(path: Path, max_chars: int = 3000) -> str:
    from docx import Document

    return " ".join(p.text for p in Document(path).paragraphs)[:max_chars].lower()


def _token_set(text: str) -> Set[str]:
    return {w for w in re.findall(r"\w{4,}", (text or "").lower()) if len(w) >= 4}


def _best_task_match(head: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    head_t = _token_set(head)
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for c in candidates:
        nombre = str(c.get("nombre") or "")
        blob = f"{nombre} {c.get('source_filename') or ''}"
        score = len(head_t & _token_set(blob))
        if score > best_score:
            best_score = score
            best = c
    return best if best_score >= 2 else None


async def _collect_task_docs(session_id: str) -> List[Dict[str, Any]]:
    from app.memory.factory import MemoryAdapterFactory

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    try:
        st = await mem.get_session(session_id) or {}
        out: List[Dict[str, Any]] = []
        for task in st.get("tasks_completed") or []:
            if not isinstance(task, dict):
                continue
            payload = task.get("result") or {}
            inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            for d in (inner or {}).get("documentos") or []:
                if isinstance(d, dict) and d.get("nombre"):
                    out.append(dict(d))
        return out
    finally:
        await mem.disconnect()


def _is_legacy_canonical(name: str, rfc_token: str, lic_token: str) -> bool:
    esc_rfc = re.escape(rfc_token)
    esc_lic = re.escape(lic_token)
    return bool(
        re.match(
            rf"^{esc_rfc}_{esc_lic}_Sobre(?:Complementaria|Tecnica|Economica)_\d+",
            name,
            re.I,
        )
    )


def _refresh_manifest(staged: Path, rfc: str, lic: str) -> None:
    from app.agents.packager import _file_sha256
    from app.services.deliverable_filename_service import pick_convocante_label

    rows: List[Dict[str, Any]] = []
    total = 0
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.name in ("MANIFIESTO_SHA256.json", "INDICE_ENTREGA.json"):
            continue
        rel = str(path.relative_to(staged)).replace("\\", "/")
        sz = path.stat().st_size
        total += sz
        label, mode = pick_convocante_label({"nombre": path.stem, "source_filename": path.name})
        rows.append(
            {
                "sobre": rel.split("/")[0],
                "path": rel,
                "nombre_entrega": path.name,
                "nombre_convocante": label or path.name,
                "naming_mode": f"convocante:{mode}" if label else "renamed_pending",
                "sha256": _file_sha256(path),
                "bytes": sz,
            }
        )
    utc = datetime.now(timezone.utc).isoformat()
    (staged / "MANIFIESTO_SHA256.json").write_text(
        json.dumps(
            {
                "algorithm": "SHA-256",
                "rfc_token": rfc,
                "licitacion_token": lic,
                "generated_utc": utc,
                "naming_policy": "convocante_first",
                "files": rows,
                "total_bytes": total,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (staged / "INDICE_ENTREGA.json").write_text(
        json.dumps(
            {"schema_version": "1.0.0", "session_id": lic, "files": rows, "generated_utc": utc},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()

    from app.services.deliverable_filename_service import resolve_deliverable_filename

    staged = Path("/data/outputs") / args.session / "_compranet_validated"
    if not staged.is_dir():
        print(f"ERROR: no existe {staged}")
        return 1

    manifest_path = staged / "MANIFIESTO_SHA256.json"
    rfc, lic = "NA", args.session
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            rfc = str(prev.get("rfc_token") or rfc)
            lic = str(prev.get("licitacion_token") or lic)
        except json.JSONDecodeError:
            pass

    task_docs = await _collect_task_docs(args.session)
    used: Set[str] = set()
    renamed: List[Dict[str, str]] = []

    for path in sorted(staged.rglob("*")):
        if not path.is_file() or not _is_legacy_canonical(path.name, rfc, lic):
            continue
        match = _best_task_match(_docx_head_text(path), task_docs)
        if not match:
            print("WARN sin match de tarea:", path.name)
            continue
        ext = path.suffix.lower()
        dest_name, _, _ = resolve_deliverable_filename(
            match,
            rfc_token=rfc,
            licitacion_token=lic,
            sobre_label=path.parent.name,
            orden=1,
            ext=ext,
            used_names=used,
        )
        dest = path.parent / dest_name
        if dest.resolve() != path.resolve():
            if dest.exists():
                dest.unlink()
            path.rename(dest)
        renamed.append({"from": path.name, "to": dest_name, "sobre": path.parent.name})

    _refresh_manifest(staged, rfc, lic)
    root = Path("/data/outputs") / args.session
    zip_path = root / f"{lic}_CompraNet_bundle.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in staged.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(staged).as_posix())

    remaining = [
        p.name
        for p in staged.rglob("*")
        if p.is_file() and _is_legacy_canonical(p.name, rfc, lic)
    ]
    print(
        json.dumps(
            {
                "renamed": renamed,
                "count": len(renamed),
                "remaining_canonical": remaining,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not remaining else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
