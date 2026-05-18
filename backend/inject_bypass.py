import asyncio
from app.memory.factory import MemoryAdapterFactory

async def inject_bypass():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    state = await m.get_session('vigilancia_issste')
    if not state:
        print("Error: Sesión no encontrada.")
        return
    
    print("[*] Recuperando sesión vigilancia_issste...")
    
    # 1. Inyectar el requerimiento técnico crítico
    master_list = state.get('master_compliance_list', {})
    
    guardia_item = {
        "id": "1_operativo_guardia",
        "label": "Guardia Intramuros",
        "descripcion": "Servicio de Vigilancia Guardia Intramuros turno 24x24",
        "tipo": "técnico",
        "mandatory": True
    }
    
    master_list['tecnico'] = [guardia_item]
    state['master_compliance_list'] = master_list
    print(f"[*] Inyectado requerimiento: {guardia_item['label']}")
    
    # 2. Limpiar las tareas económicas previas para forzar recalcular
    tasks = state.get('tasks_completed', [])
    clean_tasks = [t for t in tasks if t.get('task') not in [
        'stage_completed:economic', 
        'economic_proposal', 
        'go_no_go_result'
    ]]
    
    # Asegurarnos de que el orquestador sepa que Análisis y Compliance existen
    required_tasks = ['stage_completed:analysis', 'stage_completed:compliance']
    existing_task_names = [t.get('task') for t in clean_tasks]
    
    for rt in required_tasks:
        if rt not in existing_task_names:
            clean_tasks.append({"task": rt, "result": {"status": "injected_bypass"}})
            print(f"[*] Asegurada etapa obligatoria: {rt}")
            
    state['tasks_completed'] = clean_tasks
    
    # Guardar estado
    await m.save_session('vigilancia_issste', state)
    print("[*] ¡Inyección Táctica (Bypass Coronario) completada con éxito!")

if __name__ == "__main__":
    asyncio.run(inject_bypass())
