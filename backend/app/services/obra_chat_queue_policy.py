"""
Política de cola HITL para licitaciones de obra (LOPSRM / OBRA).

En obra pública la experiencia suele acreditarse con anexos documentales (T-2, T-B-2),
no con un escalar ``anos_experiencia`` en chat. Este módulo centraliza esa regla.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_OBRA_CATEGORIES = frozenset({"OBRA", "OBRA_PUBLICA", "OBRA_PUBLICA_ESTATAL", "CONSTRUCCION"})

_DOCUMENTARY_EXPERIENCE_RE = re.compile(
    r"(?i)\b("
    r"experiencia|experiencias|capacidad\s+t[eé]cnica|trabajos\s+similares|"
    r"contratos?\s+vigentes?|cartas?\s+de\s+referencia|recepci[oó]n\s+de\s+obra|"
    r"anexo\s+t[-\s]?2|t[-\s]?b[-\s]?2|formato\s+t[-\s]?b"
    r")\b"
)

_OBRA_DOCUMENTARY_PROFILE_FIELDS = frozenset(
    {
        "anos_experiencia",
        "anos_de_experiencia",
        "numero_empleados",
        "contratos_previos",
        "contratos_similares",
    }
)

_OBRA_CHAT_INFORMATIONAL_PROFILE_FIELDS = frozenset(
    {
        "anos_experiencia",
        "anos_de_experiencia",
        "numero_empleados",
        "web",
        "telefono",
        "email",
        "cedula_representante",
        "contratos_previos",
        "contratos_similares",
    }
)

_ECONOMIC_CHAT_TYPES = frozenset({"economic_price", "economic_validation_blocking"})
_BLOCKING_PROFILE_FIELDS = frozenset(
    {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
)


def session_tender_category(session_state: Optional[Dict[str, Any]]) -> str:
    triage = (session_state or {}).get("triage_context")
    if not isinstance(triage, dict):
        return ""
    return str(triage.get("tender_category") or "").strip().upper()


def is_obra_session(session_state: Optional[Dict[str, Any]]) -> bool:
    cat = session_tender_category(session_state)
    if cat in _OBRA_CATEGORIES:
        return True
    if "OBRA" in cat:
        return True
    name = str((session_state or {}).get("name") or "").upper()
    return "OBRA" in name or "CONSTRUCCI" in name


def _iter_compliance_names(session_state: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    cml = session_state.get("compliance_master_list")
    if isinstance(cml, dict):
        for cat in ("administrativo", "tecnico", "formatos"):
            for item in cml.get(cat) or []:
                if isinstance(item, dict):
                    names.append(str(item.get("nombre") or item.get("descripcion") or ""))
    panel = session_state.get("document_candidates_consolidated")
    if isinstance(panel, dict):
        for bucket in ("sobre_1_tecnico", "sobre_2_economico", "requisitos_legales", "otros_requisitos_criticos"):
            for item in panel.get(bucket) or []:
                if isinstance(item, dict):
                    names.append(
                        str(item.get("nombre_canonico") or item.get("nombre") or "")
                    )
    inv = session_state.get("document_inventory")
    if isinstance(inv, dict):
        for item in inv.get("items") or []:
            if isinstance(item, dict):
                names.append(str(item.get("display_name") or item.get("nombre") or ""))
    return [n for n in names if n.strip()]


def obra_requires_documentary_experience(session_state: Optional[Dict[str, Any]]) -> bool:
    """True si las bases/pliego exigen acreditar experiencia con anexos, no un número en chat."""
    if not isinstance(session_state, dict):
        return False
    blob = " ".join(_iter_compliance_names(session_state))
    if _DOCUMENTARY_EXPERIENCE_RE.search(blob):
        return True
    analysis = None
    for task in reversed(session_state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        if str(task.get("task") or "") != "stage_completed:analysis":
            continue
        payload = task.get("result") or {}
        analysis = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        break
    if isinstance(analysis, dict):
        st = analysis.get("solvencia_tecnica")
        if isinstance(st, dict):
            refs = st.get("referencias") if isinstance(st.get("referencias"), dict) else {}
            if refs.get("cartas_referencia_aceptadas") or refs.get("contratos_minimos"):
                return True
            exp = st.get("experiencia_mínima") or st.get("experiencia_minima")
            if isinstance(exp, dict) and not str(exp.get("años_experiencia") or exp.get("anos_experiencia") or "").strip():
                return True
    return is_obra_session(session_state)


def should_skip_datagap_field_for_session(field_key: str, session_state: Optional[Dict[str, Any]]) -> bool:
    """Evita preguntar campos de perfil genérico en obra cuando la acreditación es documental."""
    if not field_key or not is_obra_session(session_state):
        return False
    fk = str(field_key).strip().lower()
    if fk in _OBRA_DOCUMENTARY_PROFILE_FIELDS and obra_requires_documentary_experience(session_state):
        return True
    if fk in _OBRA_CHAT_INFORMATIONAL_PROFILE_FIELDS and obra_requires_documentary_experience(session_state):
        return True
    return False


def _question_field_key(question: Dict[str, Any]) -> str:
    return str(
        question.get("field")
        or question.get("field_target")
        or question.get("label")
        or ""
    ).strip().lower()


def _fill_quality_issues_from_session(
    session_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Issues vigentes del gate de llenado documental en estado de sesión."""
    if not isinstance(session_state, dict):
        return []
    hint = session_state.get("last_document_fill_quality_waiting_hints")
    if not isinstance(hint, dict):
        return []
    raw = hint.get("issues")
    if not isinstance(raw, list):
        return []
    return [i for i in raw if isinstance(i, dict)]


def normalize_obra_fill_quality_issue(issue: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Reclasifica falsos positivos de cross-tender (PORCENTAJE, BASES, GANTT…) como plantilla.
    """
    if not isinstance(issue, dict):
        return None
    err = str(issue.get("error_type") or "")
    marker = str(issue.get("detected_value") or "").strip()
    if err == "cross_tender_reference":
        from app.services.document_fill_quality_gate import is_pliego_boilerplate_marker

        if is_pliego_boilerplate_marker(marker):
            row = dict(issue)
            row["error_type"] = "placeholder_detected"
            row["field_key"] = str(row.get("field_key") or "content")
            return row
    return dict(issue)


def filter_obra_fill_quality_issues(
    issues: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Normaliza hallazgos del gate para obra pública."""
    if not is_obra_session(session_state):
        return list(issues or [])
    out: List[Dict[str, Any]] = []
    for issue in issues or []:
        norm = normalize_obra_fill_quality_issue(issue)
        if norm is not None:
            out.append(norm)
    return out


def obra_fill_quality_needs_chat_capture(
    issues: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    """
    True si el usuario debe aportar algo en chat (RFC, precios, clientes).
    False para plantillas/[Consignar] resueltas con **Generar** en panel.
    """
    if not issues:
        return False
    if not is_obra_session(session_state) or not obra_requires_documentary_experience(session_state):
        return True
    from app.services.document_fill_ux_messages import classify_fill_issues

    filtered = filter_obra_fill_quality_issues(issues, session_state)
    if not filtered:
        return False
    needs_profile, needs_clients, needs_economic, _needs_shell = classify_fill_issues(filtered)
    return bool(needs_profile or needs_clients or needs_economic)


def should_exclude_obra_fill_quality_chat_question(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    from app.services.chat_fill_quality_queue_policy import should_exclude_fill_quality_from_chat

    return should_exclude_fill_quality_from_chat(question, session_state)


def should_skip_obra_fill_quality_rag_reminder(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    from app.services.chat_fill_quality_queue_policy import should_skip_fill_quality_rag_reminder

    return should_skip_fill_quality_rag_reminder(question, session_state)


def should_exclude_obra_non_generable_chat_question(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    """
    Excluye de chat en obra lo que no llena campos generables ni precios económicos.
    """
    if not isinstance(question, dict) or not is_obra_session(session_state):
        return False

    if should_exclude_obra_fill_quality_chat_question(question, session_state):
        return True

    qtype = str(question.get("type") or "").lower()
    if qtype in _ECONOMIC_CHAT_TYPES:
        return False

    field_key = _question_field_key(question)
    bare_field = field_key.split(".")[-1] if field_key else ""

    if bare_field in _BLOCKING_PROFILE_FIELDS or field_key in _BLOCKING_PROFILE_FIELDS:
        return False

    if qtype in {"profile_field_blocking", "quality_validation_blocking", "evidence_profile_conflict"}:
        return False

    if should_skip_datagap_field_for_session(bare_field, session_state):
        return True

    if obra_requires_documentary_experience(session_state):
        if bare_field in _OBRA_CHAT_INFORMATIONAL_PROFILE_FIELDS:
            return True
        if qtype == "profile_field" and not question.get("is_blocking") and not question.get("blocking"):
            return True
        qtext = str(question.get("question") or "").lower()
        if "años de experiencia" in qtext or "anos de experiencia" in qtext:
            return True
        if qtype == "intake_planner" and "solvencia" in field_key and any(
            w in qtext for w in ("confirmar si ya tienes", "tienes la capacidad", "listo tu")
        ):
            return True

    return False


def sanitize_obra_chat_pending_questions(
    questions: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Filtra cola conversacional para obra: solo gaps generables o económicos."""
    if not is_obra_session(session_state):
        return list(questions or [])
    out: List[Dict[str, Any]] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        if should_exclude_obra_non_generable_chat_question(q, session_state):
            continue
        out.append(q)
    return out


def normalize_inventory_item_labels(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Añade alias ``nombre`` / ``nombre_canonico`` desde ``display_name`` para UI/API.
    """
    if not isinstance(item, dict):
        return {}
    row = dict(item)
    label = str(
        row.get("display_name")
        or row.get("nombre_canonico")
        or row.get("nombre")
        or row.get("label")
        or row.get("titulo")
        or ""
    ).strip()
    if label:
        row.setdefault("display_name", label)
        row.setdefault("nombre", label)
        row.setdefault("nombre_canonico", label)
        row.setdefault("label", label)
    snippet = ""
    anchors = row.get("anchors")
    if isinstance(anchors, list) and anchors:
        first = anchors[0]
        if isinstance(first, dict):
            snippet = str(first.get("snippet") or "")
    if snippet:
        row.setdefault("snippet_representativo", snippet[:600])
        row.setdefault("evidence_snippet", snippet[:600])
    return row


def enrich_inventory_payload_for_ui(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza todos los ítems del inventario canónico para consumo UI."""
    if not isinstance(payload, dict):
        return {}
    out = dict(payload)
    items = out.get("items")
    if isinstance(items, list):
        out["items"] = [normalize_inventory_item_labels(it) for it in items if isinstance(it, dict)]
    return out


def inventory_item_to_panel_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un ítem de inventario a fila del panel de formatos."""
    row = normalize_inventory_item_labels(item)
    name = str(row.get("nombre_canonico") or row.get("nombre") or "")
    cat = str(row.get("category") or "legal_administrative")
    bucket = "sobre_2_economico" if cat == "economic" else "sobre_1_tecnico"
    if cat == "legal_administrative":
        bucket = "requisitos_legales" if _DOCUMENTARY_EXPERIENCE_RE.search(name) else "sobre_1_tecnico"
    tipo = "presentar_fisico" if _DOCUMENTARY_EXPERIENCE_RE.search(name) and "anexo" in name.lower() else "generar"
    return {
        **row,
        "nombre_canonico": name,
        "nombre": name,
        "tipo": tipo,
        "tipo_accion_final": tipo,
        "tipo_accion_propuesto": tipo,
        "from_document_inventory": True,
        "sobre_clasificado": bucket,
    }
