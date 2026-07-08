"""Smoke: excerpt de muestras contra sesión ISAPEG viva."""
from __future__ import annotations

import asyncio
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "isapeg_servicios_de_limpieza"


async def main() -> None:
    from app.services.bases_sample_delivery_excerpt_service import (
        compose_sample_delivery_chat_response,
        detect_sample_delivery_intent,
        fetch_sample_delivery_excerpt_from_session,
    )
    from app.services.vector_service import VectorDbServiceClient
    from app.agents.chatbot_rag import ChatbotRAGAgent

    q = "¿Qué especifican las bases referente a la entrega recepción de muestras?"
    assert detect_sample_delivery_intent(q)

    vdb = VectorDbServiceClient()
    sources = vdb.get_sources(SESSION)
    primary = ChatbotRAGAgent._resolve_primary_bases_doc(sources)
    payload = fetch_sample_delivery_excerpt_from_session(SESSION, primary, vdb)
    print("primary:", primary)
    print("ready:", payload.get("ready"))
    print("sections:", [s.get("section_id") for s in payload.get("sections") or []])
    text = compose_sample_delivery_chat_response(payload)
    print("--- RESPONSE ---")
    print(text[:3500])


if __name__ == "__main__":
    asyncio.run(main())
