"""
Gate universal antes de FINAL_OK: anexos económicos esperados vs materializados.

Emparejamiento canónico (D.23): ``source_doc_id`` + rol de catálogo; fallback por nombre
solo si falta identidad de documento (sesiones legacy).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.delivery_coverage_report import build_delivery_coverage_report
from app.services.session_template_catalog import normalize_filename_key
from app.services.structured_economic_price_mapper import build_structured_price_slots

_FILENAME_STOP_TOKENS = frozenset(
    {
        "anexo",
        "iii",
        "p1",
        "p",
        "propuesta",
        "economica",
        "economico",
        "de",
        "la",
        "el",
        "del",
        "los",
        "las",
        "partida",
        "zona",
    }
)


def _economic_catalog_rows(coverage: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = coverage.get("rows") or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        doc_class = str(row.get("document_class") or "").lower()
        accion = str(row.get("accion_recomendada") or "").lower()
        if "economic" in doc_class or accion in ("generar", "requiere_datos_licitante"):
            ext = str(row.get("source_filename") or "").lower()
            if ext.endswith((".xlsx", ".xls")) or "propuesta econom" in ext or "anexo iii" in ext:
                out.append(row)
        elif str(row.get("sobre_inferido") or "").lower() == "economico":
            out.append(row)
    return out


def _distinctive_tokens(text: str) -> Set[str]:
    """Tokens de nombre de archivo sin ruido compartido (fallback legacy)."""
    tokens: Set[str] = set()
    for t in normalize_filename_key(text).split():
        if t in _FILENAME_STOP_TOKENS:
            continue
        if len(t) == 1 and t in "abcd":
            tokens.add(t)
            continue
        if len(t) > 1:
            tokens.add(t)
    return tokens


def _sources_match_filename(expected: str, generated: str) -> bool:
    """Empareja por nombre solo cuando no hay ``source_doc_id`` (sesiones antiguas)."""
    na = normalize_filename_key(expected)
    nb = normalize_filename_key(generated)
    if na and nb and (na in nb or nb in na):
        return True
    ta = _distinctive_tokens(expected)
    tb = _distinctive_tokens(generated)
    if not ta or not tb:
        return False
    inter = ta & tb
    if not inter:
        return False
    return len(inter) / len(ta) >= 0.5


def _build_catalog_indexes(
    session_state: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Índices por ``doc_id`` y por ``filename_key`` desde catálogos de sesión.

    Fuentes: ``session_template_catalog`` (plantillas) y ``document_catalog`` (roles semánticos).
    """
    by_doc_id: Dict[str, Dict[str, Any]] = {}
    by_filename_key: Dict[str, Dict[str, Any]] = {}

    def _merge(entry: Dict[str, Any]) -> None:
        doc_id = str(entry.get("doc_id") or "").strip()
        filename = str(entry.get("source_filename") or entry.get("filename") or "").strip()
        fkey = str(entry.get("filename_key") or normalize_filename_key(filename))
        if doc_id:
            prev = by_doc_id.get(doc_id) or {}
            by_doc_id[doc_id] = {**prev, **entry}
        if fkey:
            prev = by_filename_key.get(fkey) or {}
            by_filename_key[fkey] = {**prev, **entry}

    tpl = session_state.get("session_template_catalog")
    if isinstance(tpl, dict):
        for item in tpl.get("items") or []:
            if isinstance(item, dict):
                _merge(item)

    doc_cat = session_state.get("document_catalog")
    if isinstance(doc_cat, dict):
        entries = doc_cat.get("entries")
        if isinstance(entries, dict):
            for doc_id, ent in entries.items():
                if isinstance(ent, dict):
                    _merge(
                        {
                            "doc_id": str(ent.get("doc_id") or doc_id),
                            "source_filename": ent.get("filename"),
                            "doc_role": ent.get("doc_role"),
                            "use_cases": ent.get("use_cases") or [],
                            "provenance_ui": ent.get("provenance_ui"),
                        }
                    )
        elif isinstance(entries, list):
            for ent in entries:
                if isinstance(ent, dict):
                    _merge(
                        {
                            "doc_id": ent.get("doc_id"),
                            "source_filename": ent.get("filename"),
                            "doc_role": ent.get("doc_role"),
                            "use_cases": ent.get("use_cases") or [],
                            "provenance_ui": ent.get("provenance_ui"),
                        }
                    )

    return by_doc_id, by_filename_key


def _resolve_catalog_entry(
    *,
    source_filename: str,
    document_id: Optional[str],
    by_doc_id: Dict[str, Dict[str, Any]],
    by_filename_key: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Resuelve metadatos de catálogo para un anexo económico esperado."""
    doc_id = str(document_id or "").strip()
    if doc_id and doc_id in by_doc_id:
        return dict(by_doc_id[doc_id])
    fkey = normalize_filename_key(source_filename)
    if fkey and fkey in by_filename_key:
        return dict(by_filename_key[fkey])
    return {}


def _resolve_document_role(
    *,
    template_kind: str,
    line_document_role: str,
    catalog_entry: Dict[str, Any],
) -> str:
    """Rol efectivo: extra de línea > ``doc_role`` de catálogo > ``template_kind``."""
    if line_document_role:
        return line_document_role
    doc_role = str(catalog_entry.get("doc_role") or "").strip()
    if doc_role:
        return doc_role
    return template_kind or "structured_template"


def _collect_expected_economic_annexes(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Anexos económicos estructurados esperados, anclados a catálogo cuando existe.

    Clave de deduplicación: ``source_doc_id`` si está disponible; si no, ``source_filename``.
    """
    by_doc_id, by_filename_key = _build_catalog_indexes(session_state)
    buckets: Dict[str, Dict[str, Any]] = {}

    def _upsert(
        *,
        source_filename: str,
        template_kind: str,
        document_id: Optional[str] = None,
        line_document_role: str = "",
    ) -> None:
        source = str(source_filename or "").strip()
        if not source:
            return
        catalog_entry = _resolve_catalog_entry(
            source_filename=source,
            document_id=document_id,
            by_doc_id=by_doc_id,
            by_filename_key=by_filename_key,
        )
        doc_id = str(document_id or catalog_entry.get("doc_id") or "").strip() or None
        bucket_key = doc_id or normalize_filename_key(source)
        role = _resolve_document_role(
            template_kind=template_kind,
            line_document_role=line_document_role,
            catalog_entry=catalog_entry,
        )
        buckets[bucket_key] = {
            "source_doc_id": doc_id,
            "source_filename": source,
            "template_kind": template_kind,
            "document_role": role,
            "catalog_doc_role": catalog_entry.get("doc_role"),
            "sobre_inferido": catalog_entry.get("sobre_inferido"),
            "document_class": catalog_entry.get("document_class"),
            "filename_key": normalize_filename_key(source),
        }

    for row in session_state.get("session_line_items") or []:
        if not isinstance(row, dict):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if str(extra.get("layout") or "") != "structured_template":
            continue
        _upsert(
            source_filename=str(extra.get("source_filename") or ""),
            template_kind=str(extra.get("template_kind") or "structured").strip(),
            document_id=str(row.get("document_id") or "").strip() or None,
            line_document_role=str(extra.get("document_role") or "").strip(),
        )

    meta = session_state.get("capture_matrix_meta")
    if isinstance(meta, dict):
        for layout in meta.get("layouts") or []:
            if not isinstance(layout, dict):
                continue
            source = str(layout.get("source_file") or "").strip()
            if not source:
                continue
            fkey = normalize_filename_key(source)
            if any(
                normalize_filename_key(b.get("source_filename") or "") == fkey
                for b in buckets.values()
            ):
                continue
            _upsert(
                source_filename=source,
                template_kind=str(layout.get("row_dimension") or "matrix"),
            )

    return list(buckets.values())


def _collect_generated_economic_artifacts(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Entregables del agente económico con ``source_doc_id`` cuando el writer lo registra."""
    out: List[Dict[str, Any]] = []
    for task in session_state.get("tasks_completed") or []:
        if not isinstance(task, dict):
            continue
        tname = str(task.get("task") or "")
        if "economic" not in tname.lower():
            continue
        payload = task.get("result") or task.get("data") or {}
        if not isinstance(payload, dict):
            continue
        for doc in payload.get("documentos") or []:
            if not isinstance(doc, dict):
                continue
            nombre = str(doc.get("nombre") or "").strip()
            source_fn = str(doc.get("source_filename") or "").strip()
            out.append(
                {
                    "nombre": nombre,
                    "source_filename": source_fn,
                    "source_doc_id": str(doc.get("source_doc_id") or "").strip() or None,
                    "delivered_source_doc_id": str(doc.get("delivered_source_doc_id") or "").strip()
                    or None,
                    "ruta": str(doc.get("ruta") or "").strip() or None,
                }
            )
    return out


def _coverage_index_by_doc_id(coverage: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    if not isinstance(coverage, dict):
        return idx
    for row in coverage.get("rows") or []:
        if not isinstance(row, dict):
            continue
        doc_id = str(row.get("source_doc_id") or "").strip()
        if doc_id:
            idx[doc_id] = row
    return idx


def _expected_annex_has_delivery(
    expected: Dict[str, Any],
    generated: List[Dict[str, Any]],
    coverage_by_doc_id: Dict[str, Dict[str, Any]],
) -> Tuple[bool, str]:
    """
    Verifica si el anexo esperado ya tiene entregable.

    Precedencia: ``source_doc_id`` (artefacto o fila de cobertura) > nombre (solo legacy).
    """
    doc_id = str(expected.get("source_doc_id") or "").strip()

    if doc_id:
        for art in generated:
            art_ids = {
                str(art.get("source_doc_id") or "").strip(),
                str(art.get("delivered_source_doc_id") or "").strip(),
            }
            if doc_id in art_ids:
                return True, "generated_source_doc_id"

        cov = coverage_by_doc_id.get(doc_id)
        if cov and str(cov.get("estado_cobertura") or "") == "generado":
            return True, "coverage_catalog_doc_id"
        if cov and cov.get("archivo_entregado"):
            return True, "coverage_catalog_entregado"

        return False, ""

    source = str(expected.get("source_filename") or "").strip()
    if not source:
        return False, ""

    for art in generated:
        for key in ("source_filename", "nombre", "ruta"):
            candidate = str(art.get(key) or "").strip()
            if candidate and _sources_match_filename(source, candidate):
                return True, "filename_fallback"

    for row in coverage_by_doc_id.values():
        if str(row.get("estado_cobertura") or "") != "generado":
            continue
        delivered = str(row.get("archivo_entregado") or row.get("source_filename") or "")
        if delivered and _sources_match_filename(source, delivered):
            return True, "coverage_filename_fallback"

    return False, ""


def _detect_missing_economic_annexes(
    session_state: Dict[str, Any],
    coverage: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Detecta plantillas económicas ingestadas sin entregable generado (Ítem D.23).

    Universal: ``source_doc_id`` + rol de catálogo; sin ramas por nombre ZA/ZB.
    """
    expected = _collect_expected_economic_annexes(session_state)
    if len(expected) < 2:
        return []

    generated = _collect_generated_economic_artifacts(session_state)
    coverage_by_doc_id = _coverage_index_by_doc_id(coverage)

    if not generated and not any(
        str(r.get("estado_cobertura") or "") == "generado" for r in coverage_by_doc_id.values()
    ):
        return [
            {
                "source": str(exp.get("source_filename") or ""),
                "source_doc_id": exp.get("source_doc_id"),
                "document_role": str(exp.get("document_role") or ""),
                "template_kind": str(exp.get("template_kind") or ""),
                "reason": "sin_entregable_economico",
                "match_method": None,
            }
            for exp in expected
        ]

    missing: List[Dict[str, str]] = []
    for exp in expected:
        matched, method = _expected_annex_has_delivery(exp, generated, coverage_by_doc_id)
        if matched:
            continue
        missing.append(
            {
                "source": str(exp.get("source_filename") or ""),
                "source_doc_id": exp.get("source_doc_id"),
                "document_role": str(exp.get("document_role") or ""),
                "template_kind": str(exp.get("template_kind") or ""),
                "reason": "plantilla_ingestada_sin_generar",
                "match_method": method or None,
            }
        )
    return missing


def evaluate_economic_coverage_before_final_ok(
    session_state: Dict[str, Any],
    session_id: str,
    *,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retorna dict bloqueante si faltan precios estructurados o plantillas económicas en entrega.
    """
    line_items = list(session_state.get("session_line_items") or [])
    inputs = session_state.get("economic_user_inputs") or {}
    slots = build_structured_price_slots(line_items, inputs)
    missing_prices = [s for s in slots if s.get("captured_price") is None]
    if missing_prices:
        return {
            "code": "STRUCTURED_PRICES_PENDING",
            "message": (
                f"Faltan **{len(missing_prices)}** precio(s) en anexos económicos estructurados "
                "antes de cerrar el expediente."
            ),
            "missing_price_count": len(missing_prices),
            "missing_slots": [
                {
                    "field": s.get("field"),
                    "label": s.get("label"),
                    "source_name": s.get("source_name"),
                }
                for s in missing_prices[:20]
            ],
        }

    docs = documents if documents is not None else list(session_state.get("documents") or [])
    coverage: Optional[Dict[str, Any]] = None
    try:
        coverage = build_delivery_coverage_report(session_id, session_state, docs)
    except Exception:
        coverage = None

    if isinstance(coverage, dict):
        pending_templates: List[str] = []
        for row in _economic_catalog_rows(coverage):
            estado = str(row.get("estado_cobertura") or "")
            if estado == "pendiente_generar":
                pending_templates.append(str(row.get("source_filename") or "plantilla"))

        if pending_templates:
            return {
                "code": "ECONOMIC_TEMPLATE_NOT_GENERATED",
                "message": (
                    f"Faltan **{len(pending_templates)}** plantilla(s) económica(s) en el paquete validado."
                ),
                "pending_templates": pending_templates[:15],
            }

    missing_annexes = _detect_missing_economic_annexes(session_state, coverage)
    if missing_annexes:
        labels = ", ".join(
            f"**{(m.get('source') or '')[:48]}**" for m in missing_annexes[:5]
        )
        extra = f" … (+{len(missing_annexes) - 5} más)" if len(missing_annexes) > 5 else ""
        return {
            "code": "ECONOMIC_ANNEX_IMBALANCE",
            "message": (
                f"Detecté **{len(missing_annexes)}** anexo(s) económico(s) ingestado(s) "
                f"sin propuesta generada: {labels}{extra}. "
                "Completa la matriz y genera la propuesta económica antes de cerrar."
            ),
            "missing_annexes": missing_annexes[:15],
            "match_policy": "source_doc_id_then_catalog_then_filename_legacy",
        }
    return None
