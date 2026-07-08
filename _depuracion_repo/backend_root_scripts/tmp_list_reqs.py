import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from app.api.deps import get_connected_memory
    memory = await get_connected_memory()
    try:
        session = await memory.get_session('suministro_e_instalacin_de_paneles_solares')
        tasks = session.get('tasks_completed', [])
        for t in reversed(tasks):
            if t.get('task') == 'stage_completed:compliance':
                data = t.get('result', {}).get('data', {})
                tecnico = data.get('tecnico', [])
                formatos = data.get('formatos', [])
                print('=== TECNICO ===')
                for item in tecnico:
                    print(item.get('id',''), '|', item.get('nombre',''))
                print('=== FORMATOS ===')
                for item in formatos:
                    print(item.get('id',''), '|', item.get('nombre',''))
                break
    finally:
        await memory.disconnect()

asyncio.run(main())
