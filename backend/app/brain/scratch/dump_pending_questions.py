import asyncio
import os
import sys

# Ensure backend path is configured
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from app.memory.factory import MemoryAdapterFactory

async def main():
    memory = MemoryAdapterFactory.create_adapter()
    # Let's get all sessions and find the active one
    sessions = await memory.list_sessions()
    if not sessions:
        print("No sessions found.")
        return
    # Assume the most recently updated session
    session_id = sessions[0]["id"]
    state = await memory.get_session(session_id)
    pending = state.get("pending_questions", [])
    print(f"Session {session_id} has {len(pending)} pending questions.")
    for i, q in enumerate(pending):
        print(f"[{i}] Field: {q.get('field')} - {q.get('label')}")
        print(f"    Question: {q.get('question')}")

if __name__ == "__main__":
    asyncio.run(main())
