"""
Capa determinista de intención conversacional (SUPER ISSUE S.1–S.2).

Sin LLM ni hardcode por licitación: reglas sobre texto normalizado + contexto HITL.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class UserChatIntent(str, Enum):
    """Intenciones canónicas del chat licitante."""

    COTIZAR = "COTIZAR"
    GENERAR_EXPEDIENTE = "GENERAR_EXPEDIENTE"
    RESPONDER_PENDIENTE = "RESPONDER_PENDIENTE"
    PREGUNTAR_BASES = "PREGUNTAR_BASES"
    VER_ESTADO = "VER_ESTADO"
    AYUDA = "AYUDA"
    DESAMBIGUAR_GENERAR = "DESAMBIGUAR_GENERAR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ResolvedUserIntent:
    intent: UserChatIntent
    confidence: str = "alta"
    reason: str = ""


def normalize_for_intent(text: str) -> str:
    """Minúsculas sin acentos ni signos de puntuación básicos."""
    raw = (text or "").strip().lower()
    nk = unicodedata.normalize("NFD", raw)
    t = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!,.;:]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_bare_generar_ambiguous(query: str) -> bool:
    """
    True cuando «generar» / «adelante» / «listo» no especifican cotizar vs expediente.
    """
    q = normalize_for_intent(query)
    if not q:
        return False
    if q.startswith("cmd_"):
        return False
    bare = frozenset(
        {
            "generar",
            "genera",
            "genrar",
            "adelante",
            "listo",
            "vamos",
            "dale",
            "ok",
            "de acuerdo",
            "continuar",
            "continua",
            "sigue",
        }
    )
    if q in bare:
        return True
    if re.search(r"(^|\s)generar(\s|$)", q) or q.endswith(" generar") or q.endswith(" genera"):
        if not any(
            w in q
            for w in (
                "propuesta",
                "economica",
                "economico",
                "documento",
                "documentos",
                "expediente",
                "cotizacion",
                "cotizar",
            )
        ):
            return True
    if q.startswith("generar ") and not any(
        w in q
        for w in (
            "propuesta",
            "economica",
            "economico",
            "documento",
            "documentos",
            "expediente",
            "anexo",
            "formato",
            "cotizacion",
            "cotizar",
        )
    ):
        return True
    return False


def is_expediente_generation_command(query: str) -> bool:
    """Generar sobres / expediente (no recalcular propuesta económica)."""
    q = normalize_for_intent(query).replace("ó", "o")
    if not q:
        return False
    if q in ("cmd_trigger_doc_gen",):
        return True
    markers = (
        "generar documento",
        "generar documentos",
        "generar expediente",
        "generar anexo",
        "generar anexos",
        "generar formatos",
        "generar sobres",
        "empaquetar",
        "crear expediente",
        "armar expediente",
        "propuesta tecnica",
        "sobre tecnico",
        "sobre economico",
        "sobre administrativo",
        "compranet",
        "paquete final",
        "documentos finales",
        "todo el expediente",
    )
    return any(m in q for m in markers)


def is_economic_generation_command(query: str) -> bool:
    """Comando explícito para EconomicAgent."""
    raw = (query or "").strip()
    if raw in ("CMD_TRIGGER_GENERATION", "CMD_TRIGGER_ECONOMIC_PROPOSAL"):
        return True
    q = normalize_for_intent(raw).replace("ó", "o")
    if not q:
        return False
    if ("propuesta tecnica" in q or "sobre tecnico" in q) and "economica" not in q and "economico" not in q:
        return False
    if re.search(r"\b(generar|genera|armar|calcular|cotizar|validar|recalcular|cerrar)\b", q) and (
        "propuesta" in q or "economica" in q or "economico" in q or "cotizacion" in q
    ):
        return True
    return "generar propuesta" in q or "genera propuesta" in q


def is_status_query(query: str) -> bool:
    q = normalize_for_intent(query)
    if not q:
        return False
    status_markers = (
        "como vamos",
        "que tal vamos",
        "como va",
        "como llevamos",
        "en que vamos",
        "estatus",
        "estado del proceso",
        "estado de la licitacion",
        "avance",
        "progreso",
        "que sigue",
        "que falta",
        "que falta por hacer",
        "que hace falta",
        "donde vamos",
        "en que paso vamos",
        "cual es el siguiente paso",
        "siguiente paso",
    )
    return any(m in q for m in status_markers)


def is_help_query(query: str) -> bool:
    q = normalize_for_intent(query)
    if q in ("ayuda", "help", "auxilio"):
        return True
    if len(q) < 8:
        return False
    needles = (
        "no te entiendo",
        "no entiendo nada",
        "no entiendo",
        "que necesitas",
        "que ocupas",
        "que requieres",
        "que debo hacer",
        "que hago ahora",
        "en que me ayudas",
        "no se que hacer",
        "no se que hacer",
        "me puedes ayudar",
        "estoy perdido",
        "estoy confundido",
        "no me queda claro",
        "por donde empezar",
        "ayuda",
        "help",
    )
    return any(n in q for n in needles)


def is_bases_query(query: str) -> bool:
    q = normalize_for_intent(query)
    if len(q) < 10:
        return False
    doc_markers = ("bases", "pliego", "convocatoria", "anexo", "licitacion")
    question_markers = (
        "que dice",
        "donde dice",
        "cual es el apartado",
        "segun las bases",
        "segun el pliego",
        "literal",
        "extracto",
    )
    has_doc = any(m in q for m in doc_markers)
    has_q = "?" in (query or "") or any(m in q for m in question_markers)
    return has_doc and has_q


def is_cotizar_query(query: str) -> bool:
    q = normalize_for_intent(query).replace("ó", "o")
    if not q:
        return False
    if is_economic_generation_command(query):
        return True
    cotizar_markers = (
        "cotizar",
        "cotizacion",
        "validar propuesta",
        "recalcular propuesta",
        "cerrar cotizacion",
        "precio unitario",
        "precios unitarios",
        "capturar precio",
        "captura precio",
        "matriz de precio",
        "matriz de precios",
    )
    return any(m in q for m in cotizar_markers)


def resolve_user_intent(
    query: Optional[str],
    *,
    has_economic_pending: bool = False,
    has_any_pending: bool = False,
    current_pending_type: str = "",
    is_explicit_gen_command: bool = False,
) -> ResolvedUserIntent:
    """
    Resuelve intención sin LLM.

    Args:
        query: Mensaje del usuario.
        has_economic_pending: Hay precios/cotización pendientes en cola.
        has_any_pending: Cualquier pendiente HITL activo.
        current_pending_type: Tipo del pendiente actual (economic_price, profile_field, …).
        is_explicit_gen_command: Ya detectado comando económico explícito upstream.
    """
    q = (query or "").strip()
    if not q:
        return ResolvedUserIntent(UserChatIntent.UNKNOWN, reason="empty")

    if q.startswith("CMD_"):
        qu = q.upper()
        if "DOC_GEN" in qu:
            return ResolvedUserIntent(UserChatIntent.GENERAR_EXPEDIENTE, reason="cmd_doc_gen")
        if "ECONOMIC" in qu or "GENERATION" in qu:
            return ResolvedUserIntent(UserChatIntent.COTIZAR, reason="cmd_economic")
        return ResolvedUserIntent(UserChatIntent.VER_ESTADO, reason="ui_command")

    if is_help_query(q):
        return ResolvedUserIntent(UserChatIntent.AYUDA, reason="help_markers")

    if is_expediente_generation_command(q):
        return ResolvedUserIntent(UserChatIntent.GENERAR_EXPEDIENTE, reason="expediente_cmd")

    if is_economic_generation_command(q) or is_explicit_gen_command:
        return ResolvedUserIntent(UserChatIntent.COTIZAR, reason="economic_gen_cmd")

    if is_bare_generar_ambiguous(q) and not is_explicit_gen_command:
        return ResolvedUserIntent(UserChatIntent.DESAMBIGUAR_GENERAR, reason="bare_generar")

    if is_status_query(q):
        return ResolvedUserIntent(UserChatIntent.VER_ESTADO, reason="status_markers")

    if is_bases_query(q):
        return ResolvedUserIntent(UserChatIntent.PREGUNTAR_BASES, reason="bases_query")

    if has_economic_pending and current_pending_type in (
        "economic_price",
        "economic_price_matrix",
        "economic_validation_blocking",
    ):
        if is_cotizar_query(q):
            return ResolvedUserIntent(UserChatIntent.COTIZAR, reason="eco_pending_cotizar")
        if not is_status_query(q) and not is_bases_query(q):
            return ResolvedUserIntent(UserChatIntent.RESPONDER_PENDIENTE, reason="eco_pending_active")

    if is_cotizar_query(q):
        return ResolvedUserIntent(UserChatIntent.COTIZAR, reason="cotizar_markers")

    if has_any_pending and not is_status_query(q) and not is_bases_query(q):
        return ResolvedUserIntent(UserChatIntent.RESPONDER_PENDIENTE, reason="generic_pending")

    return ResolvedUserIntent(UserChatIntent.UNKNOWN, reason="fallback")


DISAMBIGUATE_GENERAR_MESSAGE = (
    "¿Quieres **cotizar precios pendientes** o **generar el expediente** completo? "
    "Responde con una de esas opciones."
)
