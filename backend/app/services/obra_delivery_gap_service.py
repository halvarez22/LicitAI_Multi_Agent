"""
Cierre universal de huecos T/E en entregables de obra pública.

Sin hardcode por licitación: inventario desde corpus, materialización determinística,
sync admin→SOBRE y cobertura auditable.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agents.formats import _save_docx
from app.services.administrative_letter_clauses import (
    build_administrative_letter_markdown,
    is_obra_pliego_contract_annex,
    is_obra_tabular_annex,
    resolve_document_ciudad,
    resolve_letter_asunto,
    resolve_letter_session_metadata,
    try_build_clause_markdown,
)
from app.services.document_date_resolver import resolve_document_date
from app.services.junta_bases_corpus import build_bases_corpus
from app.services.pliego_formats_enrichment_service import (
    extract_obra_te_annexes_from_bases_corpus,
    obra_te_dedupe_key,
    pliego_format_dedupe_key,
)

_OUTPUTS_ROOT = Path(os.environ.get("LICITAI_OUTPUTS_ROOT", "/data/outputs"))

# Nombres de salida cuando no existe archivo previo en disco.
_CANONICAL_NEW_FILENAMES: Dict[str, str] = {
    "obra|T3": "Anexo_T-3_Modelo_de_Contrato_firmado.docx",
    "obra|T4": "Anexo_T-4_Bases_y_Requisitos_firmados.docx",
    "obra|T5": "Anexo_T-5_Acta_Visita_Junta.docx",
    "obra|T6": "Manifestación_de_Cumplimiento_de_Obligaciones_Contractuales.docx",
    "obra|T7": "Manifestación_de_las_partes_de_la_obra_que_pretenda_subcontr.docx",
    "obra|E1": "CARTA_COMPROMISO_PROPOSICION.docx",
    "obra|E4": "Anexo_E-4_Programas_Obra_Gantt.docx",
    "obra|E5": "Anexo_E-5_Cotizaciones_Materiales.docx",
    "obra|T-B-2": "Formato_T-b_2.docx",
}

# Claves con cláusula determinística o archivo existente mapeable.
_CLAUSE_MATERIALIZE_KEYS: Set[str] = {
    "obra|T1",
    "obra|T2",
    "obra|T3",
    "obra|T4",
    "obra|T5",
    "obra|T6",
    "obra|T7",
    "obra|T8",
    "obra|T8_PRIVACIDAD",
    "obra|E1",
    "obra|E4",
    "obra|E5",
    "obra|T-B-2",
}

# Claves satisfechas por documentos económicos ya generados (alias universal).
_ECONOMIC_KEY_ALIASES: Dict[str, tuple[str, ...]] = {
    "obra|E1": ("carta compromiso", "carta_compromiso", "proposicion"),
    "obra|E2": (
        "anexo ae",
        "propuesta economica",
        "propuesta_economica",
        "catalogo",
    ),
    "obra|E3": ("analisis precios", "precios unitarios", "tabla precios"),
    "obra|E5": ("cotizaciones materiales", "materiales", "anexo e-5"),
}

# Claves de archivos ya generados que satisfacen un anexo esperado.
_SATISFIED_BY_FILE_KEY: Dict[str, tuple[str, ...]] = {
    "obra|E2": ("pliego|propuesta_economica", "obra|E2", "pliego|ANEXO_VI"),
}


def _session_root(session_id: str) -> Path:
    return _OUTPUTS_ROOT / session_id


def _scan_docx_keys(directory: Path) -> Dict[str, str]:
    """Mapa dedupe_key → ruta absoluta del primer archivo encontrado."""
    found: Dict[str, str] = {}
    if not directory.is_dir():
        return found
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith(".docx") or fn.startswith("~$"):
            continue
        key = pliego_format_dedupe_key(fn)
        if key and key not in found:
            found[key] = str(directory / fn)
    return found


def _scan_economic_keys(session_id: str) -> Dict[str, str]:
    """Archivos económicos en carpetas de generación y sobre económico."""
    root = _session_root(session_id)
    merged: Dict[str, str] = {}
    for sub in ("economic_proposal", "SOBRE_3_ECONOMICO"):
        merged.update(_scan_docx_keys(root / sub))
    # XLSX para E-3
    eco = root / "SOBRE_3_ECONOMICO"
    if eco.is_dir():
        for fn in os.listdir(eco):
            if fn.lower().endswith(".xlsx"):
                key = pliego_format_dedupe_key(fn)
                if key and key not in merged:
                    merged[key] = str(eco / fn)
    return merged


def build_obra_te_gap_report(
    session_id: str,
    session_state: Dict[str, Any],
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Inventario esperado vs disco para anexos T/E de obra.

    Returns:
        Reporte con filas, huecos y claves cubiertas.
    """
    corpus = build_bases_corpus(session_id, documents, session_state=session_state)
    inventory = extract_obra_te_annexes_from_bases_corpus(corpus)
    admin_keys = _scan_docx_keys(_session_root(session_id) / "3.documentos administrativos")
    sobre1_keys = _scan_docx_keys(_session_root(session_id) / "SOBRE_1_ADMINISTRATIVO")
    eco_keys = _scan_economic_keys(session_id)

    rows: List[Dict[str, Any]] = []
    gaps: List[str] = []
    covered: List[str] = []

    for item in inventory:
        key = str(item.get("dedupe_key") or pliego_format_dedupe_key(item.get("nombre_canonico") or ""))
        sobre = str(item.get("sobre_clasificado") or "")
        pools = [admin_keys, sobre1_keys] if "economico" not in sobre else [eco_keys, admin_keys]
        path = ""
        for pool in pools:
            if key in pool:
                path = pool[key]
                break
        if not path:
            for alt in _SATISFIED_BY_FILE_KEY.get(key, ()):
                for pool in pools:
                    if alt in pool:
                        path = pool[alt]
                        break
                if path:
                    break
        if not path:
            for alias_key, tokens in _ECONOMIC_KEY_ALIASES.items():
                if alias_key != key:
                    continue
                for pool in (eco_keys, admin_keys):
                    for k, p in pool.items():
                        blob = k.lower() + " " + Path(p).name.lower()
                        if any(t in blob for t in tokens):
                            path = p
                            break
                    if path:
                        break
        estado = "cubierto" if path else "hueco"
        if path:
            covered.append(key)
        else:
            gaps.append(key)
        rows.append(
            {
                "dedupe_key": key,
                "nombre_canonico": item.get("nombre_canonico"),
                "sobre_clasificado": sobre,
                "estado": estado,
                "archivo": path or None,
                "snippet": item.get("snippet_representativo"),
            }
        )

    return {
        "session_id": session_id,
        "inventory_count": len(inventory),
        "covered_count": len(covered),
        "gap_count": len(gaps),
        "gaps": gaps,
        "covered": covered,
        "rows": rows,
        "corpus_chars": len(corpus.combined or ""),
    }


def _build_letter_metadata(
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Metadatos compartidos para cartas determinísticas."""
    date_info = resolve_document_date(session_state)
    letter_meta = resolve_letter_session_metadata(session_state)
    dom = master_profile.get("domicilio_fiscal") or master_profile.get("domicilio") or ""
    return {
        "tender_name": str(session_state.get("licitacion_id") or session_state.get("session_id") or ""),
        "fecha": date_info.get("fecha_es"),
        "fecha_corta": date_info.get("fecha_corta"),
        "deadline_dt_iso": date_info.get("deadline_dt"),
        "footer_text": f"{master_profile.get('razon_social', '')} | RFC: {master_profile.get('rfc', '')} | Domicilio: {dom}",
        "domicilio": dom,
        "destinatario": letter_meta.get("destinatario") or "A QUIEN CORRESPONDA:",
        "concurso_label": letter_meta.get("concurso_label", ""),
        "convocante": letter_meta.get("convocante", ""),
        "entidad": letter_meta.get("entidad", ""),
        "lugar_convocante": letter_meta.get("lugar_convocante", ""),
        "ciudad": resolve_document_ciudad(master_profile, str(dom), letter_meta=letter_meta),
        "empresa": master_profile.get("razon_social", ""),
        "rfc": master_profile.get("rfc", ""),
        "representante": master_profile.get("representante_legal") or master_profile.get("representante", ""),
        "formal_closing": True,
        "bases_corpus_hint": session_state.get("bases_corpus_hint", ""),
        "session_state": session_state,
    }


def _doc_meta_for_annex(
    filename: str,
    meta: Dict[str, Any],
    *,
    snippet: str = "",
) -> Dict[str, Any]:
    """Flags de layout DOCX por tipo de anexo obra."""
    key = pliego_format_dedupe_key(filename)
    doc_meta = {**meta, "obra_tabular": is_obra_tabular_annex(filename, key)}
    if is_obra_pliego_contract_annex(filename, key):
        doc_meta["obra_pliego_contract"] = True
        doc_meta["document_title"] = resolve_letter_asunto(filename, snippet, key)
    return doc_meta


def materialize_obra_te_gaps(
    session_id: str,
    session_state: Dict[str, Any],
    master_profile: Dict[str, Any],
    *,
    documents: Optional[List[Dict[str, Any]]] = None,
    gap_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Genera o reaplica cláusulas determinísticas para huecos T/E conocidos.

    Returns:
        Resumen con archivos creados/actualizados.
    """
    docs = documents if documents is not None else []
    report = gap_report or build_obra_te_gap_report(session_id, session_state, docs)

    corpus = build_bases_corpus(session_id, docs, session_state=session_state)
    combined = str(corpus.combined or "")
    session_state = dict(session_state or {})
    if combined:
        session_state["bases_corpus_hint"] = combined[:180000]

    admin_dir = _session_root(session_id) / "3.documentos administrativos"
    admin_dir.mkdir(parents=True, exist_ok=True)
    meta = _build_letter_metadata(session_state, master_profile)

    created: List[str] = []
    updated: List[str] = []

    admin_keys = _scan_docx_keys(admin_dir)

    for row in report.get("rows") or []:
        key = str(row.get("dedupe_key") or "")
        if row.get("estado") == "cubierto":
            if key in _CLAUSE_MATERIALIZE_KEYS and row.get("archivo"):
                body = try_build_clause_markdown(
                    req_label=row.get("nombre_canonico") or key,
                    master_profile=master_profile,
                    doc_metadata=meta,
                    req_snippet=str(row.get("snippet") or ""),
                )
                if body:
                    _save_docx(
                        str(row.get("nombre_canonico") or key),
                        body,
                        str(row["archivo"]),
                        _doc_meta_for_annex(
                            str(row.get("nombre_canonico") or key),
                            meta,
                            snippet=str(row.get("snippet") or ""),
                        ),
                    )
                    updated.append(str(row["archivo"]))
            continue
        if key not in _CLAUSE_MATERIALIZE_KEYS:
            continue
        target_name = _CANONICAL_NEW_FILENAMES.get(key)
        if not target_name:
            continue
        if key.startswith("obra|E"):
            out_dir = _session_root(session_id) / "economic_proposal"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / target_name
        else:
            out_path = admin_dir / target_name
        body = try_build_clause_markdown(
            req_label=row.get("nombre_canonico") or target_name,
            master_profile=master_profile,
            doc_metadata={**meta, "req_snippet": str(row.get("snippet") or "")},
            req_snippet=str(row.get("snippet") or ""),
        ) or build_administrative_letter_markdown(
            req_nombre=target_name,
            master_profile=master_profile,
            doc_metadata=meta,
            session_state=session_state,
            req_snippet=str(row.get("snippet") or ""),
        )
        _save_docx(str(row.get("nombre_canonico") or target_name), body, str(out_path), _doc_meta_for_annex(
            target_name,
            {**meta, "req_snippet": str(row.get("snippet") or "")},
            snippet=str(row.get("snippet") or ""),
        ))
        created.append(str(out_path))

    # Reaplicar cláusulas a archivos admin ya mapeados (T-3 modelo existente, T-8, etc.)
    for fn in sorted(os.listdir(admin_dir)):
        if not fn.lower().endswith(".docx"):
            continue
        path = admin_dir / fn
        key = pliego_format_dedupe_key(fn)
        if key not in _CLAUSE_MATERIALIZE_KEYS:
            continue
        snippet = ""
        for row in report.get("rows") or []:
            if row.get("dedupe_key") == key:
                snippet = str(row.get("snippet") or "")
                break
        body = try_build_clause_markdown(
            req_label=fn,
            master_profile=master_profile,
            doc_metadata=meta,
            req_snippet=snippet,
        )
        if not body:
            continue
        _save_docx(
            fn.replace(".docx", ""),
            body,
            str(path),
            _doc_meta_for_annex(fn, meta, snippet=snippet),
        )
        if str(path) not in updated:
            updated.append(str(path))

    return {
        "created": created,
        "updated": updated,
        "admin_dir": str(admin_dir),
    }


def sync_admin_to_sobre_administrativo(session_id: str) -> Tuple[int, List[str]]:
    """
    Copia ``3.documentos administrativos`` → ``SOBRE_1_ADMINISTRATIVO`` (sin tocar carátula).

    Returns:
        (archivos_copiados, rutas_destino)
    """
    root = _session_root(session_id)
    admin = root / "3.documentos administrativos"
    sobre = root / "SOBRE_1_ADMINISTRATIVO"
    if not admin.is_dir():
        return 0, []

    sobre.mkdir(parents=True, exist_ok=True)
    for f in sobre.glob("*.docx"):
        if not f.name.startswith("00_CARATULA"):
            f.unlink()

    sources = sorted(
        p for p in admin.glob("*.docx") if not p.name.startswith("~$")
    )
    dests: List[str] = []
    for idx, src in enumerate(sources, start=1):
        dest = sobre / f"{idx:02d}_{src.name}"
        shutil.copy2(src, dest)
        dests.append(str(dest))
    return len(dests), dests


def sync_economic_to_sobre(session_id: str) -> Tuple[int, List[str]]:
    """Añade anexos E nuevos al sobre económico sin borrar archivos ya empaquetados."""
    root = _session_root(session_id)
    sobre = root / "SOBRE_3_ECONOMICO"
    sobre.mkdir(parents=True, exist_ok=True)

    existing_keys: Set[str] = set()
    for p in sobre.glob("*"):
        if p.is_file() and not p.name.startswith("00_CARATULA"):
            existing_keys.add(pliego_format_dedupe_key(p.name))

    sources: List[Path] = []
    for sub in ("economic_proposal", "2.propuesta_economica"):
        eco = root / sub
        if eco.is_dir():
            sources.extend(sorted(p for p in eco.iterdir() if p.is_file()))
    admin = root / "3.documentos administrativos"
    if admin.is_dir():
        for p in admin.glob("*.docx"):
            key = obra_te_dedupe_key(p.name) or ""
            if key.startswith("obra|E"):
                sources.append(p)

    dests: List[str] = []
    added = 0
    next_idx = len([f for f in sobre.iterdir() if f.is_file()])
    for src in sources:
        key = pliego_format_dedupe_key(src.name)
        if key in existing_keys:
            continue
        next_idx += 1
        dest = sobre / f"{next_idx:02d}_{src.name}"
        shutil.copy2(src, dest)
        dests.append(str(dest))
        existing_keys.add(key)
        added += 1
    return added, dests
