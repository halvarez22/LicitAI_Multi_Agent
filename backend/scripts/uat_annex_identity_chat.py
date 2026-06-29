#!/usr/bin/env python3
"""UAT: consultas de identidad de anexo (HRU, sin RAG)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SESSION = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"

QUERIES = [
    ("identity_ae", "que es el anexo AE en esta licitacion"),
    ("identity_literal_skip", "que dice el anexo 1 sobre garantias en las bases"),
    ("identity_catalog", "que va en el catalogo de conceptos"),
]


async def main() -> int:
    from app.api.deps import get_connected_memory
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.agents.mcp_context import MCPContextManager
    from app.contracts.agent_contracts import AgentInput
    from app.services.chat_gate5_formatter import count_visible_lines

    mem = await get_connected_memory()
    st = await mem.get_session(SESSION) or {}
    if not st:
        print(json.dumps({"pass": False, "reason": "session_not_found"}, indent=2))
        return 1

    mp = st.get("master_profile") or {}
    company_id = (
        st.get("company_id")
        or mp.get("company_id")
        or mp.get("id")
        or st.get("selected_company_id")
    )
    if not company_id:
        for c in st.get("companies") or []:
            if isinstance(c, dict) and c.get("id"):
                company_id = c["id"]
                break
    if not company_id:
        print("[FAIL] company_id no encontrado")
        return 1

    mcp = MCPContextManager(memory_repository=mem)
    agent = ChatbotRAGAgent(context_manager=mcp)
    results = []
    all_ok = True

    for mode, query in QUERIES:
        out = await agent.process(
            AgentInput(
                session_id=SESSION,
                company_id=str(company_id),
                company_data={"query": query},
                mode="full",
            )
        )
        data = out.data or {}
        respuesta = str(data.get("respuesta") or data.get("message") or "")
        tipo = str(data.get("tipo") or "")

        if mode == "identity_literal_skip":
            checks = {
                "not_annex_identity": tipo != "annex_identity_hru",
                "has_response": bool(respuesta.strip()),
            }
        else:
            checks = {
                "tipo_identity": tipo == "annex_identity_hru",
                "gate5": count_visible_lines(respuesta) <= 3,
                "has_panel_hint": "anexo" in respuesta.lower() or "catálogo" in respuesta.lower(),
            }
        passed = all(checks.values())
        all_ok &= passed
        mark = "OK" if passed else "FAIL"
        print(f"[{mark}] {mode} tipo={tipo} — {respuesta.replace(chr(10), ' | ')[:180]}")
        results.append({"mode": mode, "query": query, "tipo": tipo, "checks": checks, "pass": passed})

    summary = {"session_id": SESSION, "PASS_overall": all_ok, "results": results}
    print("\n--- JSON ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
