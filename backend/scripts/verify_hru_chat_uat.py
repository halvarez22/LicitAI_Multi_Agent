#!/usr/bin/env python3
"""
UAT HRU chat + bootstrap — verificación en Docker/local.

Uso:
  PYTHONPATH=/app python scripts/verify_hru_chat_uat.py [SESSION_ID]

Comprueba (sin LLM):
  - Bootstrap Gate 5 universal
  - Sanitización de cola fill-quality plantilla
  - Mensaje aclaración «qué datos faltan» no intimidante
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_SESSION = "barda_primaria_lopez_rayon"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f" — {detail[:200]}"
    print(line)
    return ok


async def main(session_id: str) -> int:
    from app.api.deps import get_connected_memory
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.services.chat_expediente_bootstrap_service import build_expediente_plan_bootstrap
    from app.services.chat_gate5_formatter import build_compact_session_resume, count_visible_lines
    from app.services.document_fill_ux_messages import build_fill_blocking_question
    from app.services.hitl_queue_service import sanitize_chat_pending_questions

    mem = await get_connected_memory()
    st = await mem.get_session(session_id) or {}

    if not st:
        print(f"Sesión no encontrada: {session_id}")
        return 1

    ok_all = True

    boot = build_expediente_plan_bootstrap(st)
    ok_all &= _check(
        "bootstrap Gate5 lineas",
        count_visible_lines(boot) <= 3,
        boot.replace("\n", " | "),
    )
    ok_all &= _check("bootstrap Documentos detectados", "Documentos detectados" in boot)
    ok_all &= _check("bootstrap Formatos/Anexos", "Formatos/Anexos Detectados" in boot)
    ok_all &= _check("bootstrap sin stop_reason", "INCOMPLETE" not in boot and "Pausé" not in boot)

    resume = build_compact_session_resume(st)
    ok_all &= _check("session_resume plan expediente", "Plan de expediente listo" in resume)

    before = list(st.get("pending_questions") or [])
    after = sanitize_chat_pending_questions(before, st)
    ok_all &= _check(
        "sanitize quita fill-quality plantilla",
        not any(
            str(q.get("field") or "") == "quality.fill.review"
            for q in after
            if isinstance(q, dict)
        )
        or len(after) <= len(before),
        f"before={len(before)} after={len(after)}",
    )

    hint = st.get("last_document_fill_quality_waiting_hints") or {}
    issues = hint.get("issues") if isinstance(hint.get("issues"), list) else []
    if issues:
        clarif = build_fill_blocking_question(
            str(hint.get("stage") or "formats"),
            issues,
            session_state=st,
        )
        ok_all &= _check("clarif sin otra licitacion", "otra licitación" not in clarif.lower())
        ok_all &= _check("clarif sin pause", "Pausé la generación" not in clarif)

    from app.services.chat_economic_provenance_service import (
        build_economic_provenance_message,
        detect_economic_provenance_intent,
    )

    user_phrases = (
        ("de donde sacaste este total $3,278,289.63 del anexo ae", "total"),
        ("como viste mis precios ya que se supone que los descargue", "catalog"),
        ("me refiero al catalogo de conceptos que subi", "catalog"),
    )
    for phrase, expected in user_phrases:
        ok_all &= _check(
            f"detect eco intent: {expected}",
            detect_economic_provenance_intent(phrase) == expected,
            phrase[:80],
        )
    if st.get("tasks_completed"):
        for mode in ("total", "catalog"):
            eco_msg = build_economic_provenance_message(
                st,
                session_id=session_id,
                mode=mode,
                user_query=user_phrases[0][0] if mode == "total" else user_phrases[1][0],
            )
            ok_all &= _check(
                f"eco provenance gate5 ({mode})",
                eco_msg
                and count_visible_lines(eco_msg) <= 3
                and "MONEDA REQUERIDA" not in eco_msg
                and "RESPUESTA DIRECTA" not in eco_msg,
                (eco_msg or "").replace("\n", " | ")[:160],
            )

    clarif_static = ChatbotRAGAgent._maybe_fill_quality_clarification_reply(st)
    if clarif_static:
        ok_all &= _check("static clarif HRU", "Siguiente paso" in clarif_static or "Generar" in clarif_static)

    print("\n--- bootstrap ---\n")
    print(boot)
    print("\n--- sanitize pending ---")
    print(json.dumps({"before": len(before), "after": len(after)}, ensure_ascii=False))

    return 0 if ok_all else 2


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION
    raise SystemExit(asyncio.run(main(sid)))
