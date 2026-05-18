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

    gng_override = sess.get("go_no_go_override")
    print(f"go_no_go_override: {gng_override}")
    print(f"already_authorized: {gng_override and gng_override.get('authorized_by') == 'user'}")
    
    pq = sess.get("pending_questions", [])
    print(f"Pending questions count: {len(pq)}")
    if pq:
        print(f"First 3 questions:")
        for q in pq[:3]:
            print(f"- target={q.get('field_target')}, label={q.get('label')}, type={q.get('question_type')}")
    
    print("--------------------------------")
    intake_plan = sess.get("intake_plan", {})
    print(f"intake_plan checklist_corporativo count: {len(intake_plan.get('checklist_corporativo', []))}")

    
if __name__ == "__main__":
    asyncio.run(main())
