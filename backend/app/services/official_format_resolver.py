"""
Resolver HRU de machotes oficiales publicados en bases (Fase 1).

Punto único de materialización para anexos obra|E* — usado por Formats,
EconomicWriter y reapply.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.config.settings import settings
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "official_format_policy.json"
)

# Orden de materialización del sobre económico obra.
OBRA_ECONOMIC_MATERIALIZE_ORDER: tuple[str, ...] = (
    "obra|E1",
    "obra|E2",
    "obra|E3",
    "obra|E3E",
    "obra|E4",
    "obra|E5",
)


@dataclass
class OfficialDeliverableResult:
    """Resultado de resolve_official_deliverable (HRU)."""

    content: str
    dedupe_key: str
    document_title: str
    filename: str
    official_bases_mirror: bool = False
    materialization_route: str = "deterministic_clause"
    metadata: Dict[str, Any] = field(default_factory=dict)
    slots_pending: List[str] = field(default_factory=list)


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


def annex_output_spec(dedupe_key: str) -> Dict[str, str]:
    """Nombre de archivo y título DOCX desde política."""
    entry = policy_annex_entry(dedupe_key) or {}
    return {
        "filename": str(entry.get("output_filename") or f"{dedupe_key.replace('|', '_')}.docx"),
        "doc_title": str(entry.get("doc_title") or entry.get("label_es") or dedupe_key),
    }


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


def official_template_expected_for_key(dedupe_key: str) -> bool:
    """True si la política marca el anexo como exigiendo machote oficial."""
    entry = policy_annex_entry(dedupe_key) or {}
    if entry.get("official_template_expected") is False:
        return False
    return bool(entry.get("anchors")) and official_mirror_strict_enabled()


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
    expected = official_template_expected_for_key(dedupe_key)
    return {
        "dedupe_key": dedupe_key,
        "official_bases_mirror": bool(official_mirror),
        "official_template_expected": expected and strict,
        "materialization_route": route or (
            "official_bases_mirror" if official_mirror else "deterministic_clause"
        ),
        "official_mirror_strict": strict,
    }


def _snippet_for_key(
    dedupe_key: str,
    snippets_by_key: Dict[str, str],
    session_state: Dict[str, Any],
) -> str:
    key = str(dedupe_key or "")
    if snippets_by_key.get(key):
        return str(snippets_by_key[key])
    alias = {
        "obra|E1": "_obra_e1_snippet",
        "obra|E2": "_obra_e2_snippet",
        "obra|E3": "_obra_e3_snippet",
        "obra|E3E": "_obra_e3e_snippet",
        "obra|E4": "_obra_e4_snippet",
        "obra|E5": "_obra_e5_snippet",
        "obra|T_B_SOLVENCIA": "_obra_tb_solvencia_snippet",
    }
    attr = alias.get(key)
    if attr:
        return str(session_state.get(attr) or "")
    return ""


def resolve_official_deliverable(
    dedupe_key: str,
    *,
    session_id: str = "",
    session_state: Optional[Dict[str, Any]] = None,
    master_profile: Optional[Dict[str, Any]] = None,
    economic_data: Optional[Dict[str, Any]] = None,
    mapeo_items: Optional[List[Dict[str, Any]]] = None,
    resumen: Optional[Dict[str, Any]] = None,
    snippets_by_key: Optional[Dict[str, str]] = None,
    tabla_precios_basename: str = "",
) -> OfficialDeliverableResult:
    """
    Resuelve el cuerpo markdown de un anexo económico obra (extract → fill → mirror).

    Punto único HRU para Formats, EconomicWriter y reapply.
    """
    from app.services.economic_document_reapply import load_economic_payload
    from app.services.obra_economic_annex_clauses import (
        assemble_obra_e1_corpus,
        assemble_obra_e3e_corpus,
        build_obra_e1_carta_compromiso_markdown,
        build_obra_e2_catalog_markdown,
        build_obra_e3_annex_markdown,
        build_obra_e3e_utilidad_markdown,
        build_obra_e4_programa_markdown,
        build_obra_e5_cotizaciones_markdown,
        is_official_obra_e1_mirror_content,
        is_official_obra_e2_mirror_content,
        is_official_obra_e3e_mirror_content,
        is_official_obra_e4_mirror_content,
        is_official_obra_e5_mirror_content,
        resolve_obra_concurso_label,
        resolve_obra_objeto,
    )

    key = str(dedupe_key or "").strip()
    state = dict(session_state or {})
    if session_id:
        enrich_obra_official_corpus(session_id, state)
    mp = dict(master_profile or {})
    snips = dict(snippets_by_key or {})
    items = list(mapeo_items or [])
    eco = dict(economic_data or {})

    if resumen is None:
        _, items, resumen = load_economic_payload(state, session_id=session_id)
    resumen = dict(resumen or {})

    spec = annex_output_spec(key)
    snippet = _snippet_for_key(key, snips, state)
    bases_hint = str(state.get("bases_corpus_hint") or "")

    corpus_for_context = bases_hint + " " + snippet
    if key == "obra|E1":
        corpus_for_context = assemble_obra_e1_corpus(
            session_id=session_id,
            session_state=state,
            bases_corpus_hint=bases_hint,
            req_snippet=snippet,
        )
    elif key == "obra|E3E":
        corpus_for_context = assemble_obra_e3e_corpus(
            session_id=session_id,
            session_state=state,
            bases_corpus_hint=bases_hint,
            req_snippet=snippet,
        )

    concurso = resolve_obra_concurso_label(
        session_state=state,
        session_id=session_id,
        corpus=corpus_for_context,
    )
    obra_desc = resolve_obra_objeto(
        session_state=state,
        session_id=session_id,
        corpus=corpus_for_context,
        explicit=str(state.get("objeto_obra") or state.get("obra_descripcion") or ""),
    )

    content = ""
    official_mirror = False
    route = "deterministic_clause"
    slots_pending: List[str] = []

    if key == "obra|E1":
        content = build_obra_e1_carta_compromiso_markdown(
            concurso=concurso,
            master_profile=mp,
            resumen=resumen,
            req_snippet=snippet,
            bases_corpus_hint=bases_hint,
            session_id=session_id,
            session_state=state,
            obra_descripcion=obra_desc,
            session_name=str(state.get("name") or ""),
        )
        official_mirror = is_official_obra_e1_mirror_content(content)
        route = "official_bases_mirror" if official_mirror else (
            "official_miss_shell" if should_use_miss_shell_instead_of_generic(
                snippet + bases_hint, key
            ) else "deterministic_clause"
        )
    elif key == "obra|E2":
        content = build_obra_e2_catalog_markdown(
            concurso=concurso,
            mapeo_items=items,
            resumen=resumen,
            req_snippet=snippet or bases_hint,
        )
        official_mirror = is_official_obra_e2_mirror_content(content)
        route = "official_bases_mirror" if official_mirror else (
            "official_miss_shell" if should_use_miss_shell_instead_of_generic(
                snippet + bases_hint, key
            ) else "deterministic_obra_e2"
        )
    elif key == "obra|E3":
        content = build_obra_e3_annex_markdown(
            concurso=concurso,
            mapeo_items=items,
            req_snippet=snippet or bases_hint,
            tabla_precios_basename=tabla_precios_basename,
        )
        if "[Consignar]" in content:
            slots_pending.append("tarjetas_apu_hitl")
        route = "deterministic_obra_e3_shell"
    elif key == "obra|E3E":
        util_rate = resolve_e3e_utilidad_rate_for_fill(state, resumen, eco)
        content = build_obra_e3e_utilidad_markdown(
            concurso=concurso,
            master_profile=mp,
            utilidad_rate=util_rate,
            session_id=session_id,
            session_state=state,
            bases_corpus_hint=bases_hint,
            req_snippet=snippet or bases_hint,
            obra_descripcion=obra_desc,
            session_name="",
        )
        if util_rate <= 0:
            slots_pending.append("utilidad_rate_economico")
        official_mirror = is_official_obra_e3e_mirror_content(content)
        route = "official_bases_mirror" if official_mirror else (
            "official_miss_shell" if should_use_miss_shell_instead_of_generic(
                snippet + bases_hint, key
            ) else "official_miss_shell"
        )
    elif key == "obra|E4":
        content = build_obra_e4_programa_markdown(
            concurso=concurso,
            req_snippet=snippet or bases_hint,
        )
        official_mirror = is_official_obra_e4_mirror_content(content)
        if "[Consignar]" in content:
            slots_pending.append("programas_gantt_hitl")
        route = "official_bases_mirror" if official_mirror else (
            "official_miss_shell" if should_use_miss_shell_instead_of_generic(
                snippet + bases_hint, key
            ) else "deterministic_obra_e4_shell"
        )
    elif key == "obra|E5":
        content = build_obra_e5_cotizaciones_markdown(
            concurso=concurso,
            req_snippet=snippet or bases_hint,
        )
        official_mirror = is_official_obra_e5_mirror_content(content)
        if "[Consignar]" in content:
            slots_pending.append("cotizaciones_materiales_hitl")
        route = "official_bases_mirror" if official_mirror else (
            "official_miss_shell" if should_use_miss_shell_instead_of_generic(
                snippet + bases_hint, key
            ) else "deterministic_obra_e5_shell"
        )
    else:
        content = build_official_miss_shell(
            key or "obra|?",
            concurso=concurso,
            req_line=snippet[:400],
            master_profile=mp,
        )
        route = "official_miss_shell"

    meta = resolve_materialization_meta(
        dedupe_key=key,
        content=content,
        official_mirror=official_mirror,
        route=route,
    )
    meta.update(
        {
            "obra_pliego_contract": True,
            "document_title": spec["doc_title"],
            "formal_closing": not official_mirror,
            "req_snippet": snippet,
            "session_id": session_id,
            "slots_pending": slots_pending,
        }
    )

    return OfficialDeliverableResult(
        content=content,
        dedupe_key=key,
        document_title=spec["doc_title"],
        filename=spec["filename"],
        official_bases_mirror=official_mirror,
        materialization_route=route,
        metadata=meta,
        slots_pending=slots_pending,
    )


def materialize_obra_economic_envelope(
    *,
    session_id: str,
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
    output_dir: str,
    economic_data: Optional[Dict[str, Any]] = None,
    mapeo_items: Optional[List[Dict[str, Any]]] = None,
    resumen: Optional[Dict[str, Any]] = None,
    snippets_by_key: Optional[Dict[str, str]] = None,
    tabla_precios_basename: str = "",
) -> List[Dict[str, Any]]:
    """
    Materializa E-1…E-5 (+ E-3E) en ``output_dir`` vía resolve_official_deliverable.

    Returns:
        Lista de dicts para ``generated_documents`` con trazabilidad HRU.
    """
    from app.agents.formats import _save_docx
    from app.services.document_traceability import attach_traceability, safe_file_sha256
    from app.services.economic_document_reapply import build_economic_doc_metadata

    os.makedirs(output_dir, exist_ok=True)
    state = dict(session_state or {})
    enrich_obra_official_corpus(session_id, state)
    _, items, res = load_economic_payload_fallback(
        state, session_id, mapeo_items, resumen, economic_data
    )

    doc_meta_base = build_economic_doc_metadata(
        session_id=session_id,
        session_state=state,
        master_profile=master_profile,
        resumen=res,
    )

    if not res.get("obra_breakdown"):
        return []

    out_docs: List[Dict[str, Any]] = []
    for dedupe_key in OBRA_ECONOMIC_MATERIALIZE_ORDER:
        result = resolve_official_deliverable(
            dedupe_key,
            session_id=session_id,
            session_state=state,
            master_profile=master_profile,
            economic_data=economic_data,
            mapeo_items=items,
            resumen=res,
            snippets_by_key=snippets_by_key,
            tabla_precios_basename=tabla_precios_basename,
        )
        path = os.path.join(output_dir, result.filename)
        save_meta = {**doc_meta_base, **result.metadata}
        _save_docx(result.document_title, result.content, path, save_meta)

        out_docs.append(
            attach_traceability(
                {
                    "nombre": result.document_title,
                    "ruta": path,
                    "tipo": dedupe_key.replace("obra|", "obra_").lower(),
                    "dedupe_key": dedupe_key,
                    "official_bases_mirror": result.official_bases_mirror,
                    "official_template_expected": save_meta.get("official_template_expected"),
                    "materialization_route": result.materialization_route,
                },
                template_id=dedupe_key,
                materialization_route=result.materialization_route,
                output_hash=safe_file_sha256(path),
                provenance_ui={
                    "source": result.materialization_route,
                    "dedupe_key": dedupe_key,
                    "official_bases_mirror": result.official_bases_mirror,
                    "official_template_expected": save_meta.get("official_template_expected"),
                    "slots_pending": result.slots_pending,
                },
            )
        )
    return out_docs


def resolve_e3e_utilidad_rate_for_fill(
    session_state: Dict[str, Any],
    resumen: Dict[str, Any],
    economic_data: Optional[Dict[str, Any]] = None,
) -> float:
    """
    % utilidad para el anexo E-3 E.

    HRU: solo se imprime si el usuario lo confirmó (chat/HITL). El default de
    perfil/calculadora (p. ej. 5 %) no basta para declararlo en el machote.
    """
    _ = economic_data, resumen
    user = dict((session_state or {}).get("economic_user_inputs") or {})
    for key in ("utilidad_rate", "utilidad_pct", "utilidad"):
        if key not in user or user[key] is None:
            continue
        raw = float(user[key])
        if key == "utilidad" and raw > 1:
            return raw / 100.0
        if raw > 1:
            return raw / 100.0
        if raw > 0:
            return raw
    return 0.0


def enrich_obra_official_corpus(session_id: str, session_state: Dict[str, Any]) -> None:
    """Inyecta corpus de machotes E-1/E-3E y metadatos de convocante en la sesión."""
    from app.services.obra_economic_annex_clauses import (
        fetch_obra_e1_format_corpus_from_index,
        fetch_obra_e3e_format_corpus_from_index,
        fetch_obra_licitacion_corpus_from_index,
        is_hru_consignar_placeholder,
        resolve_obra_concurso_label,
    )

    hint = str(session_state.get("bases_corpus_hint") or "")
    for fetcher, marker in (
        (fetch_obra_licitacion_corpus_from_index, "licitaci"),
        (fetch_obra_e1_format_corpus_from_index, "carta compromiso"),
        (fetch_obra_e3e_format_corpus_from_index, "utilidad propuesta"),
    ):
        try:
            blob = fetcher(session_id)
        except Exception:
            blob = ""
        if blob and marker not in hint.lower():
            hint = f"{hint}\n\n{blob}"[:160000]
    if hint:
        session_state["bases_corpus_hint"] = hint

    try:
        from app.services.convocante_resolver import (
            extract_convocante_from_text,
            merge_convocante_into_session_patch,
        )

        patch = merge_convocante_into_session_patch(session_state, hint)
        if not patch.get("convocante"):
            patch = extract_convocante_from_text(hint)
        la = dict(session_state.get("last_analysis") or {})
        for k, v in patch.items():
            if not v:
                continue
            if k == "concurso_label" and not str(session_state.get("concurso_label") or "").strip():
                session_state["concurso_label"] = v
            if not str(la.get(k) or "").strip():
                la[k] = v
        session_state["last_analysis"] = la
    except Exception:
        pass

    label = resolve_obra_concurso_label(
        session_state=session_state,
        session_id=session_id,
        corpus=hint,
    )
    if label and not is_hru_consignar_placeholder(label):
        session_state.setdefault("concurso_label", label)


def load_economic_payload_fallback(
    session_state: Dict[str, Any],
    session_id: str,
    mapeo_items: Optional[List[Dict[str, Any]]],
    resumen: Optional[Dict[str, Any]],
    economic_data: Optional[Dict[str, Any]],
) -> tuple[Any, List[Dict[str, Any]], Dict[str, Any]]:
    """Carga payload económico o usa valores ya provistos."""
    from app.services.economic_document_reapply import load_economic_payload

    if mapeo_items is not None and resumen is not None:
        return economic_data, list(mapeo_items), dict(resumen)
    eco, items, res = load_economic_payload(session_state, session_id=session_id)
    return eco or economic_data, items, res
