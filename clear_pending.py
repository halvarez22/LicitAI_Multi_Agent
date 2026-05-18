import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.api.deps import get_connected_memory

async def main():
    session_id = "licitacion_publica_nacional_40004001-003-24_"
    try:
        memory = await get_connected_memory()
    except Exception as e:
        print(f"Error connecting: {e}")
        return
        
    sess = await memory.get_session(session_id)
    if not sess:
        print("Session not found")
        return

    print("Old pending questions count:", len(sess.get("pending_questions", [])))
    
    # Just clear pending_questions and let the UI/user hit "Generar propuestas"
    sess["pending_questions"] = []
    sess["intake_plan"] = {}
    await memory.save_session(session_id, sess)
    
    print("Pending questions cleared! Now the Chatbot shouldn't greet with an old question.")
    
if __name__ == "__main__":
    asyncio.run(main())
