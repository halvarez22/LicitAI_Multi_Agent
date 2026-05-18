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
    
    # Check tasks_completed for the latest economic_proposal
    tasks = s.get('tasks_completed', [])
    latest_econ = None
    for t in reversed(tasks):
        if t.get('task') == 'economic_proposal':
            latest_econ = t.get('result', {})
            break
            
    print(json.dumps({
        'calculator_blocking': latest_econ.get('calculator_result', {}).get('blocking_issues', []) if latest_econ else [],
        'missing_fields': [m.get('label') for m in (latest_econ.get('missing', []) if latest_econ else [])]
    }, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
