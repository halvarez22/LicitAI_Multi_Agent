import asyncio
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

async def test_rag():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    try:
        mcp = MCPContextManager(memory_repository=memory)
        agent = ChatbotRAGAgent(context_manager=mcp)
        
        # Simular una pregunta
        session_id = "test-session"
        query = "Que requisitos pide la convocante?"
        
        print(f"Testing RAG with query: {query}")
        result = await agent.process(session_id, {"query": query})
        print("Result:", result)
    finally:
        await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_rag())
