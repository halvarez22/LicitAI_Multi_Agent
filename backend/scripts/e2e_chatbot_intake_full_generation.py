"""
E2E: orquestador (generation_only) + colas pending_questions + ChatbotRAG (intake)
    hasta agotar huecos + generación de artefactos en disco.

Requisitos:
  - Postgres (DATABASE_URL, misma que el backend).
  - LLM accesible (Ollama) para EconomicAgent, DataGap inferencia opcional, redactores.
  - Rutas de salida: los agentes usan /data/outputs/{session_id}. Ejecutar DENTRO del
    contenedor backend (recomendado): docker compose exec backend python scripts/e2e_chatbot_intake_full_generation.py

Datos 100%% mock (empresa y sesión efímeras). No modifica licitaciones reales del usuario.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _mock_answer(question: dict) -> str:
    """Respuesta simulada del usuario según tipo de pregunta pendiente."""
    if question.get("type") == "economic_price":
        return "18500.00"
    field = question.get("field") or ""
    if field == "rfc":
        return "mi rfc es E2E850101XYZ"
    if field == "domicilio_fiscal":
        return "mi domicilio fiscal es Calle E2E 100, Col. Mock, CDMX, CP 01000"
    if field == "representante_legal":
        return "mi representante legal es Juan Mock Pérez"
    if field == "cedula_representante":
        return "mi número de identificación es MOCK12345678901234"
    if field == "telefono":
        return "mi teléfono es 5551234567"
    if field == "email":
        return "mi correo es e2e.mock@empresa.test"
    if field == "web":
        # DataGap invalida "N/A" / cadenas cortas para web; usar URL ficticia.
        return "https://e2e-mock.example.org"
    if field == "anos_experiencia":
        return "mi empresa tiene 10 años de experiencia"
    if field == "numero_empleados":
        return "25"
    if field.startswith("price_"):
        return "25000"
    return "dato mock E2E para " + str(question.get("label", field))


async def _drain_pending_chatbot(memory, bot, sid: str, cid: str) -> int:
    """Responde vía ChatbotRAG hasta vaciar pending_questions. Retorna mensajes enviados."""
    from app.contracts.agent_contracts import AgentInput

    sent = 0
    while True:
        state = await memory.get_session(sid) or {}
        pending = state.get("pending_questions") or []
        if not pending:
            break
        idx = int(state.get("current_question_index", 0))
        if idx >= len(pending):
            break
        q = pending[idx]
        ans = _mock_answer(q)
        inp = AgentInput(session_id=sid, company_id=cid, company_data={"query": ans})
        out = await bot.process(inp)
        sent += 1
        data = out.data if out.data is not None else {}
        print(f"  [chat] -> {ans[:70]!r}")
        print(f"  [bot]  <- {(data.get('respuesta') or '')[:200]}...")
        state2 = await memory.get_session(sid) or {}
        if state2.get("pending_questions") == pending and state2.get("current_question_index", 0) == idx:
            print("  [WARN] La cola no avanzó; abortando drenado para evitar bucle infinito.")
            break
    return sent


async def main() -> int:
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.agents.orchestrator import OrchestratorAgent
    from app.agents.mcp_context import MCPContextManager
    from app.memory.factory import MemoryAdapterFactory

    memory = MemoryAdapterFactory.create_adapter()
    if memory is None:
        print("[FATAL] MemoryAdapterFactory.create_adapter() -> None (DATABASE_URL?)")
        return 1
    if not await memory.connect():
        print("[FATAL] No se pudo conectar a memoria.")
        return 1

    sid = f"e2e_chatbot_{uuid.uuid4().hex[:12]}"
    cid = f"co_e2e_{uuid.uuid4().hex[:10]}"

    compliance_data = {
        "administrativo": [],
        "tecnico": [
            {
                "id": "t_e2e_1",
                "nombre": "Servicio de integración E2E",
                "descripcion": "Implementación y pruebas automatizadas",
            }
        ],
    }

    tasks_completed = [
        {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
        {
            "task": "stage_completed:compliance",
            "result": {"status": "success", "data": compliance_data},
        },
    ]

    company = {
        "id": cid,
        "name": "E2E Mock SA de CV",
        "catalog": [],
        "master_profile": {
            "razon_social": "E2E Mock SA de CV",
            "tipo": "moral",
        },
    }

    await memory.save_company(cid, company)
    await memory.save_session(
        sid,
        {
            "id": sid,
            "tasks_completed": tasks_completed,
            "pending_questions": [],
            "current_question_index": 0,
        },
    )

    ctx = MCPContextManager(memory)
    orch = OrchestratorAgent(ctx)
    bot = ChatbotRAGAgent(ctx)

    print(f"\n[E2E] session_id={sid} company_id={cid}\n")

    max_orchestrator_rounds = 15
    total_chat_turns = 0

    for round_i in range(1, max_orchestrator_rounds + 1):
        print(f"--- Orquestador ronda {round_i} (generation_only) ---")
        res = await orch.process(
            sid,
            {
                "company_id": cid,
                "resume_generation": True,
                "company_data": {"mode": "generation_only"},
                "correlation_id": f"e2e_round_{round_i}",
            },
        )
        st = res.get("status")
        print(f"  status={st} decision={res.get('orchestrator_decision', {}).get('stop_reason')}")

        if st == "success":
            print("\n[E2E] Orquestador terminó en success.")
            out_dir = os.path.join("/data", "outputs", sid)
            if os.path.isdir(out_dir):
                names = os.listdir(out_dir)
                print(f"[E2E] Salida en disco ({out_dir}): {len(names)} entradas -> {names[:15]}")
            else:
                print(f"[E2E] No existe aún {out_dir} (¿corriste fuera de Docker?)")
            await memory.disconnect()
            return 0

        if st == "waiting_for_data":
            n = await _drain_pending_chatbot(memory, bot, sid, cid)
            total_chat_turns += n
            print(f"  Drenado chat: {n} mensajes mock.")
            continue

        print(f"[E2E] Estado no manejado: {res}")
        await memory.disconnect()
        return 2

    print(f"[E2E] Agotadas {max_orchestrator_rounds} rondas. Chat turns={total_chat_turns}")
    await memory.disconnect()
    return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
