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
        'economic_user_inputs': s.get('economic_user_inputs'),
        'last_orchestrator_decision': s.get('last_orchestrator_decision'),
        'dictamen_blocking': s.get('dictamen', {}).get('calculator_result', {}).get('blocking_issues', [])
    }, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
