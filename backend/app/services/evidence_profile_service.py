"""
evidence_profile_service.py

Construye un perfil de evidencia por sesión a partir de documentos ya extraídos
y genera un perfil efectivo con precedencia explícita para Go/No-Go.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple


_RFC_RE = re.compile(r"\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)
_ISO_RE = re.compile(r"\b(ISO\s?\d{4,5}(?::\d{4})?)\b", re.IGNORECASE)
_REPRESENTANTE_RE = re.compile(
    r"(?:representante|apoderad[oa]|administrador(?:\s+único)?)\s+legal[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,90})",
    re.IGNORECASE,
)
_EXPERIENCIA_RE = re.compile(
    r"(?:experiencia|trayectoria)\D{0,20}(\d{1,2})\s+a(?:ñ|n)os",
    re.IGNORECASE,
)
_CAPITAL_RE = re.compile(
    r"(?:capital(?:\s+contable)?|patrimonio)\D{0,20}\$?\s*([0-9][0-9,\.]{4,18})",
    re.IGNORECASE,
)
_DOMICILIO_RE = re.compile(
    r"(?:domicilio(?:\s+fiscal)?|direcci[oó]n(?:\s+fiscal)?)[:\s]+([^\n\r]{12,180})",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})\b", re.IGNORECASE)
_WEB_RE = re.compile(
    r"\b((?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?:\+?52[\s\-]?)?(?:\(?\d{2,3}\)?[\s\-]?)?\d{3}[\s\-]?\d{2}[\s\-]?\d{2,4}",
    re.IGNORECASE,
)
_CONTRATO_RE = re.compile(
    r"(?:contrato\s+n(?:u|ú|ú)mero|contrato\s+no\.?|contrato\s+#)\s*([A-Z0-9\-\/]{6,40})",
    re.IGNORECASE,
)
_ELEMENTOS_RE = re.compile(
    r"([0-9][0-9,\.]{1,10})\s+elementos?\s+de\s+vigilancia",
    re.IGNORECASE,
)
_ENTERPRISE_POSITIVE_TOKENS = (
    "acta",
    "constitutiva",
    "poder",
    "cif",
    "sat",
    "curriculum",
    "cv",
    "empresa",
    "fiscal",
    "rfc",
    "imss",
    "patronal",
    "constancia",
)
_BASES_NEGATIVE_TOKENS = (
    "licitacion",
    "convocatoria",
    "bases",
    "anexo",
    "junta",
    "fallo",
    "compranet",
)
# PDF/DOC con nombre solo numérico (p. ej. 226.pdf): suelen ser anexos de convocatoria;
# no deben llenar contacto antes que CV/actas.
_NUMERIC_SHORT_FILENAME_RE = re.compile(
    r"^\d{1,8}\.(pdf|docx?)$",
    re.IGNORECASE,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(doc: Dict[str, Any]) -> str:
    """Obtiene texto extraído de un documento de sesión si existe."""
    content = doc.get("content") or {}
    text = content.get("extracted_text") or doc.get("extracted_text") or ""
    return text if isinstance(text, str) else ""


def _doc_source(doc: Dict[str, Any]) -> str:
    content = doc.get("content") or {}
    metadata = doc.get("metadata") or {}
    return str(
        content.get("filename")
        or metadata.get("filename")
        or content.get("name")
        or doc.get("id")
        or "documento_sesion"
    )


def _source_basename(src: str) -> str:
    """Último segmento de ruta o nombre tal cual si no hay separadores."""
    if not src:
        return ""
    s = src.replace("\\", "/").rstrip("/")
    return s.split("/")[-1]


def _is_numeric_short_attachment_name(src: str) -> bool:
    """True si el nombre de archivo parece anexo neutro tipo ``226.pdf`` (solo dígitos + extensión)."""
    base = _source_basename(src)
    return bool(base and _NUMERIC_SHORT_FILENAME_RE.match(base))


def _is_cv_like_document(doc: Dict[str, Any]) -> bool:
    """Heurística de prioridad: CV / curriculum en el nombre del archivo."""
    src = _doc_source(doc).lower()
    if "curriculum" in src or "currículum" in src:
        return True
    tokens = re.split(r"[^a-z0-9áéíóúñ]+", src)
    return "cv" in tokens


def _evidence_document_sort_key(doc: Dict[str, Any]) -> Tuple[int, str]:
    """
    Orden de procesamiento: CV/curriculum primero, luego documentos con tokens empresariales,
    luego el resto (incl. anexos numéricos) para que el primer match de contacto sea el deseado.
    """
    src = _doc_source(doc).lower()
    if _is_cv_like_document(doc):
        return (0, src)
    if any(tok in src for tok in _ENTERPRISE_POSITIVE_TOKENS):
        return (1, src)
    return (2, src)


def _doc_contact_fields_eligible(doc: Dict[str, Any]) -> bool:
    """
    Si False, no se extraen email / web / teléfono / domicilio / representante desde el documento.

    Los adjuntos con nombre puramente numérico suelen ser bases o formatos de convocatoria.
    """
    if not _is_enterprise_document(doc):
        return False
    return not _is_numeric_short_attachment_name(_doc_source(doc))


def _accept_evidence_email(addr: str) -> bool:
    """Descarta correos institucionales que no son contacto fiscal típico de empresa privada."""
    if not addr or "@" not in addr:
        return False
    lower = addr.strip().lower()
    domain = lower.split("@", 1)[1]
    if ".gob.mx" in domain or domain.endswith(".gob") or ".edu.mx" in domain:
        return False
    if re.search(r"\.gob\.[^.]*$", domain):
        return False
    return True


def _first_acceptable_email(text: str) -> Optional[re.Match[str]]:
    for m in _EMAIL_RE.finditer(text):
        if _accept_evidence_email(m.group(1)):
            return m
    return None


def _accept_evidence_web(web: str) -> bool:
    """Evita falsos positivos (p. ej. ``S.A``) y dominios de convocatoria como evidencia de sitio web."""
    w = web.strip().rstrip(".,;").lower()
    if len(w) < 8:
        return False
    if w.count(".") < 1:
        return False
    if ".gob.mx" in w or re.match(r"^https?://[^/\s]*\.gob\.", w):
        return False
    host = w.split("//", 1)[-1].split("/", 1)[0]
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2 or len(parts[-1]) < 2:
        return False
    return True


def _looks_like_contract_id_phone(
    phone_raw: str, text: str, match_start: int, match_end: int
) -> bool:
    """
    Heurística: cadena de 10 dígitos sin formato de teléfono, en ventana con lenguaje de contrato.
    """
    digits = re.sub(r"\D", "", phone_raw)
    if len(digits) != 10:
        return False
    if re.search(r"[\(\)\-]", phone_raw):
        return False
    lo = max(0, match_start - 80)
    hi = min(len(text), match_end + 80)
    win = text[lo:hi].lower()
    markers = (
        "contrato",
        "contratos",
        "número",
        "numero",
        "folio",
        "expediente",
        "procedimiento",
        "compranet",
    )
    return any(m in win for m in markers)


def _is_enterprise_document(doc: Dict[str, Any]) -> bool:
    """Heurística de procedencia para evitar contaminar perfil empresarial con bases."""
    src = _doc_source(doc).lower()
    if not src:
        return False
    if src.startswith("la-"):
        return False
    if any(tok in src for tok in _BASES_NEGATIVE_TOKENS):
        return False
    if any(tok in src for tok in _ENTERPRISE_POSITIVE_TOKENS):
        return True
    # Documento neutro (p.ej. "226.pdf"): permitir para no perder evidencia útil.
    return True


def _confidence_from_text(text: str) -> float:
    chars = len((text or "").strip())
    if chars >= 2000:
        return 0.85
    if chars >= 700:
        return 0.7
    if chars >= 250:
        return 0.55
    return 0.4


def _normalize_capital(raw: str) -> Optional[str]:
    """Normaliza capital/patrimonio a string decimal sin separadores."""
    if not raw:
        return None
    candidate = raw.replace(",", "")
    try:
        value = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return str(value.quantize(Decimal("1")))


def _build_field_entry(
    *,
    value: Any,
    source_doc: str,
    confidence: float,
    snippet: str,
) -> Dict[str, Any]:
    return {
        "value": value,
        "source": "session_doc",
        "source_doc": source_doc,
        "confidence": round(float(max(0.0, min(1.0, confidence))), 3),
        "snippet": snippet[:220],
        "updated_at": _utc_now_iso(),
    }


def build_evidence_profile_from_documents(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extrae campos canónicos para Go/No-Go desde documentos ya analizados.

    Args:
        documents: Lista de documentos de sesión (memory.get_documents).

    Returns:
        Perfil estructurado por campo con procedencia y confianza.
    """
    fields: Dict[str, Dict[str, Any]] = {}
    certs: List[str] = []
    contratos_previos: List[Dict[str, Any]] = []

    ordered_docs = sorted(documents or [], key=_evidence_document_sort_key)

    for doc in ordered_docs:
        if not _is_enterprise_document(doc):
            continue
        text = _safe_text(doc)
        if len(text.strip()) < 40:
            continue
        confidence = _confidence_from_text(text)
        source_doc = _doc_source(doc)
        contact_ok = _doc_contact_fields_eligible(doc)

        if "rfc" not in fields:
            m = _RFC_RE.search(text.upper())
            if m:
                fields["rfc"] = _build_field_entry(
                    value=m.group(1).upper(),
                    source_doc=source_doc,
                    confidence=confidence,
                    snippet=m.group(0),
                )

        if contact_ok and "representante_legal" not in fields:
            m = _REPRESENTANTE_RE.search(text)
            if m:
                fields["representante_legal"] = _build_field_entry(
                    value=" ".join(m.group(1).split())[:140],
                    source_doc=source_doc,
                    confidence=max(confidence, 0.65),
                    snippet=m.group(0),
                )

        if "anos_experiencia" not in fields:
            m = _EXPERIENCIA_RE.search(text)
            if m:
                fields["anos_experiencia"] = _build_field_entry(
                    value=m.group(1),
                    source_doc=source_doc,
                    confidence=confidence,
                    snippet=m.group(0),
                )

        if "capital_contable" not in fields:
            m = _CAPITAL_RE.search(text)
            if m:
                capital = _normalize_capital(m.group(1))
                if capital:
                    fields["capital_contable"] = _build_field_entry(
                        value=capital,
                        source_doc=source_doc,
                        confidence=confidence,
                        snippet=m.group(0),
                    )

        if contact_ok and "domicilio_fiscal" not in fields:
            m = _DOMICILIO_RE.search(text)
            if m:
                fields["domicilio_fiscal"] = _build_field_entry(
                    value=" ".join(m.group(1).split())[:180],
                    source_doc=source_doc,
                    confidence=confidence,
                    snippet=m.group(0),
                )
        if contact_ok and "email" not in fields:
            m = _first_acceptable_email(text)
            if m:
                fields["email"] = _build_field_entry(
                    value=m.group(1).lower(),
                    source_doc=source_doc,
                    confidence=confidence,
                    snippet=m.group(0),
                )
        if contact_ok and "web" not in fields:
            for wm in _WEB_RE.finditer(text):
                web = wm.group(1).strip().rstrip(".,;")
                if _accept_evidence_web(web):
                    fields["web"] = _build_field_entry(
                        value=web,
                        source_doc=source_doc,
                        confidence=confidence,
                        snippet=wm.group(0),
                    )
                    break
        if contact_ok and "telefono" not in fields:
            for m in _PHONE_RE.finditer(text):
                phone_raw = m.group(0)
                digits = re.sub(r"\D", "", phone_raw)
                if len(digits) < 10:
                    continue
                if _looks_like_contract_id_phone(phone_raw, text, m.start(), m.end()):
                    continue
                fields["telefono"] = _build_field_entry(
                    value=phone_raw.strip(),
                    source_doc=source_doc,
                    confidence=confidence,
                    snippet=m.group(0),
                )
                break

        for iso_match in _ISO_RE.findall(text):
            norm = iso_match.strip().upper().replace(" ", "")
            if norm and norm not in certs:
                certs.append(norm)

        for match in _CONTRATO_RE.finditer(text):
            contrato_id = str(match.group(1) or "").strip().upper()
            if not contrato_id:
                continue
            start, end = max(0, match.start() - 120), min(len(text), match.end() + 180)
            window = text[start:end]
            elementos_match = _ELEMENTOS_RE.search(window)
            elementos = None
            if elementos_match:
                elementos = str(elementos_match.group(1)).replace(",", "")
            exists = any(x.get("contrato_id") == contrato_id for x in contratos_previos)
            if not exists:
                contratos_previos.append(
                    {
                        "contrato_id": contrato_id,
                        "elementos_vigilancia": elementos,
                        "source_doc": source_doc,
                    }
                )

    if certs:
        fields["certificaciones"] = _build_field_entry(
            value=certs,
            source_doc=fields.get("rfc", {}).get("source_doc", "session_docs"),
            confidence=0.65,
            snippet=", ".join(certs),
        )
    if contratos_previos:
        fields["contratos_previos"] = _build_field_entry(
            value=contratos_previos,
            source_doc=contratos_previos[0].get("source_doc", "session_docs"),
            confidence=0.7,
            snippet=f"Contratos detectados: {len(contratos_previos)}",
        )

    return {
        "schema_version": 1,
        "generated_at": _utc_now_iso(),
        "fields": fields,
    }


def _extract_override_value(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def _extract_evidence_value(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw.get("value")
    return None


def build_effective_profile(
    *,
    master_profile: Dict[str, Any],
    evidence_profile: Dict[str, Any],
    user_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Construye perfil efectivo con precedencia explícita:
    user_direct > session_doc > master_profile > inferencia.
    """
    overrides = user_overrides or {}
    evidence_fields = (evidence_profile or {}).get("fields") or {}
    master = master_profile or {}
    effective = dict(master)
    provenance: Dict[str, Dict[str, Any]] = {}

    all_keys = set(master.keys()) | set(evidence_fields.keys()) | set(overrides.keys())
    for key in all_keys:
        if key.startswith("_"):
            continue

        override_value = _extract_override_value(overrides.get(key))
        evidence_value = _extract_evidence_value(evidence_fields.get(key))
        master_value = master.get(key)

        if override_value not in (None, "", []):
            effective[key] = override_value
            provenance[key] = {"source": "user_direct"}
            continue

        if evidence_value not in (None, "", []):
            effective[key] = evidence_value
            entry = evidence_fields.get(key) or {}
            provenance[key] = {
                "source": "session_doc",
                "source_doc": entry.get("source_doc"),
                "confidence": entry.get("confidence"),
                "snippet": entry.get("snippet"),
            }
            continue

        if master_value not in (None, "", []):
            effective[key] = master_value
            provenance[key] = {"source": "master_profile"}
            continue

        provenance[key] = {"source": "inference"}

    return effective, provenance


_CRITICAL_FIELDS = (
    "representante_legal",
    "rfc",
    "capital_contable",
    "anos_experiencia",
    "domicilio_fiscal",
)


def detect_profile_conflicts(
    *,
    master_profile: Dict[str, Any],
    evidence_profile: Dict[str, Any],
    evidence_profile_overrides: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Detecta conflictos entre perfil maestro y evidencia documental para campos críticos.

    Si existe ``evidence_profile_overrides`` con valor resuelto para un campo, se omite
    ese conflicto (el usuario ya eligió procedencia vía HITL).
    """
    conflicts: List[Dict[str, Any]] = []
    master = master_profile or {}
    evidence_fields = (evidence_profile or {}).get("fields") or {}
    overrides = evidence_profile_overrides or {}
    for field in _CRITICAL_FIELDS:
        if _extract_override_value(overrides.get(field)) not in (None, "", []):
            continue
        master_value = master.get(field)
        evidence_entry = evidence_fields.get(field) or {}
        evidence_value = evidence_entry.get("value")
        if master_value in (None, "", []) or evidence_value in (None, "", []):
            continue
        if str(master_value).strip().lower() == str(evidence_value).strip().lower():
            continue
        conflicts.append(
            {
                "field": field,
                "master_value": master_value,
                "evidence_value": evidence_value,
                "source_doc": evidence_entry.get("source_doc"),
                "confidence": evidence_entry.get("confidence"),
                "error_type": "CONFLICTING_EVIDENCE",
            }
        )
    return conflicts


def build_conflict_pending_questions(conflicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convierte conflictos en preguntas HITL para la cola transaccional de sesión.
    """
    questions: List[Dict[str, Any]] = []
    for c in conflicts or []:
        field = str(c.get("field") or "").strip()
        if not field:
            continue
        master_value = c.get("master_value")
        evidence_value = c.get("evidence_value")
        source_doc = c.get("source_doc") or "documento de sesión"
        questions.append(
            {
                "field": field,
                "label": f"Confirmar {field.replace('_', ' ')}",
                "question": (
                    f"Detecté un conflicto para {field.replace('_', ' ')}. "
                    f"Perfil empresa: '{master_value}'. Documento ({source_doc}): '{evidence_value}'. "
                    "¿Cuál valor debo usar?"
                ),
                "type": "evidence_profile_conflict",
                "priority": "high",
                "source": "evidence_profile_bridge",
                "error_type": "CONFLICTING_EVIDENCE",
                "options": [
                    {"id": "master_profile", "label": str(master_value)},
                    {"id": "session_doc", "label": str(evidence_value)},
                ],
                "conflict_detail": c,
            }
        )
    return questions
