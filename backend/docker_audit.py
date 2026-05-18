import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def main():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    # Usando el ID de sesión de los metadatos
    session_id = "10468fa0-a136-4cde-8c8b-a350376682b1"
    state = await m.get_session(session_id)
    if not state:
        print(f"Session {session_id} not found")
        return
    ml = state.get('master_compliance_list', {})
    print('---AUDIT_START---')
    for k, items in ml.items():
        print(f'CATEGORY: {k}')
        for r in items:
            label = r.get("label") or r.get("descripcion") or "S/N"
            mandatory = r.get("mandatory", True)
            print(f"- {label} | MANDATORY: {mandatory}")
    print('---AUDIT_END---')

if __name__ == "__main__":
    asyncio.run(main())
