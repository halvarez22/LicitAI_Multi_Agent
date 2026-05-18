import asyncio
import os
import sys
from pathlib import Path

# Configurar path para importar app
sys.path.append(str(Path(__file__).parent.parent))

from app.services.context_manager import MCPContextManager
from app.agents.chatbot_rag import ChatbotRAGAgent

async def audit_chatbot_prompt(session_id: str):
    ctx = MCPContextManager()
    agent = ChatbotRAGAgent(ctx)
    
    session = await ctx.memory.get_session(session_id)
    if not session:
        print(f"No se encontró la sesión {session_id}")
        return

    # Simular la generación de la sección de candidatos
    candidates_section = agent._document_candidates_prompt_section(session)
    
    print("--- AUDITORÍA DE CONOCIMIENTO INYECTADO ---")
    if not candidates_section.strip():
        print("¡ERROR! La sección de candidatos está VACÍA.")
    else:
        print(f"Longitud de la sección: {len(candidates_section)} caracteres")
        print("Primeros 500 caracteres:")
        print(candidates_section[:500])
        
        print("\nBuscando 'Declaración de Integridad'...")
        if "Declaración de Integridad" in candidates_section:
            print("✅ 'Declaración de Integridad' ENCONTRADA en el prompt.")
        else:
            print("❌ 'Declaración de Integridad' NO ENCONTRADA en el prompt.")
            
        print("\nBuscando 'Garantía de seriedad'...")
        if "Garantía de seriedad" in candidates_section:
            print("✅ 'Garantía de seriedad' ENCONTRADA en el prompt.")
        else:
            print("❌ 'Garantía de seriedad' NO ENCONTRADA en el prompt.")

if __name__ == "__main__":
    # Usar el session_id de UNAQ si es posible, o el último
    asyncio.run(audit_chatbot_prompt("UNAQ-2026-SESSION")) # Ajustar ID si es necesario
