from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.contracts.mini_dictamen_anexos import (
    ClarificationTicket,
    ClarificationTicketStatus,
    MiniDictamenAnexoItem,
    MiniDictamenAnexos,
    MiniDictamenCoverageStatus,
    MiniDictamenDeliveryAction,
    MiniDictamenSeverity,
    MiniDictamenSourceStatus,
    MiniDictamenSummary,
)
from app.services.delivery_coverage_report import (
    _extract_compliance_master,
    build_delivery_coverage_report,
)
from app.services.session_template_catalog import (
    build_session_template_catalog,
    normalize_filename_key,
)

SCHEMA_VERSION = "1.0.0"


def _norm(value: Any) -> str:
    return normalize_filename_key(str(value or ""))


def _token_overlap(a: str, b: str) -> float:
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _extract_inventory_items(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = session_state.get("document_inventory")
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return [it for it in raw.get("items") or [] if isinstance(it, dict)]
    return []


def _slug_ticket_id(canonical_id: str) -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", str(canonical_id or "").lower()).strip("_")
    return f"clar_{token}" if token else "clar_unknown"


def _iter_compliance_items(compliance: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for bucket in ("administrativo", "tecnico", "formatos"):
        for item in compliance.get(bucket) or []:
            if isinstance(item, dict):
                yield bucket, item


def _pick_best_match(
    target_name: str,
    candidates: Iterable[Dict[str, Any]],
    *,
    candidate_name_key: str,
    min_score: float = 0.35,
) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for cand in candidates:
        name = str(cand.get(candidate_name_key) or "")
        score = _token_overlap(target_name, name)
        if name and (
            name.lower() in target_name.lower() or target_name.lower() in name.lower()
        ):
            score = max(score, 0.9)
        if score >= min_score and score > best_score:
            best_score = score
            best = {**cand, "_match_score": round(score, 3)}
    return best


def _inventory_expects_official_template(
    inventory_item: Optional[Dict[str, Any]],
    compliance_item: Optional[Dict[str, Any]],
    catalog_item: Optional[Dict[str, Any]],
) -> bool:
    if catalog_item and str(catalog_item.get("document_class") or "") == "plantilla_oferta":
        return True
    if compliance_item and str(compliance_item.get("archivo_fuente") or "").strip():
        return True
    blob = " ".join(
        [
            str((inventory_item or {}).get("description") or ""),
            str((inventory_item or {}).get("generator_hint") or ""),
            str((compliance_item or {}).get("nombre") or ""),
            str((compliance_item or {}).get("descripcion") or ""),
        ]
    )
    return bool(
        re.search(
            r"(?i)\b(anexo|forma|formato|carta|constancia|cedula|c[eé]dula|"
            r"relaci[oó]n|manifiesto|ap[eé]ndice|apendice|propuesta)\b",
            blob,
        )
    )


def _is_cross_tender_pending_issue(session_state: Dict[str, Any], label: str) -> bool:
    needle = _norm(label)
    if not needle:
        return False
    pending = list(session_state.get("pending_questions") or [])
    for q in pending:
        if not isinstance(q, dict):
            continue
        if str(q.get("type") or "") != "template_source_cross_tender_blocking":
            continue
        if needle in _norm(q.get("label")) or needle in _norm(q.get("document_hint")):
            return True
        for item in q.get("blocking_items") or []:
            if not isinstance(item, dict):
                continue
            if needle in _norm(item.get("nombre")) or needle in _norm(item.get("source_filename")):
                return True
    return False


def _clarification_error_type(
    *,
    source_status: MiniDictamenSourceStatus,
    official_template_expected: bool,
    has_catalog_item: bool,
) -> Optional[str]:
    if source_status == MiniDictamenSourceStatus.CROSS_TENDER:
        return "cross_tender_template_source"
    if source_status == MiniDictamenSourceStatus.REFERENCE_ONLY:
        return "annex_reference_without_editable_source"
    if source_status == MiniDictamenSourceStatus.MISSING and official_template_expected:
        return "required_annex_not_published" if not has_catalog_item else "missing_official_template"
    return None


def _supports_controlled_generation(
    inventory_item: Optional[Dict[str, Any]],
    compliance_item: Optional[Dict[str, Any]],
    catalog_item: Optional[Dict[str, Any]],
) -> bool:
    """Detecta anexos que pueden generarse desde el requisito aunque no exista plantilla editable."""
    comp_action = str((compliance_item or {}).get("tipo_accion") or "").lower()
    if comp_action in {"generar", "requiere_datos_licitante"}:
        return True

    cat_action = str((catalog_item or {}).get("accion_recomendada") or "").lower()
    cat_class = str((catalog_item or {}).get("document_class") or "").lower()
    if cat_action == "presentar_fisico" or cat_class in {"evidencia_visita", "credencial_empresa"}:
        return False

    display_name = str((inventory_item or {}).get("display_name") or "")
    generator_hint = str((inventory_item or {}).get("generator_hint") or "")
    blob = " ".join(
        [
            str((inventory_item or {}).get("description") or ""),
            (
                generator_hint
                if _norm(generator_hint) and _norm(generator_hint) != _norm(display_name)
                else ""
            ),
            str((compliance_item or {}).get("nombre") or ""),
            str((compliance_item or {}).get("descripcion") or ""),
        ]
    )
    if not blob.strip():
        return False

    if re.search(
        r"(?i)\b(visita|instalaciones|constancia\s+de\s+visita|original|evidencia|credencial)\b",
        blob,
    ):
        return False

    return bool(
        re.search(
            r"(?i)\b("
            r"hoja\s+membretada|rubricad[oa]|firmad[oa]|curr[ií]culum|curriculum|"
            r"relaci[oó]n\s+de\s+principales\s+clientes|anexo\s+t[eé]cnico|"
            r"propuesta|carta|declaraci[oó]n|manifiesto|formato|cedula|c[eé]dula"
            r")\b",
            blob,
        )
    )


def _clarification_question(display_name: str, reason: str) -> str:
    return (
        f"Necesito aclarar con la convocante el documento **{display_name}**. "
        f"Motivo detectado: {reason}. ¿Deseas prepararlo como punto para la junta de aclaraciones?"
    )


def _ticket_priority(severity: MiniDictamenSeverity) -> MiniDictamenSeverity:
    return MiniDictamenSeverity.BLOCKING if severity == MiniDictamenSeverity.BLOCKING else MiniDictamenSeverity.WARN


def _merge_existing_tickets(
    current_items: List[MiniDictamenAnexoItem],
    existing_raw: List[Dict[str, Any]],
) -> List[ClarificationTicket]:
    existing: Dict[str, ClarificationTicket] = {}
    for raw in existing_raw or []:
        if not isinstance(raw, dict):
            continue
        try:
            tk = ClarificationTicket.model_validate(raw)
        except Exception:
            continue
        existing[tk.ticket_id] = tk

    tickets: List[ClarificationTicket] = []
    active_ids = set()
    now = datetime.now(timezone.utc)
    for item in current_items:
        if not item.clarification_candidate:
            continue
        ticket_id = _slug_ticket_id(item.canonical_id)
        active_ids.add(ticket_id)
        prev = existing.get(ticket_id)
        status = prev.status if prev else ClarificationTicketStatus.OPEN
        if status in (
            ClarificationTicketStatus.WAIVED,
            ClarificationTicketStatus.ANSWERED,
            ClarificationTicketStatus.RESOLVED,
        ):
            item.clarification_candidate = False
            if item.coverage_status == MiniDictamenCoverageStatus.BLOCKED:
                item.coverage_status = MiniDictamenCoverageStatus.PENDING
            if item.severity == MiniDictamenSeverity.BLOCKING:
                item.severity = MiniDictamenSeverity.WARN
        ticket = ClarificationTicket(
            ticket_id=ticket_id,
            canonical_id=item.canonical_id,
            display_name=item.display_name,
            status=status,
            priority=_ticket_priority(item.severity),
            question=_clarification_question(
                item.display_name,
                item.clarification_reason or "falta o invalidez de la plantilla oficial",
            ),
            reason=item.clarification_reason or "clarification_required",
            evidence_snippet=" | ".join(item.notes[:2]) or None,
            source_filename=item.source_filename,
            source_status=item.source_status,
            resolution_note=prev.resolution_note if prev else None,
            resolution_source=prev.resolution_source if prev else None,
            created_at=prev.created_at if prev else now,
            updated_at=now,
            provenance_ui=item.provenance_ui,
        )
        tickets.append(ticket)

    for ticket_id, prev in existing.items():
        if ticket_id in active_ids:
            continue
        if prev.status in (
            ClarificationTicketStatus.WAIVED,
            ClarificationTicketStatus.RESOLVED,
        ):
            tickets.append(prev)
            continue
        prev.status = ClarificationTicketStatus.RESOLVED
        prev.updated_at = now
        if not prev.resolution_note:
            prev.resolution_note = "Revalidado automáticamente; el gap ya no está activo."
        tickets.append(prev)

    tickets.sort(key=lambda t: (t.status.value, t.ticket_id))
    return tickets


def _pending_questions_from_tickets(tickets: List[ClarificationTicket]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ticket in tickets:
        if ticket.status not in (
            ClarificationTicketStatus.OPEN,
            ClarificationTicketStatus.READY_FOR_JUNTA,
        ):
            continue
        out.append(
            {
                "field": f"clarification_tickets.{ticket.ticket_id}",
                "label": f"Aclarar anexo: {ticket.display_name}",
                "question": ticket.question,
                "document_hint": ticket.reason,
                "type": "clarification_ticket",
                "ticket_id": ticket.ticket_id,
                "canonical_id": ticket.canonical_id,
                "blocking_items": [
                    {
                        "nombre": ticket.display_name,
                        "source_filename": ticket.source_filename,
                        "error_type": ticket.reason,
                    }
                ],
            }
        )
    return out


def _summary(items: List[MiniDictamenAnexoItem]) -> MiniDictamenSummary:
    return MiniDictamenSummary(
        total_items=len(items),
        required_by_bases=sum(1 for it in items if it.required_by_bases),
        official_template_expected=sum(1 for it in items if it.official_template_expected),
        official_template_present=sum(1 for it in items if it.official_template_present),
        coverage_covered=sum(1 for it in items if it.coverage_status == MiniDictamenCoverageStatus.COVERED),
        coverage_pending=sum(1 for it in items if it.coverage_status == MiniDictamenCoverageStatus.PENDING),
        coverage_blocked=sum(1 for it in items if it.coverage_status == MiniDictamenCoverageStatus.BLOCKED),
        clarification_candidates=sum(1 for it in items if it.clarification_candidate),
        blocking_items=sum(1 for it in items if it.severity == MiniDictamenSeverity.BLOCKING),
    )


def build_mini_dictamen_anexos(
    session_id: str,
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
    *,
    catalog: Optional[Dict[str, Any]] = None,
    coverage_report: Optional[Dict[str, Any]] = None,
) -> MiniDictamenAnexos:
    inventory_items = _extract_inventory_items(session_state)
    compliance = _extract_compliance_master(session_state)
    cat = catalog or session_state.get("session_template_catalog") or build_session_template_catalog(
        session_id, documents
    )
    coverage = coverage_report or session_state.get("delivery_coverage_report") or build_delivery_coverage_report(
        session_id, session_state, documents, catalog=cat
    )

    catalog_items = [it for it in (cat.get("items") or []) if isinstance(it, dict)]
    coverage_rows = [it for it in (coverage.get("rows") or []) if isinstance(it, dict)]
    compliance_items = []
    for idx, (bucket, item) in enumerate(_iter_compliance_items(compliance), start=1):
        compliance_items.append({**item, "_bucket": bucket, "_idx": idx})

    rows: List[MiniDictamenAnexoItem] = []
    used_catalog: set[str] = set()
    used_compliance: set[int] = set()
    used_coverage: set[str] = set()

    def _coverage_for_name(name: str, *, source_doc_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if source_doc_id:
            for row in coverage_rows:
                if str(row.get("source_doc_id") or "") == str(source_doc_id):
                    return row
        row = _pick_best_match(
            name,
            coverage_rows,
            candidate_name_key="source_filename",
            min_score=0.35,
        )
        if row:
            return row
        return _pick_best_match(
            name,
            coverage_rows,
            candidate_name_key="compliance_nombre",
            min_score=0.4,
        )

    for inv in inventory_items:
        display_name = str(inv.get("display_name") or inv.get("canonical_id") or "").strip()
        if not display_name:
            continue
        comp = _pick_best_match(display_name, compliance_items, candidate_name_key="nombre", min_score=0.4)
        if not comp and str(inv.get("generator_hint") or "").strip():
            comp = _pick_best_match(
                str(inv.get("generator_hint") or ""),
                compliance_items,
                candidate_name_key="archivo_fuente",
                min_score=0.35,
            )
        cat_item = _pick_best_match(display_name, catalog_items, candidate_name_key="source_filename", min_score=0.35)
        if not cat_item and comp and str(comp.get("archivo_fuente") or "").strip():
            cat_item = _pick_best_match(
                str(comp.get("archivo_fuente") or ""),
                catalog_items,
                candidate_name_key="source_filename",
                min_score=0.4,
            )
        cov_row = _coverage_for_name(display_name, source_doc_id=(cat_item or {}).get("doc_id"))
        if cat_item:
            used_catalog.add(str(cat_item.get("filename_key") or cat_item.get("source_filename") or ""))
        if comp:
            used_compliance.add(int(comp.get("_idx") or 0))
        if cov_row:
            used_coverage.add(str(cov_row.get("source_filename") or cov_row.get("compliance_nombre") or ""))

        official_template_expected = _inventory_expects_official_template(inv, comp, cat_item)
        official_template_present = bool(
            cat_item and str(cat_item.get("document_class") or "") == "plantilla_oferta"
        )
        can_generate_controlled = _supports_controlled_generation(inv, comp, cat_item)
        cross_tender = False
        if cat_item:
            cross_tender = _is_cross_tender_pending_issue(
                session_state, str(cat_item.get("source_filename") or display_name)
            )

        if cross_tender:
            source_status = MiniDictamenSourceStatus.CROSS_TENDER
        elif official_template_expected and not cat_item:
            source_status = MiniDictamenSourceStatus.MISSING
        elif official_template_expected and cat_item and not official_template_present:
            source_status = MiniDictamenSourceStatus.REFERENCE_ONLY
        elif official_template_present:
            source_status = MiniDictamenSourceStatus.VALID
        elif official_template_expected:
            source_status = MiniDictamenSourceStatus.AMBIGUOUS
        else:
            source_status = MiniDictamenSourceStatus.NOT_EXPECTED

        if str((comp or {}).get("tipo_accion") or "").lower() == "presentar_fisico":
            delivery_action = MiniDictamenDeliveryAction.PRESENTAR_FISICO
        elif cat_item and str(cat_item.get("accion_recomendada") or "") == "presentar_fisico":
            delivery_action = MiniDictamenDeliveryAction.PRESENTAR_FISICO
        elif source_status == MiniDictamenSourceStatus.VALID and official_template_present:
            delivery_action = MiniDictamenDeliveryAction.MIRROR
        elif can_generate_controlled and source_status != MiniDictamenSourceStatus.CROSS_TENDER:
            delivery_action = MiniDictamenDeliveryAction.GENERATE_CONTROLLED
        elif source_status in (
            MiniDictamenSourceStatus.CROSS_TENDER,
            MiniDictamenSourceStatus.MISSING,
            MiniDictamenSourceStatus.REFERENCE_ONLY,
        ) and official_template_expected:
            delivery_action = MiniDictamenDeliveryAction.CLARIFICATION_REQUIRED
        else:
            delivery_action = MiniDictamenDeliveryAction.GENERATE_CONTROLLED

        if delivery_action == MiniDictamenDeliveryAction.PRESENTAR_FISICO:
            coverage_status = MiniDictamenCoverageStatus.PENDING
        elif cov_row and str(cov_row.get("estado_cobertura") or "") == "generado":
            coverage_status = MiniDictamenCoverageStatus.COVERED
        elif delivery_action == MiniDictamenDeliveryAction.CLARIFICATION_REQUIRED:
            coverage_status = MiniDictamenCoverageStatus.BLOCKED
        else:
            coverage_status = MiniDictamenCoverageStatus.PENDING

        blocking_error = _clarification_error_type(
            source_status=source_status,
            official_template_expected=official_template_expected,
            has_catalog_item=bool(cat_item),
        )
        clarification_candidate = bool(
            delivery_action == MiniDictamenDeliveryAction.CLARIFICATION_REQUIRED and blocking_error
        )

        notes: List[str] = []
        if inv.get("description"):
            notes.append(str(inv.get("description")))
        if comp and comp.get("archivo_fuente"):
            notes.append(f"Compliance cita fuente: {comp.get('archivo_fuente')}")
        if cov_row and cov_row.get("causa"):
            notes.append(str(cov_row.get("causa")))

        item = MiniDictamenAnexoItem(
            canonical_id=str(inv.get("canonical_id") or display_name),
            display_name=display_name,
            category=str(inv.get("category") or (comp or {}).get("_bucket") or "administrativo"),
            required_by_bases=True,
            official_template_expected=official_template_expected,
            official_template_present=official_template_present,
            source_status=source_status,
            delivery_action=delivery_action,
            coverage_status=coverage_status,
            severity=(
                MiniDictamenSeverity.BLOCKING
                if coverage_status == MiniDictamenCoverageStatus.BLOCKED
                else MiniDictamenSeverity.WARN
                if coverage_status == MiniDictamenCoverageStatus.PENDING
                else MiniDictamenSeverity.INFO
            ),
            source_filename=str((cat_item or {}).get("source_filename") or (comp or {}).get("archivo_fuente") or "") or None,
            source_document_class=(cat_item or {}).get("document_class"),
            source_action_recommended=(cat_item or {}).get("accion_recomendada"),
            compliance_linked=comp is not None,
            compliance_bucket=(comp or {}).get("_bucket"),
            compliance_tipo_accion=(comp or {}).get("tipo_accion"),
            coverage_linked=cov_row is not None,
            coverage_match_method=(cov_row or {}).get("match_method"),
            delivered_file=(cov_row or {}).get("archivo_entregado"),
            clarification_candidate=clarification_candidate,
            clarification_reason=blocking_error,
            blocking_error_type=blocking_error,
            notes=notes[:4],
            provenance_ui={
                "source": "mini_dictamen_anexos",
                "reason": "inventory_catalog_compliance_coverage_fusion",
                "inventory_tier": inv.get("tier"),
                "catalog_match_score": (cat_item or {}).get("_match_score"),
                "compliance_match_score": (comp or {}).get("_match_score"),
            },
        )
        rows.append(item)

    for cat_item in catalog_items:
        cat_key = str(cat_item.get("filename_key") or cat_item.get("source_filename") or "")
        if cat_key in used_catalog:
            continue
        cov_row = _coverage_for_name(
            str(cat_item.get("source_filename") or ""),
            source_doc_id=cat_item.get("doc_id"),
        )
        if cov_row:
            used_coverage.add(str(cov_row.get("source_filename") or cov_row.get("compliance_nombre") or ""))
        action = str(cat_item.get("accion_recomendada") or "")
        delivery_action = (
            MiniDictamenDeliveryAction.PRESENTAR_FISICO
            if action == "presentar_fisico"
            else MiniDictamenDeliveryAction.MIRROR
            if str(cat_item.get("document_class") or "") == "plantilla_oferta"
            else MiniDictamenDeliveryAction.NOT_APPLICABLE
        )
        coverage_status = (
            MiniDictamenCoverageStatus.COVERED
            if cov_row and str(cov_row.get("estado_cobertura") or "") == "generado"
            else MiniDictamenCoverageStatus.PENDING
            if delivery_action != MiniDictamenDeliveryAction.NOT_APPLICABLE
            else MiniDictamenCoverageStatus.NOT_APPLICABLE
        )
        rows.append(
            MiniDictamenAnexoItem(
                canonical_id=f"catalog_{cat_key or len(rows)}",
                display_name=str(cat_item.get("source_filename") or "Documento catalogado"),
                category=str(cat_item.get("sobre_inferido") or "administrativo"),
                required_by_bases=False,
                official_template_expected=str(cat_item.get("document_class") or "") == "plantilla_oferta",
                official_template_present=str(cat_item.get("document_class") or "") == "plantilla_oferta",
                source_status=(
                    MiniDictamenSourceStatus.VALID
                    if str(cat_item.get("document_class") or "") == "plantilla_oferta"
                    else MiniDictamenSourceStatus.REFERENCE_ONLY
                ),
                delivery_action=delivery_action,
                coverage_status=coverage_status,
                severity=(
                    MiniDictamenSeverity.WARN
                    if coverage_status == MiniDictamenCoverageStatus.PENDING
                    else MiniDictamenSeverity.INFO
                ),
                source_filename=str(cat_item.get("source_filename") or "") or None,
                source_document_class=cat_item.get("document_class"),
                source_action_recommended=cat_item.get("accion_recomendada"),
                coverage_linked=cov_row is not None,
                coverage_match_method=(cov_row or {}).get("match_method"),
                delivered_file=(cov_row or {}).get("archivo_entregado"),
                notes=["Documento suministrado por la convocante, fuera del universo canónico detectado en bases."],
                provenance_ui={
                    "source": "session_template_catalog",
                    "reason": "catalog_only_item",
                },
            )
        )

    for comp in compliance_items:
        comp_idx = int(comp.get("_idx") or 0)
        if comp_idx in used_compliance:
            continue
        nombre = str(comp.get("nombre") or comp.get("archivo_fuente") or "").strip()
        if not nombre:
            continue
        cov_row = _coverage_for_name(nombre)
        action = str(comp.get("tipo_accion") or "").lower()
        expected_template = bool(
            action == "generar"
            and re.search(r"(?i)\b(anexo|formato|carta|cedula|c[eé]dula|manifiesto)\b", nombre)
        )
        if _is_cross_tender_pending_issue(session_state, str(comp.get("archivo_fuente") or nombre)):
            source_status = MiniDictamenSourceStatus.CROSS_TENDER
        elif str(comp.get("archivo_fuente") or "").strip():
            source_status = MiniDictamenSourceStatus.VALID
        elif expected_template:
            source_status = MiniDictamenSourceStatus.MISSING
        else:
            source_status = MiniDictamenSourceStatus.NOT_EXPECTED
        delivery_action = (
            MiniDictamenDeliveryAction.PRESENTAR_FISICO
            if action == "presentar_fisico"
            else MiniDictamenDeliveryAction.CLARIFICATION_REQUIRED
            if expected_template and source_status != MiniDictamenSourceStatus.VALID
            else MiniDictamenDeliveryAction.GENERATE_CONTROLLED
            if action in {"generar", "requiere_datos_licitante"}
            else MiniDictamenDeliveryAction.NOT_APPLICABLE
        )
        coverage_status = (
            MiniDictamenCoverageStatus.COVERED
            if cov_row and str(cov_row.get("estado_cobertura") or "") == "generado"
            else MiniDictamenCoverageStatus.BLOCKED
            if delivery_action == MiniDictamenDeliveryAction.CLARIFICATION_REQUIRED
            else MiniDictamenCoverageStatus.PENDING
            if delivery_action != MiniDictamenDeliveryAction.NOT_APPLICABLE
            else MiniDictamenCoverageStatus.NOT_APPLICABLE
        )
        error_type = _clarification_error_type(
            source_status=source_status,
            official_template_expected=expected_template,
            has_catalog_item=False,
        )
        rows.append(
            MiniDictamenAnexoItem(
                canonical_id=f"compliance_{comp.get('_bucket')}_{comp_idx}",
                display_name=nombre,
                category=str(comp.get("_bucket") or "administrativo"),
                required_by_bases=True,
                official_template_expected=expected_template,
                official_template_present=bool(comp.get("archivo_fuente")),
                source_status=source_status,
                delivery_action=delivery_action,
                coverage_status=coverage_status,
                severity=(
                    MiniDictamenSeverity.BLOCKING
                    if coverage_status == MiniDictamenCoverageStatus.BLOCKED
                    else MiniDictamenSeverity.WARN
                    if coverage_status == MiniDictamenCoverageStatus.PENDING
                    else MiniDictamenSeverity.INFO
                ),
                source_filename=str(comp.get("archivo_fuente") or "") or None,
                compliance_linked=True,
                compliance_bucket=comp.get("_bucket"),
                compliance_tipo_accion=comp.get("tipo_accion"),
                coverage_linked=cov_row is not None,
                coverage_match_method=(cov_row or {}).get("match_method"),
                delivered_file=(cov_row or {}).get("archivo_entregado"),
                clarification_candidate=bool(error_type and coverage_status == MiniDictamenCoverageStatus.BLOCKED),
                clarification_reason=error_type,
                blocking_error_type=error_type,
                notes=[str(comp.get("descripcion") or "Ítem proveniente de compliance")],
                provenance_ui={
                    "source": "compliance_master_list",
                    "reason": "compliance_only_item",
                },
            )
        )

    rows.sort(key=lambda it: (-int(it.required_by_bases), it.category, it.display_name.lower()))
    tickets = _merge_existing_tickets(
        rows, list(session_state.get("clarification_tickets") or [])
    )
    return MiniDictamenAnexos(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        summary=_summary(rows),
        items=rows,
        clarification_tickets=tickets,
    )


def merge_clarification_pending_questions(
    session_state: Dict[str, Any],
    tickets: List[ClarificationTicket],
) -> List[Dict[str, Any]]:
    preserved = [
        q
        for q in list(session_state.get("pending_questions") or [])
        if isinstance(q, dict)
        and str(q.get("type") or "") not in {"clarification_ticket", "mini_dictamen_blocking"}
    ]
    return preserved + _pending_questions_from_tickets(tickets)


def get_blocking_annex_rows_for_stage(
    session_state: Dict[str, Any],
    stage: str,
) -> List[Dict[str, Any]]:
    raw = session_state.get("mini_dictamen_anexos")
    if not isinstance(raw, dict):
        return []
    items = [it for it in raw.get("items") or [] if isinstance(it, dict)]
    if stage == "packager":
        allowed = None
    elif stage == "technical":
        allowed = {"technical", "tecnico"}
    elif stage == "formats":
        allowed = {"administrativo", "legal_administrative", "formatos"}
    elif stage == "economic_writer":
        allowed = {"economic", "economico"}
    else:
        allowed = None

    out: List[Dict[str, Any]] = []
    for item in items:
        if str(item.get("severity") or "") != MiniDictamenSeverity.BLOCKING.value:
            continue
        if str(item.get("coverage_status") or "") != MiniDictamenCoverageStatus.BLOCKED.value:
            continue
        if allowed is not None and str(item.get("category") or "") not in allowed:
            continue
        out.append(item)
    return out


def build_stage_blocking_questions(
    stage: str,
    blocking_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    label_map = {
        "technical": "plantilla técnica",
        "formats": "plantilla administrativa",
        "economic_writer": "plantilla económica",
        "packager": "anexo obligatorio",
    }
    kind = label_map.get(stage, "anexo")
    out: List[Dict[str, Any]] = []
    for row in blocking_rows:
        out.append(
            {
                "field": f"mini_dictamen_anexos.{row.get('canonical_id')}",
                "label": f"Validar {kind}: {row.get('display_name')}",
                "question": (
                    f"No puedo continuar porque el {kind} **{row.get('display_name')}** "
                    "requiere aclaración, fuente válida o resolución manual."
                ),
                "document_hint": row.get("clarification_reason") or row.get("blocking_error_type"),
                "type": "mini_dictamen_blocking",
                "blocking_items": [row],
            }
        )
    return out


async def build_and_persist_mini_dictamen(memory: Any, session_id: str) -> MiniDictamenAnexos:
    session_state = await memory.get_session(session_id) or {}
    try:
        documents = await memory.get_documents(session_id)
    except Exception:
        documents = []
    catalog = session_state.get("session_template_catalog")
    if not isinstance(catalog, dict):
        catalog = build_session_template_catalog(session_id, documents)
    coverage = session_state.get("delivery_coverage_report")
    if not isinstance(coverage, dict):
        coverage = build_delivery_coverage_report(
            session_id, session_state, documents, catalog=catalog
        )

    mini = build_mini_dictamen_anexos(
        session_id,
        session_state,
        documents,
        catalog=catalog,
        coverage_report=coverage,
    )
    session_state["session_template_catalog"] = catalog
    session_state["delivery_coverage_report"] = coverage
    session_state["mini_dictamen_anexos"] = mini.model_dump(mode="json")
    session_state["clarification_tickets"] = [
        t.model_dump(mode="json") for t in mini.clarification_tickets
    ]
    session_state["pending_questions"] = merge_clarification_pending_questions(
        session_state, mini.clarification_tickets
    )
    await memory.save_session(session_id, dict(session_state))
    try:
        from app.services.junta_aclaraciones_questions_service import (
            build_and_persist_junta_aclaraciones_questions,
        )

        await build_and_persist_junta_aclaraciones_questions(
            memory, session_id, session_state=session_state
        )
    except Exception as exc:
        logger.warning(
            "junta_questions_after_mini_dictamen_skipped",
            session_id=session_id,
            error=str(exc)[:160],
        )
    return mini


async def resolve_clarification_ticket(
    memory: Any,
    session_id: str,
    ticket_id: str,
    *,
    status: str,
    resolution_note: str = "",
    resolution_source: str = "manual",
) -> ClarificationTicket:
    session_state = await memory.get_session(session_id) or {}
    tickets = list(session_state.get("clarification_tickets") or [])
    matched = False
    now = datetime.now(timezone.utc).isoformat()
    for raw in tickets:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("ticket_id") or "") != ticket_id:
            continue
        raw["status"] = status
        raw["resolution_note"] = resolution_note or raw.get("resolution_note")
        raw["resolution_source"] = resolution_source
        raw["updated_at"] = now
        matched = True
        break
    if not matched:
        raise ValueError(f"No existe clarification_ticket={ticket_id}")
    session_state["clarification_tickets"] = tickets
    await memory.save_session(session_id, dict(session_state))
    mini = await build_and_persist_mini_dictamen(memory, session_id)
    for ticket in mini.clarification_tickets:
        if ticket.ticket_id == ticket_id:
            return ticket
    raise ValueError(f"No fue posible rehidratar clarification_ticket={ticket_id}")


async def revalidate_mini_dictamen_after_acta(
    memory: Any,
    session_id: str,
    acta_text: str,
) -> MiniDictamenAnexos:
    session_state = await memory.get_session(session_id) or {}
    raw_tickets = list(session_state.get("clarification_tickets") or [])
    if raw_tickets and acta_text:
        blob = _norm(acta_text)
        now = datetime.now(timezone.utc).isoformat()
        for raw in raw_tickets:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("status") or "") not in {"open", "ready_for_junta"}:
                continue
            terms = [
                str(raw.get("display_name") or ""),
                str(raw.get("source_filename") or ""),
            ]
            if any(term and (_norm(term) in blob or _token_overlap(blob, term) >= 0.45) for term in terms):
                raw["status"] = ClarificationTicketStatus.ANSWERED.value
                raw["resolution_source"] = "post_clarification_acta"
                raw["resolution_note"] = (
                    "El acta de aclaraciones menciona el anexo o la plantilla; "
                    "se requiere revalidación operativa posterior."
                )
                raw["updated_at"] = now
        session_state["clarification_tickets"] = raw_tickets
        await memory.save_session(session_id, dict(session_state))
    return await build_and_persist_mini_dictamen(memory, session_id)
