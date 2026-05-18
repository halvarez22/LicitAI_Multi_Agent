
import asyncio
import os
import sys

# Asegurar que el path sea correcto para importar app
sys.path.append("/app")

from app.memory.factory import MemoryAdapterFactory

async def cleanup():
    # Inicializar el adaptador de memoria (Postgres)
    memory = MemoryAdapterFactory.create_adapter()
    if not memory:
        print("Error: No se pudo crear el adaptador de memoria.")
        return

    # IMPORTANTE: Conectar para inicializar async_session
    print("Conectando a la base de datos...")
    connected = await memory.connect()
    if not connected:
        print("Error: No se pudo conectar a la base de datos.")
        return

    session_id = "limpieza_isapeg"
    print(f"Buscando sesión: {session_id}")
    session = await memory.get_session(session_id)
    if not session:
        print(f"Sesión {session_id} no encontrada.")
        return

    print(f"Sesión {session_id} encontrada. Humanizando mensajes...")
    
    # 1. Limpiar pending_questions
    pending = session.get("pending_questions") or []
    count_pending = 0
    for q in pending:
        q_text = str(q.get("question", ""))
        if "No cierres la app" in q_text or "error de extracción" in q_text:
            q["question"] = "Necesito tu ayuda para completar algunos precios faltantes en tu propuesta económica."
            count_pending += 1
        
        # Limpiar instrucciones económicas en items bloqueantes
        blocking_items = q.get("blocking_items") or []
        for it in blocking_items:
            instr = str(it.get("instruction", ""))
            if "No cierres la app" in instr or "error de extracción" in instr:
                 it["instruction"] = "Por favor, proporciona el precio unitario para este concepto para poder continuar."
                 count_pending += 1

    # 2. Limpiar en tasks_completed
    tasks = session.get("tasks_completed") or []
    count_tasks = 0
    for t in tasks:
        if t.get("task") == "economic_proposal":
            res = t.get("result") or {}
            val_res = res.get("validation_result") or {}
            
            # Limpiar blocking_issues
            issues = val_res.get("blocking_issues") or []
            new_issues = []
            for issue in issues:
                if "No cierres la app" in issue or "error de extracción" in issue:
                    new_issues.append("Faltan precios unitarios por capturar en la propuesta.")
                    count_tasks += 1
                else:
                    new_issues.append(issue)
            val_res["blocking_issues"] = new_issues
            
            # Limpiar validations items
            validations = val_res.get("validations") or []
            for v in validations:
                evid = str(v.get("evidencia", ""))
                if "No cierres la app" in evid or "error de extracción" in evid:
                    v["evidencia"] = "Existen partidas con precio cero o no detectado que requieren intervención manual."
                    count_tasks += 1

    session["pending_questions"] = pending
    session["tasks_completed"] = tasks
    
    await memory.save_session(session_id, session)
    print(f"Sesión {session_id} humanizada exitosamente.")
    print(f"Cambios en pending: {count_pending}")
    print(f"Cambios en tasks: {count_tasks}")

if __name__ == "__main__":
    asyncio.run(cleanup())
