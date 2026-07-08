"""Smoke: identidad de anexo K contra sesión ISAPEG viva."""
from __future__ import annotations

import asyncio
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "isapeg_servicios_de_limpieza"


async def main() -> None:
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.services.bases_annex_identity_service import (
        compose_annex_identity_bases_response,
        detect_annex_bases_intent,
        fetch_annex_identity_from_bases,
    )
    from app.services.vector_service import VectorDbServiceClient

    queries = (
        "¿De qué va el Anexo K?",
        "¿Hay alusión al Anexo K en p. 15?",
    )
    vdb = VectorDbServiceClient()
    sources = vdb.get_sources(SESSION)
    primary = ChatbotRAGAgent._resolve_primary_bases_doc(sources)
    print("primary:", primary)
    for q in queries:
        print("\n=== QUERY ===", q)
        assert detect_annex_bases_intent(q)
        payload = fetch_annex_identity_from_bases(SESSION, primary, vdb, q)
        print("ready:", payload.get("ready"))
        print("conflicts:", len(payload.get("conflicts") or []))
        text = compose_annex_identity_bases_response(payload)
        print("--- RESPONSE ---")
        print(text[:4000])


if __name__ == "__main__":
    asyncio.run(main())
