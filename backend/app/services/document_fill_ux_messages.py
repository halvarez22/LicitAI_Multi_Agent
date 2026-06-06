"""
Mensajes UX en lenguaje humano para bloqueos del gate de llenado documental.
Pensado para usuarios sin experiencia en licitaciones.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

_FIELD_LABELS_ES: Dict[str, str] = {
    "razon_social": "nombre completo de la empresa (razón social)",
    "rfc": "RFC de la empresa",
    "representante_legal": "nombre del representante legal",
    "domicilio_fiscal": "domicilio fiscal",
    "domicilio": "domicilio de la empresa",
    "telefono": "teléfono de contacto",
    "email": "correo de contacto",
    "content": "texto del documento (quedó incompleto o con espacios en blanco)",
    "subtotal": "subtotal de la cotización",
    "iva": "IVA",
    "total": "total de la cotización",
    "economic_totals": "totales de la cotización (subtotal, IVA y total deben cuadrar)",
    "tarifa_mensual": "tarifa mensual del servicio",
}

_PROFILE_FIELDS = frozenset(
    {"rfc", "razon_social", "representante_legal", "domicilio_fiscal", "domicilio", "telefono", "email"}
)

_STAGE_LABELS_ES: Dict[str, str] = {
    "technical": "propuesta técnica",
    "formats": "formatos y anexos administrativos",
    "economic_writer": "propuesta económica",
    "economic": "propuesta económica",
}


def humanize_field_key(field_key: str) -> str:
    """Traduce claves internas a texto que entienda cualquier usuario."""
    key = str(field_key or "").strip().lower()
    if not key:
        return "un dato obligatorio"
    if key in _FIELD_LABELS_ES:
        return _FIELD_LABELS_ES[key]
    return key.replace("_", " ")


def humanize_stage(stage: str) -> str:
    return _STAGE_LABELS_ES.get(str(stage or "").strip().lower(), "documentos de la propuesta")


def issue_needs_company_profile(issue: Dict[str, Any]) -> bool:
    """True si el hallazgo apunta a datos faltantes en Empresas (RFC, representante, etc.)."""
    fk = str(issue.get("field_key") or "").lower()
    err = str(issue.get("error_type") or "")
    if str(issue.get("document_id") or "") == "profile":
        return True
    if fk in _PROFILE_FIELDS and err in ("required_field_missing", "source_confidence_insufficient"):
        return True
    return False


def issue_needs_client_references(issue: Dict[str, Any]) -> bool:
    """True si falta relación de clientes/contratos previos (TE-03, currículum)."""
    if str(issue.get("error_type") or "") != "placeholder_detected":
        return False
    snippet = str(issue.get("detected_value") or "").lower()
    return (
        "cliente" in snippet
        or "domicilio del" in snippet
        or ("|" in snippet and "[" in snippet)
    )


def issue_is_document_shell(issue: Dict[str, Any]) -> bool:
    return str(issue.get("error_type") or "") == "document_shell_detected"


def issue_is_policy_metric_only(issue: Dict[str, Any]) -> bool:
    return str(issue.get("error_type") or "") == "policy_coverage_insufficient"


def issue_needs_economic_data(issue: Dict[str, Any]) -> bool:
    fk = str(issue.get("field_key") or "").lower()
    snippet = str(issue.get("detected_value") or "").lower()
    if fk in {"subtotal", "iva", "total", "economic_totals", "price_fill", "tarifa_mensual"}:
        return True
    if any(
        tok in snippet
        for tok in (
            "tarifa mensual",
            "precio unitario",
            "integracion del costo",
            "integración del costo",
            "tabla de precios",
        )
    ):
        return True
    return bool(
        str(issue.get("error_type") or "") == "cross_field_inconsistency"
        and fk in {"subtotal", "iva", "total"}
    )


def classify_fill_issues(
    issues: Sequence[Dict[str, Any]],
) -> Tuple[bool, bool, bool, bool]:
    """(needs_profile, needs_clients, needs_economic, needs_shell_redo)"""
    needs_profile = needs_clients = needs_economic = needs_shell = False
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        if issue_needs_company_profile(issue):
            needs_profile = True
        if issue_needs_client_references(issue):
            needs_clients = True
        if issue_needs_economic_data(issue):
            needs_economic = True
        if issue_is_document_shell(issue):
            needs_shell = True
    return needs_profile, needs_clients, needs_economic, needs_shell


def pick_fill_gate_pending_label(issues: Sequence[Dict[str, Any]]) -> str:
    """Etiqueta corta para pending_questions según el tipo real de hallazgo."""
    needs_profile, needs_clients, needs_economic, needs_shell = classify_fill_issues(issues)
    if needs_economic and not needs_profile:
        return "Completar tarifa o precios"
    if needs_profile:
        return "Completar datos de la empresa"
    if needs_clients:
        return "Completar experiencia o clientes"
    if needs_shell:
        return "Regenerar anexos sin texto legal"
    return "Revisar formatos con marcadores pendientes"


def human_line_for_issue(issue: Dict[str, Any], *, company_name: Optional[str] = None) -> str:
    """Una línea accionable por hallazgo del gate."""
    if not isinstance(issue, dict):
        return "• Falta completar un dato en uno de los documentos generados."
    doc = str(issue.get("document_id") or "un documento").replace("_", " ")
    field = humanize_field_key(str(issue.get("field_key") or ""))
    err = str(issue.get("error_type") or "")
    company = (company_name or "").strip()
    company_bit = f" de **{company}**" if company else " de tu empresa"

    if err == "required_field_missing":
        if issue_needs_company_profile(issue):
            return f"• En **{doc}** falta en **Empresas**: **{field}**."
        return f"• En **{doc}** falta: **{field}**."
    if err == "placeholder_detected":
        if issue_needs_client_references(issue):
            return (
                f"• En **{doc}** falta la **lista de clientes o contratos previos** "
                f"(nombre, domicilio, teléfono). **RFC y representante{company_bit} ya están bien.**"
            )
        snippet = str(issue.get("detected_value") or "").strip()
        doc_lower = doc.lower()
        if "propuesta" in doc_lower or "te-" in doc_lower or field == "content":
            return (
                f"• En **{doc}** quedó **texto sin terminar**. Pulsa **Generar** otra vez; "
                f"si pide experiencia, escríbeme clientes o contratos en el chat."
            )
        if issue_needs_economic_data(issue):
            return (
                f"• En **{doc}** falta la **tarifa o precio mensual** del servicio. "
                "Se completará en la **propuesta económica**; también puedes escribírmela aquí."
            )
        if snippet:
            short = snippet[:70] + ("…" if len(snippet) > 70 else "")
            return f"• En **{doc}** quedó texto sin llenar (ej. «{short}»)."
        return f"• En **{doc}** quedaron espacios o texto de plantilla sin completar."
    if err == "cross_tender_reference":
        marker = str(issue.get("detected_value") or "").strip()
        return (
            f"• En **{doc}** aparece información de **otra licitación**"
            + (f" («{marker[:50]}»)." if marker else ".")
            + " Revisa que los archivos correspondan a **esta** licitación."
        )
    if err == "cross_field_inconsistency":
        return f"• En **{doc}** hay números que **no cuadran** ({field}). Revisa la cotización."
    if err == "source_confidence_insufficient":
        if issue_needs_company_profile(issue):
            return f"• Confirma **{field}** en **Empresas** o escríbelo aquí en el chat."
        return f"• Necesito confirmar **{field}** en **{doc}**."
    if err == "document_shell_detected":
        return (
            f"• **{doc}** quedó solo con encabezado y firma, **sin declaración legal**. "
            "Pulsa **Generar** otra vez (no hace falta ir a Empresas)."
        )
    if err == "document_metadata_leak":
        return (
            f"• **{doc}** incluyó etiquetas internas del sistema. "
            "Pulsa **Generar** otra vez."
        )
    return f"• En **{doc}** hay que corregir: **{field}**."


def _build_intro(
    stage_label: str,
    company_phrase: str,
    issues: Sequence[Dict[str, Any]],
    *,
    experience_summary: Optional[str] = None,
) -> str:
    needs_profile, needs_clients, needs_economic, needs_shell = classify_fill_issues(issues)
    if needs_shell and not needs_profile and not needs_clients:
        return (
            f"⏸️ **Pausé la generación** al armar la **{stage_label}** porque uno o más anexos "
            f"quedaron **sin el texto legal** (solo membrete). **No es un problema de Empresas.** "
            f"Pulsa **Generar** de nuevo para reintentar la redacción."
        )
    if needs_clients and not needs_profile:
        base = (
            f"⏸️ **Pausé la generación** al armar la **{stage_label}** porque falta "
            f"**experiencia o clientes previos** en un anexo técnico. "
            f"**Los datos de Empresas{company_phrase} (RFC, representante) ya están cargados.**"
        )
        if experience_summary:
            return f"{base}\n\n📄 {experience_summary}"
        return base
    if needs_economic and not needs_profile:
        return (
            f"⏸️ **Pausé la generación** en la **{stage_label}** por datos de **cotización o precios**."
        )
    if not needs_profile and not needs_clients and not needs_economic:
        return (
            f"⏸️ **Pausé la generación** al armar la **{stage_label}** porque algunos "
            f"archivos quedaron con **texto incompleto o plantilla** sin terminar. "
            f"**Los datos de Empresas{company_phrase} (RFC, domicilio, representante) ya se usaron "
            f"en la mayoría de los documentos.**"
        )
    return (
        f"⏸️ **Pausé la generación** al armar la **{stage_label}** porque faltan datos "
        f"para rellenar los documentos con información real{company_phrase}."
    )


def _build_next_steps(
    issues: Sequence[Dict[str, Any]],
    *,
    experience_summary: Optional[str] = None,
) -> str:
    needs_profile, needs_clients, needs_economic, needs_shell = classify_fill_issues(issues)
    lines = ["**Qué puedes hacer ahora (elige lo más fácil):**"]
    if needs_shell and not needs_profile:
        lines.append("1. Pulsa **Generar** otra vez (el sistema reintentará la redacción legal).")
        return "\n".join(lines)
    step = 1
    if needs_clients:
        if experience_summary:
            lines.append(
                f"{step}. Pulsa **Generar** otra vez — usaré los **documentos de experiencia "
                f"en Fuentes** para llenar la tabla de clientes del anexo técnico."
            )
        else:
            lines.append(
                f"{step}. **Escríbeme aquí** 1–3 clientes o contratos previos "
                f"(nombre, domicilio, teléfono). Ejemplo: «Cliente Hospital Regional, León, tel. 4771234567»."
            )
        step += 1
    if needs_profile:
        lines.append(
            f"{step}. Ve a **Empresas** → completa RFC, razón social y representante legal → **Guardar**."
        )
        step += 1
    if needs_economic:
        lines.append(
            f"{step}. Revisa la **cotización / Excel** o escribe los precios que faltan en el chat."
        )
        step += 1
    if step == 1:
        lines.append(f"{step}. **Escríbeme aquí** el dato que falta y yo lo incorporo.")
        step += 1
    lines.append(f"{step}. Pulsa otra vez **Generar** en el panel.")
    return "\n".join(lines)


def _build_chat_prompt(
    issues: Sequence[Dict[str, Any]],
    *,
    experience_summary: Optional[str] = None,
) -> str:
    needs_profile, needs_clients, needs_economic, _needs_shell = classify_fill_issues(issues)
    if needs_clients and not needs_profile:
        if experience_summary:
            return (
                "Escribe **generar** o pulsa **Generar** en el panel — tomaré los clientes "
                "de tus **documentos de experiencia en Fuentes**. Solo escríbeme referencias "
                "a mano si quieres usar otras distintas."
            )
        return (
            "Respóndeme con tus clientes o contratos de referencia (nombre, ciudad, teléfono). "
            "No hace falta ir a Empresas si RFC y representante ya están completos."
        )
    if needs_economic and not needs_profile and not needs_clients:
        return (
            "Puedes **seguir generando** (la tarifa se captura en **Propuesta económica**) "
            "o escríbeme aquí la tarifa mensual, por ejemplo: «$13,326.63 MXN horario diurno»."
        )
    if needs_profile and not needs_clients:
        return "Escríbeme el RFC, representante legal o domicilio que falte, o complétalo en Empresas."
    return "Escríbeme en una frase lo que falta y te guío paso a paso."


def build_fill_quality_user_brief(
    stage: str,
    issues: Sequence[Dict[str, Any]],
    *,
    company_name: Optional[str] = None,
    max_lines: int = 6,
    experience_summary: Optional[str] = None,
) -> Dict[str, str]:
    """
    Arma mensaje principal para chat/UI cuando la generación se pausa por llenado.

    Returns:
        dict con ``title``, ``intro``, ``body``, ``next_steps``, ``chat_prompt``
    """
    stage_label = humanize_stage(stage)
    company = (company_name or "").strip()
    company_phrase = f" de **{company}**" if company else " de tu empresa"

    lines: List[str] = []
    seen: set[str] = set()
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("document_id") or "").startswith("stage:"):
            continue
        if issue_is_policy_metric_only(issue):
            continue
        line = human_line_for_issue(issue, company_name=company_name)
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= max_lines:
            break

    if not lines:
        lines = [
            "• Algunos documentos se generaron con **campos vacíos** o texto de plantilla.",
            f"• Necesito datos concretos para continuar{company_phrase}.",
        ]

    extra = ""
    if issues and len(issues) > max_lines:
        extra = f"\n\n_(Hay {len(issues) - max_lines} detalle(s) más en la pestaña **Calidad documental**.)_"

    body = "\n".join(lines)
    intro = _build_intro(stage_label, company_phrase, issues or [], experience_summary=experience_summary)
    next_steps = _build_next_steps(issues or [], experience_summary=experience_summary)
    chat_prompt = _build_chat_prompt(issues or [], experience_summary=experience_summary)

    needs_profile, needs_clients, needs_economic, needs_shell = classify_fill_issues(
        issues or []
    )
    if needs_shell and not needs_profile:
        title = "Anexos sin texto legal — regenerar"
    elif needs_clients and not needs_profile:
        title = "Falta relación de clientes en la propuesta técnica"
    elif needs_economic and not needs_profile and not needs_clients:
        title = "Tarifa mensual pendiente (propuesta económica)"
    else:
        title = f"Faltan datos para la {stage_label}"

    return {
        "title": title,
        "intro": intro,
        "body": body + extra,
        "next_steps": next_steps,
        "chat_prompt": chat_prompt,
        "full_message": f"{intro}\n\n{body}{extra}\n\n{next_steps}\n\n{chat_prompt}",
    }


def build_fill_blocking_question(
    stage: str,
    issues: Sequence[Dict[str, Any]],
    *,
    company_name: Optional[str] = None,
    experience_summary: Optional[str] = None,
) -> str:
    """Pregunta HITL corta para pending_questions / chatbot."""
    brief = build_fill_quality_user_brief(
        stage,
        issues,
        company_name=company_name,
        max_lines=4,
        experience_summary=experience_summary,
    )
    return brief["full_message"]


def _primary_action_for_issue(issue: Dict[str, Any]) -> Dict[str, str]:
    """Botón principal en tarjeta de validación según tipo de hallazgo."""
    if issue_needs_client_references(issue):
        return {"label": "Escribir clientes en el chat", "type": "navigate", "target": "chat_pricing"}
    if issue_needs_company_profile(issue):
        return {"label": "Completar en Empresas", "type": "navigate", "target": "companies"}
    if issue_needs_economic_data(issue):
        return {"label": "Revisar cotización", "type": "navigate", "target": "economic_panel"}
    err = str(issue.get("error_type") or "")
    if err == "cross_tender_reference":
        return {"label": "Revisar archivos", "type": "navigate", "target": "upload_area"}
    if err == "placeholder_detected":
        return {"label": "Escribir en el chat", "type": "navigate", "target": "chat_pricing"}
    return {"label": "Escribir en el chat", "type": "navigate", "target": "chat_pricing"}


def build_fill_validation_event(
    issue: Dict[str, Any],
    *,
    stage: str = "technical",
) -> Dict[str, Any]:
    """Evento UX listo para ValidationAlert / frontend."""
    err = str(issue.get("error_type") or "document_fill_issue")
    field = humanize_field_key(str(issue.get("field_key") or ""))
    line = human_line_for_issue(issue).lstrip("• ")

    if issue_needs_client_references(issue):
        title = "Falta lista de clientes o contratos"
    elif err == "required_field_missing":
        title = f"Falta: {field}"
    elif err == "placeholder_detected":
        title = "Quedó texto sin llenar en un documento"
    elif err == "cross_tender_reference":
        title = "Parece mezclarse otra licitación"
    elif err == "cross_field_inconsistency":
        title = "Los números no cuadran"
    else:
        title = "Hay que corregir un dato"

    return {
        "error_type": err,
        "severity": "block",
        "context": {
            "stage": stage,
            "document_id": issue.get("document_id"),
            "field_key": issue.get("field_key"),
            "detected_value": issue.get("detected_value"),
            "expected_rule": issue.get("expected_rule"),
        },
        "ux": {
            "title": title,
            "user_message": line,
            "primary_action": _primary_action_for_issue(issue),
            "secondary_action": {
                "label": "Volver a generar",
                "type": "navigate",
                "target": "chat_pricing",
            },
            "impact": "Sin este dato no puedo terminar de armar tu propuesta.",
        },
        "meta": {"mapping_found": True, "source": "document_fill_quality_gate"},
    }
