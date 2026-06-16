#!/usr/bin/env python3
"""
Cierra huecos T/E de obra pública: materializa, sync SOBRE y re-empaqueta CompraNet.

Uso:
  PYTHONPATH=/app python scripts/close_obra_delivery_gaps.py SESSION_ID
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.deps import get_connected_memory
from app.services.convocante_resolver import merge_convocante_into_session_patch
from app.services.junta_bases_corpus import build_bases_corpus
from app.services.economic_document_reapply import reapply_obra_economic_annexes
from app.services.obra_delivery_gap_service import (
    build_obra_te_gap_report,
    materialize_obra_te_gaps,
    sync_admin_to_sobre_administrativo,
    sync_economic_to_sobre,
)
from app.services.vector_service import VectorDbServiceClient


async def _enrich_session_state(session_id: str, state: dict, mem) -> dict:
    session_state = dict(state)
    try:
        vdb = VectorDbServiceClient()
        if not str(session_state.get("bases_corpus_hint") or "").strip():
            cal_res = vdb.query_texts(
                session_id,
                "anexo T-1 T-2 T-3 T-4 T-5 T-6 T-7 T-8 E-1 E-2 E-3 E-4 E-5 bases requisitos",
                n_results=25,
            )
            cal_docs = cal_res.get("documents") or []
            session_state["bases_corpus_hint"] = "\n".join(d for d in cal_docs if d)[:120000]

        docs = await mem.get_documents(session_id)
        corpus = build_bases_corpus(session_id, docs, session_state=session_state)
        combined = str(corpus.combined or "").strip()
        if combined:
            session_state["bases_corpus_hint"] = combined[:180000]
        patch = merge_convocante_into_session_patch(session_state, combined or corpus.combined)
        if patch.get("convocante"):
            la = dict(session_state.get("last_analysis") or {})
            for k, v in patch.items():
                if v and not str(la.get(k) or "").strip():
                    la[k] = v
            session_state["last_analysis"] = la
            if patch.get("destinatario"):
                session_state["destinatario"] = patch["destinatario"]
            session_state["convocante"] = patch.get("convocante")
    except Exception:
        pass
    return session_state


async def main() -> int:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    session_state = await _enrich_session_state(session_id, state, mem)
    documents = await mem.get_documents(session_id)
    mp = state.get("master_profile") or {}

    before = build_obra_te_gap_report(session_id, session_state, documents)
    mat = materialize_obra_te_gaps(
        session_id,
        session_state,
        mp,
        documents=documents,
        gap_report=before,
    )
    eco_reapply = reapply_obra_economic_annexes(
        session_id=session_id,
        session_state=session_state,
        master_profile=mp,
        memory=mem,
        gap_report=before,
    )
    n_admin, admin_dests = sync_admin_to_sobre_administrativo(session_id)
    n_eco, eco_dests = sync_economic_to_sobre(session_id)

    after = build_obra_te_gap_report(session_id, session_state, documents)

    import os
    import subprocess

    repack = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "repack_session_compranet.py"),
            "--session",
            session_id,
        ],
        cwd=str(_ROOT),
        env={**os.environ, "PYTHONPATH": str(_ROOT)},
        capture_output=True,
        text=True,
    )
    repack_code = repack.returncode
    if repack.stdout.strip():
        print(repack.stdout)
    if repack.stderr.strip():
        print(repack.stderr, file=sys.stderr)

    out = {
        "session_id": session_id,
        "before": {
            "inventory": before.get("inventory_count"),
            "gaps": before.get("gaps"),
            "gap_count": before.get("gap_count"),
        },
        "materialize": mat,
        "economic_reapply": eco_reapply,
        "sync_admin": n_admin,
        "sync_economic": n_eco,
        "after": {
            "inventory": after.get("inventory_count"),
            "gaps": after.get("gaps"),
            "gap_count": after.get("gap_count"),
            "covered": after.get("covered"),
        },
        "repack_exit_code": repack_code,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if after.get("gap_count", 1) == 0 and repack_code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
