#!/usr/bin/env python3
"""UAT BARDA: validación chat procedencia económica vía agente real."""
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
    ("total", "de donde sacaste este total $3,278,289.63 del anexo ae"),
    ("catalog", "como viste mis precios del catalogo de conceptos"),
]

BANNED = (
    "RESPUESTA DIRECTA",
    "MONEDA REQUERIDA",
    "ALERTA DE BRECHA",
    "[FUENTE:",
    "INSTRUCCIÓN PROPUESTA",
)


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _ok(msg: str, detail: str = "") -> None:
    line = f"[OK] {msg}"
    if detail:
        line += f" — {detail[:220]}"
    print(line)


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
        _fail("company_id no encontrado en sesión")
        return 1

    mcp = MCPContextManager(memory_repository=mem)
    agent = ChatbotRAGAgent(context_manager=mcp)

    results = []
    all_ok = True

    for mode, query in QUERIES:
        inp = AgentInput(
            session_id=SESSION,
            company_id=str(company_id),
            company_data={"query": query},
            mode="full",
        )
        out = await agent.process(inp)
        data = out.data or {}
        respuesta = str(data.get("respuesta") or data.get("message") or "")
        tipo = str(data.get("tipo") or "")
        actions = out.suggested_actions or data.get("suggested_actions") or []

        checks = {
            "has_response": bool(respuesta.strip()),
            "tipo_provenance": tipo == "economic_provenance_hru",
            "gate5_lines": count_visible_lines(respuesta) <= 3,
            "no_banned": not any(b in respuesta.upper() for b in BANNED),
            "has_total_or_catalog": (
                "3,278,289.63" in respuesta
                if mode == "total"
                else ("catálogo" in respuesta.lower() or "catalogo" in respuesta.lower())
            ),
            "has_cta": any(
                isinstance(a, dict) and "Formatos" in str(a.get("label") or "")
                for a in actions
            ) or "Siguiente paso" in respuesta or "Formatos" in respuesta,
        }
        passed = all(checks.values())
        all_ok &= passed

        preview = respuesta.replace("\n", " | ")[:200]
        if passed:
            _ok(f"chat {mode}", preview)
        else:
            _fail(f"chat {mode}: {checks} — {preview}")

        results.append(
            {
                "mode": mode,
                "query": query,
                "tipo": tipo,
                "checks": checks,
                "pass": passed,
                "preview": preview,
            }
        )

    summary = {
        "session_id": SESSION,
        "company_id": str(company_id),
        "PASS_overall": all_ok,
        "results": results,
    }
    print("\n--- JSON ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
