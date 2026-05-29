from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.document_deliverable_filter import (
    normalize_deliverable_key,
    should_show_deliverable_in_ui,
)

_VALID_ACTIONS = {"generar", "presentar_fisico", "informativo"}
_NO_APLICA_RE = re.compile(r"\b(no\s*aplica|no\s*aplicable|n/?a)\b", re.IGNORECASE)
_NOISE_RE = re.compile(
    r"(?i)\b("
    r"normas?\s+de\s+conducta|aviso\s+de\s+privacidad|glosario|"
    r"consideraciones\s+generales|lineamientos?\s+generales|"
    r"acto\s+de\s+apertura|junta\s+de\s+aclaraciones|calendario|cronograma|"
    r"criterios?\s+de\s+evaluaci[oó]n|procedimiento\s+de\s+fallo"
    r")\b"
)
_DELIVERABLE_HINTS_RE = re.compile(
    r"(?i)\b("
    r"anexo|formato|carta|manifiesto|propuesta|fianza|garant[ií]a|"
    r"acta\s+constitutiva|opini[oó]n\s+de\s+cumplimiento|sat|"
    r"constancia|certificad[oa]|curr[ií]culum|metodolog[ií]a|"
    r"programa\s+de\s+trabajo|padr[oó]n\s+de\s+proveedores"
    r")\b"
)


def _should_skip_noise_item(name: str, description: str, snippet: str, action: str) -> bool:
    """Descarta ruido documental obvio sin evidencia de entregable.

    Regla conservadora:
    - Si detecta patrón normativo/informativo y no hay hints de entregable, se excluye.
    - Si tipo_accion ya viene como generar/presentar_fisico, no se excluye por ruido.
    """
    if action in {"generar", "presentar_fisico"}:
        return False
    text = " ".join((name, description, snippet)).strip()
    if not text:
        return True
    looks_noise = bool(_NOISE_RE.search(text))
    has_deliverable_hint = bool(_DELIVERABLE_HINTS_RE.search(text))
    return looks_noise and not has_deliverable_hint


def build_candidate_document_list(
    compliance_master_list: Dict[str, Any],
    require_human_confirmation: bool = True,
    low_conf_threshold: float = 0.7,
) -> Dict[str, Any]:
    """Construye una lista candidata rápida de documentos desde compliance.

    Args:
        compliance_master_list: Salida de compliance con categorías administrativo/tecnico/formatos.
        require_human_confirmation: Si true, siempre marcar needs_human_confirmation.
        low_conf_threshold: Umbral para marcar elementos con confianza baja.

    Returns:
        Contrato fast-track con candidate_document_list, candidate_summary y contadores.
    """
    categories = ("administrativo", "tecnico", "formatos")
    out: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    unresolved_count = 0
    low_conf_count = 0

    for category in categories:
        for item in compliance_master_list.get(category, []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("nombre") or item.get("descripcion") or "Documento sin nombre").strip()
            description = str(item.get("descripcion") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not should_show_deliverable_in_ui(
                name, description, snippet, str(item.get("tipo_accion") or "")
            ):
                continue
            dedup_key = normalize_deliverable_key(name, category)
            if dedup_key in seen_keys:
                continue
            text_for_na = " ".join((name, description, snippet)).strip()
            no_aplica = bool(_NO_APLICA_RE.search(text_for_na))

            action = str(item.get("tipo_accion") or "unknown").strip().lower()
            if action not in _VALID_ACTIONS:
                action = "unknown"
            final_action = "informativo" if no_aplica else action

            # FILTRO CRÍTICO: Si es puramente informativo, no es un candidato a entregable
            if final_action == "informativo":
                continue

            if _should_skip_noise_item(name, description, snippet, action=final_action):
                continue

            try:
                confidence = float(item.get("action_confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            if action == "unknown":
                # Fast-track: mantener propuesta visible pero marcar para validación humana.
                confidence = min(confidence, 0.35)

            unresolved = (action == "unknown") or (confidence < low_conf_threshold)
            if unresolved:
                unresolved_count += 1
            if confidence < low_conf_threshold:
                low_conf_count += 1

            seen_keys.add(dedup_key)
            out.append(
                {
                    "document_id": str(item.get("id") or f"{category[:2].upper()}-{len(out)+1:02d}"),
                    "nombre": name,
                    "categoria": category,
                    "tipo_accion_propuesto": final_action if final_action in _VALID_ACTIONS else "informativo",
                    "tipo_accion_final": final_action if final_action in _VALID_ACTIONS else "informativo",
                    "confidence": round(confidence, 4),
                    "no_aplica": no_aplica,
                    "evidence_snippet": snippet[:600],
                    "provenance_ui": {
                        "source": "auto_candidate",
                        "reason": "derived_from_compliance_master_list_filtered",
                    },
                }
            )

    summary = {"generar": 0, "presentar_fisico": 0, "informativo": 0, "no_aplica": 0}
    for d in out:
        action = str(d.get("tipo_accion_final") or "informativo")
        if action in summary:
            summary[action] += 1
        if bool(d.get("no_aplica")):
            summary["no_aplica"] += 1

    needs_confirmation = bool(require_human_confirmation or unresolved_count > 0)
    return {
        "candidate_document_list": out,
        "candidate_summary": summary,
        "needs_human_confirmation": needs_confirmation,
        "unresolved_count": unresolved_count,
        "low_confidence_count": low_conf_count,
    }


def merge_fast_track_actions_into_consolidated(
    consolidated: Dict[str, Any],
    fast_track: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Propaga ``tipo_accion_final`` del fast-track (compliance) a la salida CCC por nombre.

    Evita que anexos marcados como ``presentar_fisico`` aparezcan como ``generar`` tras fusionar.
    """
    if not isinstance(consolidated, dict) or not isinstance(fast_track, dict):
        return consolidated if isinstance(consolidated, dict) else {}

    action_by_key: Dict[str, str] = {}
    for doc in fast_track.get("candidate_document_list") or []:
        if not isinstance(doc, dict):
            continue
        name = str(doc.get("nombre") or "")
        action = str(
            doc.get("tipo_accion_final") or doc.get("tipo_accion_propuesto") or ""
        ).strip().lower()
        if action not in _VALID_ACTIONS:
            continue
        for cat in (str(doc.get("categoria") or ""), ""):
            action_by_key[normalize_deliverable_key(name, cat)] = action

    buckets = (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    )

    def _enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(item)
        nombre = str(out.get("nombre_canonico") or out.get("nombre") or "")
        matched_actions: List[str] = []
        for cat in ("administrativo", "tecnico", "formatos", ""):
            action = action_by_key.get(normalize_deliverable_key(nombre, cat))
            if action:
                matched_actions.append(action)
                break
        for ev in out.get("evidencia_original") or []:
            if not isinstance(ev, dict):
                continue
            ev_name = str(ev.get("nombre") or "")
            for cat in ("administrativo", "tecnico", "formatos", ""):
                action = action_by_key.get(normalize_deliverable_key(ev_name, cat))
                if action:
                    matched_actions.append(action)
                    break
        if matched_actions and all(a == "presentar_fisico" for a in matched_actions):
            action = "presentar_fisico"
        elif matched_actions:
            action = matched_actions[0]
        else:
            action = None
        if action:
            out["tipo"] = action
            out["tipo_accion_final"] = action
        return out

    result = dict(consolidated)
    for bucket in buckets:
        items = result.get(bucket)
        if isinstance(items, list):
            result[bucket] = [_enrich(it) for it in items if isinstance(it, dict)]
    return result


async def build_corporate_physical_panel_list(
    memory: Any,
    session_id: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Lista para el panel «Documentos detectados»: solo credenciales empresariales en físico.

    Fuentes (precedencia): compliance filtrado → CCC filtrado → requisitos numerados en bases (RAG).
    """
    from app.services.corporate_physical_enrichment_service import (
        extract_corporate_physical_from_bases_rag,
    )
    from app.services.document_deliverable_filter import (
        filter_corporate_physical_consolidated,
        filter_corporate_physical_from_compliance_list,
    )

    state = session_state if isinstance(session_state, dict) else await memory.get_session(session_id)
    if not isinstance(state, dict):
        return {"candidate_document_list": [], "_meta": {"filtered_corporate_physical_only": True, "total": 0}}

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add_rows(rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("nombre") or row.get("nombre_canonico") or "")
            key = normalize_deliverable_key(name, str(row.get("categoria") or ""))
            if not name or key in seen:
                continue
            seen.add(key)
            merged.append(row)

    cml = state.get("compliance_master_list")
    if isinstance(cml, dict):
        for cat in ("administrativo", "tecnico", "formatos"):
            for item in filter_corporate_physical_from_compliance_list(cml.get(cat) or [], cat):
                _add_rows(
                    [
                        {
                            "document_id": str(item.get("id") or f"corp-cml-{len(merged)+1:02d}"),
                            "nombre": str(item.get("nombre") or item.get("descripcion") or "Documento"),
                            "categoria": "expediente_empresarial",
                            "tipo_accion_propuesto": "presentar_fisico",
                            "tipo_accion_final": "presentar_fisico",
                            "confidence": float(item.get("action_confidence") or 0.78),
                            "evidence_snippet": str(item.get("snippet") or "")[:600],
                            "provenance_ui": {
                                "source": "compliance_master_list",
                                "reason": "corporate_physical_credential",
                            },
                        }
                    ]
                )

    consolidated = state.get("document_candidates_consolidated")
    if isinstance(consolidated, dict):
        filtered = filter_corporate_physical_consolidated(consolidated)
        _add_rows(filtered.get("candidate_document_list") or [])

    if len(merged) < 3:
        _add_rows(extract_corporate_physical_from_bases_rag(session_id))

    return {
        "candidate_document_list": merged,
        "_meta": {
            "filtered_corporate_physical_only": True,
            "total": len(merged),
        },
    }


async def ensure_session_document_candidates(
    memory: Any,
    session_id: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Garantiza candidatos de documentos en sesión a partir de ``compliance_master_list``.

    Si falta ``document_candidates_consolidated`` (p. ej. análisis previo al CCC o fallo
    silencioso), reconstruye fast-track + consolidado y persiste.
    """
    from app.config.settings import settings

    state = session_state if isinstance(session_state, dict) else await memory.get_session(session_id)
    if not isinstance(state, dict):
        return None

    existing = (
        state.get("document_candidates_consolidated")
        or state.get("document_candidates_final")
        or state.get("document_candidates_v1")
    )
    flat_source = state.get("document_candidates_v1") or state.get("document_candidates_final")
    if isinstance(existing, dict) and existing.get("sobre_1_tecnico") is not None:
        if isinstance(flat_source, dict) and flat_source.get("candidate_document_list"):
            merged = merge_fast_track_actions_into_consolidated(existing, flat_source)
            try:
                from app.services.document_deliverable_filter import (
                    filter_consolidated_document_candidates,
                )

                merged = filter_consolidated_document_candidates(merged)
            except Exception:
                pass
            await memory.save_session(
                session_id, {"document_candidates_consolidated": merged}
            )
            return merged
        return existing
    if isinstance(existing, dict) and existing.get("candidate_document_list"):
        return existing

    cml = state.get("compliance_master_list")
    if not isinstance(cml, dict) or not any(cml.get(z) for z in ("administrativo", "tecnico", "formatos")):
        return None

    fast_track = build_candidate_document_list(
        compliance_master_list=cml,
        require_human_confirmation=bool(settings.FAST_TRACK_REQUIRE_HUMAN_CONFIRM),
        low_conf_threshold=float(settings.FAST_TRACK_LOW_CONF_THRESHOLD),
    )

    consolidated: Dict[str, Any] = {}
    try:
        from app.services.compliance_consolidation_service import ComplianceConsolidator

        consolidated = await ComplianceConsolidator().consolidate(raw_items=cml, session_id=session_id)
    except Exception:
        consolidated = {}

    updates: Dict[str, Any] = {
        "document_candidates_v1": fast_track,
        "document_candidates_final": fast_track,
    }
    if isinstance(consolidated, dict) and consolidated.get("sobre_1_tecnico") is not None:
        consolidated = merge_fast_track_actions_into_consolidated(consolidated, fast_track)
        try:
            from app.services.document_deliverable_filter import (
                filter_consolidated_document_candidates,
            )

            consolidated = filter_consolidated_document_candidates(consolidated)
        except Exception:
            pass
        updates["document_candidates_consolidated"] = consolidated

    await memory.save_session(session_id, updates)
    return updates.get("document_candidates_consolidated") or fast_track
