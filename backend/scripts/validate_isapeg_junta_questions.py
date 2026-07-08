"""Validación ad-hoc de preguntas para junta (ISAPEG)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SESSION = sys.argv[1] if len(sys.argv) > 1 else "isapeg_servicios_de_limpieza"

FOREIGN_MARKERS = (
    "imss-bienestar",
    "focon",
    "007h0m",
    "la-07-h0m",
    "operario por turno",
    "constitución federal",
    "articulo 16",
    "cláusula 4.2",
    "clausula 4.2",
    "página 18",
    "pagina 18",
    "12 años",
    "12 anos",
    "no se proporciona información sobre el perfil",
)


async def main() -> None:
    from app.api.deps import get_connected_memory
    from app.services.junta_aclaraciones_questions_service import (
        build_and_persist_junta_aclaraciones_questions,
        is_internal_junta_item,
    )
    from app.services.junta_bases_corpus import (
        build_bases_corpus,
        primary_bases_combined,
        resolve_primary_bases_filename,
    )
    from app.services.junta_contamination_gate import passes_junta_question_gate

    mem = await get_connected_memory()
    bundle = await build_and_persist_junta_aclaraciones_questions(
        mem, SESSION, force_refresh=True
    )
    state = await mem.get_session(SESSION) or {}
    docs = await mem.get_documents(SESSION)
    corpus = build_bases_corpus(SESSION, docs, session_state=state)
    primary_fn = resolve_primary_bases_filename(
        corpus.filenames or [fn for fn, _ in corpus.segments]
    )

    out: dict = {
        "session_id": SESSION,
        "primary_bases": primary_fn,
        "segment_files": [fn for fn, _ in corpus.segments],
        "schema_version": bundle.schema_version,
        "excluded_contamination": bundle.excluded_contamination,
        "contamination_gate_enabled": bundle.contamination_gate_enabled,
        "summary": bundle.summary.model_dump(mode="json"),
        "items": [],
    }

    counts = {"ok": 0, "warn": 0, "bad": 0}
    for it in bundle.items:
        if is_internal_junta_item(it):
            continue
        if it.status.value == "excluida":
            continue
        blob = f"{it.pregunta} {it.motivo}".lower()
        flags: list[str] = []
        foreign = [m for m in FOREIGN_MARKERS if m in blob]
        if foreign:
            flags.append("contaminacion:" + ",".join(foreign))
        if not passes_junta_question_gate(
            it.pregunta,
            corpus=corpus,
            session_hint=SESSION,
            source_ref=str(it.source_ref or ""),
            motivo=str(it.motivo or ""),
        ):
            flags.append("gate_fail")
        if len(it.pregunta) < 40:
            flags.append("pregunta_corta")
        if it.provenance_ui.get("citation_quality") == "datos_insuficientes":
            flags.append("cita_insuficiente")

        if any(f.startswith("contaminacion") or f == "gate_fail" for f in flags):
            verdict = "bad"
        elif flags:
            verdict = "warn"
        else:
            verdict = "ok"
        counts[verdict] += 1
        out["items"].append(
            {
                "question_id": it.question_id,
                "source": it.source.value,
                "source_ref": it.source_ref,
                "tipo": it.tipo.value,
                "prioridad": it.prioridad.value,
                "verdict": verdict,
                "flags": flags,
                "citation_quality": it.provenance_ui.get("citation_quality"),
                "pregunta": it.pregunta[:320],
            }
        )

    out["verdict_counts"] = {**counts, "total": sum(counts.values())}
    path = Path("out/isapeg_junta_validation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict_counts"], ensure_ascii=False, indent=2))
    print(
        f"excluded_contamination={out['excluded_contamination']} "
        f"para_convocante={out['summary'].get('para_convocante')}"
    )
    print(f"WROTE {path}")
    for i, row in enumerate(out["items"], 1):
        flag_s = ",".join(row["flags"]) if row["flags"] else "-"
        print(f"{i:2d} [{row['verdict'].upper()}] {row['source']} | {flag_s}")
        print(f"    {row['pregunta'][:140]}...")


if __name__ == "__main__":
    asyncio.run(main())
