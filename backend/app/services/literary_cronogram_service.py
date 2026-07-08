"""
Citas literales de cronograma alineadas al submission_checklist (verdad canónica HRU).

Usa el mismo corpus indexado y ``extract_hito_from_bases_text`` que el panel de hitos.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.checklist.hito_scheduler import _HITO_ORDER, _NOMBRES_ES
from app.services.cronograma_bases_extract import (
    extract_hito_from_bases_text,
    parse_spanish_date_fragment,
)
from app.services.cronograma_enrichment_service import is_placeholder_cronograma_value


def _normalize_match_text(text: str) -> str:
    """Misma normalización que ``alert_fingerprint`` sin truncar (contención en blob)."""
    t = re.sub(r"\s+", " ", str(text or "").lower().strip())
    t = re.sub(r"[^\w\s$.,]", "", t)
    t = re.sub(r"(\d)[,\.](?=\d{3})", r"\1", t)
    return t


def _literal_in_blob(literal: str, blob: str) -> bool:
    lit_n = _normalize_match_text(literal)
    blob_n = _normalize_match_text(blob)
    if not lit_n or not blob_n:
        return False
    if lit_n in blob_n:
        return True
    return lit_n[:48] in blob_n or lit_n[:32] in blob_n


def _raw_date_in_literal(raw: str, literal: str) -> bool:
    """True si la fecha del hito (checklist) aparece en el literal extraído."""
    dt = parse_spanish_date_fragment(raw)
    if dt is None:
        return _normalize_match_text(raw)[:24] in _normalize_match_text(literal)
    lit_n = _normalize_match_text(literal)
    month_names = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    month = month_names[dt.month - 1]
    return month in lit_n and str(dt.year) in lit_n and str(dt.day) in lit_n


def _weak_presentacion_literal(literal: str) -> bool:
    lit = _normalize_match_text(literal)
    if "proposicion" in lit or "apertura" in lit or "entregarse" in lit:
        return False
    return lit.startswith("fecha y hora para tal efecto")


def _clean_literary_sentence(text: str, max_len: int = 480) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return _trim_at_sentence_boundary(s, max_len=max_len)


def _ensure_schedule_time_from_checklist(text: str, raw: str) -> str:
    """Si el checklist trae hora y el literal no, la añade (misma verdad canónica)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s or not raw:
        return s
    if re.search(r"\d{1,2}:\d{2}", s):
        return s
    time_needle = _time_needle_from_raw(raw)
    if not time_needle:
        return s
    suffix = f" a las {time_needle} horas."
    base = s.rstrip(".")
    return base + suffix


def _trim_procedural_act_sentence(text: str) -> str:
    """Cierra en fecha+hora del acto; evita colas de dirección (Blvd., etc.)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return s

    # Presupuestos + ruido de dirección + hora de cita (orden visita / similares).
    m_pres_time = re.search(
        r"(?is)(.+?\bpresupuestos\b)\s*"
        r"(?:(?!a las \d{1,2}:\d{2}).)*?"
        r"(a las \d{1,2}:\d{2}\s*(?:horas?|hrs?))",
        s,
    )
    if m_pres_time:
        return f"{m_pres_time.group(1).strip()}, {m_pres_time.group(2).strip()}."

    m_place = re.search(
        r"(?is)(.+?\d{1,2}:\d{2}\s*(?:horas?|hrs)\s+en la\s+dirección\s+de\s+costos\s+y\s+presupuestos)",
        s,
    )
    if m_place:
        return m_place.group(1).strip() + "."
    m = re.search(
        r"(?is)(.+?\d{1,2}:\d{2}\s*(?:horas?|hrs)"
        r"(?:\s+en la[^.]{0,160}?presupuestos)?)\s*\.",
        s,
    )
    if m:
        return m.group(1).strip() + "."
    m_date_time = re.search(
        r"(?is)(.+?\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+(?:año\s+)?20\d{2}"
        r"[^.]*?a las \d{1,2}:\d{2}\s*(?:horas?|hrs?))",
        s,
    )
    if m_date_time:
        return m_date_time.group(1).strip() + "."
    m2 = re.search(
        r"(?is)(.+?\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+(?:año\s+)?20\d{2}"
        r"(?:\s*,?\s*a las\s+\d{1,2}:\d{2}\s*(?:horas?|hrs))?)\s*\.",
        s,
    )
    if m2:
        return m2.group(1).strip() + "."
    return _trim_at_sentence_boundary(s)


def _trim_at_sentence_boundary(text: str, max_len: int = 420) -> str:
    """Recorta en fin de oración (punto), sin dejar fragmentos a medias."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return s
    if len(s) <= max_len and s.endswith("."):
        return s
    if len(s) > max_len:
        window = s[:max_len]
        dot = window.rfind(".")
        if dot >= 60:
            return s[: dot + 1].strip()
    if not s.endswith("."):
        dot = s.find(".")
        if 40 <= dot < max_len:
            return s[: dot + 1].strip()
        if dot >= max_len:
            return s[: dot + 1].strip()
    return s[:max_len].rstrip()


def _act_anchor_start(hito_id: str, blob: str, pos: int) -> int:
    """Retrocede al ancla del acto para no arrancar a mitad de dirección."""
    blob_l = blob.lower()
    if hito_id == "junta_aclaraciones":
        for kw in ("junta de aclaraciones", "junta (s) de aclaraciones"):
            jp = blob_l.rfind(kw, 0, pos)
            if jp >= 0 and pos - jp < 420:
                return jp
    if hito_id == "visita_instalaciones":
        for kw in ("visita al sitio", "visita a las instalaciones", "visita a las"):
            ip = blob_l.rfind(kw, 0, pos)
            if ip >= 0 and pos - ip < 260:
                return ip
    if hito_id == "fallo":
        fp = blob_l.rfind("acto de fallo", 0, pos)
        if fp >= 0:
            return fp
    if hito_id == "presentacion_proposiciones":
        for kw in (
            "presentación y apertura",
            "presentacion y apertura",
            "fecha y hora para tal efecto",
        ):
            pp = blob_l.rfind(kw, 0, min(len(blob), pos + 100))
            if pp >= 0 and pp <= pos + 80:
                return pp
    if hito_id == "publicacion_convocatoria":
        for kw in ("publicación de la convocatoria", "publicacion de la convocatoria"):
            pp = blob_l.rfind(kw, 0, pos)
            if pp >= 0 and pos - pp < 320:
                return pp
    if hito_id == "firma_contrato":
        for kw in ("firma del contrato", "firmar el contrato"):
            fp = blob_l.rfind(kw, 0, pos)
            if fp >= 0 and pos - fp < 320:
                return fp
    return pos


def _find_literal_pos(blob: str, literal: str, hito_id: str) -> int:
    """Posición del literal en el blob; evita falsos positivos (p. ej. «juntamente»)."""
    s = re.sub(r"\s+", " ", literal).strip()
    if hito_id == "junta_aclaraciones":
        for kw in ("JUNTA DE ACLARACIONES", "Junta de aclaraciones", "junta de aclaraciones"):
            p = blob.find(kw)
            if p >= 0:
                return p
    if hito_id == "visita_instalaciones":
        for kw in (
            "VISITA AL SITIO",
            "Visita al sitio",
            "visita al sitio",
            "visita a las instalaciones",
        ):
            p = blob.find(kw)
            if p >= 0:
                return p
    if hito_id == "publicacion_convocatoria":
        for kw in (
            "PUBLICACIÓN DE LA CONVOCATORIA",
            "Publicación de la convocatoria",
            "publicación de la convocatoria",
        ):
            p = blob.find(kw)
            if p >= 0:
                return p
    if hito_id == "firma_contrato":
        for kw in ("FIRMA DEL CONTRATO", "Firma del contrato", "firma del contrato"):
            p = blob.find(kw)
            if p >= 0:
                return p
    for n in (80, 64, 48, 32):
        if len(s) < n:
            continue
        needle = s[:n]
        pos = blob.find(needle)
        if pos < 0:
            pos = blob.lower().find(needle.lower())
        if pos >= 0:
            return pos
    return -1


def _extract_complete_sentence_from_blob(
    blob: str, literal: str, hito_id: str, max_len: int = 420
) -> str:
    """Reconstruye oración completa desde el blob íntegro (evita cortes de chunk)."""
    s = re.sub(r"\s+", " ", str(literal or "")).strip()
    if not blob or not s:
        return _trim_at_sentence_boundary(s, max_len=max_len)

    for n in (80, 64, 48, 32):
        if len(s) < n:
            continue
        needle = s[:n]
        pos = _find_literal_pos(blob, needle, hito_id) if n >= 48 else -1
        if pos < 0:
            pos = blob.find(needle)
        if pos < 0:
            pos = blob.lower().find(needle.lower())
        if pos < 0:
            continue
        start = _act_anchor_start(hito_id, blob, pos)
        window = blob[start : start + max_len + 160]
        end_m = re.search(r"\.\s", window)
        if end_m:
            out = re.sub(r"\s+", " ", window[: end_m.start() + 1]).strip()
        else:
            dot = window.find(".")
            out = re.sub(
                r"\s+",
                " ",
                window[: (dot + 1 if dot >= 0 else len(window))],
            ).strip()
        if len(out) >= 30:
            polished = _trim_at_sentence_boundary(out, max_len=max_len)
            if hito_id in (
                "visita_instalaciones",
                "junta_aclaraciones",
                "presentacion_proposiciones",
                "fallo",
            ):
                polished = _trim_procedural_act_sentence(polished)
            return polished
    return _trim_at_sentence_boundary(s, max_len=max_len)


def _polish_presentacion_literal(
    literal: str, raw: str, blob: str, nombre: str
) -> str:
    """Etiqueta el acto y conserva solo la oración con la fecha de apertura."""
    lit_n = _normalize_match_text(literal)
    has_act = "proposicion" in lit_n or "apertura" in lit_n
    date_sent: Optional[str] = None
    for text in (literal, blob):
        for m in re.finditer(
            r"(?is)(el\s+d[ií]a\s+\d{1,2}\s+de\s+[a-záéíóúñü]+(?:\s+(?:de|del)\s+(?:año\s+)?20\d{2})?[^.]*\.)",
            text,
        ):
            if _raw_date_in_literal(raw, m.group(1)):
                date_sent = re.sub(r"\s+", " ", m.group(1)).strip()
                break
        if date_sent:
            break
    if date_sent and not has_act:
        return _trim_at_sentence_boundary(f"{nombre}. {date_sent}")
    if has_act:
        return _extract_complete_sentence_from_blob(
            blob, literal, "presentacion_proposiciones"
        )
    if raw:
        return _trim_at_sentence_boundary(f"{nombre}: {raw}")
    return _trim_at_sentence_boundary(literal)


def _literal_needs_repolish(hito_id: str, literal: str) -> bool:
    """True si el literal persistido quedó corto, en mayúsculas o con ruido de dirección."""
    s = str(literal or "").strip()
    if not s:
        return True
    low = s.lower()
    if re.search(r"\bblvd\b", low):
        return True
    if not s.endswith("."):
        return True
    if hito_id == "junta_aclaraciones" and s.startswith("JUNTA DE"):
        return True
    if hito_id == "fallo" and low.startswith("acto de fallo"):
        return True
    if hito_id == "visita_instalaciones" and low.startswith("visita al sitio"):
        return True
    return False


def _label_procedural_literal(hito_id: str, nombre: str, text: str) -> str:
    """Prefijo legible del acto (misma presentación que presentación de proposiciones)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return s
    if hito_id == "junta_aclaraciones" and s.upper().startswith("JUNTA DE ACLARACIONES"):
        rest = re.sub(
            r"(?is)^junta\s+de\s+aclaraciones\s*",
            "",
            s,
        ).strip()
        if rest:
            lead = rest[0].upper() + rest[1:]
            return f"{nombre}. {lead}" if not lead.endswith(".") else f"{nombre}. {lead}"
    if hito_id == "fallo" and s.lower().startswith("acto de fallo"):
        lead = s[0].upper() + s[1:]
        return lead if lead.endswith(".") else lead + "."
    if hito_id == "visita_instalaciones":
        if s.lower().startswith("visita") and not s.lower().startswith(
            nombre.lower()[:16]
        ):
            lead = s[0].upper() + s[1:]
            return f"{nombre}. {lead}" if not lead.endswith(".") else f"{nombre}. {lead}"
    return s


def _polish_hito_literal(
    hito_id: str,
    literal: str,
    raw: str,
    blob: str,
    hito: Dict[str, Any],
) -> str:
    """Oración legible, con acto identificable y sin truncar a mitad de frase."""
    nombre = str(hito.get("nombre") or _NOMBRES_ES.get(hito_id, hito_id))
    if hito_id == "presentacion_proposiciones":
        return _polish_presentacion_literal(literal, raw, blob, nombre)
    if hito_id in ("publicacion_convocatoria", "firma_contrato"):
        extracted = extract_hito_from_bases_text(hito_id, blob)
        if extracted and _extracted_quality_ok(hito_id, extracted) and _literal_in_blob(
            extracted, blob
        ):
            return _trim_at_sentence_boundary(extracted)
        around = _sentence_around_date(blob, raw, hito_id=hito_id)
        if around:
            return _trim_at_sentence_boundary(around)
        expanded = _extract_complete_sentence_from_blob(blob, literal, hito_id)
        if expanded and len(expanded) > 24:
            return _trim_at_sentence_boundary(expanded)
        if nombre.lower().split(":")[0] in literal.lower()[: max(40, len(nombre))]:
            return _trim_at_sentence_boundary(literal)
        return _trim_at_sentence_boundary(f"{nombre}: {raw}" if raw else literal)
    expanded = _extract_complete_sentence_from_blob(blob, literal, hito_id)
    if hito_id in ("visita_instalaciones", "junta_aclaraciones", "fallo"):
        expanded = _trim_procedural_act_sentence(expanded)
        expanded = _ensure_schedule_time_from_checklist(expanded, raw)
        expanded = _label_procedural_literal(hito_id, nombre, expanded)
    return expanded


def _extracted_quality_ok(hito_id: str, literal: str) -> bool:
    """Rechaza extractos que no mencionan el acto (p. ej. ventana rota por chunk)."""
    lit = _normalize_match_text(literal)
    if not lit:
        return False
    if hito_id == "presentacion_proposiciones":
        return bool(
            re.search(r"\d{1,2}\s+de\s+\w+", lit)
            or "proposicion" in lit
            or "apertura" in lit
            or "entregarse" in lit
            or "fecha y hora para tal efecto" in lit
        )
    required: Dict[str, Tuple[str, ...]] = {
        "junta_aclaraciones": ("junta",),
        "fallo": ("fallo",),
        "firma_contrato": ("firma", "contrato"),
        "visita_instalaciones": ("visita", "sitio", "instalaciones"),
        "publicacion_convocatoria": ("publicacion", "convocatoria"),
    }
    tokens = required.get(hito_id)
    if not tokens:
        return True
    return any(tok in lit for tok in tokens)


def _time_needle_from_raw(raw: str) -> Optional[str]:
    m = re.search(r"(\d{1,2}:\d{2})", str(raw or ""))
    return m.group(1) if m else None


def _sentence_around_date(blob: str, raw: str, hito_id: Optional[str] = None) -> Optional[str]:
    """Oración del blob que contiene la fecha del checklist (fail-closed)."""
    dt = parse_spanish_date_fragment(raw)
    time_needle = _time_needle_from_raw(raw)
    if dt is None:
        needle = _normalize_match_text(raw)[:32]
        blob_n = _normalize_match_text(blob)
        if not needle or needle not in blob_n:
            return None
        day = needle.split()[0] if needle else ""
        pos = blob.lower().find(day) if day else -1
        if pos < 0:
            return None
    else:
        month_names = (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        )
        month = month_names[dt.month - 1]
        patterns = [
            rf"(?is)\bel\s+d[ií]a\s+{dt.day}\s+de\s+{month}[^.\n]{{0,120}}?{re.escape(time_needle)}"
            if time_needle
            else None,
            rf"(?is)\b{dt.day}\s+de\s+{month}[^.\n]{{0,120}}?{re.escape(time_needle)}"
            if time_needle
            else None,
            rf"(?is)\bel\s+d[ií]a\s+{dt.day}\s+de\s+{month}",
            rf"(?is)\b{dt.day}\s+de\s+{month}",
        ]
        pos = -1
        for pat in [p for p in patterns if p]:
            for m in re.finditer(pat, blob):
                if time_needle and time_needle not in m.group(0):
                    continue
                pos = m.start()
                break
            if pos >= 0:
                break
        if pos < 0:
            return None

    start = max(0, blob.rfind(".", 0, pos) + 1, blob.rfind("\n", 0, pos) + 1)
    if hito_id == "junta_aclaraciones":
        blob_l = blob.lower()
        for kw in ("junta de aclaraciones", "junta (s) de aclaraciones"):
            junta_pos = blob_l.rfind(kw, 0, pos)
            if junta_pos >= 0 and pos - junta_pos < 400:
                start = junta_pos
                break
    elif hito_id == "publicacion_convocatoria":
        blob_l = blob.lower()
        for kw in ("publicación de la convocatoria", "publicacion de la convocatoria"):
            pub_pos = blob_l.rfind(kw, 0, pos)
            if pub_pos >= 0 and pos - pub_pos < 400:
                start = pub_pos
                break
    elif hito_id == "firma_contrato":
        blob_l = blob.lower()
        for kw in ("firma del contrato", "firmar el contrato"):
            firma_pos = blob_l.rfind(kw, 0, pos)
            if firma_pos >= 0 and pos - firma_pos < 400:
                start = firma_pos
                break
    end_match = re.search(r"[.\n]", blob[pos:])
    end = pos + (end_match.start() + 1 if end_match else min(420, len(blob) - pos))
    sentence = _clean_literary_sentence(blob[start:end])
    return sentence if len(sentence) > 20 else None


def _pick_hito_literal(hito_id: str, blob: str, hito: Dict[str, Any]) -> Optional[str]:
    raw = str(hito.get("fecha_texto_raw") or "").strip()
    extracted = extract_hito_from_bases_text(hito_id, blob)
    if extracted and _extracted_quality_ok(hito_id, extracted) and _literal_in_blob(
        extracted, blob
    ):
        if hito_id == "presentacion_proposiciones" and _weak_presentacion_literal(
            extracted
        ):
            if _raw_date_in_literal(raw, extracted):
                return _clean_literary_sentence(extracted, max_len=480)
        else:
            return extracted

    if raw and _hito_raw_usable(raw):
        around = _sentence_around_date(blob, raw, hito_id=hito_id)
        if around:
            return around
        nombre = str(hito.get("nombre") or _NOMBRES_ES.get(hito_id, hito_id))
        if _literal_in_blob(raw, blob):
            return f"{nombre}: {raw}"[:480]
        return f"{nombre}: {raw}"[:480]
    return None


def _resolve_literal_page_session_wide(
    vdb: Any,
    session_id: str,
    literal: str,
    raw: str,
) -> Tuple[Optional[Any], Optional[str]]:
    """Busca ancla en cualquier fuente indexada de la sesión (bases, convocatoria)."""
    needles: List[str] = []
    for candidate in (literal, raw):
        if not candidate:
            continue
        norm = _normalize_match_text(candidate)
        if norm:
            needles.append(norm[:80])
            needles.append(norm[:48])
    dt = parse_spanish_date_fragment(raw)
    if dt is not None:
        month_names = (
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        )
        month = month_names[dt.month - 1]
        needles.append(_normalize_match_text(f"{dt.day} de {month}"))
        needles.append(_normalize_match_text(f"{dt.day} de {month} del año {dt.year}"))

    seen: set = set()
    for needle in needles:
        if not needle or needle in seen:
            continue
        seen.add(needle)
        for doc, meta in vdb.scan_session_chunks(session_id):
            if not isinstance(meta, dict):
                continue
            if _normalize_match_text(str(doc or "")).find(needle) >= 0:
                return meta.get("page"), str(meta.get("source") or "")
    return None, None


_CHECKLIST_FALLBACK_CITE = "· Calendario del expediente (Fechas críticas)"


def _hito_raw_usable(raw: str) -> bool:
    """True si el hito del checklist aporta fecha o texto no placeholder."""
    s = str(raw or "").strip()
    if not s:
        return False
    if parse_spanish_date_fragment(s) is not None:
        return True
    return not is_placeholder_cronograma_value(s)


def _bases_blob_from_index(vdb: Any, session_id: str, primary_doc: str) -> str:
    """Texto íntegro del PDF de bases reconstruido desde Chroma (por página)."""
    pages: set = set()
    try:
        for _doc, meta in vdb.scan_session_chunks(session_id, source_filter=primary_doc):
            if isinstance(meta, dict) and meta.get("page") is not None:
                pages.add(meta.get("page"))
    except Exception:
        return ""

    def _page_key(p: Any) -> int:
        try:
            return int(str(p))
        except (TypeError, ValueError):
            return 0

    parts: List[str] = []
    for pg in sorted(pages, key=_page_key):
        chunks = vdb.fetch_page_documents(session_id, primary_doc, pg) or []
        if chunks:
            parts.append("\n".join(chunks))
    return "".join(parts)


def _text_contains_literal(haystack: str, literal: str) -> bool:
    lit_n = _normalize_match_text(literal)
    if not lit_n:
        return False
    hay_n = _normalize_match_text(haystack)
    return lit_n in hay_n or lit_n[:48] in hay_n or lit_n[:32] in hay_n


def _resolve_literal_page(
    vdb: Any,
    session_id: str,
    primary_doc: str,
    literal: str,
    blob: str,
) -> Tuple[Optional[Any], Optional[str]]:
    """Página y fuente indexadas donde aparece el literal (fail-closed si no hay ancla)."""
    if not _normalize_match_text(literal):
        return None, primary_doc

    for doc, meta in vdb.scan_session_chunks(session_id, source_filter=primary_doc):
        if not isinstance(meta, dict):
            continue
        if _text_contains_literal(str(doc or ""), literal):
            return meta.get("page"), str(meta.get("source") or primary_doc)

    pages: set = set()
    for _doc, meta in vdb.scan_session_chunks(session_id, source_filter=primary_doc):
        if isinstance(meta, dict) and meta.get("page") is not None:
            pages.add(meta.get("page"))

    for pg in sorted(pages, key=lambda p: int(str(p)) if str(p).isdigit() else 0):
        page_text = "\n".join(
            vdb.fetch_page_documents(session_id, primary_doc, pg) or []
        )
        if page_text and _text_contains_literal(page_text, literal):
            return pg, primary_doc

    if _literal_in_blob(literal, blob):
        for _doc, meta in vdb.scan_session_chunks(session_id, source_filter=primary_doc):
            if isinstance(meta, dict) and meta.get("page") is not None:
                if _text_contains_literal(str(_doc or ""), literal):
                    return meta.get("page"), str(meta.get("source") or primary_doc)

    return None, primary_doc


def _resolve_primary_bases_doc(session_id: str, vdb: Any) -> Optional[str]:
    """Prioriza BASES sobre CONVOCATORIA en fuentes indexadas de la sesión."""
    sources: List[str] = []
    try:
        for _doc, meta in vdb.scan_session_chunks(session_id):
            if isinstance(meta, dict) and meta.get("source"):
                src = str(meta["source"]).strip()
                if src and src not in sources:
                    sources.append(src)
    except Exception:
        return None
    if not sources:
        return None
    from app.agents.chatbot_rag import ChatbotRAGAgent

    return ChatbotRAGAgent._resolve_primary_bases_doc(sources)


def _build_hito_provenance_ui(
    *,
    checklist_only: bool,
    source: Optional[str],
    page: Optional[Any],
) -> Dict[str, Any]:
    if checklist_only:
        return {
            "source": "submission_checklist",
            "badge": "checklist_calendar",
            "page": None,
            "document": source,
            "anchor_kind": "checklist_fallback",
        }
    return {
        "source": "vector_index",
        "badge": "index_verified",
        "page": page,
        "document": source,
        "anchor_kind": "indexed",
    }


def resolve_hito_literary_bundle(
    hito_id: str,
    hito: Dict[str, Any],
    session_id: str,
    primary_doc: str,
    vdb: Any,
    blob: str,
    cronograma_fragment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Literal, procedencia y fecha compacta para un hito (panel + chat HRU).
    """
    from app.checklist.hito_scheduler import resolve_display_fecha_best

    raw_display = str(hito.get("fecha_texto_raw") or "").strip()
    pick_hito = dict(hito)
    cron_frag = str(cronograma_fragment or "").strip() or None
    if cron_frag and len(cron_frag) > len(raw_display):
        pick_hito["fecha_texto_raw"] = cron_frag

    pick_raw = str(pick_hito.get("fecha_texto_raw") or "").strip()
    if not _hito_raw_usable(pick_raw) and not _hito_raw_usable(raw_display):
        return {}

    if not _hito_raw_usable(pick_raw) and _hito_raw_usable(raw_display):
        pick_hito["fecha_texto_raw"] = raw_display
        pick_raw = raw_display

    literal = _pick_hito_literal(hito_id, blob, pick_hito)
    if not literal:
        nombre = str(hito.get("nombre") or _NOMBRES_ES.get(hito_id, hito_id))
        literal = f"{nombre}: {pick_raw or raw_display}"[:480]

    literal = _polish_hito_literal(hito_id, literal, pick_raw or raw_display, blob, hito)

    extracted = extract_hito_from_bases_text(hito_id, blob)
    page_candidates = [literal, extracted, pick_raw, raw_display, cron_frag or ""]
    page, source = None, primary_doc
    for candidate in page_candidates:
        if not candidate:
            continue
        page, source = _resolve_literal_page(
            vdb, session_id, primary_doc, str(candidate), blob
        )
        if page is not None:
            break
    checklist_only = False
    if page is None:
        page, source = _resolve_literal_page_session_wide(
            vdb, session_id, literal, pick_raw or raw_display
        )
    if page is None:
        checklist_only = True
        source = primary_doc

    fecha_texto_raw, fecha_hora = resolve_display_fecha_best(
        extracted,
        literal,
        cron_frag,
        pick_raw,
        raw_display,
    )

    return {
        "fecha_texto_raw": fecha_texto_raw,
        "fecha_hora": fecha_hora,
        "bases_literal": literal,
        "provenance_ui": _build_hito_provenance_ui(
            checklist_only=checklist_only,
            source=source,
            page=page,
        ),
        "checklist_only": checklist_only,
        "page": page,
        "source": source,
    }


def enrich_checklist_hitos_literary(
    hitos: List[Dict[str, Any]],
    session_id: str,
    session_state: Dict[str, Any],
    cronograma: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Enriquece hitos con literal de bases, procedencia y fecha compacta (HRU).
    """
    if not hitos or not session_id:
        return hitos

    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    primary_doc = _resolve_primary_bases_doc(session_id, vdb)
    if not primary_doc:
        return hitos

    blob = _bases_blob_from_index(vdb, session_id, primary_doc)
    if len(blob) < 80:
        blob = ""

    out: List[Dict[str, Any]] = []
    for h in hitos:
        if not isinstance(h, dict):
            out.append(h)
            continue
        hid = str(h.get("id") or "")
        if hid not in _HITO_ORDER:
            out.append(dict(h))
            continue
        cron_frag = None
        if isinstance(cronograma, dict):
            cron_frag = str(cronograma.get(hid) or "").strip() or None
        enriched = dict(h)
        if blob:
            bundle = resolve_hito_literary_bundle(
                hid,
                enriched,
                session_id,
                primary_doc,
                vdb,
                blob,
                cronograma_fragment=cron_frag,
            )
            if bundle.get("fecha_texto_raw"):
                enriched["fecha_texto_raw"] = bundle["fecha_texto_raw"]
            if bundle.get("fecha_hora") is not None:
                enriched["fecha_hora"] = bundle["fecha_hora"]
            if bundle.get("bases_literal"):
                enriched["bases_literal"] = bundle["bases_literal"]
            if bundle.get("provenance_ui"):
                enriched["provenance_ui"] = bundle["provenance_ui"]
        elif cron_frag:
            from app.checklist.hito_scheduler import _resolve_display_fecha_raw

            fecha_raw, fecha_hora = _resolve_display_fecha_raw(cron_frag)
            enriched["fecha_texto_raw"] = fecha_raw
            if fecha_hora is not None:
                enriched["fecha_hora"] = fecha_hora
        out.append(enriched)
    return out


def build_canonical_literary_cronogram(
    session_state: Dict[str, Any],
    session_id: str,
    primary_doc: str,
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """
    Viñetas literales en orden de hitos del checklist, ancladas al índice.

    Returns:
        (bullets_markdown, top_citation_dict)
    """
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.services.vector_service import VectorDbServiceClient

    if not session_id or not primary_doc:
        return [], None

    checklist = session_state.get("submission_checklist") or {}
    hitos_raw = checklist.get("hitos") or []
    hitos_by_id = {
        str(h.get("id")): h
        for h in hitos_raw
        if isinstance(h, dict) and h.get("id")
    }
    if not hitos_by_id:
        return [], None

    vdb = VectorDbServiceClient()
    blob = _bases_blob_from_index(vdb, session_id, primary_doc)
    if len(blob) < 200:
        return [], None

    bullets: List[str] = []
    top_citation: Optional[Dict[str, Any]] = None

    for hito_id in _HITO_ORDER:
        hito = hitos_by_id.get(hito_id)
        if not hito:
            continue
        raw = str(hito.get("fecha_texto_raw") or "").strip()
        if not _hito_raw_usable(raw):
            continue

        stored_literal = str(hito.get("bases_literal") or "").strip()
        prov = hito.get("provenance_ui") if isinstance(hito.get("provenance_ui"), dict) else {}
        if stored_literal and not _literal_needs_repolish(hito_id, stored_literal):
            literal = stored_literal
            checklist_only = prov.get("anchor_kind") == "checklist_fallback"
            page = prov.get("page")
            source = str(prov.get("document") or primary_doc)
        else:
            bundle = resolve_hito_literary_bundle(
                hito_id, hito, session_id, primary_doc, vdb, blob
            )
            literal = str(bundle.get("bases_literal") or "").strip()
            if not literal:
                continue
            checklist_only = bool(bundle.get("checklist_only"))
            page = bundle.get("page")
            source = str(bundle.get("source") or primary_doc)

        if checklist_only:
            cite = _CHECKLIST_FALLBACK_CITE
        else:
            cite = ChatbotRAGAgent._format_literary_cite(
                {"source": source, "page": page}, primary_doc
            )
        bullets.append(f"- {literal}\n  {cite}")
        citation = {
            "literal": literal,
            "source": source,
            "page": page,
            "hito_id": hito_id,
            "checklist_only": checklist_only,
        }
        if top_citation is None and not checklist_only:
            top_citation = citation

    return bullets, top_citation
