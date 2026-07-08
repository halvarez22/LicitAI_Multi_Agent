"""Validación ad-hoc del panel Formatos/Anexos (ISAPEG)."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

SESSION = sys.argv[1] if len(sys.argv) > 1 else "isapeg_servicios_de_limpieza"

# Anexos/formatos típicos ISAPEG limpieza Guanajuato (referencia documental, no hardcode de detección)
ISAPEG_EXPECTED = {
    "anexo a-i", "anexo a-ii", "anexo ab", "anexo f", "anexo iii", "anexo k", "anexo m",
    "propuesta tecnica", "integracion del costo", "d-iii", "constancia de visitas",
    "oferta economica", "anexo l",
}

FOREIGN_MARKERS = (
    "imss-bienestar",
    "contrato federal",
    "compranet",
    "focon",
    "apendice 1",
    "operario por turno",
    "zona a propuesta",
    "partida 2 entrega de materiales",
    "protocolo de actuacion en materia de contrataciones",
    "informacion reservada y confidencial",
    "registro de propuesta tecnica",
    "modelo de poliza de fianza para garantizar el cumplimiento",
    "analisis de precios unitarios",
    "7.0. puntos sus ingresos",
)


def _broken_label(name: str) -> bool:
    n = name.strip()
    if re.search(r"Anexo\s+[IVXLC\d]+:\s*\)\s*$", n, re.I):
        return True
    if re.search(r"Anexo\s+VIII:\s*\)\s*$", n, re.I):
        return True
    if len(n) < 28 and re.search(r"Anexo\s+[IVXLC]+:\s*\)", n, re.I):
        return True
    return False


async def main() -> None:
    from app.api.deps import get_connected_memory
    from app.services.document_candidate_list_service import build_formats_panel_consolidated
    from app.services.document_deliverable_filter import (
        is_corporate_physical_credential_for_panel,
        is_formats_panel_noise,
        pliego_format_anchor_in_corpus,
    )
    from app.services.junta_bases_corpus import (
        build_bases_corpus,
        extract_template_codes,
        primary_bases_combined,
        resolve_primary_bases_filename,
    )
    from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

    mem = await get_connected_memory()
    state = await mem.get_session(SESSION)
    docs = await mem.get_documents(SESSION)
    corpus = build_bases_corpus(SESSION, docs, session_state=state)
    primary = primary_bases_combined(corpus)
    primary_fn = resolve_primary_bases_filename(
        corpus.filenames or [fn for fn, _ in corpus.segments]
    )
    panel = await build_formats_panel_consolidated(mem, SESSION, state)

    out: dict = {
        "session_id": SESSION,
        "primary_bases": primary_fn,
        "segment_files": [fn for fn, _ in corpus.segments],
        "primary_text_len": len(primary),
        "meta": panel.get("_meta"),
        "items": [],
        "summary": {},
    }

    buckets = {
        "SOBRE_1": panel.get("sobre_1_tecnico") or [],
        "SOBRE_2": panel.get("sobre_2_economico") or [],
        "LEGAL": panel.get("requisitos_legales") or [],
    }

    counts = {"ok": 0, "warn": 0, "bad": 0}
    for bk, items in buckets.items():
        for it in items:
            name = str(it.get("nombre_canonico") or it.get("nombre") or "")
            snip = str(it.get("snippet_representativo") or it.get("snippet") or "")
            tipo = str(it.get("tipo") or it.get("tipo_accion_final") or "")
            blob = f"{name} {snip}".lower()
            flags: list[str] = []
            foreign = [m for m in FOREIGN_MARKERS if m in blob]
            if foreign:
                flags.append("contaminacion:" + ",".join(foreign))
            if is_formats_panel_noise(name, "", snip):
                flags.append("ruido_panel")
            if is_corporate_physical_credential_for_panel(name, "", snip):
                flags.append("credencial_fisica_mal_bucket")
            anchor_primary = pliego_format_anchor_in_corpus(name, snip, primary)
            anchor_full = pliego_format_anchor_in_corpus(name, snip, corpus.combined)
            codes = extract_template_codes(name)
            inv = bool(it.get("from_document_inventory"))
            if not anchor_primary and not codes and not inv:
                flags.append("sin_ancla_bases_primarias")
            if anchor_full and not anchor_primary:
                flags.append("solo_pdf_ajeno")
            if _broken_label(name):
                flags.append("etiqueta_rota")
            if name.endswith("…") or "Número…" in name:
                flags.append("truncado")
            if re.search(r"(?i)pago de penas convencionales", name):
                flags.append("causal_no_formato")
            if re.search(r"(?i)comprobante fiscal|cfdi", blob) and "presentar" in tipo:
                flags.append("economico_no_legal")
            if re.search(r"(?i)visita a instalaciones", name) and tipo == "presentar_fisico":
                flags.append("visita_ok_fisico")

            if any(
                f.startswith("contaminacion")
                or f.startswith("solo_pdf_ajeno")
                or f == "causal_no_formato"
                or f == "ruido_panel"
                for f in flags
            ):
                verdict = "bad"
            elif flags:
                verdict = "warn"
            else:
                verdict = "ok"
            counts[verdict] += 1

            out["items"].append(
                {
                    "bucket": bk,
                    "nombre": name,
                    "tipo": tipo,
                    "verdict": verdict,
                    "flags": flags,
                    "dedupe_key": pliego_format_dedupe_key(name),
                    "template_codes": codes,
                    "anchor_primary": anchor_primary,
                    "from_inventory": inv,
                    "snippet": snip[:200],
                }
            )

    out["summary"] = {
        **counts,
        "total": sum(counts.values()),
        "generar": sum(1 for i in out["items"] if i["tipo"] == "generar"),
    }

    # expected coverage heuristic
    primary_low = primary.lower()
    found_expected = [e for e in ISAPEG_EXPECTED if e in primary_low]
    missing_expected = [e for e in ISAPEG_EXPECTED if e not in primary_low]
    out["summary"]["expected_in_bases"] = found_expected
    out["summary"]["expected_missing_in_bases_text"] = missing_expected

    path = Path("out/isapeg_formats_validation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    print(f"WROTE {path}")
    for i, row in enumerate(out["items"], 1):
        flag_s = ",".join(row["flags"]) if row["flags"] else "-"
        print(f"{i:2d} [{row['verdict'].upper()}] {row['bucket']} | {row['tipo']} | {flag_s}")
        print(f"    {row['nombre'][:100]}")


if __name__ == "__main__":
    asyncio.run(main())
