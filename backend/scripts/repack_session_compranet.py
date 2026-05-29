#!/usr/bin/env python3
"""
Re-empaqueta CompraNet (nombres convocante + manifiesto) sin regenerar LLM.

Usa metadatos de tareas + catálogo ingestado (universal). Si no hay SOBRE_* en disco,
reconstruye desde ``_compranet_validated`` emparejando por orden de empaquetado previo.

Uso:
  python scripts/repack_session_compranet.py --session SESSION_ID
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
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SOBR_E_KEYS = ("sobre_1", "sobre_2", "sobre_3")
_LABEL_BY_SK = {
    "sobre_1": "SobreComplementaria",
    "sobre_2": "SobreTecnica",
    "sobre_3": "SobreEconomica",
}


def _canonical_order_key(name: str) -> int:
    m = re.search(r"_(\d{2})(?:\.|$)", name)
    if m:
        return int(m.group(1))
    m = re.search(r"_(\d+)(?:\.|$)", name)
    return int(m.group(1)) if m else 999


def _find_estructura_sobres(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    er = state.get("execution_results") or {}
    for key in ("document_packager", "packager"):
        block = er.get(key)
        if isinstance(block, dict):
            data = block.get("data") if isinstance(block.get("data"), dict) else block
            est = (data or {}).get("estructura_sobres")
            if est:
                return est
    for task in reversed(state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        payload = task.get("result") or task.get("data") or {}
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        est = (data or {}).get("estructura_sobres")
        if est:
            return est
    return None


def _collect_gen_docs_from_tasks(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    gen: Dict[str, List[Dict[str, Any]]] = {
        "administrativa": [],
        "tecnica": [],
        "economica": [],
    }
    for task in state.get("tasks_completed") or []:
        if not isinstance(task, dict):
            continue
        tn = str(task.get("task") or "")
        payload = task.get("result") or task.get("data") or {}
        if not isinstance(payload, dict):
            continue
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        docs = (inner or {}).get("documentos") or []
        if tn == "formats_generation_COMPLETED":
            for d in docs:
                if isinstance(d, dict):
                    gen["administrativa"].append(dict(d))
        elif tn == "technical_writing_COMPLETED":
            for d in docs:
                if isinstance(d, dict):
                    gen["tecnica"].append(dict(d))
    root = Path("/data/outputs") / str(state.get("session_id") or "")
    eco_dir = root / "economic_proposal"
    if eco_dir.is_dir():
        for f in sorted(eco_dir.iterdir()):
            if f.is_file():
                gen["economica"].append(
                    {
                        "nombre": f.name,
                        "ruta": str(f.resolve()),
                        "status": "OK",
                    }
                )
    return gen


def _catalog_generar_items(
    session_id: str, documents: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    from app.services.session_template_catalog import build_session_template_catalog

    cat = build_session_template_catalog(session_id, documents)
    out: Dict[str, List[Dict[str, Any]]] = {
        "administrativo": [],
        "tecnico": [],
        "economico": [],
    }
    for item in cat.get("items") or []:
        if item.get("accion_recomendada") != "generar":
            continue
        sobre = str(item.get("sobre_inferido") or "administrativo")
        if sobre in out:
            out[sobre].append(item)
    for k in out:
        out[k].sort(key=lambda x: str(x.get("source_filename") or ""))
    return out


def _enrich_doc_from_catalog(doc: Dict[str, Any], catalog_row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    sf = str(catalog_row.get("source_filename") or "").strip()
    if sf:
        out["source_filename"] = sf
        if not _looks_generic_nombre(str(out.get("nombre") or "")):
            pass
        else:
            out["nombre"] = sf
    return out


def _looks_generic_nombre(name: str) -> bool:
    n = (name or "").strip().lower()
    if len(n) < 4:
        return True
    if re.match(r"^(te|fo|ad|ae|dd)[-_]?\d+", n):
        return True
    if n in ("documento", "propuesta", "carta de presentación", "carta de presentacion"):
        return True
    return False


def _bucket_docs_by_sobre(
    gen_docs: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    from app.agents.document_packager import _classify_doc_to_sobre_key, _sort_docs_for_sobre

    buckets: Dict[str, List[Dict[str, Any]]] = {sk: [] for sk in _SOBR_E_KEYS}
    for cat, docs in gen_docs.items():
        for d in docs:
            item = dict(d)
            item.setdefault("categoria", cat)
            sk = _classify_doc_to_sobre_key(item)
            buckets[sk].append(item)
    for sk in buckets:
        buckets[sk] = _sort_docs_for_sobre(buckets[sk])
    return buckets


def _estructura_from_sobre_dirs(session_id: str) -> Dict[str, Any]:
    from app.agents.document_packager import _SOBR_E_SHELLS

    root = Path("/data/outputs") / session_id
    key_by_folder = {
        "SOBRE_1_ADMINISTRATIVO": "sobre_1",
        "SOBRE_2_TECNICO": "sobre_2",
        "SOBRE_3_ECONOMICO": "sobre_3",
    }
    out: Dict[str, Any] = {}
    for folder, sk in key_by_folder.items():
        sd = root / folder
        if not sd.is_dir():
            continue
        shell = _SOBR_E_SHELLS.get(sk, {})
        docs: List[Dict[str, Any]] = []
        orden = 0
        for fn in sorted(sd.iterdir()):
            if not fn.is_file() or fn.name.startswith("00_CARATULA"):
                continue
            orden += 1
            docs.append(
                {
                    "orden": orden,
                    "nombre": fn.name,
                    "archivo": fn.name,
                }
            )
        out[sk] = {
            "titulo": shell.get("titulo", sk),
            "carpeta": str(sd),
            "documentos": docs,
            "total_documentos": len(docs),
        }
    return out


def _estructura_from_validated(
    session_id: str,
    state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Empareja archivos en ``_compranet_validated`` con metadatos de tareas + catálogo.
    """
    from app.agents.document_packager import _SOBR_E_SHELLS

    root = Path("/data/outputs") / session_id
    validated = root / "_compranet_validated"
    if not validated.is_dir():
        return None, ["No existe _compranet_validated"]

    gen_docs = _collect_gen_docs_from_tasks(state)
    state_with_sid = {**state, "session_id": session_id}
    buckets = _bucket_docs_by_sobre(gen_docs)
    catalog = _catalog_generar_items(session_id, documents)
    warnings: List[str] = []

    for sk, label in _LABEL_BY_SK.items():
        sobre_dir = validated / label
        if not sobre_dir.is_dir():
            continue
        files_on_disk = sorted(
            [f for f in sobre_dir.iterdir() if f.is_file()],
            key=lambda p: _canonical_order_key(p.name),
        )
        meta_list = list(buckets.get(sk) or [])
        cat_key = {
            "sobre_1": "administrativo",
            "sobre_2": "tecnico",
            "sobre_3": "economico",
        }[sk]
        cat_rows = list(catalog.get(cat_key) or [])

        if len(meta_list) < len(files_on_disk) and cat_rows:
            while len(meta_list) < len(files_on_disk):
                idx = len(meta_list)
                row = cat_rows[idx] if idx < len(cat_rows) else cat_rows[-1]
                meta_list.append(
                    {
                        "nombre": row.get("source_filename"),
                        "source_filename": row.get("source_filename"),
                    }
                )
            warnings.append(
                f"{label}: metadatos ampliados desde catálogo ingestado "
                f"({len(files_on_disk)} archivos)."
            )

        if len(meta_list) != len(files_on_disk):
            warnings.append(
                f"{label}: {len(files_on_disk)} archivos vs {len(meta_list)} metadatos"
            )
            n = min(len(meta_list), len(files_on_disk))
            files_on_disk = files_on_disk[:n]
            meta_list = meta_list[:n]

        docs_finales: List[Dict[str, Any]] = []
        for orden, (fpath, meta) in enumerate(zip(files_on_disk, meta_list), start=1):
            merged = dict(meta)
            if orden - 1 < len(cat_rows) and not merged.get("source_filename"):
                merged = _enrich_doc_from_catalog(merged, cat_rows[orden - 1])
            docs_finales.append(
                {
                    "orden": orden,
                    "nombre": merged.get("nombre") or merged.get("source_filename") or fpath.name,
                    "source_filename": merged.get("source_filename"),
                    "archivo_fuente": merged.get("archivo_fuente"),
                    "archivo": fpath.name,
                }
            )

        shell = _SOBR_E_SHELLS.get(sk, {})
        buckets[sk] = docs_finales  # type: ignore[assignment]

    estructura: Dict[str, Any] = {}
    for sk in _SOBR_E_KEYS:
        label = _LABEL_BY_SK[sk]
        sobre_dir = validated / label
        if not sobre_dir.is_dir():
            continue
        docs_finales = buckets.get(sk) or []
        if not docs_finales:
            continue
        shell = _SOBR_E_SHELLS.get(sk, {})
        estructura[sk] = {
            "titulo": shell.get("titulo", sk),
            "carpeta": str(sobre_dir.resolve()),
            "documentos": docs_finales,
            "total_documentos": len(docs_finales),
        }

    return (estructura if estructura else None), warnings


async def _rename_validated_in_place(
    session_id: str,
    state: Dict[str, Any],
    documents: List[Dict[str, Any]],
    profile: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], List[str]]:
    """
    Renombra archivos en ``_compranet_validated`` sin borrar la carpeta (re-empaque seguro).
    """
    from app.agents.packager import (
        CompraNetPackager,
        _file_sha256,
        _sanitize_token,
    )
    from app.services.deliverable_filename_service import resolve_deliverable_filename

    estructura, warnings = _estructura_from_validated(session_id, state, documents)
    if not estructura:
        return False, {}, ["No se pudo armar estructura desde validado"]

    rfc_s = _sanitize_token(str(profile.get("rfc") or ""))
    lic_s = _sanitize_token(str(state.get("licitacion_id") or session_id))
    if not rfc_s or rfc_s == "NA":
        return False, {}, ["RFC no disponible (perfil empresa o manifiesto previo)"]

    root = Path("/data/outputs") / session_id
    staged = root / "_compranet_validated"
    index_rows: List[Dict[str, Any]] = []

    for sk, info in estructura.items():
        label = _LABEL_BY_SK.get(sk, sk)
        sobre_dir = Path(str(info.get("carpeta") or staged / label))
        used: set[str] = set()
        for doc in info.get("documentos") or []:
            if not isinstance(doc, dict):
                continue
            archivo = str(doc.get("archivo") or "")
            src = sobre_dir / archivo
            if not src.is_file():
                warnings.append(f"Falta en disco: {src}")
                continue
            ext = src.suffix.lower()
            try:
                orden_i = int(doc.get("orden") or 1)
            except (TypeError, ValueError):
                orden_i = 1
            dest_name, naming_mode, conv_label = resolve_deliverable_filename(
                doc,
                rfc_token=rfc_s,
                licitacion_token=lic_s,
                sobre_label=label,
                orden=orden_i,
                ext=ext,
                used_names=used,
            )
            dest = sobre_dir / dest_name
            if src.resolve() != dest.resolve():
                if dest.exists():
                    dest.unlink()
                src.rename(dest)
            rel = f"{label}/{dest_name}".replace("\\", "/")
            digest = _file_sha256(dest)
            sz = dest.stat().st_size
            index_rows.append(
                {
                    "sobre": label,
                    "path": rel,
                    "nombre_entrega": dest_name,
                    "nombre_convocante": conv_label,
                    "naming_mode": naming_mode,
                    "canonical_fallback": "",
                    "sha256": digest,
                    "bytes": sz,
                }
            )

    if not index_rows:
        return False, {}, ["No se renombró ningún archivo"]

    total = sum(int(r.get("bytes") or 0) for r in index_rows)
    indice = {
        "schema_version": "1.0.0",
        "session_id": lic_s,
        "rfc_token": rfc_s,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "files": index_rows,
    }
    (staged / "INDICE_ENTREGA.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "algorithm": "SHA-256",
        "rfc_token": rfc_s,
        "licitacion_token": lic_s,
        "generated_utc": indice["generated_utc"],
        "naming_policy": "convocante_first",
        "files": index_rows,
        "total_bytes": total,
        "zip_compatible": "ZIP_DEFLATED level 6 (stdlib zipfile)",
    }
    (staged / "MANIFIESTO_SHA256.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    zip_path = root / f"{lic_s}_CompraNet_bundle.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in staged.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(staged).as_posix())

    pr_data = {
        "success": True,
        "validation_passed": True,
        "manifest_path": str((staged / "MANIFIESTO_SHA256.json").resolve()),
        "zip_path": str(zip_path.resolve()),
        "staged_root": str(staged.resolve()),
        "files": index_rows,
        "total_bytes": total,
    }
    return True, pr_data, warnings


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-empaque CompraNet universal (nombres convocante)"
    )
    parser.add_argument("--session", required=True)
    args = parser.parse_args()

    from app.agents.packager import CompraNetPackager, build_pack_session_data_from_outputs
    from app.memory.factory import MemoryAdapterFactory
    from app.services.delivery_coverage_report import build_and_persist_coverage

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    try:
        state = await mem.get_session(args.session) or {}
        documents = await mem.get_documents(args.session)

        estructura = _find_estructura_sobres(state)
        warnings: List[str] = []
        if not estructura:
            estructura = _estructura_from_sobre_dirs(args.session)
        if not estructura:
            estructura, warnings = _estructura_from_validated(
                args.session, state, documents
            )
        if not estructura:
            print("ERROR: No hay estructura, SOBRE_* ni _compranet_validated utilizable.")
            return 1

        profile = state.get("master_profile") or {}
        if not isinstance(profile, dict):
            profile = {}
        if not profile.get("rfc") and state.get("company_id"):
            company = await mem.get_company(str(state["company_id"]))
            if isinstance(company, dict):
                mp = company.get("master_profile")
                if isinstance(mp, dict):
                    profile = {**profile, **mp}
                elif isinstance(mp, str):
                    try:
                        profile = {**profile, **json.loads(mp)}
                    except json.JSONDecodeError:
                        pass
        manifest_path = (
            Path("/data/outputs") / args.session / "_compranet_validated" / "MANIFIESTO_SHA256.json"
        )
        if not profile.get("rfc") and manifest_path.is_file():
            try:
                prev = json.loads(manifest_path.read_text(encoding="utf-8"))
                if prev.get("rfc_token"):
                    profile = {**profile, "rfc": prev["rfc_token"]}
            except (json.JSONDecodeError, OSError):
                pass

        validated_dir = Path("/data/outputs") / args.session / "_compranet_validated"
        use_inplace = validated_dir.is_dir() and not _estructura_from_sobre_dirs(args.session)

        if use_inplace:
            ok, pr_data, warnings = await _rename_validated_in_place(
                args.session, state, documents, profile
            )
            if not ok:
                print("FAIL:", "; ".join(warnings))
                return 1
            pr_dict = pr_data
        else:
            pack_session = build_pack_session_data_from_outputs(
                session_id=args.session,
                packager_agent_data={
                    "folder_raiz": str(Path("/data/outputs") / args.session),
                    "estructura_sobres": estructura,
                },
                company_data={
                    "master_profile": profile,
                    "licitacion_id": state.get("licitacion_id") or args.session,
                },
            )
            pr = CompraNetPackager().pack(pack_session)
            if not pr.success:
                print("FAIL:", "; ".join(pr.errors))
                return 1
            pr_dict = pr.to_dict()
            warnings = []

        state = await mem.get_session(args.session) or {}
        er = dict(state.get("execution_results") or {})
        er["compranet_packaging"] = pr_dict
        state["execution_results"] = er
        await mem.save_session(args.session, state)
        await build_and_persist_coverage(mem, args.session)

        files_list = pr_dict.get("files") or []
        conv = sum(
            1
            for f in files_list
            if str(f.get("naming_mode", "")).startswith("convocante")
        )
        out = {
            "session_id": args.session,
            "success": True,
            "mode": "inplace_rename" if use_inplace else "full_pack",
            "warnings": warnings,
            "files": len(files_list),
            "convocante_named": conv,
            "staged_root": pr_dict.get("staged_root"),
            "manifest_path": pr_dict.get("manifest_path"),
            "names_by_sobre": {},
        }
        for row in files_list:
            sobre = (row.get("path") or "").split("/")[0]
            out["names_by_sobre"].setdefault(sobre, []).append(row.get("nombre_entrega"))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        await mem.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
