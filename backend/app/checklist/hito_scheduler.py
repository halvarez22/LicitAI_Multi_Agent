"""
Construcción y actualización de hitos a partir del cronograma normalizado del AnalystAgent.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.agents.analyst import normalize_cronograma_dict

# Orden de presentación en UI (mismo orden canónico que el analista).
_HITO_ORDER: Tuple[str, ...] = (
    "publicacion_convocatoria",
    "visita_instalaciones",
    "junta_aclaraciones",
    "presentacion_proposiciones",
    "fallo",
    "firma_contrato",
)

_NOMBRES_ES: Dict[str, str] = {
    "publicacion_convocatoria": "Publicación de la convocatoria",
    "visita_instalaciones": "Visita a instalaciones",
    "junta_aclaraciones": "Junta de aclaraciones",
    "presentacion_proposiciones": "Presentación y apertura de proposiciones",
    "fallo": "Fallo",
    "firma_contrato": "Firma del contrato",
}

# Patrones comunes en bases mexicanas: DD/MM/YYYY [HH:MM] [hrs]
_RE_FECHA = re.compile(
    r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b"
    r"(?:\s+(\d{1,2})[:h](\d{2})(?:\s*(?:hrs?|horas?)?)?)?",
    re.IGNORECASE,
)


def parse_fecha_hito(texto: str) -> Optional[datetime]:
    """
    Intenta obtener un datetime naive a partir de fragmentos típicos en bases (México).

    Returns:
        datetime o None si no hay match o el texto es claramente no fechable.
    """
    if not texto or not isinstance(texto, str):
        return None
    t = texto.strip()
    low = t.lower()
    if not t or low in ("no especificado", "n/e", "—", "-", "según bases", "por definir"):
        return None
    m = _RE_FECHA.search(t.replace("h", ":", 1) if "h" in low and ":" not in t else t)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    hh, mm = 0, 0
    if m.group(4) and m.group(5):
        hh, mm = int(m.group(4)), int(m.group(5))
    try:
        return datetime(y, mo, d, hh, mm, 0, 0)
    except ValueError:
        return None


def _hito_dict_from_canon(hito_id: str, valor_cronograma: str) -> Dict[str, Any]:
    nombre = _NOMBRES_ES.get(hito_id, hito_id.replace("_", " ").title())
    raw = (valor_cronograma or "").strip() or "No especificado"
    parsed = parse_fecha_hito(raw)
    return {
        "id": hito_id,
        "nombre": nombre,
        "fecha_texto_raw": raw,
        "fecha_hora": parsed,
        "obligatorio": True,
        "estado": "pendiente",
        "evidencia": None,
        "notificado": False,
    }


def build_hitos_from_cronograma(cronograma: Any) -> List[Dict[str, Any]]:
    """Normaliza cronograma y devuelve lista de dicts listos para HitoModel."""
    norm = normalize_cronograma_dict(cronograma)
    return [_hito_dict_from_canon(k, norm.get(k, "No especificado")) for k in _HITO_ORDER]


def merge_hitos_preservar_completados(
    nuevos: List[Dict[str, Any]],
    anteriores: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Tras re-ejecutar el Analista: actualiza textos/fechas pero conserva completado y evidencia.
    """
    prev_by_id = {h.get("id"): h for h in anteriores if isinstance(h, dict) and h.get("id")}
    out: List[Dict[str, Any]] = []
    for h in nuevos:
        hid = h.get("id")
        old = prev_by_id.get(hid)
        if old and old.get("estado") == "completado":
            merged = {**h, "estado": "completado", "evidencia": old.get("evidencia")}
            if old.get("notificado"):
                merged["notificado"] = True
            out.append(merged)
        else:
            out.append(dict(h))
    return out


def aplicar_estados_vencido(hitos: List[Dict[str, Any]], ahora: Optional[datetime] = None) -> None:
    """Marca vencido si hay fecha parseada en el pasado y el hito no está completado."""
    now = ahora or datetime.utcnow()
    for h in hitos:
        if h.get("estado") == "completado":
            continue
        fh = h.get("fecha_hora")
        if isinstance(fh, datetime) and fh < now:
            h["estado"] = "vencido"


def calcular_porcentaje(hitos: List[Dict[str, Any]]) -> float:
    if not hitos:
        return 0.0
    done = sum(1 for h in hitos if h.get("estado") == "completado")
    return round(100.0 * done / len(hitos), 1)
