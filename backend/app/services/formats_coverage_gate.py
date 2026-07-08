"""
Gates de completitud para formatos administrativos y entrega CompraNet.

Evita ``FINAL_OK`` / éxito en UI cuando faltan anexos «generar» materializados.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config.settings import settings


def count_panel_admin_generar(
    panel_payload: Dict[str, Any],
    *,
    exclude_obra_economic_envelope: bool = False,
) -> int:
    """
    Cuenta ítems «generar» que el agente Formats intenta fusionar desde el panel.

    Replica la lógica de ``FormatsAgent`` (excluye modelo de propuesta técnica).
    Con ``exclude_obra_economic_envelope``, omite E-1…E-5 (+ E-3E) materializados
    por ``EconomicWriter`` cuando hay desglose obra.
    """
    import re

    deferred_keys: set[str] = set()
    if exclude_obra_economic_envelope:
        from app.services.official_format_resolver import economic_envelope_dedupe_keys
        from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

        deferred_keys = set(economic_envelope_dedupe_keys())

    total = 0
    for bucket in (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    ):
        for row in panel_payload.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("tipo_accion_final") or row.get("tipo") or "") != "generar":
                continue
            nombre = str(row.get("nombre_canonico") or row.get("nombre") or "").strip()
            if not nombre:
                continue
            nombre_low = nombre.lower()
            if re.search(
                r"modelo.*propuesta\s+t[eé]cnica|propuesta\s+t[eé]cnica.*modelo",
                nombre_low,
            ):
                continue
            if deferred_keys:
                from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

                if pliego_format_dedupe_key(nombre) in deferred_keys:
                    continue
            total += 1
    return total


def count_obra_economic_envelope_deferred(panel_payload: Dict[str, Any]) -> int:
    """Ítems «generar» del panel que EconomicWriter materializa (obra|E*)."""
    full = count_panel_admin_generar(panel_payload, exclude_obra_economic_envelope=False)
    admin = count_panel_admin_generar(panel_payload, exclude_obra_economic_envelope=True)
    return max(0, full - admin)


def evaluate_formats_stage_completeness(
    *,
    generated_count: int,
    mirror_queue_size: int,
    llm_queue_size: int,
    generation_skipped: List[Dict[str, Any]],
    panel_expected: int,
    deferred_to_economic_count: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Bloquea cierre de la etapa ``formats`` si la materialización está muy por debajo
    de lo intentado o de lo esperado por el panel consolidado.
    """
    min_ratio = float(getattr(settings, "FORMATS_MIN_DELIVERABLE_RATIO", 0.85) or 0.85)
    deferred = max(0, int(deferred_to_economic_count or 0))
    raw_attempted = max(0, int(mirror_queue_size) + int(llm_queue_size))
    attempted = max(0, raw_attempted - deferred)
    expected = max(int(panel_expected or 0), raw_attempted) - deferred
    if expected < 3:
        return None

    threshold = max(1, int(expected * min_ratio))
    if generated_count >= threshold:
        return None

    pending_names = [
        str(s.get("nombre") or s.get("req_name") or "")
        for s in generation_skipped
        if isinstance(s, dict)
        and not s.get("deferred_to_economic_writer")
        and str(s.get("nombre") or s.get("req_name") or "").strip()
    ]

    return {
        "code": "FORMATS_INCOMPLETE_DELIVERY",
        "message": (
            f"Solo se materializaron **{generated_count}** de **{expected}** "
            f"formatos administrativos esperados (umbral mínimo: {threshold}). "
            f"Revisa los anexos omitidos y vuelve a generar."
        ),
        "generated_count": generated_count,
        "expected_count": expected,
        "threshold_count": threshold,
        "attempted_count": attempted,
        "panel_expected_count": int(panel_expected or 0),
        "deferred_to_economic_count": deferred,
        "skipped_count": len(generation_skipped),
        "skipped": generation_skipped[:25],
        "pending_names": pending_names[:15],
    }


def evaluate_delivery_completeness_before_final_ok(
    session_state: Dict[str, Any],
    session_id: str,
    *,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Gate universal antes de ``FINAL_OK``: plantillas de oferta vs paquete validado.
    """
    from app.services.delivery_coverage_report import build_delivery_coverage_report

    docs = documents if documents is not None else list(session_state.get("documents") or [])
    try:
        coverage = build_delivery_coverage_report(session_id, session_state, docs)
    except Exception:
        return None

    summary = coverage.get("summary") or {}
    esperadas = int(summary.get("esperadas_generar") or 0)
    generadas = int(summary.get("generadas") or 0)
    pendientes = int(summary.get("pendientes_generar") or 0)
    if esperadas < 3:
        return None

    min_ratio = float(getattr(settings, "DELIVERY_MIN_COVERAGE_RATIO", 0.85) or 0.85)
    ratio = generadas / esperadas if esperadas else 1.0
    if ratio >= min_ratio and pendientes == 0:
        return None
    if ratio >= min_ratio and pendientes <= max(0, int(esperadas * (1 - min_ratio))):
        return None

    pending_rows = [
        r
        for r in (coverage.get("rows") or [])
        if isinstance(r, dict)
        and r.get("estado_cobertura") == "pendiente_generar"
        and str(r.get("accion_recomendada") or "") == "generar"
    ]
    pending_names = [
        str(r.get("source_filename") or r.get("compliance_nombre") or "")
        for r in pending_rows[:15]
        if str(r.get("source_filename") or r.get("compliance_nombre") or "").strip()
    ]

    return {
        "code": "DELIVERY_COVERAGE_GAP",
        "message": (
            f"El expediente validado tiene **{generadas}** de **{esperadas}** "
            f"plantillas generadas ({round(ratio * 100, 1)} %). "
            f"Faltan **{pendientes}** antes de cerrar la entrega."
        ),
        "esperadas_generar": esperadas,
        "generadas": generadas,
        "pendientes_generar": pendientes,
        "cobertura_pct": summary.get("cobertura_generacion_pct"),
        "manifest_files_count": coverage.get("manifest_files_count"),
        "pending_templates": pending_names,
    }
