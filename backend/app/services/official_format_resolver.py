"""
Resolver HRU de machotes oficiales publicados en bases.

Fase 0: modo estricto, shell [Consignar] si hay evidencia de formato y no hay espejo;
bloqueo de LLM en anexos obra|T/E. Fase 1+: extract/fill unificado por dedupe_key.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "official_format_policy.json"
)


@lru_cache(maxsize=1)
def load_official_format_policy() -> Dict[str, Any]:
    """Carga política versionada de anclas y decisiones HRU."""
    if not _POLICY_PATH.is_file():
        return {}
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def official_mirror_strict_enabled() -> bool:
    """True si el modo estricto HRU está activo (default: True)."""
    return bool(getattr(settings, "OFFICIAL_MIRROR_STRICT", True))


def policy_annex_entry(dedupe_key: str) -> Optional[Dict[str, Any]]:
    annexes = load_official_format_policy().get("annexes") or {}
    return annexes.get(str(dedupe_key or "").strip()) if dedupe_key else None


def economic_envelope_dedupe_keys() -> List[str]:
    raw = load_official_format_policy().get("economic_envelope_dedupe_keys") or []
    return [str(k) for k in raw]


def is_llm_blocked_obra_annex(dedupe_key: str = "", req_label: str = "") -> bool:
    """
    True si, en modo estricto, no debe usarse LLM para redactar el cuerpo.

    Aplica a anexos obra|T* y obra|E* (formatos de pliego).
    """
    if not official_mirror_strict_enabled():
        return False
    key = str(dedupe_key or pliego_format_dedupe_key(req_label) or "").strip()
    if not key.startswith("obra|"):
        return False
    prefixes = load_official_format_policy().get("llm_blocked_dedupe_prefixes") or [
        "obra|E",
        "obra|T",
    ]
    return any(key.startswith(str(p)) for p in prefixes)


def corpus_has_format_anchors(corpus: str, dedupe_key: str) -> bool:
    """
    True si el corpus contiene anclas suficientes del machote publicado en bases.
    """
    entry = policy_annex_entry(dedupe_key)
    if not entry:
        return False
    text = str(corpus or "").upper()
    anchors = [str(a).upper() for a in (entry.get("anchors") or []) if a]
    min_hits = int(entry.get("min_anchors") or 2)
    hits = sum(1 for a in anchors if a in text)
    return hits >= min(min_hits, len(anchors))


def should_use_miss_shell_instead_of_generic(
    corpus: str,
    dedupe_key: str,
) -> bool:
    """
    Modo estricto: si las bases publicaron machote pero no se extrajo espejo,
    devolver shell [Consignar] en lugar de carta genérica inventada.
    """
    if not official_mirror_strict_enabled():
        return False
    return corpus_has_format_anchors(corpus, dedupe_key)


def build_official_miss_shell(
    dedupe_key: str,
    *,
    concurso: str = "",
    req_line: str = "",
    master_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Documento mínimo cuando hay evidencia de machote oficial pero no se pudo espejar.

    Fail-closed HRU: placeholders explícitos, sin redacción genérica sustituta.
    """
    entry = policy_annex_entry(dedupe_key) or {}
    label = str(entry.get("label_es") or dedupe_key.replace("obra|", "Anexo "))
    mp = master_profile or {}
    razon = str(mp.get("razon_social") or "[Consignar — razón social]").strip()
    rep = str(
        mp.get("representante_legal") or mp.get("representante") or "[Consignar — representante legal]"
    ).strip()
    concurso_line = str(concurso or "[Consignar — número de licitación]").strip()
    req = str(req_line or "Requisito publicado en bases del concurso.").strip()

    lines = [
        f"**{label.upper()}**",
        f"**Concurso:** {concurso_line}",
        f"**Requisito publicado en bases:** {req}",
        "",
        "**[Consignar]** — Las bases publican un **formato oficial** para este anexo. "
        "El sistema no pudo extraer el machote del índice de bases con anclas verificables. "
        "Revise que el PDF de bases esté indexado o adjunte el formato en el canal de carga.",
        "",
        "Campos pendientes de verificación:",
        "- Texto íntegro del machote publicado por la convocante",
        "- Datos del oferente y montos desde motor económico verificado",
        "",
        f"**Participante:** {razon}",
        f"**Representante legal:** {rep}",
        "",
        "Protesto lo necesario una vez integrado el formato oficial.",
    ]
    return "\n".join(lines)


def resolve_materialization_meta(
    *,
    dedupe_key: str,
    content: str,
    official_mirror: bool = False,
    route: str = "",
) -> Dict[str, Any]:
    """Metadata unificada de procedencia para entrega y gates."""
    strict = official_mirror_strict_enabled()
    expected = bool(policy_annex_entry(dedupe_key)) or dedupe_key in economic_envelope_dedupe_keys()
    return {
        "dedupe_key": dedupe_key,
        "official_bases_mirror": bool(official_mirror),
        "official_template_expected": expected and strict,
        "materialization_route": route or (
            "official_bases_mirror" if official_mirror else "deterministic_clause"
        ),
        "official_mirror_strict": strict,
    }
