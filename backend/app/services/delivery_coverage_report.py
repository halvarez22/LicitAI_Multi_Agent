"""
Reporte de cobertura: plantillas esperadas vs entregables en ``_compranet_validated``.

Universal por sesión; explica omisiones con causa estable (sin listas por convocante).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.session_template_catalog import (
    CATALOG_SCHEMA_VERSION,
    build_session_template_catalog,
    normalize_filename_key,
)

REPORT_SCHEMA_VERSION = "1.0.0"
_OUTPUTS_ROOT = Path(os.environ.get("LICITAI_OUTPUTS_ROOT", "/data/outputs"))


def _extract_compliance_master(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Obtiene compliance administrativo/tecnico/formatos desde sesión."""
    injected = session_state.get("compliance_master_list")
    if isinstance(injected, dict) and injected:
        return injected
    for task in reversed(session_state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        if task.get("task") == "stage_completed:compliance":
            res = task.get("result") or {}
            if isinstance(res, dict) and res.get("data"):
                return res["data"]
        if task.get("task") == "master_compliance_list":
            res = task.get("result") or task.get("data") or {}
            return res.get("data", res) if isinstance(res, dict) else {}
    return {}


def _collect_generated_artifacts(session_state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Archivos generados registrados en tareas (última corrida por tipo)."""
    out: List[Dict[str, Any]] = []
    seen_paths: Set[str] = set()
    for task in session_state.get("tasks_completed") or []:
        if not isinstance(task, dict):
            continue
        tname = str(task.get("task") or "")
        payload = task.get("result") or task.get("data") or {}
        if not isinstance(payload, dict):
            continue
        docs = payload.get("documentos") or []
        if tname == "formats_generation_COMPLETED":
            kind = "formats"
        elif tname == "technical_writing_COMPLETED":
            kind = "technical"
        else:
            continue
        for d in docs:
            if not isinstance(d, dict):
                continue
            nombre = str(d.get("nombre") or "")
            ruta = str(d.get("ruta") or "")
            if ruta:
                if ruta in seen_paths:
                    continue
                seen_paths.add(ruta)
                out.append(
                    {
                        "kind": kind,
                        "nombre": nombre,
                        "ruta": ruta,
                        "filename_key": normalize_filename_key(
                            str(d.get("source_filename") or nombre)
                        ),
                        "source_doc_id": d.get("source_doc_id"),
                        "source_filename": d.get("source_filename"),
                        "source_hash": d.get("source_hash"),
                        "output_hash": d.get("output_hash"),
                        "template_id": d.get("template_id"),
                        "mirror_mode": d.get("mirror_mode"),
                        "materialization_route": d.get("materialization_route"),
                        "provenance_ui": d.get("provenance_ui"),
                    }
                )
    return out


def _load_manifest_rows(session_id: str) -> List[Dict[str, Any]]:
    """Filas del índice/manifiesto CompraNet si existe."""
    index_path = _OUTPUTS_ROOT / session_id / "_compranet_validated" / "INDICE_ENTREGA.json"
    manifest_path = _OUTPUTS_ROOT / session_id / "_compranet_validated" / "MANIFIESTO_SHA256.json"
    source_path = index_path if index_path.is_file() else manifest_path
    if not source_path.is_file():
        return []
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    files = data.get("files") or []
    rows: List[Dict[str, Any]] = []
    for f in files:
        if isinstance(f, dict) and f.get("path"):
            row = dict(f)
            row["filename_key"] = normalize_filename_key(
                str(f.get("source_filename") or str(f.get("nombre_entrega") or f.get("path") or ""))
            )
            rows.append(row)
    return rows


def _token_overlap(a: str, b: str) -> float:
    """Similitud simple por tokens compartidos (Jaccard)."""
    ta = set(normalize_filename_key(a).split())
    tb = set(normalize_filename_key(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _find_compliance_link(
    filename: str,
    compliance: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Busca ítem de compliance que cite este archivo."""
    key = normalize_filename_key(filename)
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for bucket in ("administrativo", "tecnico", "formatos"):
        for item in compliance.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            src = str(item.get("archivo_fuente") or "")
            if not src:
                continue
            score = _token_overlap(filename, src)
            if src.lower() in filename.lower() or filename.lower() in src.lower():
                score = max(score, 0.85)
            if score > best_score and score >= 0.35:
                best_score = score
                best = {**item, "_bucket": bucket, "_match_score": round(score, 3)}
    if best:
        return best
    # Segunda pasada: overlap nombre del requisito vs archivo
    for bucket in ("administrativo", "tecnico", "formatos"):
        for item in compliance.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            nombre = str(item.get("nombre") or "")
            score = _token_overlap(filename, nombre)
            if score >= 0.45:
                return {**item, "_bucket": bucket, "_match_score": round(score, 3)}
    return None


def _match_generated(
    filename: str,
    generated: List[Dict[str, Any]],
    manifest_rows: List[Dict[str, Any]],
    *,
    source_doc_id: Optional[str] = None,
    filename_key: str = "",
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Devuelve (row, metodo_match) o (None, "").
    """
    key = filename_key or normalize_filename_key(filename)
    if source_doc_id:
        for g in generated:
            if str(g.get("source_doc_id") or "") == str(source_doc_id):
                return g, "generated_source_doc_id"
        for row in manifest_rows:
            if str(row.get("source_doc_id") or "") == str(source_doc_id):
                return row, "manifest_source_doc_id"
    for g in generated:
        if key and key == str(g.get("filename_key") or ""):
            return g, "generated_filename_key"
    for row in manifest_rows:
        if key and key == str(row.get("filename_key") or ""):
            return row, "manifest_filename_key"
    for g in generated:
        if _token_overlap(filename, g.get("nombre") or "") >= 0.4:
            return g, "task_documento"
    for row in manifest_rows:
        path = str(row.get("path") or "")
        base = path.split("/")[-1]
        if _token_overlap(filename, base) >= 0.35:
            return row, "manifiesto_fuzzy"
    # Palabras distintivas del anexo (ej. "declaracion integridad" -> integridad)
    tokens = [t for t in key.split() if len(t) > 4]
    for g in generated:
        gkey = g.get("filename_key") or normalize_filename_key(g.get("nombre") or "")
        if any(t in gkey for t in tokens[:6]):
            return g, "task_token"
    return None, ""


def _estado_y_causa(
    doc_class: str,
    accion: str,
    archivo_entregado: Optional[str],
    compliance_item: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    """Determina estado de cobertura y explicación UX."""
    if doc_class in ("pliego_referencia", "informativo"):
        return "no_aplica", "Documento de pliego o referencia; no forma parte del expediente Word/Excel a generar."
    if accion == "presentar_fisico":
        return (
            "presentar_fisico",
            "Original o constancia del licitante/terceros; el sistema no genera este tipo de evidencia.",
        )
    if accion != "generar":
        return "no_aplica", f"Acción recomendada: {accion}."

    if archivo_entregado:
        return "generado", "Materializado en la última corrida de generación o manifiesto CompraNet."

    tipo = str((compliance_item or {}).get("tipo_accion") or "").lower()
    if compliance_item and tipo not in ("generar", "requiere_datos_licitante"):
        return (
            "omitido_por_clasificacion",
            f"Compliance clasificó como «{tipo}»; no entra al router de generación automática.",
        )
    if compliance_item and not (compliance_item.get("archivo_fuente") or "").strip():
        return (
            "pendiente_generar",
            "Plantilla identificada en ingesta pero sin «archivo_fuente» en compliance; "
            "falta enlace para espejo/relleno (fase 2).",
        )
    return (
        "pendiente_generar",
        "Plantilla de oferta esperada; aún no hay archivo equivalente en el paquete validado. "
        "Próximo paso: relleno espejo desde archivo ingestado (sin hardcode por licitación).",
    )


def build_delivery_coverage_report(
    session_id: str,
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Construye el reporte de cobertura completo para API/UI.

    Args:
        session_id: Sesión.
        session_state: Estado persistido (tasks, dictamen, etc.).
        documents: Documentos ingestados.
        catalog: Catálogo precomputado; si es None se construye aquí.
    """
    cat = catalog or build_session_template_catalog(session_id, documents)
    compliance = _extract_compliance_master(session_state)
    generated = _collect_generated_artifacts(session_state)
    manifest_rows = _load_manifest_rows(session_id)

    rows: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {
        "generado": 0,
        "pendiente_generar": 0,
        "presentar_fisico": 0,
        "omitido_por_clasificacion": 0,
        "no_aplica": 0,
    }

    for item in cat.get("items") or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("source_filename") or "")
        doc_class = str(item.get("document_class") or "")
        accion = str(item.get("accion_recomendada") or "")
        compliance_item = _find_compliance_link(filename, compliance)
        matched_row, match_method = _match_generated(
            filename,
            generated,
            manifest_rows,
            source_doc_id=item.get("doc_id"),
            filename_key=str(item.get("filename_key") or ""),
        )
        archivo_entregado = None
        if matched_row:
            archivo_entregado = matched_row.get("ruta") or matched_row.get("path") or matched_row.get("nombre")
        estado, causa = _estado_y_causa(
            doc_class, accion, archivo_entregado, compliance_item
        )
        counts[estado] = counts.get(estado, 0) + 1

        rows.append(
            {
                "source_filename": filename,
                "filename_key": item.get("filename_key"),
                "document_class": doc_class,
                "accion_recomendada": accion,
                "sobre_inferido": item.get("sobre_inferido"),
                "estado_cobertura": estado,
                "causa": causa,
                "archivo_entregado": archivo_entregado,
                "match_method": match_method or None,
                "source_doc_id": item.get("doc_id"),
                "delivered_source_doc_id": (matched_row or {}).get("source_doc_id"),
                "source_hash": (matched_row or {}).get("source_hash"),
                "output_hash": (matched_row or {}).get("output_hash") or (matched_row or {}).get("sha256"),
                "template_id": (matched_row or {}).get("template_id"),
                "mirror_mode": (matched_row or {}).get("mirror_mode"),
                "materialization_route": (matched_row or {}).get("materialization_route"),
                "provenance_ui": (matched_row or {}).get("provenance_ui"),
                "compliance_vinculado": compliance_item is not None,
                "compliance_tipo_accion": (compliance_item or {}).get("tipo_accion"),
                "compliance_nombre": (compliance_item or {}).get("nombre"),
            }
        )

    plantillas = [r for r in rows if r.get("document_class") == "plantilla_oferta"]
    esperadas_generar = [r for r in plantillas if r.get("accion_recomendada") == "generar"]
    generadas = [r for r in esperadas_generar if r.get("estado_cobertura") == "generado"]
    pendientes = [r for r in esperadas_generar if r.get("estado_cobertura") == "pendiente_generar"]

    denom = len(esperadas_generar) or 1
    cobertura_pct = round(100.0 * len(generadas) / denom, 1)

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "catalog_schema_version": cat.get("schema_version", CATALOG_SCHEMA_VERSION),
        "session_id": session_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": cat.get("objective"),
        "manifest_files_count": len(manifest_rows),
        "generated_artifacts_count": len(generated),
        "summary": {
            "plantillas_oferta_total": len(plantillas),
            "esperadas_generar": len(esperadas_generar),
            "generadas": len(generadas),
            "pendientes_generar": len(pendientes),
            "presentar_fisico": counts.get("presentar_fisico", 0),
            "no_aplica_referencia": counts.get("no_aplica", 0),
            "cobertura_generacion_pct": cobertura_pct,
        },
        "counts_by_estado": counts,
        "catalog_stats": cat.get("stats"),
        "rows": rows,
    }


async def build_and_persist_coverage(
    memory: Any,
    session_id: str,
) -> Dict[str, Any]:
    """
    Construye catálogo + cobertura y persiste en la sesión.

    Returns:
        Reporte de cobertura completo.
    """
    session_state = await memory.get_session(session_id) or {}
    documents = await memory.get_documents(session_id)
    catalog = build_session_template_catalog(session_id, documents)
    report = build_delivery_coverage_report(
        session_id, session_state, documents, catalog=catalog
    )
    session_state["session_template_catalog"] = catalog
    session_state["delivery_coverage_report"] = report
    await memory.save_session(session_id, dict(session_state))
    try:
        from app.services.mini_dictamen_anexos_service import (
            build_and_persist_mini_dictamen,
        )

        await build_and_persist_mini_dictamen(memory, session_id)
    except Exception as exc:
        # El reporte de cobertura no debe romperse si falla la capa canónica,
        # pero sí dejar rastro para diagnóstico.
        print(f"[delivery_coverage_report] mini_dictamen refresh failed: {exc}")
    return report
