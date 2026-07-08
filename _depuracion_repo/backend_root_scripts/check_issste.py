import asyncio
import sys
import json

sys.path.append(".")
from app.api.deps import get_connected_memory

async def check():
    m = await get_connected_memory()
    s = await m.get_session('vigilancia_issste')
    if not s:
        print("Session not found")
        return
    
    print(json.dumps({
        'has_dictamen': 'dictamen' in s,
        'selected_company_id': s.get('selected_company_id'),
        'tasks_completed': [t.get('task') for t in s.get('tasks_completed', [])],
        'compliance_master_list': bool(s.get('document_candidates_final') or s.get('document_candidates_v1'))
    }, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
