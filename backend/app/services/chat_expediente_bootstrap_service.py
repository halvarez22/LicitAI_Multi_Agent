"""
Bootstrap HRU universal post-análisis: plan de expediente para cualquier licitación.

Deriva qué debe recabar el licitante vs qué genera la app desde estado de sesión
(inventario, CCC, compliance) — sin mapas por licitación ni texto fijo por obra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.obra_chat_queue_policy import _DOCUMENTARY_EXPERIENCE_RE

_GENERABLE_TIPOS = frozenset(
    {
        "generar",
        "requiere_datos_licitante",
        "presentar_digital",
        "llenar_formato",
        "llenar_plantilla",
    }
)
_USER_TIPOS = frozenset({"presentar_fisico", "aportar_documento", "consignar_fisico"})

_CCC_BUCKETS = (
    "sobre_1_tecnico",
    "sobre_2_economico",
    "requisitos_legales",
    "otros_requisitos_criticos",
    "candidate_document_list",
)


@dataclass
class ExpedienteBootstrapFacts:
    """Hechos derivados del estado para copy Gate 5."""

    session_name: str = "esta licitación"
    company_label: str = ""
    user_attach_labels: List[str] = field(default_factory=list)
    generate_labels: List[str] = field(default_factory=list)

    @property
    def user_attach_count(self) -> int:
        return len(self.user_attach_labels)

    @property
    def generate_count(self) -> int:
        return len(self.generate_labels)


def _clean_display_name(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    if not text:
        return ""
    try:
        from app.services.formats_panel_hru_service import resolve_panel_display_name

        text = resolve_panel_display_name(text)
    except Exception:
        pass
    if len(text) > 88:
        text = text[:85].rsplit(" ", 1)[0] + "…"
    return text


def _item_name(item: Dict[str, Any]) -> str:
    return _clean_display_name(
        str(
            item.get("nombre_canonico")
            or item.get("display_name")
            or item.get("nombre")
            or item.get("label")
            or item.get("descripcion")
            or ""
        )
    )


def _item_tipo(item: Dict[str, Any]) -> str:
    return str(
        item.get("tipo_accion_final")
        or item.get("tipo_accion_propuesto")
        or item.get("tipo_accion")
        or item.get("tipo")
        or ""
    ).strip().lower()


def _is_user_attach_item(item: Dict[str, Any]) -> bool:
    tipo = _item_tipo(item)
    if tipo in _USER_TIPOS:
        return True
    name = _item_name(item)
    if not name:
        return False
    blob = name.lower()
    if _DOCUMENTARY_EXPERIENCE_RE.search(name) and re.search(
        r"(?i)\banexo\b|\bformato\b|\bmodelo\b", name
    ):
        return True
    try:
        from app.services.document_deliverable_filter import (
            is_corporate_physical_credential_for_panel,
        )

        snippet = str(item.get("snippet_representativo") or item.get("snippet") or "")
        if is_corporate_physical_credential_for_panel(name, "", snippet, tipo):
            return True
    except Exception:
        pass
    if item.get("requires_user_document") is True:
        return True
    if str(item.get("categoria") or "") == "expediente_empresarial":
        return True
    if tipo in _GENERABLE_TIPOS:
        return False
    if "consignar" in blob and "fisico" in blob:
        return True
    return False


def _is_generable_item(item: Dict[str, Any]) -> bool:
    tipo = _item_tipo(item)
    if tipo in _USER_TIPOS:
        return False
    name = _item_name(item)
    if not name:
        return False
    if _is_user_attach_item(item):
        return False
    if tipo in _GENERABLE_TIPOS or tipo == "generar":
        return True
    try:
        from app.services.document_candidate_list_service import _formats_panel_tipo_for_item

        panel_tipo = _formats_panel_tipo_for_item(item)
        return panel_tipo == "generar"
    except Exception:
        pass
    if re.search(r"(?i)\banexo\s+[a-z0-9\-]+|\bformato\b|\bmodelo\b", name):
        return True
    return False


def _dedupe_append(target: List[str], seen: Set[str], label: str) -> None:
    key = re.sub(r"\s+", " ", label.strip().lower())
    if not key or key in seen:
        return
    seen.add(key)
    target.append(label)


def _iter_ccc_items(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    ccc = state.get("document_candidates_consolidated")
    if not isinstance(ccc, dict):
        return
    for bucket in _CCC_BUCKETS:
        for item in ccc.get(bucket) or []:
            if isinstance(item, dict):
                yield item


def _iter_compliance_items(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    cml = state.get("compliance_master_list")
    if not isinstance(cml, dict):
        return
    for cat in ("administrativo", "tecnico", "formatos", "economico"):
        for item in cml.get(cat) or []:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("categoria", cat)
                yield row


def _iter_inventory_items(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    inv = state.get("document_inventory")
    if not isinstance(inv, dict):
        return
    for item in inv.get("items") or []:
        if isinstance(item, dict):
            yield item


def _company_label_from_state(state: Dict[str, Any]) -> str:
    mp = state.get("master_profile")
    if isinstance(mp, dict):
        name = str(mp.get("razon_social") or mp.get("nombre") or "").strip()
        if name:
            return name
    cid = str(state.get("company_id") or "").strip()
    return cid


def collect_expediente_bootstrap_facts(state: Dict[str, Any]) -> ExpedienteBootstrapFacts:
    """
    Clasifica ítems del expediente en «recabar tú» vs «generar app» desde estado canónico.
    """
    facts = ExpedienteBootstrapFacts(
        session_name=str(state.get("name") or "esta licitación").strip() or "esta licitación",
        company_label=_company_label_from_state(state),
    )
    user_seen: Set[str] = set()
    gen_seen: Set[str] = set()

    for item in list(_iter_ccc_items(state)) + list(_iter_compliance_items(state)) + list(
        _iter_inventory_items(state)
    ):
        name = _item_name(item)
        if not name:
            continue
        if _is_user_attach_item(item):
            _dedupe_append(facts.user_attach_labels, user_seen, name)
        elif _is_generable_item(item):
            _dedupe_append(facts.generate_labels, gen_seen, name)

    return facts


def _format_examples(labels: List[str], *, max_show: int = 2) -> str:
    if not labels:
        return ""
    shown = labels[:max_show]
    chunk = ", ".join(f"**{lbl}**" for lbl in shown)
    rest = len(labels) - len(shown)
    if rest > 0:
        chunk += f" y **{rest}** más"
    return chunk


def build_expediente_detail_line(facts: ExpedienteBootstrapFacts) -> str:
    """Segunda línea Gate 5: rol usuario vs app (universal)."""
    company = facts.company_label or "tu empresa"
    segments: List[str] = []

    if facts.user_attach_count > 0:
        examples = _format_examples(facts.user_attach_labels)
        segments.append(
            f"Debes **recabar y adjuntar** {facts.user_attach_count} documento(s) empresarial(es)"
            + (f" (p. ej. {examples})" if examples else "")
            + "; revísalos en **Documentos detectados** del panel central."
        )
    else:
        segments.append(
            "Revisa **Documentos detectados** en el panel central por si las bases "
            "exigen credenciales o constancias de tu empresa."
        )

    if facts.generate_count > 0:
        gen_examples = _format_examples(facts.generate_labels, max_show=1)
        segments.append(
            f"Yo **generaré {facts.generate_count} formato(s)/anexo(s)** del pliego "
            f"con los datos de **{company}**"
            + (f" (incl. {gen_examples})" if gen_examples else "")
            + " y marcadores **[Consignar]** donde debas consignar evidencia."
        )
    else:
        segments.append(
            f"Yo **rellenaré los formatos y anexos** detectados con los datos de **{company}** "
            "y **[Consignar]** donde haga falta evidencia tuya."
        )

    detail = " ".join(segments)
    if len(detail) > 420:
        detail = (
            f"Recaba lo indicado en **Documentos detectados**; yo genero formatos/anexos "
            f"con **{company}** y **[Consignar]** donde aplique."
        )
    return detail


def build_expediente_plan_bootstrap(state: Dict[str, Any]) -> str:
    """
    Mensaje Gate 5 universal post-análisis (cualquier tipo de licitación).
    """
    from app.services.chat_gate5_formatter import format_gate5_message

    facts = collect_expediente_bootstrap_facts(state)
    status = f"Plan de expediente listo para **{facts.session_name}**."
    detail = build_expediente_detail_line(facts)
    cta = (
        "Abre **Formatos/Anexos Detectados** en el panel central, revisa el plan por sobres "
        "y pulsa **Generar** cuando tu empresa esté seleccionada."
    )
    return format_gate5_message(status=status, detail=detail, cta=cta)


def build_expediente_panel_help_extended(state: Dict[str, Any]) -> str:
    """
    Texto extendido (panel / ayuda) — no para saludo de chat Gate 5.
    """
    facts = collect_expediente_bootstrap_facts(state)
    company = facts.company_label or "la empresa seleccionada"
    lines = [
        f"Plan de expediente para **{facts.session_name}**.",
        "",
        "**Documentos detectados** (panel central): lista desplegable de documentos "
        "empresariales que debes **recabar y adjuntar** a tu propuesta. Pulsa cada ítem "
        "para ver el detalle.",
        "",
        "**Formatos/Anexos Detectados**: formatos del pliego que **generaré** por sobre, "
        f"rellenando datos de **{company}**.",
        "",
        "Cuando hayas revisado ambas listas, pulsa **Generar** en el panel izquierdo; "
        "puedes dejar correr la generación — te aviso en el chat solo si falta algo cotizable.",
    ]
    if facts.user_attach_labels:
        lines.append("")
        lines.append("Documentación tuya detectada: " + ", ".join(facts.user_attach_labels[:6]))
    return "\n".join(lines)
