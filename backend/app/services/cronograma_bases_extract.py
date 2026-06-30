"""
Extracción determinista de fechas de actos licitatorios desde texto de bases/convocatoria.

Sin hardcodes por licitación: patrones de redacción frecuentes en bases mexicanas.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Pattern, Tuple

from app.agents.analyst import normalize_cronograma_dict
from app.services.cronograma_enrichment_service import is_placeholder_cronograma_value

# Fragmento de fecha en español (MX): «26 de enero del 2026», «10 de diciembre del año 2025», hora opcional.
_DATE_ES = (
    r"\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+(?:año\s+)?20\d{2}"
    r"(?:\s*(?:,|\s+)?(?:a\s+las\s+)?\d{1,2}[:h]\d{2}(?:\s*(?:a\.?m\.?|p\.?m\.?|horas?|hrs?\.?)?)?)?"
)

_RE_DATE_ES = re.compile(_DATE_ES, re.IGNORECASE)
_RE_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")

_HITO_LABELS_ES: Dict[str, str] = {
    "publicacion_convocatoria": "Publicación de la convocatoria",
    "visita_instalaciones": "Visita a instalaciones",
    "junta_aclaraciones": "Junta de aclaraciones",
    "presentacion_proposiciones": "Presentación y apertura de proposiciones",
    "fallo": "Fallo",
    "firma_contrato": "Firma del contrato",
}

# Filas típicas en tablas «Evento | Fecha | Hora» (estatales, UNAQ, universidades).
_EVENTO_ROW_ALIASES: Dict[str, Tuple[str, ...]] = {
    "publicacion_convocatoria": (
        r"env[ií]o\s+de\s+invitaciones",
        r"publicaci[oó]n\s+de\s+la\s+convocatoria",
    ),
    "visita_instalaciones": (
        r"visita\s+al\s+sitio",
        r"visita\s+a\s+las?\s+instalaciones",
    ),
    "junta_aclaraciones": (
        r"junta\s+de\s+aclaraciones?",
    ),
    "presentacion_proposiciones": (
        r"recepci[oó]n\s+de\s+propuestas",
        r"presentaci[oó]n\s+y\s+apertura",
        r"apertura\s+de\s+propuestas\s+t[eé]cnicas",
    ),
    "fallo": (
        r"emisi[oó]n\s+de\s+fallo",
        r"^fallo\b",
    ),
    "firma_contrato": (
        r"firma\s+del\s+contrato",
    ),
}

# Oración típica tras encabezado de acto.
_RE_SE_LLEVARA = re.compile(
    rf"(?is)(se\s+llevar[aá]\s+a\s+cabo\s+(?:el\s+)?(?:d[ií]a\s+)?{_DATE_ES}[^.]+\.)"
)
_RE_ENTREGARSE = re.compile(
    rf"(?is)(entregarse\s+a\s+m[aá]s\s+tardar\s+(?:el\s+)?(?:d[ií]a\s+)?{_DATE_ES}[^.]+\.)"
)
_RE_VISITAS_PLURAL = re.compile(
    rf"(?is)(las?\s+visitas?\s+se\s+llevar[aá]n\s+a\s+cabo[^.]+\.)"
)
_RE_ACTO_FALLO = re.compile(
    rf"(?is)((?:celebrar[aá]\s+el\s+)?acto\s+de\s+fallo[^.]{{0,160}}?{_DATE_ES}[^.]+\.)"
)

# Ventana de texto tras ancla de sección (bases OPM, CDMX, estatales, etc.).
_SECTION_ANCHORS: Dict[str, Tuple[str, ...]] = {
    "visita_instalaciones": (
        r"(?is)\bvisita\s+(?:a[l]?\s+)?(?:el\s+)?(?:sitio|instalaciones?)",
        r"(?is)\bvisitas?\s+a[l]?\s+instalaciones",
        r"(?is)\bvisita\s+al\s+sitio\b",
    ),
    "junta_aclaraciones": (
        r"(?is)\bjunta\s+(?:\(s\)\s+)?de\s+aclaraciones\b",
    ),
    "presentacion_proposiciones": (
        r"(?is)\b(?:acto\s+de\s+)?presentaci[oó]n\s+y\s+apertura\s+de\s+proposiciones\b",
        r"(?is)\bfecha\s+y\s+hora\s+para\s+tal\s+efecto\b",
    ),
    "fallo": (
        r"(?is)\bacto\s+de\s+fallo\b",
        r"(?is)\bg\)\s*fallo\b",
        r"(?is)\bfallo\s+se\s+llevar",
    ),
    "firma_contrato": (
        r"(?is)\b(?:firma\s+del\s+contrato|firmar\s+el\s+contrato)\b",
        r"(?is)\bh\)\s*firma\s+del\s+contrato\b",
    ),
    "publicacion_convocatoria": (
        r"(?is)\bpublicaci[oó]n\s+de\s+la\s+convocatoria\b",
        r"(?is)\bconvocatoria\s+se\s+public",
    ),
}

_SENTENCE_PATTERNS: Tuple[Pattern[str], ...] = (
    _RE_SE_LLEVARA,
    _RE_ENTREGARSE,
    _RE_VISITAS_PLURAL,
    _RE_ACTO_FALLO,
    re.compile(
        rf"(?is)((?:presentaci[oó]n|junta|visita|fallo|firma)[^.]{{0,80}}?{_DATE_ES}[^.]+\.)"
    ),
)

_HITO_GENERIC_SENTENCE_RE: Dict[str, Pattern[str]] = {
    "publicacion_convocatoria": re.compile(
        rf"(?is)((?:publicaci[oó]n|convocatoria)[^.]{{0,120}}?{_DATE_ES}[^.]+\.)"
    ),
    "visita_instalaciones": re.compile(
        rf"(?is)((?:visita|visitas)[^.]{{0,160}}?{_DATE_ES}[^.]+\.)"
    ),
    "junta_aclaraciones": re.compile(
        rf"(?is)(junta[^.]{{0,160}}?{_DATE_ES}[^.]+\.)"
    ),
    "presentacion_proposiciones": re.compile(
        rf"(?is)((?:presentaci[oó]n|entregarse)[^.]{{0,200}}?{_DATE_ES}[^.]+\.)"
    ),
    "fallo": re.compile(rf"(?is)(fallo[^.]{{0,200}}?{_DATE_ES}[^.]+\.)"),
    "firma_contrato": re.compile(
        rf"(?is)((?:firma\s+del\s+contrato|firmar\s+el\s+contrato)[^.]{{0,160}}?{_DATE_ES}[^.]+\.)"
    ),
}


def _patterns_for_hito(hito_id: Optional[str]) -> Tuple[Pattern[str], ...]:
    """Patrones de oración acotados al acto; evita arrastrar «acto de fallo» a otros hitos."""
    if not hito_id:
        return _SENTENCE_PATTERNS
    out: List[Pattern[str]] = []
    if hito_id == "visita_instalaciones":
        out.extend((_RE_VISITAS_PLURAL, _RE_SE_LLEVARA))
    elif hito_id == "junta_aclaraciones":
        out.append(_RE_SE_LLEVARA)
    elif hito_id == "presentacion_proposiciones":
        out.extend((_RE_ENTREGARSE, _RE_SE_LLEVARA))
    elif hito_id == "fallo":
        out.extend((_RE_ACTO_FALLO, _RE_SE_LLEVARA))
    elif hito_id == "firma_contrato":
        out.append(_RE_SE_LLEVARA)
    else:
        out.append(_RE_SE_LLEVARA)
    generic = _HITO_GENERIC_SENTENCE_RE.get(hito_id)
    if generic is not None:
        out.append(generic)
    return tuple(out)


def _clean_sentence(text: str, max_len: int = 420) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def _extract_in_window(window: str, hito_id: Optional[str] = None) -> Optional[str]:
    if not window or not window.strip():
        return None
    for pat in _patterns_for_hito(hito_id):
        m = pat.search(window)
        if m:
            cleaned = _clean_sentence(m.group(1))
            if cleaned and not is_placeholder_cronograma_value(cleaned):
                return cleaned
    dm = _RE_DATE_ES.search(window)
    if dm:
        start = max(0, dm.start() - 80)
        snippet = _clean_sentence(window[start : dm.end() + 60])
        if snippet and not is_placeholder_cronograma_value(snippet):
            return snippet
    return None


def _window_after_anchor(blob: str, anchor: str, width: int = 650) -> str:
    m = re.search(anchor, blob)
    if not m:
        return ""
    # Incluye el ancla para capturar «acto de fallo el día…» y variantes similares.
    return blob[m.start() : m.end() + width]


def extract_hito_from_bases_text(hito_id: str, blob: str) -> Optional[str]:
    """Devuelve oración con fecha para un hito o None si no hay señal en el texto."""
    if not blob or not hito_id:
        return None
    for anchor in _SECTION_ANCHORS.get(hito_id, ()):
        found = _extract_in_window(_window_after_anchor(blob, anchor), hito_id=hito_id)
        if found:
            return found
    return None


# Tablas «Evento | Fecha | Lugar» (CompraNet, ISSSTE, dependencias federales).
_CRONO_TABLE_ROW_SPECS: Tuple[Tuple[str, str], ...] = (
    (
        "publicacion_convocatoria",
        r"(?is)publicaci[oó]n\s+de\s+la\s+convocatoria\s*\|\s*([^|]+?)\s*\|",
    ),
    (
        "visita_instalaciones",
        r"(?is)visita\s+a\s+las?\s+instalaciones\s*\|\s*([^|]+?)\s*\|",
    ),
    (
        "junta_aclaraciones",
        r"(?is)junta\s+de\s+aclaraci[oó]n(?:es)?(?:\s+(?:a\s+las?\s+)?bases)?\s*\|\s*([^|]+?)\s*\|",
    ),
    (
        "presentacion_proposiciones",
        r"(?is)presentaci[oó]n\s+y\s+apertura.{0,200}?\|\s*([^|]+?)\s*\|",
    ),
    ("fallo", r"(?is)\bfallo\s*\|\s*([^|]+?)\s*\|"),
    (
        "firma_contrato",
        r"(?is)firma\s+del\s+contrato\s*\|\s*([^|]+?)\s*\|",
    ),
)


def _hito_sentence(hito_id: str, val: str) -> str:
    label = _HITO_LABELS_ES.get(hito_id, hito_id)
    return _clean_sentence(f"{label}: {val}", max_len=220)


def _table_cell_to_cronograma_sentence(hito_id: str, cell: str) -> Optional[str]:
    """Convierte celda de fecha de tabla en fragmento parseable (conserva hora si existe)."""
    val = re.sub(r"\s+", " ", str(cell or "").replace("\n", " ").strip())
    if not val:
        return None
    if is_placeholder_cronograma_value(val):
        # Celdas cortas «04 de enero de 2024» / «17/04/2026» son fechas válidas en tablas.
        if _RE_DATE_ES.search(val) and len(val) < 28 and _RE_DATE_ES.search(val).group(0).strip() == val.strip():
            pass
        elif _RE_SLASH_DATE.search(val) and len(val) < 16:
            pass
        else:
            return None
    if not _RE_DATE_ES.search(val) and not _RE_SLASH_DATE.search(val):
        return None
    if _RE_DATE_ES.search(val) and len(val) >= 28 and is_placeholder_cronograma_value(val):
        return None
    return _hito_sentence(hito_id, val)


def _event_cell_matches(hito_id: str, event_cell: str) -> bool:
    cell = re.sub(r"\s+", " ", str(event_cell or "").strip().lower())
    if not cell or cell.startswith("---") or cell == "evento":
        return False
    for pat in _EVENTO_ROW_ALIASES.get(hito_id, ()):
        if re.search(pat, cell, re.I):
            return True
    return False


def _merge_evento_table_lines(lines: list[str]) -> list[str]:
    """Une filas partidas por OCR (nombre del evento en una línea, fecha en la siguiente)."""
    merged: list[str] = []
    buf = ""
    for line in lines:
        if re.match(r"^\s*---", line):
            continue
        if re.search(r"\b\d{1,2}/\d{1,2}/20\d{2}\b", line) or (buf and "|" in line):
            if buf:
                line = f"{buf} {line}".strip()
                buf = ""
            merged.append(line)
        elif "|" in line:
            merged.append(line)
        elif line.strip():
            buf = f"{buf} {line}".strip() if buf else line.strip()
    if buf:
        merged.append(buf)
    return merged


def _extract_evento_fecha_hora_pipe_table(blob: str) -> Dict[str, str]:
    """Tablas Evento | Fecha | Hora con fechas dd/mm/yyyy (OCR markdown, estatales/UNAQ)."""
    out: Dict[str, str] = {}
    if not re.search(r"Evento\s*\|[^\n]{0,80}Fecha", blob, re.I):
        return out
    header = re.search(r"(?im)^\s*\|?\s*Evento\s*\|", blob)
    if not header:
        return out
    chunk = blob[header.start() : header.start() + 4500]
    for line in _merge_evento_table_lines(chunk.splitlines()):
        date_m = _RE_SLASH_DATE.search(line)
        if not date_m or "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        event_cell = cells[0] if cells else line.split("|", 1)[0]
        time_m = re.search(
            r"(\d{1,2}[:h]\d{2}(?:\s*hrs?\.?)?(?:\s+\d{1,2}[:h]\d{2}(?:\s*hrs?\.?)?)?)",
            line[date_m.end() :],
            re.I,
        )
        date_val = date_m.group(0)
        if time_m:
            date_val = f"{date_val} {time_m.group(1).strip()}"
        for hito_id in _HITO_LABELS_ES:
            if hito_id in out:
                continue
            if _event_cell_matches(hito_id, event_cell):
                sentence = _hito_sentence(hito_id, date_val)
                if sentence:
                    out[hito_id] = sentence
                break
    return out


def _year_from_cronograma_fragment(text: str) -> Optional[int]:
    if not text:
        return None
    parsed = parse_spanish_date_fragment(str(text))
    if parsed is not None:
        return parsed.year
    m = re.search(r"\b(20\d{2})\b", str(text))
    return int(m.group(1)) if m else None


def _dominant_corpus_years(blob: str, min_hits: int = 5) -> Tuple[str, ...]:
    from collections import Counter

    counts = Counter(re.findall(r"20\d{2}", str(blob or "")))
    return tuple(y for y, n in counts.most_common(5) if n >= min_hits)


def _cronograma_year_unsupported_by_corpus(text: str, blob: str) -> bool:
    """True si el año citado no aparece en el corpus y hay otro año dominante."""
    year = _year_from_cronograma_fragment(text)
    if year is None:
        return False
    year_s = str(year)
    if len(re.findall(re.escape(year_s), blob)) >= 3:
        return False
    dominant = _dominant_corpus_years(blob)
    return bool(dominant and year_s not in dominant)


def _scrub_untrusted_cronograma(out: Dict[str, str], blob: str) -> Dict[str, str]:
    cleaned = dict(out)
    for key, val in list(cleaned.items()):
        if is_placeholder_cronograma_value(val):
            continue
        if _cronograma_year_unsupported_by_corpus(val, blob):
            cleaned[key] = "No especificado"
    return cleaned


_RE_TABLE_JUNK_CELL = re.compile(
    r"(?is)fecha\s+y\s+hora|^\s*---\s*$|\bturno\b|\bpuntos\b",
)


def _score_calendar_table_match(
    hito_id: str, cell: str, match: re.Match[str], blob: str
) -> int:
    """Mayor puntaje = celda de fecha más probable en tabla de calendario."""
    sentence = _table_cell_to_cronograma_sentence(hito_id, cell)
    if not sentence:
        return -1
    score = 10
    if _RE_DATE_ES.search(cell):
        score += 25
    if _RE_SLASH_DATE.search(cell):
        score += 25
    if _RE_TABLE_JUNK_CELL.search(cell.strip()):
        score -= 80
    anchor = blob.rfind("Evento | Fecha", 0, match.start())
    if anchor < 0:
        anchor = blob.rfind("Evento|Fecha", 0, match.start())
    if anchor >= 0 and match.start() - anchor < 3000:
        score += 35
    return score


def extract_cronograma_from_calendar_table(blob: str) -> Dict[str, str]:
    """
    Extrae fechas desde tablas markdown/OCR con columnas Evento | Fecha | Lugar.

    Usa el mejor match por hito (no el primero) para evitar falsos positivos narrativos.
    """
    out: Dict[str, str] = {}
    if not str(blob or "").strip():
        return out
    out.update(_extract_evento_fecha_hora_pipe_table(blob))
    for hito_id, pattern in _CRONO_TABLE_ROW_SPECS:
        if hito_id in out:
            continue
        best: Optional[re.Match[str]] = None
        best_score = -1
        for m in re.finditer(pattern, blob):
            sc = _score_calendar_table_match(hito_id, m.group(1), m, blob)
            if sc > best_score:
                best_score = sc
                best = m
        if best is None or best_score < 0:
            continue
        sentence = _table_cell_to_cronograma_sentence(hito_id, best.group(1))
        if sentence:
            out[hito_id] = sentence
    return out


def cronograma_has_extracted_dates(cronograma: object, *, min_dates: int = 1) -> bool:
    """True si el dict normalizado tiene al menos ``min_dates`` actos con fecha real (no placeholder)."""
    norm = normalize_cronograma_dict(cronograma)
    count = 0
    for val in norm.values():
        s = str(val or "").strip()
        if not s:
            continue
        if parse_spanish_date_fragment(s) is not None:
            count += 1
            continue
        if not is_placeholder_cronograma_value(s):
            count += 1
    return count >= min_dates


def extract_cronograma_from_bases_text(blob: str) -> Dict[str, str]:
    """
    Recorre todas las claves canónicas y completa las que tengan ancla + fecha en el corpus.
    Prioridad: tabla Evento|Fecha, luego anclas por sección narrativa.
    """
    out: Dict[str, str] = {}
    if not str(blob or "").strip():
        return out
    norm_blob = blob
    table = extract_cronograma_from_calendar_table(norm_blob)
    out.update(table)
    for hito_id in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    ):
        if hito_id in out:
            continue
        val = extract_hito_from_bases_text(hito_id, norm_blob)
        if val:
            out[hito_id] = val
    return out


def merge_cronograma_with_bases(
    cronograma: object,
    bases_text: str,
) -> Dict[str, str]:
    """
    Fusiona cronograma del analista con extracción determinista.

    La tabla «Evento | Fecha» tiene prioridad sobre valores ya guardados (corrige fechas
    erróneas del LLM). Los anclas narrativas solo rellenan placeholders restantes.
    """
    blob = str(bases_text or "")
    if not blob.strip():
        return normalize_cronograma_dict(cronograma)
    out = _scrub_untrusted_cronograma(normalize_cronograma_dict(cronograma), blob)
    table = extract_cronograma_from_calendar_table(blob)
    for key, val in table.items():
        if val and not is_placeholder_cronograma_value(val):
            out[key] = val
    for hito_id in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    ):
        current = out.get(hito_id)
        if not is_placeholder_cronograma_value(current) and not _cronograma_year_unsupported_by_corpus(
            str(current or ""), blob
        ):
            continue
        val = extract_hito_from_bases_text(hito_id, blob)
        if val:
            out[hito_id] = val
    return out


_MESES_ES: Dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFD", s)
    return "".join(c for c in nk if unicodedata.category(c) != "Mn")


def parse_spanish_date_fragment(text: str):
    """
    Intenta parsear «DD de mes de|del YYYY [a las HH:MM]» desde un fragmento de bases.

    Returns:
        datetime naive o None.
    """
    from datetime import datetime

    if not text:
        return None
    m = re.search(
        r"(?i)(\d{1,2})\s+de\s+([a-záéíóúñü]+)\s+(?:de|del)\s+(?:año\s+)?(20\d{2})",
        str(text),
    )
    if not m:
        slash = _RE_SLASH_DATE.search(str(text))
        if slash:
            day, month, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
            try:
                return datetime(year, month, day, 0, 0, 0, 0)
            except ValueError:
                return None
        return None
    day = int(m.group(1))
    month_name = _strip_accents(m.group(2).lower())
    year = int(m.group(3))
    month = _MESES_ES.get(month_name)
    if not month:
        return None
    hh, mm = 0, 0
    tail = text[m.end() : m.end() + 80]
    tm = re.search(
        r"(?i)(?:a\s+las\s+)?(\d{1,2})[:h](\d{2})(?:\s*(?:a\.?m\.?|p\.?m\.?|horas?)?)?",
        tail,
    )
    if not tm:
        tm = re.search(r"(?i)(\d{1,2})[:h](\d{2})\s*horas", text[m.start() : m.end() + 120])
    if tm:
        hh, mm = int(tm.group(1)), int(tm.group(2))
        if re.search(r"(?i)p\.?\s*m", tail) and hh < 12:
            hh += 12
    try:
        return datetime(year, month, day, hh, mm, 0, 0)
    except ValueError:
        return None
