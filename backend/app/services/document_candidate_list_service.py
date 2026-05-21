from __future__ import annotations

import re
from typing import Any, Dict, List

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
